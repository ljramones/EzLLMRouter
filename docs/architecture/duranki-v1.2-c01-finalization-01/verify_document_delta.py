#!/usr/bin/env python3
"""Verify only this document package. No product imports, network or application work."""
from pathlib import Path, PurePosixPath
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_CEILING
import argparse, copy, hashlib, json, re, sys
from urllib.parse import unquote, urlsplit

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def check(root):
    a='DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md'
    assert digest(root/'inputs/DURANKI-v1.2-CLAUDE-REVIEW-03-2026-10-25.md')=='867c1a7635bac5e4cca56a957aebe95f47b31c3936b8664ca61d6001719a550f'
    assert digest(root/'predecessor'/a).startswith('3cb18d2dae9a2abf')
    # Reproduce the small textual delta, rather than inspecting only final keywords.
    ops=json.loads((root/'ERRATUM-REPLACEMENTS.json').read_text())['operations']
    for name in [a,'DURANKI-v1.2-C01-ROADMAP.md']:
        t=(root/'predecessor'/name).read_text()
        for op in [o for o in ops if o['file']==name]:
            assert t.count(op['old'])==1,(name,op['clause'])
            t=t.replace(op['old'],op['new'])
        assert t==(root/name).read_text(),name+' non-declared text change'
    def sections(text):
        chunks={}; key='header'; lines=[]
        for line in text.splitlines(keepends=True):
            m=re.match(r'^#{2,4} (\d+(?:\.\d+)*)(?:\.|\s)',line)
            if m:
                assert key not in chunks,key
                chunks[key]=''.join(lines);key=m.group(1);lines=[]
            lines.append(line)
        chunks[key]=''.join(lines);return chunks
    before=sections((root/'predecessor'/a).read_text());after=sections((root/a).read_text())
    assert before.keys()==after.keys(),'section identity changed'
    changed=[k for k in before if before[k]!=after[k]]
    assert set(changed)=={'header','5.3','5.4','9.4','16','16.1'},changed
    # Original source copies in inputs remain byte-identical to the C01 manifest.
    original_rows=[]
    for line in (root/'predecessor/MANIFEST.sha256').read_text().splitlines():
        h,n=line.split(None,1);n=n.strip()
        if n.startswith('inputs/'):
            assert digest(root/n)==h,n
            original_rows.append(n)
        elif (root/'predecessor'/n).exists():
            assert digest(root/'predecessor'/n)==h,('predecessor changed',n)
    j='DURANKI-v1.2-C01-ASSURANCE-REGISTER.json'
    old=json.loads((root/'predecessor'/j).read_text());new=json.loads((root/j).read_text())
    oldby={x['id']:x for x in old['entries']}; newby={x['id']:x for x in new['entries']}
    assert len(newby)==87 and oldby.keys()==newby.keys()
    assert sum(x['kind']=='requirement' for x in newby.values())==86
    assert newby['T-84']['canonical_id']=='T-49'
    olds={s['id']:s for e in old['entries'] for s in e.get('subcases',[])}
    news={s['id']:s for e in new['entries'] for s in e.get('subcases',[])}
    assert len(olds)==71 and len(news)==73
    assert set(news)-set(olds)=={'T-07.a','T-14.a'}
    assert not(set(olds)-set(news))
    revised=[sid for sid in olds if olds[sid]!=news[sid]]
    assert set(revised)=={'T-46.b','T-79.c','T-48.g'},revised
    for e in new['entries']:
        assert e.get('result_status') not in ['PASS','PASSED','COMPLETE']
        for s in e.get('subcases',[]):
            assert s['id'].startswith(e['id']+'.')
            assert s.get('result_status') not in ['PASS','PASSED','COMPLETE']
        for ref in e.get('evidence_refs',[]):assert ref in new['evidence']
    assert len({s['id'] for e in new['entries'] for s in e.get('subcases',[])})==73
    md=(root/'DURANKI-v1.2-C01-ASSURANCE-REGISTER.md').read_text()
    # Each parent map row and subcase row occurs exactly once.
    for pid in newby:assert len(re.findall(r'^\| '+re.escape(pid)+r' \|',md,re.M))==1,pid
    for sid in news:assert len(re.findall(r'^\| '+re.escape(sid)+r' \|',md,re.M))==1,sid
    for sid in ['T-07.a','T-14.a','T-46.b','T-79.c','T-48.g']:assert news[sid]['requirement'] in md
    # Preserve earlier vectors and check the new financial example independently.
    v=json.loads((root/'FICTIONAL-TARIFF-VECTORS.json').read_text())
    ov=json.loads((root/'predecessor/FICTIONAL-TARIFF-VECTORS.json').read_text())
    vc=copy.deepcopy(v);pair=vc['tariff_b'].pop('per_attempt_rounding_pair');assert vc==ov
    q=Decimal(v['ledger_quantum']);rounding=lambda x:x.quantize(q,rounding=ROUND_HALF_EVEN)
    ceiling=lambda x:x.quantize(q,rounding=ROUND_CEILING)
    aa=[];bb=[]
    for n in range(1,26):
        x=max(Decimal('.005'),Decimal('.003')*((n+9)//10));aa.append(ceiling(x));assert rounding(x)<=ceiling(x)
        y=Decimal(n)*(Decimal('.0003000005') if n<=10 else Decimal('.0004000005'));bb.append(ceiling(y));assert rounding(y)<=ceiling(y)
    assert max(aa)==Decimal(v['tariff_a']['maximum_domain_bound'])
    assert max(bb)==Decimal(v['tariff_b']['maximum_domain_bound'])
    for c in v['tariff_a']['cases']:
        raw=max(Decimal('.005'),Decimal('.003')*((c['documents']+9)//10));assert raw==Decimal(c['raw']) and rounding(raw)==Decimal(c['settled'])
    for c in v['tariff_b']['cases']:
        n=c['documents'];raw=n*(Decimal('.0003000005') if n<=10 else Decimal('.0004000005'));assert raw==Decimal(c['raw']) and rounding(raw)==Decimal(c['settled']) and ceiling(raw)==Decimal(c['request_bound'])
    rate=Decimal(pair['rate_per_document']);split=3*rounding(rate);batch=rounding(3*rate)
    assert split==Decimal(pair['separate_attempts']['settled_total'])==Decimal('0.000900000')
    assert batch==Decimal(pair['batched_attempt']['settled'])==Decimal('0.000900002')
    assert 3*ceiling(rate)==Decimal(pair['separate_attempts']['summed_request_bounds'])
    assert ceiling(3*rate)==Decimal(pair['batched_attempt']['upward_request_bound'])
    assert batch-split==Decimal(pair['settled_difference'])
    # Only links in active authored Markdown are evaluated here. Copied inputs and old
    # historical diffs retain original locators, including unavailable repository files.
    checked_links=[]
    for f in root.glob('*.md'):
        t=f.read_text();assert t.count('```')%2==0,(f.name,'unbalanced fence')
        for m in re.finditer(r'\]\(([^\n]+?)\)',t):
            u=m.group(1).strip();parts=urlsplit(u)
            if parts.scheme or u.startswith('#'):continue
            loc=unquote(parts.path)
            if not loc:continue
            if loc=='MANIFEST.sha256' and not (root/loc).exists():continue
            assert (f.parent/loc).exists(),(f.name,u)
            checked_links.append([f.name,u])
    manifest_verified=None
    manifest=root/'MANIFEST.sha256'
    if manifest.exists():
        seen=set()
        for l in manifest.read_text().splitlines():
            h,n=l.split(None,1);n=n.strip();pp=PurePosixPath(n)
            assert not pp.is_absolute() and '..' not in pp.parts and n not in seen
            seen.add(n);assert digest(root/n)==h,n
        actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}-{'MANIFEST.sha256'}
        assert seen==actual,('manifest coverage',seen^actual)
        manifest_verified=len(seen)
    return {'status':'PASS_DOCUMENT_DELTA_CHECKS','review03_sha256':digest(root/'inputs/DURANKI-v1.2-CLAUDE-REVIEW-03-2026-10-25.md'),'changed_architecture_sections':changed,'unchanged_sections':len(before)-len(changed),'original_input_copies_unchanged':len(original_rows),'register':{'parent_and_alias_ids':87,'canonical_parents':86,'retired_aliases':1,'subcases':73,'added':['T-07.a','T-14.a'],'amended':['T-46.b','T-79.c'],'rounding_extension':'T-48.g','unqualified_parent_passes':0},'tariffs':{'original_vector_data_preserved':True,'tariff_a_domain_cases':25,'tariff_b_domain_cases':25,'split_settled_usd':str(split),'batch_settled_usd':str(batch)},'active_markdown_links_checked':len(checked_links),'manifest_payloads_verified':manifest_verified,'product_tests_run':0,'provider_requests':0,'scope':'Document consistency, exact identities, source-record integrity and fictional arithmetic only; not independent closure, owner adoption or runtime qualification.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);args=p.parse_args()
    try: result=check(args.root.resolve())
    except Exception as exc:
        print(json.dumps({'status':'FAIL_DOCUMENT_DELTA_CHECKS','error':str(exc)},indent=2));sys.exit(1)
    print(json.dumps(result,indent=2))
