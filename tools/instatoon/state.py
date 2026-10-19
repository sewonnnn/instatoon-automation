"""Compact v2 storage: current JSON documents plus one transactional JSONL journal."""
from copy import deepcopy
import hashlib
import json
import os
import shutil
from uuid import uuid4
from PIL import Image
from .common import (ToolError, artifact_refs, identifier, lock, now, read_json,
                     require, write_json)
from .legacy_state import PHASES, STATUSES, validate_storyboard


def episode_path(ws, req):
    return ws.output(f"outputs/{identifier(req['series_id'])}/episodes/{identifier(req['episode_id'])}")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def content_hash(state):
    return fingerprint({k: v for k, v in state.items() if k not in {
        'approvals', 'exports', 'updated_at', 'event_seq', 'phase', 'status', 'next_action'}})


def _read(directory):
    """Journal is committed first; replay recovers a crash before episode.json replacement."""
    journal = directory / 'history.jsonl'
    events = []
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            events.append(json.loads(line))
    state = {}
    for seq, event in enumerate(events, 1):
        require(event['seq'] == seq and event['before'] == fingerprint(state), 'Invalid history chain')
        for key in event['remove']:
            state.pop(key, None)
        state.update(event['set'])
        require(event['after'] == fingerprint(state), 'Invalid history checksum')
    path = directory / 'episode.json'
    if path.exists():
        saved = read_json(path)
        require(saved.get('schema_version') == 2, 'Legacy project: migrate before editing')
        if saved.get('event_seq', 0) < len(events):
            require(saved == _replay_prefix(events, saved['event_seq']), 'Changed episode state', 'stale_state')
            write_json(path, state)
        else:
            require(saved == state, 'Changed episode state', 'stale_state')
    elif events:
        write_json(path, state)
    return state or None


def _replay_prefix(events, count):
    state = {}
    for event in events[:count]:
        for key in event['remove']:
            state.pop(key, None)
        state.update(event['set'])
    return state


def _commit(directory, old, state, action):
    old = old or {}
    state = deepcopy(state)
    state['event_seq'] = old.get('event_seq', 0) + 1
    state['updated_at'] = now()
    event = {'seq': state['event_seq'], 'at': state['updated_at'], 'action': action,
             'before': fingerprint(old), 'after': fingerprint(state),
             'set': {k: v for k, v in state.items() if old.get(k) != v or k not in old},
             'remove': [k for k in old if k not in state]}
    journal = directory / 'history.jsonl'
    # Atomic replace prevents a partially appended JSON line after process interruption.
    previous = journal.read_bytes() if journal.exists() else b''
    temporary = directory / '.history.pending'
    with temporary.open('wb') as f:
        f.write(previous + (json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n').encode())
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, journal)
    write_json(directory / 'episode.json', state)
    return state


def save_series(ws, req):
    sid = identifier(req['series_id'])
    directory = ws.output(f'outputs/{sid}')
    with lock(directory):
        path = directory / 'series.json'
        old = read_json(path) if path.exists() else None
        require(req.get('expected_revision') == (old['revision'] if old else None), 'Series revision conflict', 'conflict')
        series = deepcopy(req['series'])
        for ref in artifact_refs(series):
            ws.verify(ref)
        series.update(schema_version=2, series_id=sid, revision=(old['revision'] if old else 0)+1, updated_at=now())
        write_json(path, series)
        return {'series': series}


def save_revision(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        old = _read(directory)
        require('expected_revision' in req and req['expected_revision'] == (old['current_revision'] if old else None), 'Revision conflict', 'conflict')
        state = deepcopy(req['state'])
        require(state.get('phase') in PHASES and state.get('status') in STATUSES, 'Invalid phase or status')
        require(state['phase'] != 'exported', 'Only export_episode can set exported')
        require(not any(k in state for k in ('approvals', 'exports', 'snapshot', 'current_revision', 'event_seq')), 'Reserved state field')
        documents = deepcopy(req.get('documents', {}))
        require(set(documents) <= {'brief', 'storyboard'}, 'Unsupported document')
        if 'storyboard' in documents:
            validate_storyboard(documents['storyboard'])
        state.update(schema_version=2, episode_id=req['episode_id'], series_id=req['series_id'],
                     current_revision=f"r{int(old['current_revision'][1:])+1 if old else 1:03d}",
                     documents=documents, approvals=deepcopy(old.get('approvals', [])) if old else [])
        for ref in artifact_refs({k:v for k,v in state.items() if k not in {'approvals', 'migration'}}):
            ws.verify(ref)
        runs = state.get('runs', [])
        require(len({r['run_id'] for r in runs}) == len(runs), 'Duplicate run ID')
        for run in runs:
            identifier(run['run_id'])
            for key in ('quality_retries', 'technical_retries'):
                require(type(run.get(key, 0)) is int and run.get(key, 0) >= 0, 'Invalid retry count')
        prior = {r['run_id']:r for r in (old or {}).get('runs', [])}
        current = {r['run_id']:r for r in runs}
        require(prior.keys() <= current.keys(), 'Run history must be preserved')
        for rid, run in prior.items():
            for key in ('quality_retries', 'technical_retries'):
                require(current[rid].get(key, 0) >= run.get(key, 0), 'Retry count decreased')
        state = _commit(directory, old, state, 'save')
        return {'state': state, 'artifacts': []}


def inspect_refs(ws, state):
    issues = []
    for ref in artifact_refs({k:v for k,v in state.items() if k not in {'approvals', 'migration'}}):
        try:
            ws.verify(ref)
        except (ToolError, OSError) as error:
            issues.append({'code': getattr(error, 'code', 'missing_artifact'), 'message': str(error)})
    return issues


def load_project(ws, req):
    with lock(episode_path(ws, req)):
        state = _read(episode_path(ws, req))
        require(state is not None, 'Episode not found')
        return {'state': state, 'issues': inspect_refs(ws, state)}


def validate_final(ws, state):
    require(not inspect_refs(ws, state), 'Changed or missing artifact', 'stale_artifact')
    board = state['documents']['storyboard']
    validate_storyboard(board)
    panels = state.get('ordered_panels', [])
    require([(p['panel_id'],p['order']) for p in panels] == [(p['panel_id'],p['order']) for p in sorted(board['panels'],key=lambda p:p['order'])], 'Output panels do not match storyboard')
    for panel, source in zip(panels, sorted(board['panels'],key=lambda p:p['order'])):
        report = panel['render_report']
        require(report['panel'] == source and report['status'] == 'pass', 'Render uses outdated panel')
        require(report['outputs'] == {k:panel[k] for k in ('1080','1920')}, 'Render/output mismatch')
        require('layout' in report, 'Inline render layout required')
        for size in ('1080','1920'):
            with Image.open(ws.verify(panel[size])) as im:
                require(im.format == 'PNG' and im.size == (int(size),int(size)), 'Wrong PNG dimensions')
    qa = state['final_qa']
    require(qa['target_revision'] == state['current_revision'] and qa['decision'] == 'pass', 'Current visual QA required')
    require(qa['outputs_hash'] == fingerprint(panels), 'QA targets different outputs')
    require(not any(i.get('severity') == 'blocking' for i in qa.get('issues', [])), 'Blocking QA issue')
    return panels


def validate_episode(ws, req):
    try:
        result = load_project(ws, req)
        state, issues = result['state'], result['issues']
        if req.get('stage') == 'final':
            validate_final(ws, state)
        elif 'storyboard' in state.get('documents', {}):
            validate_storyboard(state['documents']['storyboard'])
    except (ToolError, KeyError, ValueError, OSError) as error:
        issues = [{'code': getattr(error, 'code', 'invalid_input'), 'message': str(error)}]
    return {'decision': 'needs_changes' if issues else 'pass', 'issues': issues}


def record_approval(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        old = _read(directory)
        require(old and req['target_revision'] == old['current_revision'], 'Approval revision conflict')
        require(req['stage'] in {'storyboard','final'} and req.get('user_response','').strip(), 'Actual approval required')
        require(not inspect_refs(ws, old), 'Changed artifact')
        if req['stage'] == 'final':
            require(old['phase'] == 'final_review', 'Final review required')
            validate_final(ws, old)
        else:
            validate_storyboard(old['documents']['storyboard'])
        approval = {'approval_id':uuid4().hex,'stage':req['stage'],'target_revision':old['current_revision'],
                    'content_hash':content_hash(old),'user_response':req['user_response'],'recorded_at':now()}
        state = deepcopy(old)
        state['approvals'].append(approval)
        _commit(directory, old, state, 'approve')
        return {'approval':approval}


def export_episode(ws, req):
    directory = episode_path(ws, req)
    with lock(directory):
        old = _read(directory)
        require(old and req['target_revision'] == old['current_revision'], 'Export revision conflict')
        panels = validate_final(ws, old)
        approvals = [a for a in old.get('approvals',[]) if a.get('stage') == 'final' and a.get('target_revision') == old['current_revision'] and a.get('content_hash') == content_hash(old)]
        require(approvals, 'Final user approval required', 'approval_required')
        if 'exports' in old:
            for ref in artifact_refs(old['exports']):
                ws.verify(ref)
            return {'manifest':old['exports'], 'artifacts':[]}
        dest = directory/'exports'/old['current_revision']
        exported=[]
        for panel in panels:
            item={'panel_id':panel['panel_id'],'order':panel['order']}
            for size in ('1080','1920'):
                path=dest/size/f"{panel['order']:02d}-{panel['panel_id']}.png"
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    require(ws.artifact(path,'composed')['sha256'] == panel[size]['sha256'], 'Existing export differs')
                else:
                    shutil.copyfile(ws.verify(panel[size]),path)
                item[size]=ws.artifact(path,'composed')
            exported.append(item)
        manifest={'approved_revision':old['current_revision'],'approval_id':approvals[-1]['approval_id'],'ordered_panels':exported}
        state=deepcopy(old)
        state.update(exports=manifest,phase='exported',status='done',next_action='')
        _commit(directory,old,state,'export')
        return {'manifest':manifest,'artifacts':[]}
