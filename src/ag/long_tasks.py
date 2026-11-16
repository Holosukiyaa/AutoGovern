"""One append-only structured authority for long goals; reads have no side effects."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from contextvars import ContextVar
_PROOF_READ=ContextVar("long_goal_proof_read",default=False)
from pathlib import Path
from typing import Any
from .managed import ChainBroken, real_root
from .store import project_dir
SCHEMA = 'ag.long-goal.v1'
COLLECTIONS = ('results','constraints','facts','plans','dependencies','investigations','capabilities','evidence','decisions','iterations')
KINDS = {'fact':'facts','plan':'plans','investigation':'investigations','capability':'capabilities'}

class LongTaskConflict(ChainBroken):
    def __init__(self, expected, current, differences):
        self.code = 'long-task-revision-conflict'
        self.details = {'code':self.code,'expected_revision':expected,'current_revision':current,'diff':differences}
        super().__init__(f'{self.code}: expected {expected}, current {current}; reload history/diff')

def _fail(message):
    raise ChainBroken('long-task-' + message)

def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)

def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()

def _id(value='', prefix='item'):
    text = str(value or f'{prefix}-{uuid.uuid4().hex[:12]}')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', text):
        _fail('invalid-id: ' + text)
    return text

def _text(value, label):
    if not isinstance(value,str) or not value.strip():
        _fail('missing-' + label)
    return value

def _source(value):
    if not isinstance(value,dict):
        _fail('source-required: use {kind,ref,text?}')
    _text(value.get('kind'),'source-kind'); _text(value.get('ref'),'source-ref')
    return copy.deepcopy(value)

def storage_path(root):
    return project_dir(Path(root)) / 'long-goals.sqlite3'

def _open(root, *, write=False, create=False):
    path = storage_path(root)
    if not path.is_file() and not create:
        if write: _fail('not-found')
        return None
    existed=path.exists()
    if create: path.parent.mkdir(parents=True,exist_ok=True)
    con=None
    try:
        con = sqlite3.connect(path.as_uri() + ('?mode=rwc' if create else '?mode=rw' if write else '?mode=ro'),uri=True,timeout=15,isolation_level=None)
        con.row_factory = sqlite3.Row
        if create and not existed and not con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            con.executescript("BEGIN IMMEDIATE; CREATE TABLE metadata(schema TEXT NOT NULL); INSERT INTO metadata VALUES('ag.long-goal.v1'); CREATE TABLE events(goal_id TEXT NOT NULL,revision INTEGER NOT NULL,ts TEXT NOT NULL,operation TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL,PRIMARY KEY(goal_id,revision)); COMMIT;")
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok' or con.execute('SELECT schema FROM metadata').fetchall()[0][0]!=SCHEMA:
            con.close(); _fail('corrupt-store')
        return con
    except (sqlite3.Error,IndexError) as exc:
        if con is not None: con.close()
        _fail(f'corrupt-store: {path}: {exc}')

def _events(con, goal_id):
    try:
        rows = con.execute('SELECT * FROM events WHERE goal_id=? ORDER BY revision',(goal_id,)).fetchall()
        events=[]; previous=''
        for expected,row in enumerate(rows,1):
            operation=json.loads(row['operation'])
            body={'goal_id':goal_id,'revision':expected,'ts':row['ts'],'operation':operation,'previous_hash':previous}
            if row['revision']!=expected or row['previous_hash']!=previous or row['event_hash']!=_hash(body): _fail('corrupt-history: '+goal_id)
            events.append({**body,'event_hash':row['event_hash']}); previous=row['event_hash']
        return events
    except (ValueError,TypeError,sqlite3.Error) as exc:
        _fail(f'corrupt-history: {goal_id}: {exc}')

def _find(goal, collection, identity):
    for row in goal[collection]:
        if row['id']==identity: return row
    _fail(f'missing-reference: {collection}/{identity}')

def _result_ids(goal, ids, *, default_all=False):
    if ids is None and default_all: return [r['id'] for r in goal['results'] if r['state']=='active']
    if not isinstance(ids,list) or not ids or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids): _fail('result-ids-required')
    for identity in ids: _find(goal,'results',identity)
    return list(ids)

def _row(op, revision, *, prefix='item'):
    row={k:copy.deepcopy(v) for k,v in op.items() if k!='type'}
    row['id']=_id(row.get('id'),prefix); row['revision']=revision
    return row

def _append(goal,collection,row):
    if any(item['id']==row['id'] for name in COLLECTIONS for item in goal[name]): _fail('duplicate-id: '+row['id'])
    goal[collection].append(row)

def _graph(goal):
    edges={r['id']:[] for r in goal['results']}
    for row in goal['results']:
        if row.get('parent_result_id'):
            _find(goal,'results',row['parent_result_id']); edges[row['id']].append(row['parent_result_id'])
    for row in goal['dependencies']:
        if row.get('state')=='removed': continue
        _find(goal,'results',row['result_id']); _find(goal,'results',row['depends_on'])
        edges[row['result_id']].append(row['depends_on'])
        if row.get('parent_result_id'): _find(goal,'results',row['parent_result_id'])
    visiting=set(); visited=set()
    def visit(identity):
        if identity in visiting: _fail('dependency-cycle: '+identity)
        if identity in visited: return
        visiting.add(identity)
        for other in edges[identity]: visit(other)
        visiting.remove(identity); visited.add(identity)
    for identity in edges: visit(identity)

def _return_to(goal,value):
    if not isinstance(value,dict) or not value.get('result_id'): _fail('return-point-required')
    _find(goal,'results',value['result_id'])
    if value.get('goal_id',goal['goal_id'])!=goal['goal_id']: _fail('return-point-outside-goal')

def _intent_changes(goal,changes):
    if not isinstance(changes,list) or not changes: _fail('changes-required')
    for change in changes:
        if not isinstance(change,dict): _fail('invalid-change')
        target=change.get('target'); field=change.get('field'); value=copy.deepcopy(change.get('value'))
        if target=='goal' and field=='title': goal['title']=_text(value,'title')
        elif target in {'result','constraint'} and field in ({'text','state','parent_result_id'} if target=='result' else {'text','scope','state'}):
            row=_find(goal,'results' if target=='result' else 'constraints',str(change.get('id') or ''))
            if field=='state' and value not in {'active','removed','superseded'}: _fail('invalid-intent-state')
            if field=='text': _text(value,'text')
            if field=='scope' and value!=['*']: _result_ids(goal,value)
            row[field]=value
        elif target in {'add_result','add_constraint'}:
            payload=dict(value) if isinstance(value,dict) else {}; payload['type']=target
            payload.setdefault('source',change.get('source') or goal['source']); payload['id']=_id(payload.get('id'),target[4:])
            _reduce(goal,payload,goal['revision']+1,intent_change=True)
        else: _fail('invalid-intent-change')
    _graph(goal)

def _reduce(goal,op,revision,*,intent_change=False):
    kind=op['type']
    common={'type','id','source'}
    allowed={
      'add_result':{'text','state','parent_result_id'},
      'add_constraint':{'text','state','scope'},
      'add_dependency':{'result_id','depends_on','state','reason','parent_result_id','return_to'},
      'update_dependency':{'changes'},'propose_change':{'changes','reason'},
      'reject_proposal':{'reason'},'set_return_to':{'return_to'},
      'bind_iteration':{'task_id','contribution','result_ids','return_to','package_fingerprint','authorization_identity','intent_revision','reviewed_intent_revision','input_fingerprints','state'},
      'update_iteration':{'changes'},
      'add_evidence':{'task_id','candidate','report_id','check_id','package_fingerprint','input_fingerprints','result_ids','goal_id','intent_revision','reviewed_intent_revision','delivery_proof','description'},
      'confirm_coverage':{'evidence_id','result_ids','rationale'},
      '_authorize':{'proposal_id','authorization'},
    }
    if kind.startswith('add_') and kind[4:] in KINDS: fields={'text','state','result_ids','value','candidate','reason','availability','supersedes'}
    elif kind.startswith('update_') and kind[7:] in KINDS: fields={'changes'}
    else: fields=allowed.get(kind,set())
    if set(op)-common-fields: _fail('unexpected-operation-fields: '+','.join(sorted(set(op)-common-fields)))
    if kind in {'add_result','add_constraint'}:
        if not intent_change and goal.get('authorized_intent_revision'): _fail('intent-change-requires-proposal')
        collection='results' if kind=='add_result' else 'constraints'; row=_row(op,revision,prefix=collection[:-1])
        _text(row.get('text'),collection+'-text'); row.setdefault('state','active')
        if row['state']!='active': _fail('new-intent-row-must-be-active')
        if collection=='constraints':
            row.setdefault('scope',['*'])
            if row['scope']!=['*']: _result_ids(goal,row['scope'])
        _append(goal,collection,row)
        if not intent_change: goal['intent_revision']+=1
    elif kind.startswith('add_') and kind[4:] in KINDS:
        collection=KINDS[kind[4:]]; row=_row(op,revision,prefix=kind[4:]); _text(row.get('text'),kind[4:]+'-text')
        row.setdefault('result_ids',[r['id'] for r in goal['results']]); _result_ids(goal,row['result_ids'])
        row.setdefault('state','unknown' if collection in {'facts','capabilities'} else 'open')
        if row['state'] in {'verified','passed','complete','completed'}: _fail('fact-cannot-complete-result')
        _append(goal,collection,row)
    elif kind.startswith('update_') and kind[7:] in KINDS:
        row=_find(goal,KINDS[kind[7:]],_text(op.get('id'),'id')); changes=op.get('changes')
        if not isinstance(changes,dict) or not changes or set(changes)-{'text','state','result_ids','value','candidate','reason','availability','supersedes'}: _fail('invalid-fact-changes')
        if 'text' in changes: _text(changes['text'],'text')
        if 'result_ids' in changes: _result_ids(goal,changes['result_ids'])
        if changes.get('state') in {'verified','passed','complete','completed'}: _fail('fact-cannot-complete-result')
        row.update(copy.deepcopy(changes)); row.update(source=op['source'],revision=revision)
    elif kind in {'add_dependency','update_dependency'}:
        if kind=='add_dependency':
            row=_row(op,revision,prefix='dependency'); row.setdefault('state','unknown'); row.setdefault('parent_result_id',row.get('result_id')); row.setdefault('return_to',{'result_id':row.get('result_id')}); _append(goal,'dependencies',row)
        else:
            row=_find(goal,'dependencies',_text(op.get('id'),'id')); changes=op.get('changes')
            if not isinstance(changes,dict) or not changes or set(changes)-{'state','reason','depends_on','parent_result_id','return_to'}: _fail('invalid-dependency-changes')
            row.update(copy.deepcopy(changes)); row.update(source=op['source'],revision=revision)
        if row.get('state') not in {'unknown','blocked','ready','removed'}: _fail('invalid-dependency-state')
        _text(row.get('result_id'),'dependency-result'); _text(row.get('depends_on'),'dependency-target'); _return_to(goal,row.get('return_to'))
    elif kind=='propose_change':
        trial=copy.deepcopy(goal); _intent_changes(trial,op.get('changes')); row=_row(op,revision,prefix='decision')
        row.update(state='pending',base_intent_revision=goal['intent_revision'],proposed_intent_revision=goal['intent_revision']+1)
        row['preview_hash']=_hash({'goal_id':goal['goal_id'],'base_intent_revision':goal['intent_revision'],'changes':row['changes']}); _append(goal,'decisions',row)
    elif kind=='_authorize':
        if op.get('proposal_id'):
            row=_find(goal,'decisions',op['proposal_id'])
            if row['state']!='pending' or row['base_intent_revision']!=goal['intent_revision']: _fail('stale-proposal')
            _intent_changes(goal,row['changes']); goal['intent_revision']+=1; row.update(state='accepted',authorization=op['authorization'],revision=revision)
        goal['authorized_intent_revision']=goal['intent_revision']; goal['authorization']=copy.deepcopy(op['authorization'])
    elif kind=='reject_proposal':
        row=_find(goal,'decisions',_text(op.get('id'),'id'))
        if row['state']!='pending': _fail('proposal-not-pending')
        row.update(state='rejected',reason=_text(op.get('reason'),'reason'),source=op['source'],revision=revision)
    elif kind=='add_evidence':
        row=_row(op,revision,prefix='evidence'); _result_ids(goal,row.get('result_ids'))
        for field in ('task_id','candidate','report_id','check_id','package_fingerprint'): _text(row.get(field),'evidence-'+field)
        if not isinstance(row.get('input_fingerprints'),dict) or set(row['input_fingerprints'])!=set(row['result_ids']) or not row.get('delivery_proof'): _fail('evidence-proof-required')
        row['coverage']=[]; _append(goal,'evidence',row)
    elif kind=='confirm_coverage':
        row=_find(goal,'evidence',_text(op.get('evidence_id'),'evidence-id')); selected=_result_ids(goal,op.get('result_ids'))
        if set(selected)-set(row['result_ids']): _fail('coverage-outside-evidence-scope')
        row['coverage'].append({'result_ids':selected,'rationale':_text(op.get('rationale'),'coverage-rationale'),'source':op['source'],'revision':revision})
    elif kind=='bind_iteration':
        row=_row(op,revision,prefix='iteration'); _text(row.get('task_id'),'iteration-task'); _text(row.get('contribution'),'iteration-contribution'); _result_ids(goal,row.get('result_ids')); _text(row.get('package_fingerprint'),'iteration-package')
        row.setdefault('state','active'); _return_to(goal,row.get('return_to')); _append(goal,'iterations',row); goal['return_to']=copy.deepcopy(row['return_to'])
    elif kind=='update_iteration':
        row=_find(goal,'iterations',_text(op.get('id'),'id')); changes=op.get('changes')
        if not isinstance(changes,dict) or not changes or set(changes)-{'state','candidate','reason','return_to'}: _fail('invalid-iteration-changes')
        if changes.get('state',row['state']) not in {'active','returned','blocked','abandoned'}: _fail('invalid-iteration-state')
        if 'return_to' in changes: _return_to(goal,changes['return_to'])
        row.update(copy.deepcopy(changes)); row.update(source=op['source'],revision=revision); goal['return_to']=copy.deepcopy(row['return_to'])
    elif kind=='set_return_to':
        _return_to(goal,op.get('return_to')); goal['return_to']=copy.deepcopy(op['return_to'])
    else: _fail('unsupported-operation: '+str(kind))
    _graph(goal)

def _replay(events):
    if not events: _fail('not-found')
    first=events[0]; created=first['operation']
    if created.get('type')!='create': _fail('corrupt-history: missing creation')
    goal={'schema':SCHEMA,'goal_id':first['goal_id'],'title':created['title'],'original':created['original'],'source':created['source'],'revision':1,'intent_revision':1,'authorized_intent_revision':0,'return_to':None,'created_at':first['ts'],'updated_at':first['ts'],**{name:[] for name in COLLECTIONS}}
    for name,kind in (('results','add_result'),('constraints','add_constraint')):
        for row in created.get(name,[]): _reduce(goal,{'type':kind,**row},1,intent_change=True)
    for event in events[1:]:
        _reduce(goal,event['operation'],event['revision']); goal.update(revision=event['revision'],updated_at=event['ts'])
    return goal

def _append_event(con,goal_id,operation,events):
    body={'goal_id':goal_id,'revision':len(events)+1,'ts':datetime.now(timezone.utc).isoformat(),'operation':operation,'previous_hash':events[-1]['event_hash'] if events else ''}
    signature=_hash(body); con.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(goal_id,body['revision'],body['ts'],_json(operation),body['previous_hash'],signature))
    return {**body,'event_hash':signature}

def create_goal(root,title,original,source,*,results=None,constraints=None,goal_id=''):
    root=real_root(Path(root))
    if not root.is_dir(): _fail('project-not-found')
    identity=_id(goal_id,'goal'); provenance=_source(source)
    operation={'type':'create','title':_text(title,'title'),'original':_text(original,'original'),'source':provenance,'results':[],'constraints':[]}
    for name,values in (('results',results or []),('constraints',constraints or [])):
        for item in values:
            if not isinstance(item,dict): _fail('invalid-initial-item')
            row=copy.deepcopy(item); row['id']=_id(row.get('id'),name[:-1]); row['source']=_source(row.get('source') or provenance); operation[name].append(row)
    _replay([{'goal_id':identity,'revision':1,'ts':'','operation':operation}])
    con=_open(root,write=True,create=True)
    try:
        con.execute('BEGIN IMMEDIATE')
        if _events(con,identity): _fail('duplicate-goal: '+identity)
        _append_event(con,identity,operation,[]); con.execute('COMMIT')
    finally: con.close()
    return read_goal(root,identity)

def _load(root,goal_id):
    _id(goal_id); con=_open(Path(root))
    if con is None: _fail('not-found: '+goal_id)
    try:
        events=_events(con,goal_id); return _replay(events),events
    finally: con.close()

def _ancestors(goal,selected):
    ordered=list(selected); index=0
    while index<len(ordered):
        identity=ordered[index]; row=_find(goal,'results',identity); parents=[row.get('parent_result_id')]
        for dep in goal['dependencies']:
            if dep.get('state')!='removed' and dep['result_id']==identity: parents.extend([dep['depends_on'],dep.get('parent_result_id')])
        for parent in parents:
            if parent and parent not in ordered: ordered.append(parent)
        index+=1
    return ordered

def _context(goal,result_id):
    relevant=set(_ancestors(goal,[result_id])); rows={}
    for name in ('results','constraints','facts','capabilities','dependencies'):
        def include(row):
            if name=='results': return row['id'] in relevant
            if name=='constraints': return row.get('state')=='active' and (row.get('scope')==['*'] or bool(set(row.get('scope',[])) & relevant))
            if name=='dependencies': return row['result_id'] in relevant and row.get('state')!='removed'
            return bool(set(row.get('result_ids',[])) & relevant)
        rows[name]=[{k:copy.deepcopy(v) for k,v in row.items() if k not in {'source','revision'}} for row in goal[name] if include(row)]
    candidates=[{'id':row['id'],'candidate':row['candidate']} for row in goal['iterations'] if result_id in row['result_ids'] and row.get('candidate')]
    return {'goal_id':goal['goal_id'],'title':goal['title'],'inputs':rows,'candidates':candidates}

def _delivery_proof(root,row):
    token=_PROOF_READ.set(True)
    try: return _delivery_proof_inner(root,row)
    finally: _PROOF_READ.reset(token)

def _delivery_proof_inner(root,row):
    from .delivery import build_delivery_snapshot
    from .store import load_task_timeline
    from .loop import load_task
    from .managed import project_key
    snapshot=build_delivery_snapshot(Path(root),str(row['task_id']))
    if not snapshot.get('found'): _fail('evidence-task-not-found')
    link=snapshot.get('goal_link') or {}
    if link.get('goal_id')!=row.get('goal_id') or set(row['result_ids'])-set(link.get('result_ids') or []): _fail('evidence-task-scope-mismatch')
    if link.get('intent_revision')!=row.get('reviewed_intent_revision'): _fail('evidence-task-intent-mismatch')
    verified=(snapshot.get('progress') or {}).get('verified') or []
    proofs=[item for item in verified if item.get('candidate')==row['candidate'] and item.get('report_id')==row['report_id']]
    if not proofs: _fail('evidence-not-currently-verified')
    timeline=load_task_timeline(Path(root),row['task_id']); verifies=[step['verify'] for step in timeline['steps'] if isinstance(step.get('verify'),dict)]
    active=load_task(project_key(real_root(Path(root)))) or {}
    if active.get('id')==row['task_id'] and isinstance(active.get('verify'),dict): verifies.append(active['verify'])
    matching=[item for item in verifies if item.get('candidate')==row['candidate'] and (item.get('switch') or {}).get('report_id')==row['report_id']]
    if not matching or (matching[-1].get('check_selection') or {}).get('sha256')!=row['check_id']: _fail('evidence-check-binding-mismatch')
    receipt_inputs=matching[-1].get('long_goal_inputs')
    if not isinstance(receipt_inputs,dict): _fail('evidence-receipt-input-binding-missing')
    from .store import list_llm_events
    reports=list_llm_events(Path(root),'switch_event',limit=0,task_id=row['task_id'],report_id=row['report_id'])
    if len(reports)!=1 or reports[0].get('long_goal_inputs')!=receipt_inputs: _fail('evidence-review-input-binding-mismatch')
    if receipt_inputs.get('candidate')!=row['candidate'] or receipt_inputs.get('check_id')!=row['check_id']: _fail('evidence-receipt-check-candidate-mismatch')

    if receipt_inputs.get('goal_id')!=row.get('goal_id') or receipt_inputs.get('reviewed_intent_revision')!=row.get('reviewed_intent_revision') or receipt_inputs.get('intent_revision')!=row.get('intent_revision'): _fail('evidence-receipt-intent-binding-mismatch')
    if set(row['result_ids'])-set(receipt_inputs.get('result_ids') or []): _fail('evidence-receipt-scope-mismatch')
    if receipt_inputs.get('package_fingerprint')!=row.get('package_fingerprint'): _fail('evidence-receipt-package-mismatch')
    if any((receipt_inputs.get('input_fingerprints') or {}).get(identity)!=row['input_fingerprints'].get(identity) for identity in row['result_ids']): _fail('evidence-receipt-inputs-mismatch')

    return {'task_id':row['task_id'],'candidate':row['candidate'],'report_id':row['report_id'],'check_id':row['check_id'],'source':proofs[0].get('source'),'checks':proofs[0].get('checks'),'readiness':snapshot.get('readiness'),'long_goal_inputs':receipt_inputs,'product_tree':matching[-1].get('product_tree') or row['candidate']}

def _candidate_scope_changes(root, goal, evidence, proof, identities):
    """Read actual later AG candidates; user-supplied iteration candidates are not proof.

    Compare product files with Git's read-only diff rather than tree_digest, which
    writes object data. Ticket-local check files are not product candidates.
    """
    import subprocess
    from .loop import load_task
    from .managed import project_key
    from .store import load_task_timeline
    active=load_task(project_key(real_root(Path(root)))) or {}
    later=[]
    for iteration in goal['iterations']:
        if iteration['revision']>evidence['revision'] and iteration['task_id']!=evidence['task_id'] and iteration['task_id'] not in later:
            later.append(iteration['task_id'])
    if active.get('id') and active['id']!=evidence['task_id'] and (active.get('long_goal') or {}).get('goal_id')==goal['goal_id'] and active['id'] not in later:
        later.append(active['id'])
    changed={}
    product=proof['product_tree']
    for task_id in later:
        if active.get('id')==task_id:
            task=active
        else:
            timeline=load_task_timeline(Path(root),task_id)
            if timeline.get('diagnostics'): _fail('candidate-history-conflict')
            task={}
            for step in timeline['steps']:
                if isinstance(step.get('task'),dict) and step['task'].get('id')==task_id: task.update(step['task'])
        link=task.get('long_goal') or {}
        if link.get('goal_id')!=goal['goal_id'] or task.get('process')=='abandoned': continue
        affected=[identity for identity in identities if set(_ancestors(goal,[identity])) & set(link.get('result_ids') or [])]
        if not affected: continue
        process=task.get('process','active')
        if process=='completed':
            head=task.get('merged_head')
            if not head: _fail('candidate-completed-head-missing')
            comparison=subprocess.run(['git','--no-optional-locks','-C',str(root),'rev-parse',str(head)+'^{tree}'],capture_output=True,text=True,encoding='utf-8')
            if comparison.returncode: _fail('candidate-completed-tree-unavailable')
            different=comparison.stdout.strip()!=product
        else:
            tree=Path(str(task.get('worktree') or ''))
            if not tree.is_dir(): _fail('candidate-worktree-unavailable')
            comparison=subprocess.run(['git','--no-optional-locks','-C',str(tree),'diff','--quiet',product,'--'],capture_output=True)
            if comparison.returncode not in {0,1}: _fail('candidate-comparison-unavailable')
            untracked=subprocess.run(['git','--no-optional-locks','-C',str(tree),'ls-files','--others','--exclude-standard','-z'],capture_output=True)
            if untracked.returncode: _fail('candidate-untracked-unavailable')
            product_additions=[name for name in untracked.stdout.split(b'\0') if name and not name.replace(b'\\',b'/').startswith(b'.ag-check/')]
            different=bool(comparison.returncode or product_additions)
        if different:
            for identity in affected: changed[identity]='candidate-changed:'+identity+':task:'+task_id
    return changed

def _view(root,goal,*,check_delivery=True):
    goal=copy.deepcopy(goal)
    for evidence in goal['evidence']:
        valid_ids=[identity for identity in evidence['result_ids'] if evidence['input_fingerprints'].get(identity)==_hash(_context(goal,identity))]
        reasons=['inputs-changed:'+identity for identity in evidence['result_ids'] if identity not in valid_ids]
        if check_delivery and not _PROOF_READ.get():
            try:
                proof=_delivery_proof(root,evidence)
                changed=_candidate_scope_changes(root,goal,evidence,proof,valid_ids)
                reasons.extend(changed.values()); valid_ids=[identity for identity in valid_ids if identity not in changed]
            except ChainBroken as exc: reasons.append(str(exc)); valid_ids=[]
        evidence.update(valid=not reasons,valid_result_ids=valid_ids,invalidation_reasons=reasons)
    verified=set()
    for evidence in goal['evidence']:
        for coverage in evidence['coverage']: verified.update(set(coverage['result_ids']) & set(evidence['valid_result_ids']))
    covered=set(verified); verified=set()
    def dependency_valid(identity, seen):
        if identity not in covered or identity in seen: return False
        if _find(goal,'results',identity).get('state')!='active': return False
        deps=[r for r in goal['dependencies'] if r['result_id']==identity and r.get('state')!='removed']
        return all(r.get('state')=='ready' and dependency_valid(r['depends_on'],seen | {identity}) for r in deps)
    for identity in covered:
        if dependency_valid(identity,set()): verified.add(identity)
    for result in goal['results']:
        blockers=[row['id'] for row in goal['dependencies'] if row['result_id']==result['id'] and row.get('state')!='removed' and (row.get('state')!='ready' or row['depends_on'] not in verified)]
        result['status']='removed' if result.get('state')!='active' else 'blocked' if blockers else 'verified' if result['id'] in verified else 'unverified'
        result['blockers']=blockers; result['input_fingerprint']=_hash(_context(goal,result['id']))
    active=[row for row in goal['results'] if row.get('state')=='active']; pending=[row for row in goal['decisions'] if row['state']=='pending']
    goal['status']='verified' if active and all(row['status']=='verified' for row in active) and not pending and goal['authorized_intent_revision']==goal['intent_revision'] else 'pending-decision' if pending else 'draft' if not goal['authorized_intent_revision'] else 'active'
    goal['remaining']=[{'id':row['id'],'text':row['text'],'status':row['status'],'blockers':row['blockers']} for row in active if row['status']!='verified']; goal['authority']=str(storage_path(root))
    return goal

def read_goal(root,goal_id):
    goal,_=_load(root,goal_id); return _view(root,goal)

def list_goals(root):
    con=_open(Path(root))
    if con is None: return []
    try: return [_view(root,_replay(_events(con,row[0]))) for row in con.execute('SELECT DISTINCT goal_id FROM events ORDER BY goal_id')]
    finally: con.close()

def goal_history(root,goal_id,*,since_revision=0):
    _,events=_load(root,goal_id); return [event for event in events if event['revision']>since_revision]

def goal_diff(root,goal_id,since_revision):
    goal,events=_load(root,goal_id)
    if isinstance(since_revision,bool) or not isinstance(since_revision,int) or not 0<=since_revision<=goal['revision']: _fail('invalid-diff-revision')
    return {'goal_id':goal_id,'from_revision':since_revision,'to_revision':goal['revision'],'intent_revision':goal['intent_revision'],'events':[e for e in events if e['revision']>since_revision]}

def apply_operation(root,goal_id,operation,expected_revision,*,source=None):
    return _apply(root,goal_id,operation,expected_revision,source=source)

def _apply(root,goal_id,operation,expected_revision,*,source=None,internal=False):
    if isinstance(expected_revision,bool) or not isinstance(expected_revision,int) or expected_revision<1: _fail('expected-revision-required')
    if not isinstance(operation,dict) or not isinstance(operation.get('type'),str): _fail('typed-operation-required')
    op=copy.deepcopy(operation)
    if op['type'].startswith('_') and not internal: _fail('internal-operation-forbidden')
    op['source']=_source(source or op.get('source'))
    if op['type'].startswith('add_') or op['type'] in {'bind_iteration','propose_change'}: op['id']=_id(op.get('id'),op['type'].removeprefix('add_'))
    if op['type']=='propose_change':
        for change in op.get('changes',[]):
            if change.get('target') in {'add_result','add_constraint'} and isinstance(change.get('value'),dict): change['value']['id']=_id(change['value'].get('id'),change['target'][4:])
    con=_open(Path(root),write=True)
    try:
        con.execute('BEGIN IMMEDIATE'); events=_events(con,goal_id); goal=_replay(events)
        if goal['revision']!=expected_revision: raise LongTaskConflict(expected_revision,goal['revision'],[e for e in events if e['revision']>expected_revision])
        if op['type'] in {'add_evidence','confirm_coverage'}:
            evidence=op if op['type']=='add_evidence' else _find(goal,'evidence',str(op.get('evidence_id') or ''))
            if op['type']=='add_evidence':
                _result_ids(goal,evidence.get('result_ids')); iterations=[r for r in goal['iterations'] if r['task_id']==evidence.get('task_id')]
                if not iterations or set(evidence['result_ids'])-set(iterations[-1]['result_ids']): _fail('evidence-no-matching-work-package')
                inputs={identity:_hash(_context(goal,identity)) for identity in evidence['result_ids']}
                if evidence.get('input_fingerprints')!=inputs: _fail('evidence-inputs-stale')
                op['goal_id']=goal_id
                op['intent_revision']=iterations[-1]['intent_revision']
                op['reviewed_intent_revision']=iterations[-1].get('reviewed_intent_revision',iterations[-1]['intent_revision'])
                op['delivery_proof']=_delivery_proof(root,op)
            else:
                if op['source'].get('kind')!='mentor-review': _fail('coverage-requires-mentor-review-source')
                selected=_result_ids(goal,op.get('result_ids'))
                if set(selected)-set(evidence['result_ids']): _fail('coverage-outside-evidence-scope')
                if any(evidence['input_fingerprints'].get(identity)!=_hash(_context(goal,identity)) for identity in selected): _fail('evidence-inputs-stale')
                _delivery_proof(root,evidence)
        if op['type']=='bind_iteration':
            from .loop import load_task
            from .managed import project_key
            active=load_task(project_key(real_root(Path(root)))) or {}; link=active.get('long_goal') or {}
            if active.get('id')!=op.get('task_id') or link.get('goal_id')!=goal_id or set(op.get('result_ids') or [])-set(link.get('result_ids') or []): _fail('iteration-task-scope-mismatch')
            auth=goal.get('authorization') or {}
            if auth.get('task_id')!=active['id'] or auth.get('intent_identity')!=active.get('intent_identity') or not active.get('worktree_ready'): _fail('iteration-task-not-authorized')
            op['reviewed_intent_revision']=link['intent_revision']
            op['authorization_identity']=active['intent_identity']
            _result_ids(goal,op.get('result_ids')); package=work_package(root,goal_id,op['result_ids'],contribution=op.get('contribution',''),task_id=op.get('task_id',''))
            if op.get('package_fingerprint')!=package['fingerprint']: _fail('work-package-stale')
            op['intent_revision']=goal['intent_revision']; op['input_fingerprints']={identity:_hash(_context(goal,identity)) for identity in op['result_ids']}
        trial=copy.deepcopy(goal); _reduce(trial,op,expected_revision+1); _append_event(con,goal_id,op,events); con.execute('COMMIT')
    except sqlite3.Error as exc: _fail('store-write-failed: '+str(exc))
    finally: con.close()
    return read_goal(root,goal_id)

def work_package(root,goal_id,result_ids=None,*,contribution='',task_id=''):
    raw,_=_load(root,goal_id); goal=_view(root,raw); selected=_result_ids(raw,result_ids,default_all=True); ancestry=_ancestors(raw,selected); relevant=set(ancestry)
    package={'schema':'ag.long-work-package.v1','goal_id':goal_id,'title':goal['title'],'original':goal['original'],'source':goal['source'],'revision':goal['revision'],'intent_revision':goal['intent_revision'],'authorized_intent_revision':goal['authorized_intent_revision'],'result_ids':selected,'contribution':contribution,'task_id':task_id,'results':[r for r in goal['results'] if r['id'] in selected],'ancestor_results':[r for r in goal['results'] if r['id'] in relevant-set(selected)],'constraints':[r for r in goal['constraints'] if r.get('state')=='active' and (r.get('scope')==['*'] or set(r.get('scope',[])) & relevant)],'dependencies':[r for r in goal['dependencies'] if r['result_id'] in relevant and r.get('state')!='removed'],'remaining':goal['remaining'],'pending_decisions':[r for r in goal['decisions'] if r['state']=='pending'],'return_to':goal['return_to'] or ({'goal_id':goal_id,'result_id':selected[0]} if selected else None),'authority':goal['authority']}
    for name in ('facts','plans','investigations','capabilities','evidence'): package[name]=[r for r in goal[name] if set(r.get('result_ids',[])) & relevant]
    package['input_fingerprints']={identity:_hash(_context(raw,identity)) for identity in selected}
    package['sources']=[{'collection':name,'id':r['id'],'revision':r.get('revision'),'source':r.get('source')} for name in COLLECTIONS for r in goal[name] if name in {'results','constraints'} or r in package.get(name,[])]
    package['fingerprint']=_hash(package)
    return package

def ticket_projection(root,goal_id,*,pending=False,result_ids=None,contribution=''):
    raw,_=_load(root,goal_id)
    if pending:
        proposals=[r for r in raw['decisions'] if r['state']=='pending']
        if len(proposals)!=1: _fail('projection-requires-single-pending-proposal')
        proposal=proposals[0]
        if proposal['base_intent_revision']!=raw['intent_revision']: _fail('stale-proposal')
        _intent_changes(raw,proposal['changes']); raw['intent_revision']+=1
    selected=_result_ids(raw,result_ids,default_all=True); ancestry=set(_ancestors(raw,selected))
    lines=['# 票','','## 意图',raw['title'],'',f"长期目标: {goal_id}; 意图版本: {raw['intent_revision']}",'','用户原话：',raw['original'],'','来源：'+_json(raw['source']),'']
    if contribution: lines.extend(['本轮贡献：'+contribution,''])
    for row in raw['results']:
        if row['state']=='active' and row['id'] in selected: lines.append(f"anchor: [{row['id']}] {row['text']}")
    lines.extend(['','## Parent remaining commitments (context; outside this ticket acceptance)'])
    for row in raw['results']:
        if row['state']=='active' and row['id'] not in selected: lines.append(f"- [{row['id']}] {row['text']}")
    lines.extend(['','## 红线']); constraints=[r for r in raw['constraints'] if r.get('state')=='active' and (r['scope']==['*'] or set(r['scope']) & ancestry)]
    if not constraints: lines.append('- 沿现有独立审校、人工 confirm-map 与 ready 门禁施工；本投影不授予权限。')
    for row in constraints: lines.append(f"- [{row['id']}] {row['text']}")
    lines.extend(['','## 长期记录来源','authority: '+str(storage_path(root)),'projection: one-way; do not import edits',''])
    return '\n'.join(lines)

# Binding authority lives in authorization.new_long_binding; there is no second
# snapshot/preview interpretation here.
export_ticket=ticket_projection
history=goal_history
diff=goal_diff


def record_authorization(root,goal_id,*,task_id,intent_revision,proposal_ids,preview_token,authorization):
    """Integration hook: re-read original approval and thaw; ignore caller booleans."""
    from .authorization import validate_confirmation, new_long_binding
    from .loop import load_task
    from .managed import project_key
    from .store import load_task_timeline
    from .decisions import pending_decisions
    active=load_task(project_key(real_root(Path(root)))) or {}
    if active.get('id')!=task_id: _fail('authorization-task-not-active')
    binding=active.get('long_goal')
    if not isinstance(binding,dict) or binding.get('goal_id')!=goal_id or binding.get('intent_revision')!=intent_revision or binding.get('proposal_ids',[])!=proposal_ids or binding.get('preview_token')!=preview_token: _fail('authorization-goal-binding-mismatch')
    goal=read_goal(root,goal_id)
    already=goal.get('authorization',{})
    same_authorization=already.get('intent_identity')==active.get('intent_identity') and already.get('preview_token')==preview_token
    if not same_authorization:
        current=new_long_binding(Path(root),goal_id,result_ids=binding['result_ids'],contribution=binding['contribution'],pending=bool(proposal_ids))
        if current['preview_token']!=preview_token: _fail('authorization-preview-stale')
    # Pending proposal acceptance is inside the already successful human gate.
    # Recheck its exact confirmation path, rather than normal construction (which
    # correctly refuses all still-pending proposals outside this boundary).
    validate_confirmation(Path(root),active)
    from .freeze import _tracked_files, assert_frozen
    import os
    assert_frozen(_tracked_files(Path(root)))
    if active.get('thaw_error') or not active.get('worktree_ready'): _fail('authorization-thaw-failed')
    for file in _tracked_files(Path(active['worktree'])):
        try:
            descriptor=os.open(file,os.O_WRONLY); os.close(descriptor)
        except OSError as exc: _fail('authorization-live-permissions-missing: '+str(exc))
    if pending_decisions(Path(root),task_id): _fail('authorization-decisions-pending')
    timeline=load_task_timeline(Path(root),task_id)
    if timeline.get('diagnostics'): _fail('authorization-history-conflict')
    identity=active.get('intent_identity')
    approved=[row for row in timeline['steps'] if row.get('phase')=='intent-map-confirmed' and row.get('intent_identity')==identity and row.get('by')==active.get('intent_map_confirmed_by')]
    ready=[row for row in timeline['steps'] if row.get('phase')=='worktree-ready' and row.get('intent_identity')==identity]
    if not approved or not ready or not active.get('worktree_ready') or active.get('authorization_identity')!=identity: _fail('authorization-original-proof-missing')
    if len(proposal_ids)>1: _fail('authorize-one-proposal-per-reviewed-preview')
    goal=read_goal(root,goal_id)
    proof={'task_id':task_id,'intent_identity':identity,'authorization_identity':active.get('authorization_identity'),'report_id':(active.get('ticket_review') or {}).get('report_id'),'preview_token':preview_token,'approved':approved[-1],'ready':ready[-1]}
    already=goal.get('authorization',{})
    if not same_authorization:
        if goal['intent_revision']!=intent_revision: _fail('authorization-intent-revision-stale')
        goal=_apply(root,goal_id,{'type':'_authorize','proposal_id':proposal_ids[0] if proposal_ids else '', 'authorization':proof},goal['revision'],source={'kind':'confirm-map','ref':'task:'+task_id},internal=True)
    if not any(row['task_id']==task_id and row.get('authorization_identity')==identity for row in goal['iterations']):
        package=work_package(root,goal_id,binding['result_ids'],contribution=binding['contribution'],task_id=task_id)
        return apply_operation(root,goal_id,{'type':'bind_iteration','id':_id(prefix='iteration'),'task_id':task_id,'contribution':binding['contribution'],'result_ids':binding['result_ids'],'return_to':binding.get('return_to') or {'goal_id':goal_id,'result_id':binding['result_ids'][0]},'package_fingerprint':package['fingerprint'],'authorization_identity':identity,'reviewed_intent_revision':intent_revision},goal['revision'],source={'kind':'ag-task','ref':'task:'+task_id})
    return goal


def record_iteration(root,goal_id,*,task_id,contribution,process,product,return_to=None,evidence=None):
    """Record a task return; task success alone never supplies result coverage."""
    from .delivery import build_delivery_snapshot
    snapshot=build_delivery_snapshot(Path(root),task_id)
    if not snapshot.get('found'): _fail('iteration-task-not-found')
    if snapshot.get('process')!=process: _fail('iteration-process-mismatch')
    goal=read_goal(root,goal_id); matches=[row for row in goal['iterations'] if row['task_id']==task_id]
    if not matches: _fail('iteration-not-bound')
    row=matches[-1]
    if row['contribution']!=contribution: _fail('iteration-contribution-mismatch')
    state='returned' if process=='completed' else 'abandoned' if process=='abandoned' else 'blocked'
    if row.get('state')==state: return goal
    changes={'state':state,'reason':f'AG task {task_id}: {process}/{product}'}
    if return_to: changes['return_to']=return_to
    return apply_operation(root,goal_id,{'type':'update_iteration','id':row['id'],'changes':changes},goal['revision'],source={'kind':'ag-return','ref':'task:'+task_id})
