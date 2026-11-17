"""Readable Markdown long goals; SQLite is a read-only legacy history."""
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
from . import long_markdown as md
from contextlib import contextmanager
import os
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

def storage_path(root, goal_id=''):
    base=project_dir(Path(root)) / 'long'
    return base / _id(goal_id) / 'long.md' if goal_id else base

def document_path(root,goal_id):
    return storage_path(root,goal_id)

def _runtime_path(root,goal_id):
    return document_path(root,goal_id).parent / 'runtime.json'

@contextmanager
def _document_lock(path):
    lock=Path(path).with_name('.long-write.lock')
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        _fail('document-busy: '+str(path))
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)

def _runtime(root,goal_id):
    path=_runtime_path(root,goal_id)
    if not path.is_file():return {'events':[]}
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('schema')!='ag.long-markdown.runtime.v1' or not isinstance(value.get('events',[]),list):_fail('corrupt-runtime: '+str(path))
        return value
    except (ValueError,TypeError) as exc:_fail('corrupt-runtime: '+str(path)+': '+str(exc))

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

def create_goal(root,title,original,source,*,results=None,constraints=None,goal_id=''):
    root=real_root(Path(root))
    if not root.is_dir():_fail('project-not-found')
    identity=_id(goal_id,'goal'); provenance=_source(source)
    _text(title,'title');_text(original,'original')
    if '\n' in title or '\r' in title:_fail('title-must-be-one-line')
    values={}
    used_ids={item['id'] for item in list(results or [])+list(constraints or []) if isinstance(item,dict) and item.get('id')}
    for name,items in (('results',results or [{'text':original.splitlines()[0]}]),('constraints',constraints or [])):
        values[name]=[]
        for item in items:
            if not isinstance(item,dict):_fail('invalid-initial-item')
            row=copy.deepcopy(item)
            if not row.get('id'):
                number=len(values[name])+1;prefix='r' if name=='results' else 'c'
                while prefix+str(number) in used_ids:number+=1
                row['id']=prefix+str(number);used_ids.add(row['id'])
            row['id']=_id(row['id'],name[:-1]);row['source']=_source(row.get('source') or provenance);row.setdefault('state','active')
            if name=='constraints':row.setdefault('scope',['*'])
            values[name].append(row)
    path=document_path(root,identity)
    if path.exists():_fail('duplicate-goal: '+identity)
    # Never silently shadow a SQLite goal; conversion is an explicit action.
    from . import legacy_long_tasks as legacy
    if any(g['goal_id']==identity for g in legacy.list_goals(root)):_fail('legacy-goal-requires-explicit-migration: '+identity)
    content=md.render(title,original,provenance,values['results'],values['constraints'])
    document=md.Document(path,content).require()
    trial={'goal_id':identity,**copy.deepcopy(document.intent),**{name:[] for name in COLLECTIONS if name not in {'results','constraints'}}}
    _graph(trial)
    path.parent.mkdir(parents=True,exist_ok=True)
    with _document_lock(path):
        if path.exists():_fail('duplicate-goal: '+identity)
        md.atomic_write(path,document.data)
        now=datetime.now(timezone.utc).isoformat()
        runtime={'schema':'ag.long-markdown.runtime.v1','created_at':now,'updated_at':now,'events':[{'sequence':1,'goal_id':identity,'revision':document.revision,'intent_revision':document.intent_revision,'ts':now,'operation':{'type':'create','source':provenance},'document_sha256':document.sha,'intent_sha256':document.intent_sha,'after_markdown':document.text}]}
        try:md.atomic_write(_runtime_path(root,identity),(_json(runtime)+'\n').encode('utf-8'))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return read_goal(root,identity)

def _load(root,goal_id):
    _id(goal_id);path=document_path(root,goal_id)
    if not path.is_file():_fail('not-found: '+goal_id)
    document=md.Document(path)
    runtime=_runtime(root,goal_id)
    goal={'schema':'ag.long-markdown.v1','goal_id':goal_id,**copy.deepcopy(document.intent),
        'revision':document.revision,'intent_revision':document.intent_revision,
        'authorized_intent_revision':runtime.get('authorized_intent_revision',0),
        'return_to':runtime.get('return_to'),'created_at':runtime.get('created_at',''),
        'updated_at':runtime.get('updated_at',''),**{name:copy.deepcopy(runtime.get(name,[])) for name in COLLECTIONS if name not in {'results','constraints'}}}
    # Derive chronology from append order, never from content-hash revisions.
    created={}
    for ordinal,event in enumerate(runtime.get('events',[]),1):
        operation=event.get('operation') or {}
        if operation.get('id') and (operation.get('type','').startswith('add_') or operation.get('type')=='bind_iteration'):
            created.setdefault(operation['id'],ordinal)
    for name in COLLECTIONS:
        if name in {'results','constraints'}:continue
        for row in goal[name]:
            if row['id'] in created:row['created_sequence']=created[row['id']]
    if runtime.get('authorization'):goal['authorization']=copy.deepcopy(runtime['authorization'])
    # The revision is derived from visible content, never from a hidden cached goal.
    goal.update(format='markdown',read_only=False,document_path=str(path),document_sha256=document.sha,intent_sha256=document.intent_sha,
        summary={name:document.body(name).strip() for name in ('current','blocker','next')},
        issues=document.issues,outline={name:{'line':document.text[:span[0]].count('\n')+1,'anchor':name} for name,span in document.regions.items()})
    if runtime.get('authorized_intent_sha256')!=document.intent_sha and goal['authorized_intent_revision']==goal['intent_revision']:goal['authorized_intent_revision']=0
    return goal,runtime.get('events',[])

def _require_valid(goal):
    if goal.get('read_only'):_fail('legacy-read-only: use explicit long migrate')
    if goal.get('issues'):raise md.DocumentError(goal['document_path'],goal['issues'])
    _graph(goal)

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
    return {'goal_id':goal['goal_id'],'title':goal['title'],'original':goal['original'],'source':goal['source'],'intent_sha256':goal.get('intent_sha256'),'inputs':rows,'candidates':candidates}

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
        if iteration.get('created_sequence',0)>evidence.get('created_sequence',0) and iteration['task_id']!=evidence['task_id'] and iteration['task_id'] not in later:
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
    goal['remaining']=[{'id':row['id'],'text':row['text'],'status':row['status'],'blockers':row['blockers']} for row in active if row['status']!='verified']; goal['authority']=str(document_path(root,goal['goal_id']))
    return goal

def read_goal(root,goal_id):
    if not document_path(root,goal_id).is_file():
        from . import legacy_long_tasks as legacy
        goal=legacy.read_goal(root,goal_id)
        return {**goal,'format':'legacy-sqlite','read_only':True,'migration_required':True,'document_path':None,'issues':[]}
    goal,_=_load(root,goal_id)
    if goal['issues']:
        goal.update(status='invalid-markdown',remaining=[{'id':row['id'],'text':row['text'],'status':'unverified','blockers':[]} for row in goal['results']],authority=goal['document_path'])
        return goal
    return _view(root,goal)

def list_goals(root):
    base=storage_path(root);goals=[];seen=set()
    if base.is_dir():
        for path in sorted(base.glob('*/long.md')):
            goal=read_goal(root,path.parent.name);goals.append(goal);seen.add(goal['goal_id'])
    from . import legacy_long_tasks as legacy
    for goal in legacy.list_goals(root):
        if goal['goal_id'] not in seen:goals.append({**goal,'format':'legacy-sqlite','read_only':True,'migration_required':True,'issues':[]})
    return goals

def goal_history(root,goal_id,*,since_revision=0):
    if not document_path(root,goal_id).is_file():
        from . import legacy_long_tasks as legacy
        return legacy.goal_history(root,goal_id,since_revision=since_revision)
    goal,events=_load(root,goal_id)
    if since_revision==0:return events
    index=next((i for i,e in enumerate(events) if e['revision']==since_revision),None)
    if index is None:
        if goal['revision']==since_revision:return []
        return [{'sequence':len(events)+1,'revision':goal['revision'],'type':'external-edit','document_sha256':goal['document_sha256'],'notice':'Revision is not in persisted history; compare visible document.'}]
    return events[index+1:]

def goal_diff(root,goal_id,since_revision):
    goal=read_goal(root,goal_id)
    if goal.get('read_only'):
        from . import legacy_long_tasks as legacy
        return legacy.goal_diff(root,goal_id,since_revision)
    _,events=_load(root,goal_id);before=None
    for event in events:
        if event.get('revision')==since_revision:before=event.get('after_markdown')
        elif event.get('previous_revision')==since_revision and before is None:before=event.get('before_markdown')
    result={'goal_id':goal_id,'from_revision':since_revision,'to_revision':goal['revision'],'intent_revision':goal['intent_revision'],'document_sha256':goal.get('document_sha256'),'events':goal_history(root,goal_id,since_revision=since_revision)}
    if since_revision==goal['revision']:before=md.Document(document_path(root,goal_id)).text
    if before is not None:
        import difflib
        current=md.Document(document_path(root,goal_id)).text
        result['markdown_diff']=''.join(difflib.unified_diff(before.splitlines(keepends=True),current.splitlines(keepends=True),fromfile='long.md@'+str(since_revision),tofile='long.md@'+str(goal['revision'])))
    else:result['markdown_diff']=None;result['notice']='This externally edited revision was never journaled; historical text is unavailable.'
    return result

def apply_operation(root,goal_id,operation,expected_revision,*,source=None):
    return _apply(root,goal_id,operation,expected_revision,source=source)

def _records(goal,operation,source,now):
    lines=[f"- {now} · {operation['type']} · 来源 {source['kind']}: {source['ref']}"]
    kind=operation['type']
    if kind=='bind_iteration':lines.append(f"- 子票 `{operation['task_id']}` · {operation['contribution']}；尚待归档原票。")
    if kind=='update_iteration':lines.append('- 返回：'+_json(operation.get('changes',{})))
    if kind=='propose_change':lines.append('- 待决定：'+str(operation.get('reason',''))+'；不自动改变当前承诺。')
    if kind=='archive_ticket':lines.append(f"- 子票 `{operation['task_id']}` · {operation['phase']} · [独立原票]({operation['path']}) · SHA256 `{operation['sha256']}`")
    if operation.get('text'):lines.append('- '+operation['text'])
    return '\n'.join(lines)+'\n'

def _readable_value(value):
    if value is None or value=='':return '待补'
    if isinstance(value,list):return '；'.join(_readable_value(v) for v in value) or '无'
    if isinstance(value,dict):return '；'.join(str(k)+'：'+_readable_value(v) for k,v in value.items()) or '无'
    return str(value).replace('\n',' / ')


def _owned_entry(body,key,content,placeholder=''):
    """Replace one generated entry; retain all notes outside that owned entry."""
    begin='<!-- ag-entry:'+key+' -->';end='<!-- /ag-entry:'+key+' -->'
    entry=begin+'\n'+content.rstrip()+'\n'+end
    pattern=re.compile(re.escape(begin)+r'.*?'+re.escape(end),re.S)
    if pattern.search(body):return pattern.sub(lambda _:entry,body,count=1)
    if placeholder:body=body.replace(placeholder,'')
    return body.rstrip()+'\n\n'+entry+'\n'


def _change_lines(document,changes):
    lines=[]
    if isinstance(changes,dict):
        for name,value in changes.items():
            labels={'title':'交付标题','original':'交付目标与原话','results':'完成标准','constraints':'约束','source':'来源'}
            lines.append('- '+labels.get(name,name)+'：'+_readable_value(document.intent.get(name))+' → '+_readable_value(value))
    elif isinstance(changes,list):
        for change in changes:
            target=change.get('target');field=change.get('field');identity=change.get('id','')
            old=document.intent.get(field) if target=='goal' else next((r.get(field) for r in document.intent.get('results' if target=='result' else 'constraints',[]) if r['id']==identity),None)
            lines.append('- '+str(identity or target)+' · '+str(field or '新增')+'：'+_readable_value(old)+' → '+_readable_value(change.get('value')))
    if not lines:lines=['- 旧 → 新：待补；详见对应历史差异。']
    return lines


def _views_signature(root,goal,task_id=None):
    from .store import load_task_timeline
    identities=[r['task_id'] for r in goal['iterations']]
    if task_id and task_id not in identities:identities.append(task_id)
    archives={str(path):md.digest(path.read_bytes()) for identity in identities for path in (Path(goal['document_path']).parent/'tickets'/identity).glob('*.md')}
    timelines={identity:load_task_timeline(Path(root),identity) for identity in identities}
    return _hash({'view_format':'ag.readable-folds.v1','iterations':goal['iterations'],'evidence':goal['evidence'],'decisions':goal['decisions'],'archives':archives,'timelines':timelines})


def _human_updates(root,goal,document,op,events,now):
    kind=op['type'];updates={};task_id=op.get('task_id')
    if kind=='refresh_views':
        working=document
        for iteration in goal['iterations']:
            parts=_human_updates(root,goal,working,{'type':'update_iteration','id':iteration['id'],'source':op['source']},events,now)
            updates.update(parts);working=md.Document(document.path,document.patch(updates))
        for proposal in goal['decisions']:
            action='propose_change' if proposal['state']=='pending' else 'reject_proposal' if proposal['state']=='rejected' else '_authorize'
            parts=_human_updates(root,goal,working,{'type':action,'id':proposal['id'],'proposal_id':proposal['id'],'source':proposal['source']},events,proposal.get('event_time') or next((e.get('ts') for e in events if (e.get('operation') or {}).get('id')==proposal['id']),now))
            updates.update(parts);working=md.Document(document.path,document.patch(updates))
        if op.get('task_id') and not any(r['task_id']==op['task_id'] for r in goal['iterations']):
            updates.update(_human_updates(root,goal,working,{'type':'archive_ticket','task_id':op['task_id'],'source':op['source']},events,now))
        return updates
    if kind=='update_iteration':task_id=_find(goal,'iterations',op['id'])['task_id']
    if kind in {'bind_iteration','update_iteration','archive_ticket','add_evidence'} and task_id:
        rows=[row for row in goal['iterations'] if row['task_id']==task_id]
        if not rows:
            from .delivery import build_delivery_snapshot
            snapshot=build_delivery_snapshot(Path(root),task_id)
            binding=snapshot.get('long_goal',{}).get('binding') or {}
            if not snapshot.get('found') or binding.get('goal_id')!=goal['goal_id']:_fail('view-task-scope-mismatch')
            rows=[{'task_id':task_id,'contribution':binding.get('contribution') or '未确认子票','result_ids':binding.get('result_ids',[]),'return_to':binding.get('return_to'),'state':'abandoned' if snapshot.get('process')=='abandoned' else 'unconfirmed','reason':'尚无授权迭代；不授予权限'}]
        if rows:
            row=rows[-1];state={'active':'施工中','returned':'本轮已返回；父目标仍须核对','blocked':'受阻','abandoned':'已放弃'}.get(row.get('state'),'待核对')
            lines=['<details>','<summary>'+row['contribution']+' · '+state+'</summary>','',
                '**本票贡献**：'+row['contribution'],'','**本票节点**：'+_readable_value(row['result_ids']),'','**原票**','']
            folder=document.path.parent/'tickets'/task_id
            for phase,label in [('intent','开票原文'),('completed','完成现场'),('abandoned','放弃现场')]:
                if (folder/(phase+'.md')).is_file():lines.append('- ['+label+'](tickets/'+task_id+'/'+phase+'.md)')
            if not any((folder/(phase+'.md')).is_file() for phase in ('intent','completed','abandoned')):lines.append('已开票，原文尚待归档；不冒充已归档原票。')
            lines.extend(['','**返回点**：'+_readable_value(row.get('return_to')),'','**分支或返回原因**：'+_readable_value(row.get('reason')),'','**回归要求**：重核本票完成标准、适用约束与受后续候选影响的旧证据；详细范围见原票。','','**未完承诺**：其余完成标准与待决仍保留；本轮返回不等于长票完成。','','</details>'])
            updates['tickets']=_owned_entry(document.body('tickets'),'task-'+task_id,'\n'.join(lines),'尚无已开子票；完成标准仍为承诺。')
            from .store import load_task_timeline,list_llm_events
            timeline=load_task_timeline(Path(root),task_id)
            steps=timeline.get('steps') or []
            event_time=next((step.get('ts') for step in reversed(steps) if step.get('phase') in {'start','re-seal','anchor-preview','finish','abandon','verify-result','verify-switch','intent-map-confirmed'}),'待补')
            scene=['<details>','<summary>'+row['contribution']+' · 现场记录</summary>','',
                '- 本次记录时间：'+now+'（归档/返回动作时间，不是业务核验时间）',
                '- 最近业务事件时间：'+str(event_time)+'（原 AG 时间线；不以文件编辑时间替代）',
                '- 本次业务核验时间：本动作未执行新的业务核验。',
                '- 核验对象：子票 `'+task_id+'`；贡献 '+row['contribution']]
            proofs=[r for r in goal['evidence'] if r.get('task_id')==task_id]
            for proof in proofs:
                proof_event=next((event for event in events if (event.get('operation') or {}).get('type')=='add_evidence' and (event.get('operation') or {}).get('id')==proof['id']),{})
                scene.append('- 原证据登记时间：'+str(proof_event.get('ts') or (now if kind=='add_evidence' else '待补'))+'（登记时间；验证发生时间见原回执）')
                receipts=list_llm_events(Path(root),'switch_event',limit=0,task_id=task_id,report_id=str(proof['report_id']))
                receipt=receipts[-1] if receipts else {}
                scene.append('- 原业务核验时间：'+str(receipt.get('ts') or '待补')+'；只回看原回执，本次未重验。')
                scene.extend(['- 已记录候选：`'+str(proof['candidate'])+'`', '- 原核验回执：`'+str(proof['report_id'])+'`；检查 `'+str(proof['check_id'])+'`','- 当时输入范围：'+_readable_value(proof['result_ids'])+'；当前适用性须由 read/package 重新校验。'])
            if not proofs:
                verification=next((step.get('verify') for step in reversed(steps) if isinstance(step.get('verify'),dict)),{})
                if verification:
                    report=(verification.get('switch') or {}).get('report_id')
                    scene.extend(['- 原验证候选：`'+str(verification.get('candidate') or '待补')+'`','- 原验证回执：'+str(report or '待补')+'；尚未登记父目标覆盖，不表示长票结果已完成。'])
                    scene.append('- 原验证检查：`'+str((verification.get('check_selection') or {}).get('sha256') or '待补')+'`')
                    verify_time=next((step.get('ts') for step in reversed(steps) if step.get('phase') in {'verify-result','verify-switch'} and isinstance(step.get('verify'),dict)),None)
                    scene.append('- 原验证事件时间：'+str(verify_time or '待补')+'（原始记录；本次未重新核验）')
                    inputs=verification.get('long_goal_inputs') or {}
                    scene.append('- 原验证输入：结果范围 '+_readable_value(inputs.get('result_ids'))+'；意图版本 '+_readable_value(inputs.get('intent_revision'))+'；审阅版本 '+_readable_value(inputs.get('reviewed_intent_revision'))+'；文档版本 '+_readable_value(inputs.get('revision')))
                else:scene.append('- 业务核验回执：尚未登记；子票状态本身不替代证据。')
            scene.extend(['- 记录来源：'+op['source']['kind']+' · '+op['source']['ref'],'','</details>'])
            updates['scene']=_owned_entry(document.body('scene'),'scene-'+task_id,'\n'.join(scene),'尚未取得业务核验回执；文档更新时间不是业务核验时间。')
    if kind in {'propose_change','edit_intent','reject_proposal'} or kind=='_authorize' and op.get('proposal_id'):
        key=op.get('id') or op.get('proposal_id') or 'edit-'+str(len(events)+1)
        proposal=next((r for r in goal['decisions'] if r['id']==key),{})
        pending=kind=='propose_change';changes=op.get('changes') or proposal.get('changes') or {}
        lines=['<details>','<summary>'+('待决定的变更' if pending else '意图变更或决定')+' · '+now+'</summary>','',
            '- 事件时间：'+now,
            '- 决定状态：'+('待用户决定；当前承诺不变' if pending else '已通过真实确认链接受' if kind=='_authorize' else '已拒绝' if kind=='reject_proposal' else '直接编辑后待独审及本人确认'),
            *_change_lines(document,changes),
            '- 原因：'+_readable_value(op.get('reason') or proposal.get('reason')),
            '- 决定者或来源：'+op['source']['kind']+' · '+op['source']['ref'],
            '- 影响：'+('待补；不得自动缩减剩余承诺' if pending else '按新的可见完成标准和适用约束重新核对；新意图不继承旧授权'),
            '- 返回点：'+_readable_value(goal.get('return_to')),
            '- 回归点：受影响结果及其祖先依赖、约束与原票拒绝边界。',
            '- 旧证据范围：'+_readable_value([{'结果':r.get('result_ids'),'回执':r.get('report_id')} for r in goal['evidence']])+'；不自动证明新意图。','','</details>']
        body=document.body('changes')
        old_begin='<!-- ag-entry:change-'+str(key)+' -->';old_end='<!-- /ag-entry:change-'+str(key)+' -->'
        body=re.sub(re.escape(old_begin)+r'.*?'+re.escape(old_end),'',body,flags=re.S)
        updates['changes']=_owned_entry(body,'change-'+str(key)+'-'+kind,'\n'.join(lines),'尚无变更记录。')
    return updates


def _apply(root,goal_id,operation,expected_revision,*,source=None,internal=False):
    if isinstance(expected_revision,bool) or not isinstance(expected_revision,int) or expected_revision<1:_fail('expected-revision-required')
    if not isinstance(operation,dict) or not isinstance(operation.get('type'),str):_fail('typed-operation-required')
    if not document_path(root,goal_id).is_file():_fail('legacy-read-only: use explicit long migrate')
    op=copy.deepcopy(operation);expected_sha=op.pop('expected_document_sha256',None)
    if op['type'].startswith('_') and not internal:_fail('internal-operation-forbidden')
    op['source']=_source(source or op.get('source'))
    if op['type'].startswith('add_') or op['type'] in {'bind_iteration','propose_change'}:op['id']=_id(op.get('id'),op['type'].removeprefix('add_'))
    path=document_path(root,goal_id)
    with _document_lock(path):
        document=md.Document(path);goal,events=_load(root,goal_id)
        if goal['revision']!=expected_revision or expected_sha is not None and expected_sha!=document.sha:raise LongTaskConflict(expected_revision,goal['revision'],goal_diff(root,goal_id,expected_revision))
        if op['type']=='refresh_views':
            signature=_views_signature(root,goal,op.get('task_id'))
            cached=_runtime(root,goal_id)
            if cached.get('view_signature')==signature and cached.get('document_sha256')==document.sha:return read_goal(root,goal_id)
        if op['type']=='set_summary':
            # Unknown prose elsewhere is preserved; updating next/current/blocker
            # does not need to reinterpret an unrelated result or constraint.
            changes=op.get('changes')
            if not isinstance(changes,dict) or not changes or set(changes)-{'current','blocker','next','flow'}:_fail('invalid-summary-changes')
            for name,value in changes.items():_text(value,name)
            data=document.patch(changes)
            affected=[issue for issue in md.Document(path,data).issues if issue['code']=='mermaid-format' and 'flow' in changes]
            if affected:raise md.DocumentError(path,affected)
        else:
            _require_valid(goal)
            if op['type']=='propose_change':
                for change in op.get('changes',[]):
                    if change.get('target') in {'add_result','add_constraint'} and isinstance(change.get('value'),dict):change['value']['id']=_id(change['value'].get('id'),change['target'][4:])
            if op['type'] in {'add_evidence','confirm_coverage'}:
                evidence=op if op['type']=='add_evidence' else _find(goal,'evidence',str(op.get('evidence_id') or ''))
                if op['type']=='add_evidence':
                    _result_ids(goal,evidence.get('result_ids'));iterations=[r for r in goal['iterations'] if r['task_id']==evidence.get('task_id')]
                    if not iterations or set(evidence['result_ids'])-set(iterations[-1]['result_ids']):_fail('evidence-no-matching-work-package')
                    inputs={identity:_hash(_context(goal,identity)) for identity in evidence['result_ids']}
                    if evidence.get('input_fingerprints')!=inputs:_fail('evidence-inputs-stale')
                    op['goal_id']=goal_id;op['intent_revision']=iterations[-1]['intent_revision'];op['reviewed_intent_revision']=iterations[-1].get('reviewed_intent_revision',iterations[-1]['intent_revision'])
                    op['delivery_proof']=_delivery_proof(root,op)
                else:
                    if op['source'].get('kind')!='mentor-review':_fail('coverage-requires-mentor-review-source')
                    proof=_delivery_proof(root,evidence)
                    if proof!=evidence['delivery_proof']:_fail('evidence-proof-changed')
                    view=_view(root,goal);current=_find(view,'evidence',evidence['id'])
                    if not set(op.get('result_ids') or []).issubset(current.get('valid_result_ids',[])):_fail('evidence-invalid-for-coverage')
            if op['type']=='bind_iteration':
                from .loop import load_task
                from .managed import project_key
                active=load_task(project_key(real_root(Path(root)))) or {}; link=active.get('long_goal') or {}
                if active.get('id')!=op.get('task_id') or link.get('goal_id')!=goal_id or set(op.get('result_ids') or [])-set(link.get('result_ids') or []): _fail('iteration-task-scope-mismatch')
                from .authorization import validate_ticket
                from .long_authorization import recorded
                if not recorded(active) or not active.get('worktree_ready') or active.get('thaw_error'): _fail('iteration-task-not-authorized')
                validate_ticket(Path(root),active)
                if not active.get('long_authorization'):
                    auth=goal.get('authorization') or {}
                    if auth.get('task_id')!=active['id'] or auth.get('intent_identity')!=active.get('intent_identity'): _fail('iteration-task-not-authorized')
                op['reviewed_intent_revision']=link['intent_revision']
                op['authorization_identity']=active['intent_identity']
                _result_ids(goal,op.get('result_ids')); package=work_package(root,goal_id,op['result_ids'],contribution=op.get('contribution',''),task_id=op.get('task_id',''))
                if op.get('package_fingerprint')!=package['fingerprint']: _fail('work-package-stale')
                op['intent_revision']=goal['intent_revision']; op['input_fingerprints']={identity:_hash(_context(goal,identity)) for identity in op['result_ids']}
            if op['type']=='set_position':
                identity=_text(op.get('result_id'),'position-result')
                row=_find(goal,'results',identity)
                if row.get('state')!='active':_fail('position-result-inactive')
                _text(op.get('current'),'position-current')
            elif op['type']=='edit_intent':
                changes=op.get('changes')
                if not isinstance(changes,dict) or not changes or set(changes)-{'title','original','results','constraints','source'}:_fail('invalid-intent-changes')
                for name,value in changes.items():goal[name]=copy.deepcopy(value)
                _graph(goal)
            elif op['type']=='refresh_views':
                if set(op)-{'type','source','task_id'}:_fail('unexpected-refresh-fields')
            elif op['type']=='archive_ticket':
                if not internal:_fail('internal-operation-forbidden')
            else:_reduce(goal,op,goal['revision']+1,intent_change=False)
            replacements={}
            if op['type']=='set_position':
                replacements.update(current=op['current'],flow=md.business_flow(_view(root,goal)['results'],op['result_id']))
                for name in ('blocker','next'):
                    if name in op:replacements[name]=_text(op[name],name)
            for name in ('original','source','results','constraints'):
                if goal[name]!=document.intent[name]:replacements[name]=md.row_text(goal[name],name,goal['source']) if name in {'results','constraints'} else md.source_text(goal[name]) if name=='source' else goal[name]
            now=datetime.now(timezone.utc).isoformat()
            replacements.update(_human_updates(root,goal,document,op,events,now))
            record_body=document.body('records')
            if goal['iterations']:record_body=record_body.replace('尚无已开子票；以上完成标准是承诺，不是原票。','各轮独立原票与返回点见上方子票折叠；以下仅为原始审计详情。')
            replacements['records']=record_body.rstrip()+'\n\n'+_records(goal,op,op['source'],now)
            data=document.patch(replacements,title=goal['title'] if goal['title']!=document.title else None)
            if op['type']=='refresh_views':data=data.replace('节点、进展与原票索引 · 原回执以记录核验'.encode('utf-8'),'原始审计日志 · 技术详情'.encode('utf-8'),1)
            md.Document(path,data).require()
        final_document=md.Document(path,data)
        now=datetime.now(timezone.utc).isoformat();runtime=_runtime(root,goal_id)
        runtime.update(schema='ag.long-markdown.runtime.v1',created_at=runtime.get('created_at') or now,updated_at=now,document_sha256=final_document.sha,return_to=goal.get('return_to'),**{name:goal[name] for name in COLLECTIONS if name not in {'results','constraints'}})
        if goal.get('authorization'):runtime['authorization']=goal['authorization']
        if op['type']=='_authorize':runtime.update(authorized_intent_revision=final_document.intent_revision,authorized_intent_sha256=final_document.intent_sha)
        event={'sequence':len(events)+1,'goal_id':goal_id,'revision':final_document.revision,'previous_revision':document.revision,'intent_revision':final_document.intent_revision,'ts':now,'operation':op,'before_sha256':document.sha,'document_sha256':final_document.sha,'intent_sha256':final_document.intent_sha,'before_markdown':document.text,'after_markdown':final_document.text}
        runtime['events']=events+[event]
        if op['type']=='refresh_views':runtime['view_signature']=_views_signature(root,goal,op.get('task_id'))
        # Prepare every serialization and validation before the first mutation.
        runtime_data=(_json(runtime)+'\n').encode('utf-8')
        old_runtime=_runtime_path(root,goal_id).read_bytes() if _runtime_path(root,goal_id).is_file() else None
        md.atomic_write(path,data,expected_sha=document.sha)
        try:md.atomic_write(_runtime_path(root,goal_id),runtime_data)
        except BaseException:
            md.atomic_write(path,document.data,expected_sha=final_document.sha)
            if old_runtime is not None:md.atomic_write(_runtime_path(root,goal_id),old_runtime)
            raise
    return read_goal(root,goal_id)

def work_package(root,goal_id,result_ids=None,*,contribution='',task_id=''):
    _require_valid(read_goal(root,goal_id))
    raw,_=_load(root,goal_id); goal=_view(root,raw); selected=_result_ids(raw,result_ids,default_all=True); ancestry=_ancestors(raw,selected); relevant=set(ancestry)
    package={'schema':'ag.long-work-package.v1','goal_id':goal_id,'title':goal['title'],'original':goal['original'],'source':goal['source'],'revision':goal['revision'],'intent_revision':goal['intent_revision'],'authorized_intent_revision':goal['authorized_intent_revision'],'result_ids':selected,'contribution':contribution,'task_id':task_id,'results':[r for r in goal['results'] if r['id'] in selected],'ancestor_results':[r for r in goal['results'] if r['id'] in relevant-set(selected)],'constraints':[r for r in goal['constraints'] if r.get('state')=='active' and (r.get('scope')==['*'] or set(r.get('scope',[])) & relevant)],'dependencies':[r for r in goal['dependencies'] if r['result_id'] in relevant and r.get('state')!='removed'],'remaining':goal['remaining'],'pending_decisions':[r for r in goal['decisions'] if r['state']=='pending'],'return_to':goal['return_to'] or ({'goal_id':goal_id,'result_id':selected[0]} if selected else None),'authority':goal['authority'],'document_path':goal.get('document_path'),'document_sha256':goal.get('document_sha256'),'intent_sha256':goal.get('intent_sha256'),'outline':goal.get('outline',{})}
    for name in ('facts','plans','investigations','capabilities','evidence'): package[name]=[r for r in goal[name] if set(r.get('result_ids',[])) & relevant]
    package['input_fingerprints']={identity:_hash(_context(raw,identity)) for identity in selected}
    package['sources']=[{'collection':name,'id':r['id'],'revision':r.get('revision'),'source':r.get('source')} for name in COLLECTIONS for r in goal[name] if name in {'results','constraints'} or r in package.get(name,[])]
    package['fingerprint']=_hash(package)
    return package

def ticket_projection(root,goal_id,*,pending=False,result_ids=None,contribution='',authorization_context=True):
    _require_valid(read_goal(root,goal_id))
    raw,_=_load(root,goal_id)
    if pending:
        proposals=[r for r in raw['decisions'] if r['state']=='pending']
        if len(proposals)!=1: _fail('projection-requires-single-pending-proposal')
        proposal=proposals[0]
        if proposal['base_intent_revision']!=raw['intent_revision']: _fail('stale-proposal')
        _intent_changes(raw,proposal['changes']); raw['intent_revision']=_candidate_intent(raw)['intent_revision']
    selected=_result_ids(raw,result_ids,default_all=True); ancestry=set(_ancestors(raw,selected))
    lines=['# 票','','## 意图',raw['title'],'',f"长期目标: {goal_id}; 意图版本: {raw['intent_revision']}",'','用户原话：',raw['original'],'','来源：'+_json(raw['source']),'']
    if contribution: lines.extend(['本轮贡献：'+contribution,''])
    for row in raw['results']:
        if row['state']=='active' and row['id'] in selected: lines.append(f"anchor: [{row['id']}] {row['text']}")
    lines.extend(['','## Parent remaining commitments (context; outside this ticket acceptance)'])
    for row in raw['results']:
        if row['state']=='active' and row['id'] not in selected: lines.append(f"- [{row['id']}] {row['text']}")
    if authorization_context:
        lines.extend(['','## 父长票授权范围（整体批准一次）','首次确认批准完整父目标、全部结果与约束；本轮只验收选定结果。已批准范围内后续子票独立审票后继承授权，目标或约束变化重新交用户决定。'])
        other_constraints=[r for r in raw['constraints'] if r.get('state')=='active' and not (r['scope']==['*'] or set(r['scope']) & ancestry)]
        for row in other_constraints: lines.append(f"- 父约束 [{row['id']}]（适用 {', '.join(row['scope'])}）：{row['text']}")
    lines.extend(['','## 红线']); constraints=[r for r in raw['constraints'] if r.get('state')=='active' and (r['scope']==['*'] or set(r['scope']) & ancestry)]
    if not constraints: lines.append('- 沿现有独立审校、有效父授权与真实 ready 门禁施工；无原始授权须用户本人首次 confirm-map，本投影不授予权限。' if authorization_context else '- 沿现有独立审校、人工 confirm-map 与 ready 门禁施工；本投影不授予权限。')
    for row in constraints: lines.append(f"- [{row['id']}] {row['text']}")
    lines.extend(['','## 长期记录来源','authority: '+str(document_path(root,goal_id)),'projection: immutable single-ticket scope; edit parent long.md for future intent',''])
    return '\n'.join(lines)

# Binding authority lives in authorization.new_long_binding; there is no second
# snapshot/preview interpretation here.
export_ticket=ticket_projection
history=goal_history
diff=goal_diff


def record_inherited_iteration(root, task):
    binding=task['long_goal']; goal_id=binding['goal_id']; goal=read_goal(root,goal_id)
    if any(row['task_id']==task['id'] and row.get('authorization_identity')==task['intent_identity'] for row in goal['iterations']): return goal
    package=work_package(root,goal_id,binding['result_ids'],contribution=binding['contribution'],task_id=task['id'])
    return apply_operation(root,goal_id,{'type':'bind_iteration','id':_id(prefix='iteration'),'task_id':task['id'],'contribution':binding['contribution'],'result_ids':binding['result_ids'],'return_to':binding.get('return_to') or {'goal_id':goal_id,'result_id':binding['result_ids'][0]},'package_fingerprint':package['fingerprint'],'authorization_identity':task['intent_identity'],'reviewed_intent_revision':binding['intent_revision']},goal['revision'],source={'kind':'ag-inherited-child','ref':'task:'+task['id']})


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
    proof={'task_id':task_id,'reviewed_intent_revision':intent_revision,'authorized_intent_revision':preview_intent(root,goal_id,pending=bool(proposal_ids))['intent_revision'],'authorized_intent_sha256':preview_intent(root,goal_id,pending=bool(proposal_ids))['intent_sha256'],'intent_identity':identity,'authorization_identity':active.get('authorization_identity'),'report_id':(active.get('ticket_review') or {}).get('report_id'),'preview_token':preview_token,'approved':approved[-1],'ready':ready[-1]}
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
    if not matches:
        if process=='abandoned' and goal['authorized_intent_revision']!=goal['intent_revision']:return goal
        _fail('iteration-not-bound')
    row=matches[-1]
    if row['contribution']!=contribution: _fail('iteration-contribution-mismatch')
    state='returned' if process=='completed' else 'abandoned' if process=='abandoned' else 'blocked'
    if row.get('state')==state: return goal
    changes={'state':state,'reason':f'AG task {task_id}: {process}/{product}'}
    if return_to: changes['return_to']=return_to
    return apply_operation(root,goal_id,{'type':'update_iteration','id':row['id'],'changes':changes},goal['revision'],source={'kind':'ag-return','ref':'task:'+task_id})

# ---- Explicit legacy conversion and immutable, phase-specific child tickets ----
def _legacy_readable_history(root,goal,events,sqlite_sha):
    """A readable immutable archive, independent of the new editable authority."""
    from . import legacy_long_tasks as legacy
    lines=['# 旧长票只读历史 · '+goal['title'],'',
        '> 历史快照；保留原数据与证据，迁移不表示重新核验，不继承施工授权。','',
        '原 SQLite：`'+str(legacy.storage_path(root))+'`',
        '原库 SHA256：`'+sqlite_sha+'`',
        '原目标：`'+goal['goal_id']+'`；历史版本：`'+str(goal['revision'])+'`','',
        '**原话**','',goal['original'],'','**原来源**','',
        '```json',json.dumps(goal['source'],ensure_ascii=False,indent=2),'```','',
        '**原返回点**','', '```json',json.dumps(goal.get('return_to'),ensure_ascii=False,indent=2),'```','']
    labels={'results':'承诺结果','constraints':'约束','facts':'事实','plans':'计划','dependencies':'依赖与分支返回','investigations':'调查','capabilities':'能力','evidence':'真实证据与当时输入','decisions':'决定与变更','iterations':'历轮贡献与候选'}
    for name in COLLECTIONS:
        lines.extend(['<details>','<summary>'+labels[name]+' · '+str(len(goal[name]))+' 项</summary>',''])
        for row in goal[name]:
            lines.extend(['### '+row['id'],str(row.get('text') or row.get('contribution') or row.get('description') or row.get('reason') or ''),'','```json',json.dumps(row,ensure_ascii=False,indent=2),'```',''])
        if not goal[name]:lines.append('无历史记录。')
        lines.extend(['','</details>',''])
    lines.extend(['<details>','<summary>原始增量历史 · '+str(len(events))+' 次</summary>',''])
    for event in events:
        lines.extend(['### 版本 '+str(event['revision'])+' · '+event['operation']['type'],event.get('ts',''),'','```json',json.dumps(event,ensure_ascii=False,indent=2),'```',''])
    lines.extend(['</details>','','公开只读入口：`ag long legacy-read <PROJECT_ROOT> '+goal['goal_id']+'` 与 `ag long legacy-history <PROJECT_ROOT> '+goal['goal_id']+'`。',''])
    return '\n'.join(lines)


def migration_candidate(root,goal_id):
    """Read SQLite without writes and return reviewable draft plus readable history."""
    from . import legacy_long_tasks as legacy
    if document_path(root,goal_id).exists():_fail('already-markdown: '+goal_id)
    goal=legacy.read_goal(root,goal_id);events=legacy.goal_history(root,goal_id)
    sqlite_sha=md.digest(legacy.storage_path(root).read_bytes())
    content=md.render(goal['title'],goal['original'],goal['source'],goal['results'],goal['constraints'])
    document=md.Document(document_path(root,goal_id),content).require()
    history_name='legacy-history-'+sqlite_sha[:12]+'.md'
    history=_legacy_readable_history(root,goal,events,sqlite_sha)
    notice=('旧 SQLite 历史只读保留；[展开完整原话、事实、依赖、证据与返回点]('+history_name+')。\n'
        '原库 SHA256：`'+sqlite_sha+'`；原版本 `'+str(goal['revision'])+'`。\n'
        '此 Markdown 为显式转换草稿；旧授权、子票通过和摘要均不授予本票权限。\n'
        '公开只读历史：`ag long legacy-read <PROJECT_ROOT> '+goal_id+'` / `ag long legacy-history <PROJECT_ROOT> '+goal_id+'`。\n')
    return {'goal_id':goal_id,'format':'markdown','authorized':False,'legacy_authority':str(legacy.storage_path(root)),
        'legacy_revision':goal['revision'],'legacy_sha256':sqlite_sha,
        'document_path':str(document.path),'markdown':document.patch({'records':notice}).decode('utf-8'),
        'history_path':str(document.path.parent/history_name),'history_markdown':history,'history_sha256':md.digest(history)}


def migrate_goal(root,goal_id,*,expected_legacy_sha256=None):
    """Publish an unauthorized draft and readable immutable history; SQLite intact."""
    candidate=migration_candidate(root,goal_id)
    if expected_legacy_sha256 and candidate['legacy_sha256']!=expected_legacy_sha256:_fail('legacy-conversion-conflict')
    path=document_path(root,goal_id);data=candidate['markdown'].encode('utf-8');history_path=Path(candidate['history_path'])
    doc=md.Document(path,data)
    unexpected=[issue for issue in doc.issues if issue['code']!='broken-link' or history_path.name not in issue['message']]
    if unexpected:raise md.DocumentError(path,unexpected)
    path.parent.mkdir(parents=True,exist_ok=True)
    with _document_lock(path):
        if path.exists():_fail('already-markdown: '+goal_id)
        if md.digest(Path(candidate['legacy_authority']).read_bytes())!=candidate['legacy_sha256']:_fail('legacy-conversion-conflict')
        history_existed=history_path.is_file();history_data=candidate['history_markdown'].encode('utf-8')
        if history_existed and history_path.read_bytes()!=history_data:_fail('legacy-history-immutable-conflict')
        try:
            if not history_existed:md.atomic_write(history_path,history_data)
            md.Document(path,data).require()
            md.atomic_write(path,data)
        except BaseException:
            if not history_existed:history_path.unlink(missing_ok=True)
            raise
    return {**read_goal(root,goal_id),'legacy_authority':candidate['legacy_authority'],'legacy_read_only':True,
        'legacy_sha256':candidate['legacy_sha256'],'legacy_history_path':str(history_path),'legacy_history_sha256':candidate['history_sha256']}


def archive_ticket(root,goal_id,task_id,text,source_path='',*,phase='intent',expected_revision=None):
    """Keep reviewed intent and final scene as separate immutable originals.

    intent.md is the exact opening ticket; completed.md is the terminal scene.
    A subsequent round has another task directory and cannot replace either.
    """
    _id(task_id)
    if phase not in {'intent','completed','abandoned'}:_fail('invalid-archive-phase')
    if not isinstance(text,str) or not text.strip():_fail('archive-ticket-text-required')
    goal=read_goal(root,goal_id);_require_valid(goal)
    if not any(row.get('task_id')==task_id for row in goal['iterations']):_fail('archive-ticket-not-bound')
    if expected_revision is not None and expected_revision!=goal['revision']:raise LongTaskConflict(expected_revision,goal['revision'],[])
    path=document_path(root,goal_id).parent/'tickets'/task_id/(phase+'.md');data=text.encode('utf-8')
    existed=path.is_file()
    if existed and path.read_bytes()!=data:_fail('archive-ticket-immutable: '+str(path))
    relative=path.relative_to(document_path(root,goal_id).parent).as_posix()
    if not existed:md.atomic_write(path,data)
    try:
        if relative not in md.Document(document_path(root,goal_id)).body('records'):
            _apply(root,goal_id,{'type':'archive_ticket','task_id':task_id,'phase':phase,'path':relative,'sha256':md.digest(data),'source_path':str(source_path)},goal['revision'],source={'kind':'ag-ticket-archive','ref':str(source_path) or 'task:'+task_id},internal=True)
    except BaseException:
        if not existed:path.unlink(missing_ok=True)
        raise
    return {'path':str(path),'relative_path':relative,'sha256':md.digest(data),'phase':phase}


def _candidate_intent(goal):
    """Canonicalize a proposed visible intent through the same Markdown parser."""
    content=md.render(goal['title'],goal['original'],goal['source'],goal['results'],goal['constraints'])
    document=md.Document(Path(goal.get('document_path') or 'long.md'),content).require()
    return {'intent_revision':document.intent_revision,'intent_sha256':document.intent_sha,'intent':document.intent}


def preview_intent(root,goal_id,*,pending=False):
    """Integration helper: proposal previews use the eventual visible intent hash."""
    goal,_=_load(root,goal_id);_require_valid(goal)
    if pending:
        proposals=[row for row in goal['decisions'] if row['state']=='pending']
        if len(proposals)!=1:_fail('projection-requires-single-pending-proposal')
        if proposals[0]['base_intent_revision']!=goal['intent_revision']:_fail('stale-proposal')
        _intent_changes(goal,proposals[0]['changes'])
    return _candidate_intent(goal)
