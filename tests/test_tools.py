from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image
from tools.instatoon.common import Workspace, ToolError, digest, read_json, write_json
from tools.instatoon.render import render_panel, build_preview
from tools.instatoon.legacy_state import save_revision, load_project, validate_episode, record_approval, export_episode


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


@pytest.fixture
def font():
    candidates = [os.environ.get("INSTATOON_TEST_FONT", ""),
                  "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    pytest.skip("Set INSTATOON_TEST_FONT to a Korean TTF/OTF/TTC font")


def request(ws, font, text="분명 주말이었는데… 커피부터 마시자."):
    art = ws.output("outputs/source.png")
    art.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1920,1920), "#fff8ed").save(art)
    panel = {"panel_id": "p1", "order": 1, "characters": ["c1"], "action": "커피를 든다",
             "texts": [{"text_id": "t1", "text": text, "kind": "dialogue", "speaker_id": "c1", "reading_order": 1}]}
    item = {"text_id": "t1", "box": {"x": 120,"y": 160,"width": 880,"height": 360},
            "tail": {"x": 1060,"y": 700}, "font_path": font,"font_size": 64,"reading_order": 1}
    disclosure = {"text": "AI 생성 이미지", "box": {"x": 1380,"y": 1770,"width": 420,"height": 90},
                  "font_path": font,"font_size": 30,"padding": 12,"stroke_width": 0}
    return {"metadata_files": True, "art": ws.artifact(art,"art"),"panel": panel,
            "layout": {"schema_version": 1,"panel_id": "p1", "canvas": {"width":1920,"height":1920},
                       "items": [item],"protected_regions": [],"disclosure": disclosure},
            "output_dir": "outputs/render1"}


def save(ws, state=None, expected=None, documents=None):
    return save_revision(ws, {"series_id": "series1", "episode_id": "ep1", "expected_revision": expected,
                             "state": state or {"phase":"planning","status":"ready"}, "documents": documents or {}})


def final_state(ws, font):
    req = request(ws,font)
    rendered = render_panel(ws,req)
    panel = {"panel_id":"p1","order":1, **rendered["report"]["outputs"], "render_report":rendered["artifacts"][-1]}
    qa = ws.output("outputs/qa.json")
    write_json(qa, {"schema_version":1,"target_revision":"r001","decision":"pass","issues":[],"ordered_panels":[panel]})
    state = {"phase":"final_review","status":"awaiting_user","ordered_panels":[panel],
             "final_qa":ws.artifact(qa,"final_qa"),"generation_provenance":[{"tool":"test_fixture"}]}
    saved = save(ws,state,documents={"storyboard":{"schema_version":1,"panels":[req["panel"]]}})
    return req, saved["state"]


def approval(ws):
    return record_approval(ws,{"series_id":"series1","episode_id":"ep1","stage":"final","target_revision":"r001",
                               "user_response":"TEST FIXTURE consent, not an actual publication approval"})


def test_revision_conflict_and_history(ws):
    first = save(ws,state={"phase":"planning","status":"ready","runs":[{"run_id":"run1","quality_retries":2}]})
    with pytest.raises(ToolError,match="conflict"):
        save(ws)
    with pytest.raises(ToolError,match="history"):
        save(ws,expected="r001")
    second = save(ws,state={"phase":"storyboarding","status":"ready","runs":[{"run_id":"run1","quality_retries":2}]},expected="r001")
    assert first["state"]["current_revision"] == "r001"
    assert second["state"]["current_revision"] == "r002"
    assert ws.verify(first["state"]["snapshot"]).exists()
    assert read_json(ws.path("outputs/series1/series.json"))["episode_ids"] == ["ep1"]


def test_path_escape_and_wrong_types(ws):
    with pytest.raises(ToolError):
        save_revision(ws,{"series_id":"../oops","episode_id":"ep1"})
    with pytest.raises(ToolError):
        ws.output("README.md")
    with pytest.raises(ToolError):
        save(ws,state={"phase":"planning","status":"ready","runs":[{"run_id":"r","quality_retries":-1}]})


def test_render_real_korean_and_dimensions(ws,font):
    req=request(ws,font)
    result=render_panel(ws,req)
    assert len(result["report"]["text_checks"][0]["lines"]) >= 2
    for size in (1920,1080):
        with Image.open(ws.verify(result["report"]["outputs"][str(size)])) as image:
            assert image.size == (size,size)
            assert image.getpixel((0,0))[:3] == (255,248,237)
    assert digest(ws.path(req["art"]["path"])) == req["art"]["sha256"]
    preview=build_preview(ws,{"panels":[{"panel_id":"p1","order":1,"image":result["artifacts"][1]}],"output_dir":"outputs/preview"})
    assert ws.verify(preview["artifacts"][0]).exists()
    with pytest.raises(ToolError,match="Already exists"):
        render_panel(ws,req)


@pytest.mark.parametrize("failure", ["overflow", "glyph", "collision", "text", "order", "canvas", "missing_text"])
def test_render_rejects_bad_layout(ws,font,failure):
    req=request(ws,font)
    item=req["layout"]["items"][0]
    if failure=="overflow": item["box"]["height"]=70
    if failure=="glyph": req["panel"]["texts"][0]["text"]="\U0010ffff"
    if failure=="collision": req["layout"]["protected_regions"]=[item["box"]]
    if failure=="text": item["lines"]=["원문과 다른 문장"]
    if failure=="order": item["reading_order"]=2
    if failure=="canvas": req["layout"]["canvas"]["width"]=1080
    if failure=="missing_text": req["layout"]["items"]=[]
    with pytest.raises(ToolError): render_panel(ws,req)
    assert not ws.path(req["output_dir"]).exists()


def test_approval_export_and_tamper(ws,font):
    req,state=final_state(ws,font)
    base={"series_id":"series1","episode_id":"ep1"}
    assert validate_episode(ws,{**base,"stage":"final"})["decision"]=="pass"
    with pytest.raises(ToolError,match="approval"):
        export_episode(ws,{**base,"target_revision":"r001"})
    approval(ws)
    exported=export_episode(ws,{**base,"target_revision":"r001"})
    for size in ("1920","1080"):
        assert exported["manifest"]["ordered_panels"][0][size]["sha256"]==state["ordered_panels"][0][size]["sha256"]
    assert export_episode(ws,{**base,"target_revision":"r001"})["manifest"]==exported["manifest"]
    ws.path(req["art"]["path"]).write_bytes(b"changed source")
    assert load_project(ws,base)["issues"]
    with pytest.raises(ToolError): export_episode(ws,{**base,"target_revision":"r001"})


def test_changed_output_cannot_be_approved(ws,font):
    _,state=final_state(ws,font)
    ws.path(state["ordered_panels"][0]["1080"]["path"]).write_bytes(b"tampered")
    with pytest.raises(ToolError): approval(ws)


def test_mutated_state_does_not_inherit_snapshot_approval(ws,font):
    final_state(ws,font)
    approval(ws)
    path=ws.path("outputs/series1/episodes/ep1/episode.json")
    state=read_json(path)
    state["ordered_panels"][0]["order"]=2
    write_json(path,state)
    assert load_project(ws,{"series_id":"series1","episode_id":"ep1"})["issues"]


def test_text_edit_reuses_art_but_invalidates_old_approval(ws,font):
    req,state=final_state(ws,font)
    approval(ws)
    modified=deepcopy(req)
    modified["panel"]["texts"][0]["text"]="오늘도 커피 한 잔!"
    modified["output_dir"]="outputs/render2"
    result=render_panel(ws,modified)
    assert result["report"]["inputs"][0]==req["art"]
    next_state={"phase":"lettering","status":"ready","artifacts":[req["art"]],"panel_states":{"p1":{"art":"done","composed":"done","qa":"ready"}}}
    save(ws,next_state,expected="r001",documents={"storyboard":{"schema_version":1,"panels":[modified["panel"]]}})
    current=load_project(ws,{"series_id":"series1","episode_id":"ep1"})["state"]
    assert current["current_revision"]=="r002"
    assert all(a["target_revision"]=="r001" for a in current["approvals"])
    with pytest.raises(ToolError):
        export_episode(ws,{"series_id":"series1","episode_id":"ep1","target_revision":"r002"})


def test_cli_returns_json_error(tmp_path):
    r=subprocess.run([sys.executable,"-m","tools.instatoon","load_project","--root",str(tmp_path),"--request","-"],input="{}",capture_output=True,text=True)
    assert r.returncode==1
    assert json.loads(r.stdout)["status"]=="error"
    assert not r.stderr


def test_concurrent_save_only_one_writer_commits(ws):
    from concurrent.futures import ThreadPoolExecutor
    def attempt():
        try:
            return save(ws)["state"]["current_revision"]
        except ToolError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==["conflict","r001"]
    assert not load_project(ws,{"series_id":"series1","episode_id":"ep1"})["issues"]


def test_final_rejects_render_from_old_storyboard(ws,font):
    req,state=final_state(ws,font)
    modified=deepcopy(req["panel"])
    modified["texts"][0]["text"]="바뀐 대사"
    qa=ws.output("outputs/qa2.json")
    write_json(qa,{"target_revision":"r002","decision":"pass","issues":[],"ordered_panels":state["ordered_panels"]})
    save(ws,{"phase":"final_review","status":"awaiting_user","ordered_panels":state["ordered_panels"],
             "final_qa":ws.artifact(qa,"final_qa")},expected="r001",
         documents={"storyboard":{"schema_version":1,"panels":[modified]}})
    report=validate_episode(ws,{"series_id":"series1","episode_id":"ep1","stage":"final"})
    assert report["decision"]=="needs_changes"
    assert "outdated" in report["issues"][0]["message"]
