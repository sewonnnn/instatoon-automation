"""Read legacy records without changing them; import active metadata and media."""
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import os
from .common import Workspace, artifact_refs, lock, read_json, require, write_json
from . import legacy_state, state


def migrate_project(ws, req):
    destination = state.episode_path(ws, req).parent.parent
    require(not destination.exists(), 'Destination series already exists')
    # Validate the complete conversion before publishing any active metadata.
    with tempfile.TemporaryDirectory(prefix='.migration-', dir=ws.root) as temporary:
        staged = Workspace(temporary)
        result = _migrate_project(staged, req)
        require(result['validation']['decision'] == 'pass', 'Migrated validation failed')
        with lock(destination.parent):
            require(not destination.exists(), 'Destination series already exists')
            os.rename(staged.path(f"outputs/{req['series_id']}"), destination)
    return result


def _migrate_project(ws, req):
    source=Workspace(req['source_root'])
    ids={k:req[k] for k in ('series_id','episode_id')}
    directory=state.episode_path(ws,ids)
    require(not (directory/'episode.json').exists(), 'Destination episode already exists')
    old=legacy_state.load_project(source,ids)['state']
    require(not legacy_state.inspect_refs(source,old), 'Legacy input references invalid')
    if old['phase'] in {'exported','final_review'}:
        legacy_state.validate_final(source,old)
    source_series=read_json(source.path(f"outputs/{req['series_id']}/series.json"))
    require(not ws.path(f"outputs/{req['series_id']}/series.json").exists(), 'Destination series already exists')

    def inline(value, stack=()):
        if isinstance(value,list):
            return [inline(v,stack) for v in value]
        if not isinstance(value,dict):
            return value
        if 'path' in value and 'sha256' in value:
            path=source.verify(value)
            require(str(path) not in stack,'Cyclic legacy metadata')
            if path.suffix == '.json':
                return inline(read_json(path),stack+(str(path),))
            dest=ws.output(f"outputs/{req['series_id']}/assets/{value['sha256']}{path.suffix}")
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():
                shutil.copyfile(path,dest)
            ref=ws.artifact(dest,value.get('role','asset'))
            require(ref['sha256']==value['sha256'],'Asset copy differs')
            return {**value,**ref}
        # Old approval evidence is preserved verbatim in the migration history entry.
        return {k:inline(v,stack) for k,v in value.items() if k not in {'artifact_hashes','snapshot','qa_path','sources_path','prompt_path'}}

    series=inline(source_series)
    for key in ('style_ref','character_refs'):
        if key in series:
            series[{'style_ref':'style','character_refs':'characters'}[key]]=series.pop(key)
    state.save_series(ws,{'series_id':ids['series_id'],'expected_revision':None,'series':series})
    active=inline({k:v for k,v in old.items() if k not in {'snapshot','approvals','exports','final_qa','schema_version','updated_at','current_revision'}})
    active.update(schema_version=2,series_id=ids['series_id'],current_revision=old['current_revision'],approvals=[])
    for panel in active.get('ordered_panels',[]):
        report=panel['render_report']
        original=next(p for p in old['ordered_panels'] if p['panel_id']==panel['panel_id'])
        old_report=read_json(source.verify(original['render_report']))
        # Legacy inputs contain art + layout reference. Keep layout once, inline.
        layout_ref=next((r for r in old_report['inputs'] if r.get('role')=='layout'),None)
        report['layout']=inline(read_json(source.verify(layout_ref))) if layout_ref else report['layout']
        report['inputs']=[inline(r) for r in old_report['inputs'] if r.get('role')!='layout']
    if 'final_qa' in old:
        qa=read_json(source.verify(old['final_qa']))
        active['final_qa']={k:v for k,v in qa.items() if k!='ordered_panels'}
        active['final_qa']['outputs_hash']=state.fingerprint(active['ordered_panels'])
    active['migration']={'source_root':str(source.root),'source_revision':old['current_revision'],
                         'legacy_approvals':old.get('approvals',[]),'note':'Storage-only migration; artwork bytes unchanged.'}
    if old['phase'] in {'final_review','exported'}:
        state.validate_final(ws,active)
    for approval in old.get('approvals',[]):
        if approval['target_revision']==old['current_revision']:
            active['approvals'].append({k:v for k,v in approval.items() if k!='artifact_hashes'} | {'content_hash':state.content_hash(active),'migrated':True})
    if old.get('exports'):
        manifest=read_json(source.verify(old['exports']))
        for ref in artifact_refs(manifest['ordered_panels']): source.verify(ref)
        active['exports']={'approved_revision':old['current_revision'],'approval_id':manifest['approval_ref']['approval_id'],
                           'ordered_panels':inline(manifest['ordered_panels'])}
    with lock(directory):
        require(not (directory/'episode.json').exists(),'Destination episode already exists')
        active=state._commit(directory,None,active,'migrate')
    return {'state':active,'validation':state.validate_episode(ws,{**ids,'stage':'final'} if 'final_qa' in active else ids)}
