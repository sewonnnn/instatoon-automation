from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
from tools.instatoon import state
from tools.instatoon.common import ToolError, read_json, write_json
from tools.instatoon.render import render_panel
from test_tools import ws, font, request

BASE={'series_id':'series1','episode_id':'ep1'}

def save(ws, expected=None, data=None, documents=None):
    return state.save_revision(ws,{**BASE,'expected_revision':expected,'state':data or {'phase':'planning','status':'ready'},'documents':documents or {}})['state']

def test_two_files_and_conflict(ws):
    save(ws)
    with pytest.raises(ToolError,match='conflict'): save(ws)
    save(ws,'r001')
    assert sorted(p.name for p in ws.root.rglob('*.json'))==['episode.json']
    assert len(list(ws.root.rglob('*.jsonl')))==1
    assert state.load_project(ws,BASE)['state']['current_revision']=='r002'

def test_concurrent_save(ws):
    def attempt(_):
        try: return save(ws)['current_revision']
        except ToolError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,range(2)))==['conflict','r001']

def test_journal_recovery_and_tamper(ws):
    first=save(ws)
    second=save(ws,'r001')
    path=state.episode_path(ws,BASE)/'episode.json'
    write_json(path,first)  # emulate journal committed but current JSON replacement interrupted
    assert state.load_project(ws,BASE)['state']==second
    second['status']='failed'; write_json(path,second)
    assert state.validate_episode(ws,BASE)['decision']=='needs_changes'

def test_compact_render_approval_export(ws,font):
    req=request(ws,font); req.pop('metadata_files')
    req['layout']['disclosure']={'enabled':False}
    result=render_panel(ws,req)
    assert not list(ws.path(req['output_dir']).glob('*.json'))
    assert result['report']['disclosure']=={'enabled':False}
    panel={'panel_id':'p1','order':1,**result['report']['outputs'],'render_report':result['report']}
    data={'phase':'final_review','status':'awaiting_user','ordered_panels':[panel],
          'final_qa':{'decision':'pass','target_revision':'r001','outputs_hash':state.fingerprint([panel]),'issues':[]}}
    doc={'storyboard':{'schema_version':1,'panels':[req['panel']]}}
    saved=save(ws,data=data,documents=doc)
    assert state.validate_episode(ws,{**BASE,'stage':'final'})['decision']=='pass'
    with pytest.raises(ToolError,match='approval'): state.export_episode(ws,{**BASE,'target_revision':'r001'})
    state.record_approval(ws,{**BASE,'stage':'final','target_revision':'r001','user_response':'TEST ONLY'})
    exported=state.export_episode(ws,{**BASE,'target_revision':'r001'})
    assert state.export_episode(ws,{**BASE,'target_revision':'r001'})==exported
    assert sorted(p.name for p in ws.root.rglob('*.json'))==['episode.json']
    changed=deepcopy(doc); changed['storyboard']['panels'][0]['texts'][0]['text']='수정한 대사'
    data['final_qa']['target_revision']='r002'
    save(ws,'r001',data,changed)
    assert state.validate_episode(ws,{**BASE,'stage':'final'})['decision']=='needs_changes'
    with pytest.raises(ToolError): state.export_episode(ws,{**BASE,'target_revision':'r002'})

def test_changed_image_detected(ws,font):
    req=request(ws,font);req.pop('metadata_files');r=render_panel(ws,req)
    save(ws,data={'phase':'lettering','status':'ready','render':r['report']})
    ws.path(r['report']['outputs']['1080']['path']).write_bytes(b'bad')
    assert state.load_project(ws,BASE)['issues']


def test_migration_is_self_contained(tmp_path,font):
    from tools.instatoon.common import Workspace
    from tools.instatoon import legacy_state
    from tools.instatoon.migrate import migrate_project
    from test_tools import final_state, approval
    import shutil
    src=Workspace(tmp_path/'legacy'); src.root.mkdir()
    final_state(src,font); approval(src)
    legacy_state.export_episode(src,{**BASE,'target_revision':'r001'})
    dest=Workspace(tmp_path/'new'); dest.root.mkdir()
    migrated=migrate_project(dest,{**BASE,'source_root':str(src.root)})
    assert migrated['validation']['decision']=='pass'
    assert sorted(p.name for p in dest.root.rglob('*.json'))==['episode.json','series.json']
    shutil.rmtree(src.root)
    assert state.validate_episode(dest,{**BASE,'stage':'final'})['decision']=='pass'
    assert state.export_episode(dest,{**BASE,'target_revision':'r001'})['manifest']['ordered_panels']
    with pytest.raises(ToolError,match='already exists'):
        migrate_project(dest,{**BASE,'source_root':str(src.root)})
