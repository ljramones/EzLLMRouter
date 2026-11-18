#!/usr/bin/env python3
"""Read-only document checks; no product imports, network, Docker or Git operations."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import stat
import zipfile
import urllib.parse

ROOT=Path(__file__).resolve().parent
ARCH='DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md'
REG='DURANKI-v1.2-C01-ASSURANCE-REGISTER'
PREFIX='duranki-v1.2-c01-erratum-01/'
EXPECTED_BASE='7ef3584b2b2d56490ad1d08eb3ae0b2d03d0f05c72a312e98ee544ac55db33a4'
EXPECTED_REVIEW='15f3adb8a8063ae0d181aa4046b44b2cd06ce9440e37f8a41470c3e3dfb78cdd'
sha=lambda b:hashlib.sha256(b).hexdigest()
def require(condition, message):
    if not condition: raise ValueError(message)
def load(rel): return json.loads((ROOT/rel).read_text())
def sections(text):
    matches=list(re.finditer(r'^###? (\d+(?:\.\d+)?)\.? .*$',text,re.M))
    return {m.group(1): text[m.start(): matches[i+1].start() if i+1<len(matches) else len(text)] for i,m in enumerate(matches)}
def all_nodes(reg):
    return {x['id']:x for e in reg['entries'] for x in [e,*e.get('subcases',[])]}
def diffpaths(a,b,path=()):
    if a==b: return []
    if isinstance(a,dict) and isinstance(b,dict):
        out=[]
        for k in a.keys()|b.keys():
            out += [path+(str(k),)] if k not in a or k not in b else diffpaths(a[k],b[k],path+(str(k),))
        return out
    if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
        return [v for i,(x,y) in enumerate(zip(a,b)) for v in diffpaths(x,y,path+(str(i),))]
    return [path]

def verify():
    package=ROOT/'history/ERRATUM-01-REVIEW-PACKAGE.zip'
    require(sha(package.read_bytes())==EXPECTED_BASE,'Original package identity')
    with zipfile.ZipFile(package) as z:
        info=z.infolist()
        require(len(info)==84 and len(set(z.namelist()))==84,'Original inventory')
        require(sum(i.file_size for i in info)<30_000_000,'Original size bound')
        for i in info:
            p=PurePosixPath(i.filename)
            require(i.filename.startswith(PREFIX) and not p.is_absolute() and '..' not in p.parts,'Original safe path')
            require(not i.is_dir() and not (i.flag_bits&1) and stat.S_IFMT(i.external_attr>>16) in (0,stat.S_IFREG),'Original ordinary unencrypted member')
        require(z.testzip() is None,'Original ZIP CRC')
        before={i.filename[len(PREFIX):]:z.read(i) for i in info}
    rows=[line.split('  ',1) for line in before['MANIFEST.sha256'].decode().splitlines() if line.strip()]
    require(len(rows)==83 and {p for _,p in rows}==set(before)-{'MANIFEST.sha256'},'Original manifest coverage')
    for digest,rel in rows: require(sha(before[rel])==digest,'Original manifest '+rel)
    review=ROOT/'inputs/DURANKI-v1.2-CLAUDE-REVIEW-04-2026-10-25.md'
    require(sha(review.read_bytes())==EXPECTED_REVIEW,'Review04 identity')
    require((ROOT/'inputs/REVIEW-04-MANIFEST.sha256').read_text().split()[0]==EXPECTED_REVIEW,'Review04 manifest')
    delta=load('FINALIZATION-DELTA-INDEX.json')
    changed={x['path'] for x in delta['modified_existing_files']}
    expected_changed={ARCH,REG+'.json',REG+'.md','DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.json','DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.md','DURANKI-v1.2-C01-REVIEW-AND-RESEARCH-MAP.md','INCORPORATION-MAP.json','START-HERE.md'}
    require(changed==expected_changed,'Changed-file scope')
    for rel,b in before.items():
        if rel=='MANIFEST.sha256': continue
        current=(ROOT/rel).read_bytes()
        require((current!=b)==(rel in changed),'Unannounced edit '+rel)
    for row in delta['modified_existing_files']:
        rel=row['path']; current=(ROOT/rel).read_bytes()
        require(sha(before[rel])==row['before_sha256'] and sha(current)==row['after_sha256'],'Delta identities '+rel)
        require(len(before[rel])==row['before_bytes'] and len(current)==row['after_bytes'],'Delta sizes '+rel)
        require((ROOT/'history/e01-before'/rel).read_bytes()==before[rel],'Before-image '+rel)
    a=(ROOT/ARCH).read_text(); old=before[ARCH].decode()
    s_old=sections(old); s_new=sections(a)
    require(set(s_old)==set(s_new),'Architecture heading identities')
    modified=[k for k in s_old if s_old[k]!=s_new[k]]
    require(set(modified)=={'5.3','5.4'},'Architecture semantic section scope')
    replacements=load('FINALIZATION-REPLACEMENTS.json')
    replay=old
    for r in replacements['text_replacements']:
        if r['file']==ARCH:
            require(replay.count(r['old'])==1,'Exact architecture replacement')
            replay=replay.replace(r['old'],r['new'])
    require(replay==a,'Architecture exact replacement replay')
    reg=load(REG+'.json'); oldreg=json.loads(before[REG+'.json'])
    nodes=all_nodes(reg); oldnodes=all_nodes(oldreg)
    require(len(reg['entries'])==87,'Parent/alias count')
    require(len(nodes)==160 and set(nodes)==set(oldnodes),'73 subcases and stable IDs')
    require(sum(e['kind']=='requirement' for e in reg['entries'])==86,'Canonical parent count')
    require(next(e for e in reg['entries'] if e['id']=='T-84')==next(e for e in oldreg['entries'] if e['id']=='T-84'),'T84 alias preserved')
    for id,node in nodes.items():
        require(node.get('result_status')==oldnodes[id].get('result_status'),'Evidence status changed '+id)
        require(node.get('evidence_refs')==oldnodes[id].get('evidence_refs'),'Evidence references changed '+id)
        require(node.get('result_status')!='PASS','Unearned PASS '+id)
    require(reg['summary']==oldreg['summary'] and reg['evidence']==oldreg['evidence'],'Summary/evidence catalogue unchanged')
    # All parent requirement strings must now be the exact existing section-16 text.
    testsection=a[a.index('## 16.'):a.index('## 17.')]
    statements={f'T-{int(k):02d}':v for k,v in re.findall(r'^(\d+)\. (.+)$',testsection,re.M)}
    for e in reg['entries']:
        if e.get('kind')=='requirement': require(e['requirement']==statements[e['id']],'Parent text correspondence '+e['id'])
    allowed_reg={('document',),('review04_finalization',)}
    for i,e in enumerate(reg['entries']):
        if e['id'] in ('T-07','T-14'): allowed_reg.add(('entries',str(i),'requirement'))
        if e['id']=='T-07':
            j=next(j for j,v in enumerate(e['subcases']) if v['id']=='T-07.a')
            for f in ('requirement','requirement_version','requirement_reference'): allowed_reg.add(('entries',str(i),'subcases',str(j),f))
        if e['id']=='T-24':
            for f in ('scoped_result','remaining_proof'): allowed_reg.add(('entries',str(i),f))
            allowed_reg.add(('entries',str(i),'supplemental_observations','0','limits'))
    reg_diffs=diffpaths(oldreg,reg)
    require(set(reg_diffs)<=allowed_reg,'Register JSON change scope')
    md=(ROOT/(REG+'.md')).read_text()
    for e in reg['entries']:
        for sub in e.get('subcases',[]):
            require(f"| {sub['id']} | {sub['requirement']} |" in md,'MD/JSON subcase match '+sub['id'])
    require('rotated-but-not-revoked' in nodes['T-07.a']['requirement'],'Rotation control')
    require('single-process standalone SQLite profile' in a and 'No database I/O runs under the first-write lock in those profiles.' in a,'Ordering profile scope')
    require('bound plan-signing key version' in a and 'not the active minting-key selector' in a,'Key status dependency')
    require('An uncertain commit, or a committed change' in a and 'closes affected admission/release' in a,'Uncertain update fail-closed')
    for rel in ('DURANKI-v1.2-C01-ROADMAP.md','FICTIONAL-TARIFF-VECTORS.json','DURANKI-DEV05-10-EVIDENCE-CAPTURE-PROMPT.md','EVIDENCE-CAPTURE-PATHS.json'):
        require((ROOT/rel).read_bytes()==before[rel],'Preserved companion '+rel)
    for rel,b in before.items():
        if rel.startswith(('inputs/','predecessor/')): require((ROOT/rel).read_bytes()==b,'Preserved input '+rel)
    # Check only authored active-document local links; quoted historical inputs keep their original links.
    link_count=0
    active=[ARCH,REG+'.md','DURANKI-v1.2-C01-ROADMAP.md','DURANKI-v1.2-C01-REVIEW-AND-RESEARCH-MAP.md','DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.md','DURANKI-v1.2-C01-REVIEW04-CLOSEOUT-01.md','START-HERE.md']
    for rel in active:
        for target in re.findall(r'\]\(([^\s]+)\)',(ROOT/rel).read_text()):
            url=urllib.parse.urlsplit(target)
            if url.scheme or target.startswith('#'): continue
            f=ROOT/urllib.parse.unquote(url.path)
            if f.name=='FINALIZATION-VALIDATION.json' and not f.exists(): continue
            require(f.exists(),'Active local link '+rel+' -> '+target); link_count+=1
    result={'status':'PASS_DOCUMENT_ONLY_FINALIZATION_CHECKS','source_package_sha256':EXPECTED_BASE,'source_payloads_verified':83,'review04_sha256':EXPECTED_REVIEW,'modified_existing_files':len(changed),'architecture_sections_changed':modified,'canonical_parents_matching_section16':86,'parent_alias_ids':87,'subcases':73,'evidence_status_changes':0,'new_runtime_passes':0,'mechanical_parent_text_repairs':['T-07','T-14'],'register_json_changed_fields':['/'.join(p) for p in sorted(reg_diffs)],'checked_active_local_links':link_count,'runtime_execution':'NONE','repo_capture':'NOT_PERFORMED','owner_adoption':'NOT_RECORDED','review_scope':'Author integrity, delta scope and document consistency only; no independent final-byte review or product execution.'}
    manifest=ROOT/'MANIFEST.sha256'
    if manifest.exists():
        mrows=[line.split('  ',1) for line in manifest.read_text().splitlines() if line.strip()]
        actual={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p!=manifest}
        require({p for _,p in mrows}==actual and len(mrows)==len(actual),'Final manifest exact coverage')
        for digest,rel in mrows: require(sha((ROOT/rel).read_bytes())==digest,'Final manifest '+rel)
        result['final_manifest_payloads_verified']=len(mrows)
    return result

if __name__=='__main__':
    print(json.dumps(verify(),indent=2,ensure_ascii=False))
