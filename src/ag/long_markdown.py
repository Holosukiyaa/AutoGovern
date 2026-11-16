"""Readable Markdown authority and surgical, optimistic document updates.

Only the visible title, original, completion criteria, constraints and source
constitute intent. Runtime receipts are deliberately separate from this parser.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from .managed import ChainBroken

REGIONS = ('original','results','constraints','source','current','blocker','next','flow','records')
OPTIONAL_REGIONS = ('tickets','scene','changes')
INTENT_REGIONS = {'original','results','constraints','source'}

def digest(value):
    data=value if isinstance(value,bytes) else value.encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def fingerprint(value):
    return digest(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))

def version(sha):
    # A document-derived token also changes for multiple successive manual edits
    # before any AG operation; a cached counter cannot detect that case.
    return int(sha[:13],16) or 1

class DocumentError(ChainBroken):
    def __init__(self,path,issues):
        self.issues=issues
        self.details={'path':str(path),'issues':issues}
        super().__init__('long-task-markdown-invalid: '+str(path)+': '+'; '.join(f"line {r['line']}: {r['message']}" for r in issues))

class Document:
    def __init__(self,path,content=None):
        self.path=Path(path)
        self.data=self.path.read_bytes() if content is None else content.encode('utf-8') if isinstance(content,str) else content
        self.issues=[]; self.regions={}
        try:self.text=self.data.decode('utf-8')
        except UnicodeDecodeError as exc:raise DocumentError(self.path,[{'line':1,'code':'utf8','message':'Invalid UTF-8 near byte '+str(exc.start)}]) from exc
        self.sha=digest(self.data); self.revision=version(self.sha)
        for name in REGIONS + OPTIONAL_REGIONS:
            begin=list(re.finditer(r'(?m)^<!-- ag:'+name+r' -->\r?\n',self.text))
            end=list(re.finditer(r'(?m)^<!-- /ag:'+name+r' -->[ \t]*(?:\r?\n|$)',self.text))
            if name in OPTIONAL_REGIONS and not begin and not end:continue
            if len(begin)!=1 or len(end)!=1 or begin[0].end()>end[0].start():
                self.issue(begin[0].start() if begin else 0,'region-'+name,'Missing, duplicated or misplaced '+name+' region')
            else:self.regions[name]=(begin[0].end(),end[0].start())
        # The authority title is in the preamble. Quoted/original tickets and
        # user notes may contain their own Markdown headings.
        preamble_end=min((span[0] for span in self.regions.values()),default=len(self.text))
        titles=list(re.finditer(r'(?m)^# (.+)\r?$',self.text[:preamble_end]))
        if len(titles)!=1:self.issue(titles[0].start() if titles else 0,'title','Expected exactly one top-level title')
        self.title=titles[0].group(1).strip() if titles else ''
        self.title_span=(titles[0].start(1),titles[0].end(1)) if titles else None
        ordered=sorted((start,end,name) for name,(start,end) in self.regions.items())
        for previous,current in zip(ordered,ordered[1:]):
            if previous[1]>current[0]:self.issue(current[0],'overlap','Overlapping regions '+previous[2]+' / '+current[2])
        self.source=self.parse_source(self.body('source'))
        self.results=self.parse_rows('results'); self.constraints=self.parse_rows('constraints')
        identities=set()
        for name,rows in [('results',self.results),('constraints',self.constraints)]:
            for row in rows:
                if row['id'] in identities:self.issue(self.regions.get(name,(0,0))[0],'duplicate-id','Duplicate item '+row['id'])
                identities.add(row['id'])
                if not row.get('source',{}).get('kind') or not row.get('source',{}).get('ref'):self.issue(self.regions.get(name,(0,0))[0],'source-required','Item '+row['id']+' requires source kind and ref')
        result_ids={r['id'] for r in self.results}
        for row in self.results:
            if row.get('parent_result_id') and row['parent_result_id'] not in result_ids:self.issue(self.regions.get('results',(0,0))[0],'bad-reference','Unknown parent '+row['parent_result_id'])
        for row in self.constraints:
            if row['scope']!=['*'] and (not row['scope'] or set(row['scope'])-result_ids):self.issue(self.regions.get('constraints',(0,0))[0],'bad-reference','Unknown constraint scope for '+row['id'])
        if not self.body('original').strip():self.issue(0,'original','Delivery outcome is empty')
        if not self.results:self.issue(0,'results','At least one completion criterion is required')
        self.check_links()
        flow=self.body('flow').strip()
        if flow and (not flow.startswith('```mermaid\n') and not flow.startswith('```mermaid\r\n') or flow.count('```')!=2 or not re.search(r'(?m)^(?:flowchart|graph) (?:LR|RL|TD|TB|BT)\s*$',flow)):
            self.issue(self.regions.get('flow',(0,0))[0],'mermaid-format','Flow requires one Mermaid fenced flowchart with a direction')
        self.intent={'title':self.title,'original':self.body('original').strip(),'source':self.source,'results':self.results,'constraints':self.constraints}
        self.intent_sha=fingerprint(self.intent)
        self.intent_revision=version(self.intent_sha)

    def issue(self,offset,code,message):
        self.issues.append({'line':self.text[:offset].count('\n')+1,'code':code,'message':message})

    def body(self,name):
        span=self.regions.get(name)
        return self.text[slice(*span)] if span else ''

    def parse_source(self,text):
        result={};last=None
        start=self.regions.get('source',(0,0))[0]
        offset=start
        for line in text.splitlines(True):
            if line.startswith('  ') and last:
                # Empty indented continuations represent empty original lines;
                # do not strip them or a user's final newline away.
                result[last]+='\n'+line[2:].rstrip('\r\n')
            elif line.strip():
                match=re.fullmatch(r'(kind|ref|text):[ \t]*(.*)',line.rstrip('\r\n'))
                if not match:self.issue(offset,'unknown-source-line','Cannot interpret source line')
                elif match[1] in result:self.issue(offset,'duplicate-source','Duplicate source '+match[1])
                else:result[match[1]]=match[2];last=match[1]
            offset+=len(line)
        if not result.get('kind') or not result.get('ref'):self.issue(start,'source-required','Source requires kind and ref')
        return result

    def parse_rows(self,name):
        rows=[]; row=None; seen_props=set();last_source_field=None; offset=self.regions.get(name,(0,0))[0]
        for line in self.body(name).splitlines(True):
            value=line.rstrip('\r\n')
            match=re.fullmatch(r'- \[([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\] (.+)',value)
            prop=re.fullmatch(r'  (state|scope|parent|source|source-kind|source-ref|source-text): (.*)',value)
            if match:
                row={'id':match[1],'text':match[2],'state':'active','source':copy.deepcopy(self.source)}
                if name=='constraints':row['scope']=['*']
                rows.append(row);seen_props=set();last_source_field=None
            elif value.startswith('    ') and row is not None and last_source_field:
                row['source'][last_source_field]+='\n'+value[4:]
            elif prop and row is not None:
                key,value=prop.groups()
                if key in seen_props:self.issue(offset,'duplicate-property','Duplicate '+key+' property')
                seen_props.add(key);last_source_field=None
                if key.startswith('source-'):
                    field=key.removeprefix('source-')
                    if key=='source-kind':row['source']={}
                    row['source'][field]=value;last_source_field=field
                elif key=='scope' and name=='constraints':row['scope']=[v.strip() for v in value.split(',') if v.strip()]
                elif key=='parent' and name=='results':row['parent_result_id']=value
                elif key=='state':
                    if value not in {'active','removed','superseded'}:self.issue(offset,'invalid-state','Unknown intent state '+value)
                    row['state']=value
                elif key=='source':
                    parts=value.split(' | ',2)
                    if len(parts)<2:self.issue(offset,'invalid-source','Use source: kind | ref | optional original text')
                    else:row['source']={'kind':parts[0],'ref':parts[1],**({'text':parts[2]} if len(parts)>2 else {})}
                else:self.issue(offset,'unknown-property','Property is not valid in '+name)
            elif value.strip():self.issue(offset,'unknown-intent-line','Cannot interpret line in '+name+'; preserve it and clarify before operating')
            offset+=len(line)
        return rows

    def check_links(self):
        from urllib.parse import unquote
        def collect_anchors(text):
            anchors=set();counts={}
            for match in re.finditer(r'(?m)^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$',text):
                heading=re.sub(r'<[^>]+>','',match[1]).strip().lower()
                heading=re.sub(r'[^\w\- ]','',heading).replace(' ','-')
                ordinal=counts.get(heading,0);counts[heading]=ordinal+1
                anchors.add(heading+('-'+str(ordinal) if ordinal else ''))
            anchors.update(match[1] for match in re.finditer(r'<(?:a|span|div)\b[^>]*\b(?:id|name)=[\"\']([^\"\']+)[\"\']',text,re.I))
            return anchors
        anchors=collect_anchors(self.text)
        definitions={m[1].casefold():m[2].strip('<>') for m in re.finditer(r'(?m)^\[([^\]]+)\]:\s*(\S+)',self.text)}
        for m in re.finditer(r'(?<!!)\[([^\]\n]+)\]\[([^\]\n]*)\]',self.text):
            ref=(m[2] or m[1]).casefold()
            if ref not in definitions:self.issue(m.start(),'broken-reference','Undefined Markdown reference '+ref)
        targets=[(m.start(),m[1].strip('<>')) for m in re.finditer(r'(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)',self.text)]
        targets.extend((self.text.find('['+name+']:'),target) for name,target in definitions.items())
        for offset,target in targets:
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target):continue
            destination,separator,fragment=target.partition('#')
            if not destination and separator and unquote(fragment) not in anchors:
                self.issue(max(offset,0),'broken-fragment','Missing Markdown heading or explicit anchor #'+unquote(fragment))
            if destination.lower().endswith('.md'):
                linked_path=self.path.parent/unquote(destination)
                if not linked_path.is_file():self.issue(max(offset,0),'broken-link','Missing Markdown file '+destination)
                elif separator:
                    try:linked_anchors=collect_anchors(linked_path.read_text(encoding='utf-8-sig'))
                    except (OSError,UnicodeDecodeError) as exc:
                        self.issue(max(offset,0),'broken-fragment','Cannot read linked Markdown '+destination+': '+str(exc))
                    else:
                        if unquote(fragment) not in linked_anchors:self.issue(max(offset,0),'broken-fragment','Missing Markdown heading or explicit anchor '+destination+'#'+unquote(fragment))

    def require(self):
        if self.issues:raise DocumentError(self.path,self.issues)
        return self

    def patch(self,replacements=None,title=None):
        edits=[]
        for name,body in (replacements or {}).items():
            if name in OPTIONAL_REGIONS and name not in self.regions:
                labels={'tickets':'各轮子票与返回点','scene':'现场依据 · 已记录现场，非实时状态','changes':'变更与待决'}
                appended='\n<details>\n<summary>'+labels[name]+'</summary>\n\n<a id="'+name+'"></a>\n<!-- ag:'+name+' -->\n'+body.rstrip('\n')+'\n<!-- /ag:'+name+' -->\n\n</details>\n'
                edits.append((len(self.text),len(self.text),appended));continue
            if name not in self.regions:raise DocumentError(self.path,self.issues or [{'line':1,'code':'missing-region','message':'Missing region '+name}])
            newline='\r\n' if '\r\n' in self.body(name) else '\n'
            body=body.replace('\r\n','\n').replace('\n',newline).rstrip('\r\n')+newline
            edits.append((*self.regions[name],body))
        if title is not None:
            if not self.title_span:raise DocumentError(self.path,self.issues)
            edits.append((*self.title_span,title))
        text=self.text
        for start,end,value in sorted(edits,reverse=True):text=text[:start]+value+text[end:]
        return text.encode('utf-8')


def source_text(source):
    return '\n'.join(f"{key}: {str(source[key]).replace(chr(10),chr(10)+'  ')}" for key in ('kind','ref','text') if key in source)+'\n'

def row_text(rows,name,default_source=None):
    lines=[]
    for row in rows:
        text=str(row['text'])
        if '\n' in text or '\r' in text:raise ChainBroken('long-task-markdown-item-must-be-one-line: '+row['id'])
        lines.append(f"- [{row['id']}] {text}")
        if row.get('state','active')!='active':lines.append('  state: '+row['state'])
        if name=='constraints' and row.get('scope',['*'])!=['*']:lines.append('  scope: '+', '.join(row['scope']))
        if row.get('parent_result_id'):lines.append('  parent: '+row['parent_result_id'])
        source=row.get('source')
        if source and source!=default_source:
            for key in ('kind','ref','text'):
                if key in source:
                    parts=str(source[key]).split('\n')
                    lines.append('  source-'+key+': '+parts[0])
                    lines.extend('    '+line for line in parts[1:])
    return '\n'.join(lines)+'\n'


def business_flow(results,current_result_id=''):
    active=[row for row in results if row.get('state','active')=='active']
    lines=['```mermaid','flowchart LR']
    current=current_result_id or next((row['id'] for row in active if row.get('status')!='verified'),active[0]['id'] if active else '')
    for i,row in enumerate(active):
        label=re.sub(r'[\[\]{}<>"`|\r\n]',' ',row['text']).strip()
        prefix=re.split(r'[：:]|[。；;]',label,maxsplit=1)[0].strip()
        label=prefix if prefix else label
        label=(label[:12]+'…') if len(label)>12 else label
        suffix=(' · 当前' if row['id']==current else ' · 已核验' if row.get('status')=='verified' else ' · 待推进')+(' · 交付终点' if i==len(active)-1 else '')
        lines.append(f'  R{i}["{label}{suffix}"]')
        if i:lines.append(f'  R{i-1} --> R{i}')
    if active:
        current_index=next((i for i,row in enumerate(active) if row['id']==current),0)
        lines.append(f'  classDef current fill:#fff4cc,stroke:#997700;\n  class R{current_index} current;')
    lines.append('```')
    return '\n'.join(lines)

def render(title,original,source,results,constraints):
    def region(name,text):
        body=text[:-1] if text.endswith('\n') else text
        return '<a id="'+name+'"></a>\n<!-- ag:'+name+' -->\n'+body+'\n<!-- /ag:'+name+' -->\n'
    return ('# '+title+'\n\n**要交付什么**\n\n'+region('original',original)+'\n**怎样算完成**\n\n'+region('results',row_text(results,'results',source))+
        '\n**现在到哪**\n\n'+region('current','草稿；尚未核验，长票未完成。')+'\n**当前卡点**\n\n'+region('blocker','尚未授权开工。')+'\n**下一步**\n\n'+region('next','审阅完成标准与约束 → 独立审票 → 用户本人确认 → 按结果节点分轮交付。')+'\n'+region('flow',business_flow(results))+
        '\n<details>\n<summary>当前有效约束</summary>\n\n'+region('constraints',row_text(constraints,'constraints',source))+'\n</details>\n\n<details>\n<summary>原话与来源</summary>\n\n'+region('source',source_text(source))+'\n</details>\n\n<details>\n<summary>原始审计日志 · 技术详情</summary>\n\n'+region('records','此处为审计索引；编辑索引文字不改变原始回执或验证结果。现况、卡点与下一步在首屏直接维护。\n\n尚无已开子票；以上完成标准是承诺，不是原票。')+'\n</details>\n'+''.join('\n<details>\n<summary>'+label+'</summary>\n\n'+region(name,body)+'\n</details>\n' for name,label,body in [('tickets','各轮子票与返回点','尚无已开子票；完成标准仍为承诺。'),('scene','现场依据 · 已记录现场，非实时状态','尚未取得业务核验回执；文档更新时间不是业务核验时间。'),('changes','变更与待决','尚无变更记录。')]))


def atomic_write(path,data,*,expected_sha=None):
    path=Path(path)
    if expected_sha is not None and (not path.is_file() or digest(path.read_bytes())!=expected_sha):raise ChainBroken('long-task-document-conflict: reload document')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
        if expected_sha is not None and digest(path.read_bytes())!=expected_sha:raise ChainBroken('long-task-document-conflict: reload document')
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
