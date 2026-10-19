from copy import deepcopy
from uuid import uuid4
import re
import shutil
from PIL import Image
from .common import (ToolError, artifact_refs, digest, identifier, lock, new_directory,
                     now, read_json, require, write_json)

PHASES = {"planning", "storyboarding", "drawing", "lettering", "final_review", "exported"}
STATUSES = {"ready", "running", "awaiting_user", "needs_changes", "failed", "done"}


def episode_path(ws, req):
    return ws.output(f"outputs/{identifier(req['series_id'])}/episodes/{identifier(req['episode_id'])}")


def validate_storyboard(doc):
    require(doc.get("schema_version") == 1, "storyboard schema_version must be 1")
    panels = doc.get("panels")
    require(isinstance(panels, list) and 1 <= len(panels) <= 10, "Expected 1–10 panels")
    ids, orders, text_ids = set(), set(), set()
    for panel in panels:
        pid = identifier(panel["panel_id"])
        require(pid not in ids, "Duplicate panel ID")
        ids.add(pid)
        order = panel["order"]
        require(type(order) is int and order not in orders, "Duplicate or invalid panel order")
        orders.add(order)
        texts = panel.get("texts")
        require(isinstance(texts, list), "Panel texts must be a list")
        reading = set()
        for text in texts:
            tid = identifier(text["text_id"])
            require(tid not in text_ids, "Duplicate text ID")
            text_ids.add(tid)
            require(isinstance(text.get("text"), str) and text["text"].strip(), "Empty text")
            require(text.get("kind") in {"dialogue", "narration", "sfx"}, "Invalid text kind")
            if text["kind"] == "dialogue":
                require(text.get("speaker_id") in panel.get("characters", []), "Dialogue speaker missing from panel")
            ro = text.get("reading_order")
            require(type(ro) is int and ro > 0 and ro not in reading, "Invalid reading order")
            reading.add(ro)
    require(orders == set(range(1, len(panels) + 1)), "Panel orders must be contiguous from 1")


def save_revision(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        current_path = directory / "episode.json"
        old = read_json(current_path) if current_path.exists() else None
        expected = old["current_revision"] if old else None
        require("expected_revision" in req and req["expected_revision"] == expected, "Revision conflict", "conflict")
        # Increment past orphan snapshots from an interrupted save; never overwrite.
        used = [int(p.name[1:]) for p in (directory / "revisions").glob("r*") if re.fullmatch(r"r\d+", p.name)]
        revision = f"r{max(used, default=0) + 1:03d}"
        state = deepcopy(req["state"])
        require(state.get("phase") in PHASES and state.get("status") in STATUSES, "Invalid phase or status")
        require(state["phase"] != "exported", "Only export_episode can set exported")
        require(not any(k in state for k in ("approvals", "current_revision", "snapshot", "documents", "exports")), "Reserved state field")
        documents = req.get("documents", {})
        require(isinstance(documents, dict), "documents must be an object")
        for name, doc in documents.items():
            require(name in {"brief", "storyboard"}, "Supported documents: brief, storyboard")
            require(isinstance(doc, dict) and doc.get("schema_version") == 1, "Document schema_version must be 1")
            if name == "storyboard":
                validate_storyboard(doc)
        # Artifacts and all dependencies are validated before publishing a snapshot.
        for ref in artifact_refs({"state": state, "documents": documents}):
            ws.verify(ref)
        state.update(schema_version=1, episode_id=req["episode_id"], current_revision=revision,
                     updated_at=now(), approvals=deepcopy(old.get("approvals", [])) if old else [])
        state.setdefault("artifacts", [])
        state.setdefault("panel_states", {})
        state.setdefault("runs", [])
        state.setdefault("next_action", "")
        require(isinstance(state["artifacts"], list) and isinstance(state["panel_states"], dict)
                and isinstance(state["runs"], list), "Invalid state collections")
        run_ids = set()
        for run in state["runs"]:
            rid = identifier(run["run_id"])
            require(rid not in run_ids, "Duplicate run ID")
            run_ids.add(rid)
            for counter in ("quality_retries", "technical_retries"):
                value = run.get(counter, 0)
                require(type(value) is int and value >= 0, "Retry counters must be nonnegative integers")
        # Callers supply complete state; retry history cannot silently disappear.
        if old:
            prior = {r["run_id"]: r for r in old.get("runs", [])}
            supplied = {r["run_id"]: r for r in state["runs"]}
            require(set(prior) <= set(supplied), "Existing run history must be preserved")
            for key, previous in prior.items():
                for counter in ("quality_retries", "technical_retries"):
                    require(supplied[key].get(counter, 0) >= previous.get(counter, 0), "Retry counts cannot decrease")
        destination = directory / "revisions" / revision
        with new_directory(destination) as temp:
            state["documents"] = {}
            for name, doc in documents.items():
                saved = dict(doc, episode_id=req["episode_id"], revision=revision)
                write_json(temp / f"{name}.json", saved)
                state["documents"][name] = {"path": ws.relative(destination / f"{name}.json"),
                                          "sha256": digest(temp / f"{name}.json"), "role": name}
            write_json(temp / "snapshot.json", state)
        state["snapshot"] = ws.artifact(destination / "snapshot.json", "snapshot")
        write_json(current_path, state)
        series_path = directory.parent.parent / "series.json"
        with lock(series_path.parent):
            series = read_json(series_path) if series_path.exists() else {
                "schema_version": 1, "series_id": req["series_id"], "episode_ids": []}
            if req["episode_id"] not in series["episode_ids"]:
                series["episode_ids"].append(req["episode_id"])
                write_json(series_path, series)
        return {"state": state, "artifacts": [state["snapshot"]]}


def inspect_refs(ws, state):
    issues = []
    # Old approvals remain history; they do not make current state stale.
    active = {k: v for k, v in state.items() if k not in {"approvals", "runs", "exports"}}
    for ref in artifact_refs(active):
        try:
            ws.verify(ref)
            if ref.get("role") == "render_report":
                report = read_json(ws.path(ref["path"]))
                for dependency in artifact_refs(report.get("inputs", [])):
                    ws.verify(dependency)
        except ToolError as error:
            issues.append({"code": error.code, "path": ref["path"], "message": str(error)})
    if "snapshot" in state and not issues:
        snapshot = read_json(ws.verify(state["snapshot"]))
        mutable = {"snapshot", "approvals", "exports", "phase", "status", "next_action", "updated_at"}
        current_content = {k: v for k, v in state.items() if k not in mutable}
        original_content = {k: v for k, v in snapshot.items() if k not in mutable}
        if current_content != original_content:
            issues.append({"code": "stale_state", "message": "State differs from its immutable revision snapshot"})
    return issues


def load_project(ws, req):
    state = read_json(episode_path(ws, req) / "episode.json")
    return {"state": state, "issues": inspect_refs(ws, state)}


def validate_final(ws, state):
    issues = inspect_refs(ws, state)
    require(not issues, str(issues), "stale_artifact")
    require("storyboard" in state["documents"], "Final output requires storyboard")
    board = read_json(ws.verify(state["documents"]["storyboard"]))
    validate_storyboard(board)
    panels = state.get("ordered_panels", [])
    expected = [(p["panel_id"], p["order"]) for p in sorted(board["panels"], key=lambda p: p["order"])]
    require([(p["panel_id"], p["order"]) for p in panels] == expected, "Output panels do not match storyboard order")
    for panel in panels:
        for size in (1920, 1080):
            path = ws.verify(panel[str(size)])
            with Image.open(path) as im:
                require(im.format == "PNG" and im.size == (size, size), f"Wrong PNG dimensions: {path}")
        report = read_json(ws.verify(panel["render_report"]))
        require(report["panel_id"] == panel["panel_id"] and report["status"] == "pass", "Invalid render report")
        require(report["outputs"] == {k: panel[k] for k in ("1920", "1080")}, "Render report/output mismatch")
        # Compare panel content, not the enclosing episode revision, for reuse.
        source = next(p for p in board["panels"] if p["panel_id"] == panel["panel_id"])
        require(report["panel"] == source, "Render uses outdated panel text or scene", "stale_artifact")
        for ref in artifact_refs(report.get("inputs", [])):
            ws.verify(ref)
    qa = read_json(ws.verify(state["final_qa"]))
    require(qa.get("target_revision") == state["current_revision"] and qa.get("decision") == "pass", "Final visual QA not passed for this revision")
    require(qa.get("ordered_panels") == panels, "Final QA targets different outputs")
    require(not any(i.get("severity") == "blocking" for i in qa.get("issues", [])), "Blocking QA issue")
    return panels


def validate_episode(ws, req):
    state = read_json(episode_path(ws, req) / "episode.json")
    issues = inspect_refs(ws, state)
    if req.get("stage") == "final":
        try:
            validate_final(ws, state)
        except (ToolError, KeyError) as error:
            issues.append({"code": getattr(error, "code", "invalid_input"), "message": str(error)})
    elif "storyboard" in state.get("documents", {}) and not issues:
        try:
            validate_storyboard(read_json(ws.verify(state["documents"]["storyboard"])))
        except (ToolError, KeyError) as error:
            issues.append({"code": getattr(error, "code", "invalid_input"), "message": str(error)})
    return {"decision": "needs_changes" if issues else "pass", "issues": issues,
            "warnings": ["Visual QA and actual user consent are evaluated by the agent, not this validator."]}


def record_approval(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        state = read_json(directory / "episode.json")
        require(req["target_revision"] == state["current_revision"], "Approval revision conflict", "conflict")
        require(req["stage"] in {"storyboard", "final"}, "This tool currently supports storyboard and final approvals")
        require(isinstance(req.get("user_response"), str) and req["user_response"].strip(), "Actual user response required")
        require(not inspect_refs(ws, state), "State contains changed artifacts", "stale_artifact")
        targets = [state["snapshot"]]
        if req["stage"] == "final":
            require(state["phase"] == "final_review", "Final approval requires final_review phase")
            panels = validate_final(ws, state)
            targets += [p[k] for p in panels for k in ("1920", "1080", "render_report")]
        else:
            require("storyboard" in state["documents"], "Missing storyboard")
            board_ref = state["documents"]["storyboard"]
            validate_storyboard(read_json(ws.verify(board_ref)))
            targets.append(board_ref)
        approval = {"approval_id": uuid4().hex, "stage": req["stage"], "target_id": state["episode_id"],
                    "target_revision": state["current_revision"], "artifact_hashes": targets,
                    "user_response": req["user_response"], "recorded_at": now()}
        state["approvals"].append(approval)
        write_json(directory / "episode.json", state)
        return {"approval": approval}


def export_episode(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        state = read_json(directory / "episode.json")
        require(req["target_revision"] == state["current_revision"], "Export revision conflict", "conflict")
        panels = validate_final(ws, state)
        approvals = [a for a in state["approvals"] if a["stage"] == "final" and a["target_revision"] == state["current_revision"]]
        require(approvals, "Final user approval required", "approval_required")
        approval = approvals[-1]
        require(approval["artifact_hashes"][0] == state["snapshot"], "Approval snapshot mismatch")
        for ref in approval["artifact_hashes"]:
            ws.verify(ref)
        destination = directory / "exports" / state["current_revision"]
        manifest = {"schema_version": 1, "episode_id": state["episode_id"],
                    "approved_revision": state["current_revision"], "approval_ref": approval,
                    "generation_provenance": state.get("generation_provenance", []), "ordered_panels": []}
        if destination.exists():
            existing = read_json(destination / "export-manifest.json")
            require(existing["approval_ref"] == approval, "Existing export uses different approval", "conflict")
            for ref in artifact_refs(existing):
                ws.verify(ref)
            manifest = existing
        else:
            with new_directory(destination) as temp:
                for panel in panels:
                    item = {"panel_id": panel["panel_id"], "order": panel["order"]}
                    for size in ("1920", "1080"):
                        relative = f"{size}/{panel['order']:02d}-{panel['panel_id']}.png"
                        target = temp / relative
                        target.parent.mkdir(exist_ok=True)
                        shutil.copyfile(ws.verify(panel[size]), target)
                        require(digest(target) == panel[size]["sha256"], "Export bytes changed", "stale_artifact")
                        item[size] = dict(panel[size], path=ws.relative(destination / relative))
                    manifest["ordered_panels"].append(item)
                write_json(temp / "export-manifest.json", manifest)
        state.update(phase="exported", status="done", next_action="", exports=ws.artifact(destination / "export-manifest.json", "export_manifest"))
        write_json(directory / "episode.json", state)
        return {"manifest": manifest, "artifacts": [state["exports"]]}
