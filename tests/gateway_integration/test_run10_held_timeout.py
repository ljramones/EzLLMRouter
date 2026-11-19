#!/usr/bin/env python3
"""Focused reviewer tests. No Docker, LiteLLM runtime, installs or external network.

Usage: python ...py --repo PATH --runtime PATH --timeout-source completion_timeout.py
Repository is a reviewer copy or the corrected checkout; runtime is an unchanged,
verified run-10 evidence directory. The LiteLLM helper is compiled as an inspected
AST class only, not imported as a package. Synthetic verifier fixtures are new,
labelled test data, never modifications of historical logs.
"""
import argparse, ast, asyncio, contextlib, copy, glob, hashlib, importlib.util, io, json
from pathlib import Path
import socket, sys, tempfile, typing, unittest

p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True)
p.add_argument('--runtime',type=Path,required=True);p.add_argument('--timeout-source',type=Path,required=True)
args, remaining=p.parse_known_args();ROOT=args.repo.resolve();KIT=ROOT/'tests/gateway_integration'
for d in [ROOT/'server/src',ROOT/'tests/development_slice',KIT,KIT/'inputs/mach33_duranki_client-0.0.3-py3-none-any.whl']:
 sys.path.insert(0,str(d))
for name in ('httpcore','httpx','anyio','h11','certifi','idna','sniffio','typing_extensions'):
 matches=glob.glob(str(ROOT/'gateway-inputs/dev04/wheels'/(name+'-*.whl')))
 if len(matches)!=1: raise RuntimeError('frozen wheel mismatch: '+name)
 sys.path.insert(0,matches[0])
import httpx
from duranki_server.gateway.proxy_recipe import GatewayProxyRecipe, public_destination, proxy_policy
from duranki_server.gateway.guard import ACTIVE, Invocation, provider_expectation
from duranki_server.gateway.owned_sender_transport import LocalSendAuthority, OwnedSocketStream
from duranki_server.canonical import ContractError
from duranki_server.core import Coordinator
from duranki_server.plans import PlanAuthority
from duranki_server.store import SQLiteStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_model_identity import BoundAdapter
FIXTURE=json.loads((ROOT/'tests/development_slice/fixture.json').read_text())
REQUEST=json.loads((ROOT/'tests/development_slice/request.json').read_text())

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
VERIFY=module('review_verifier',KIT/'verify_choice_b_freshness.py')

def run_verifier(directory):
 old=sys.argv;sys.argv=['verify_choice_b_freshness.py',str(directory)]
 try:
  with contextlib.redirect_stdout(io.StringIO()) as out: VERIFY.main()
  return json.loads(out.getvalue())
 finally:sys.argv=old

def synthetic_fixture(directory, error_type='ContractError'):
 """Entirely invented unit data, separate from the owner run."""
 ids=['attempt.synthetic.'+str(i) for i in range(5)];held,queued=ids[2:4]
 def obj(name,value): (directory/(name+'.stdout')).write_text(json.dumps(value)+'\n')
 def lines(name,value): (directory/(name+'.stdout')).write_text(''.join(json.dumps(x)+'\n' for x in value))
 (directory/'choice-b-freshness-hold-sid.stdout').write_text('submission.synthetic.held\n')
 (directory/'choice-b-freshness-queued-sid.stdout').write_text('submission.synthetic.queued\n')
 obj('choice-b-freshness-hold-status',{'submission_id':'submission.synthetic.held','attempt_id':held,'submission_state':'completed','candidate_access':'present'})
 obj('choice-b-freshness-queued-status',{'submission_id':'submission.synthetic.queued','attempt_id':queued,'submission_state':'failed_before_transmit','candidate_access':'unavailable_due_failure','dispatch_state':'failed_before_dispatch','terminal_error_code':'FDC_REJECTED','terminal_attempt_id':queued})
 obj('choice-b-freshness-real-pool-queued',{'attempt_id':queued,'pool_queued':True})
 obj('choice-b-freshness-authority-revoked',{'authority_state':'revoked','epoch':1,'monotonic_ns':20})
 obj('choice-b-freshness-authority-restored',{'authority_state':'active','epoch':2,'monotonic_ns':100})
 lines('choice-b-freshness-pool-observations',[{'attempt_id':queued,'event':'queued_in_owned_httpcore_pool','monotonic_ns':10}])
 events=[];receipts=[];sends=[];arrivals=[]
 for aid in ids:
  events += [{'attempt_id':aid,'stage':stage,'monotonic_ns':i+1} for i,stage in enumerate(['entered','commit_acknowledged','released_to_lower_transport'])]
  if aid==queued:events += [{'attempt_id':aid,'stage':'lower_error','monotonic_ns':25}]
  receipt={'method':'POST','url':'http://127.0.0.1:8766/v1/chat/completions','body_sha256':'synthetic-only-not-a-real-digest','body_bytes':4,'timeout_seconds':dict.fromkeys(['connect','read','write','pool'],30.0 if aid in [held,queued] else 1.0)}
  receipts.append({'attempt_id':aid,'receipt':receipt})
  sends.append({'attempt_id':aid,'first_bytes_accepted_by_local_socket':aid!=queued,'first_acceptance_events':int(aid!=queued),'lower_error':error_type if aid==queued else None})
  if aid!=queued:arrivals.append({'attempt_id':aid,'method':'POST','body_sha256':receipt['body_sha256'],'body_bytes':4})
 lines('choice-b-freshness-guard-events',events);lines('choice-b-freshness-receipts',receipts)
 lines('choice-b-freshness-send-events',sends);lines('choice-b-freshness-receiver-final',arrivals)
 lines('choice-b-freshness-receiver-controls',[
  {'event':'hold_entered_after_receiver_arrival','at_ns':5},
  {'event':'hold_released','at_ns':30},
  {'event':'hold_response_released','at_ns':40}])
 obj('choice-b-freshness-positive-after',{'state':'delivered','receiver_delta':1})
 for name in ['choice-b-freshness-receiver-before-horizon','choice-b-freshness-receiver-after-horizon']:lines(name,arrivals[:3])
 (directory/'choice-b-freshness-horizon.stdout').write_text('5200\n')
 obj('choice-b-freshness-store',{'submissions':5,'preparatory_intents':5,'guard_dispatches':5,'usage_revisions':4})
 return held,queued

def edit_obj(d,name,fn):
 p=d/(name+'.stdout');v=json.loads(p.read_text());fn(v);p.write_text(json.dumps(v)+'\n')

def edit_rows(d,name,fn):
 p=d/(name+'.stdout');v=[json.loads(x) for x in p.read_text().splitlines()];fn(v);p.write_text(''.join(json.dumps(x)+'\n' for x in v))

class Run10Controls(unittest.TestCase):
 def projection(self):
  return {'destination':public_destination(FIXTURE),'work':{'messages':copy.deepcopy(REQUEST['messages']),'requested_features':['text'],'generation_settings':{'max_output_tokens':32}}}
 def test_private_recipe_binds_each_timeout_and_keeps_public_work(self):
  projection=self.projection(); original=copy.deepcopy(projection)
  for ms in [1000,30000]:
   raw,control=GatewayProxyRecipe().expected(projection,ms);body=json.loads(raw)
   self.assertEqual(body['timeout'],ms/1000);self.assertEqual(body['max_retries'],0)
   self.assertEqual(control['timeout_ms'],ms);self.assertEqual(control['content_length'],len(raw))
   self.assertEqual(control['body_sha256'],hashlib.sha256(raw).hexdigest())
   self.assertEqual(projection,original);self.assertNotIn('timeout',provider_expectation(projection))
 def test_invalid_timeout_not_bound_as_default(self):
  for ms in [True,0,-1,1.5]:
   with self.assertRaises(ValueError):GatewayProxyRecipe().expected(self.projection(),ms)
 def test_selected_pinned_timeout_resolver_prefers_explicit_budget(self):
  raw=args.timeout_source.read_bytes()
  if hashlib.sha256(raw).hexdigest()!='eff70b501760bab0c31fe86a1b6c0dcde0045c8fdd50503016fc88178abf0898':
   # Exact expected hash supplied in the handoff; substituted by author below.
   raise AssertionError('pinned helper byte identity mismatch')
  tree=ast.parse(raw);cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='CompletionTimeout')
  ns={'httpx':httpx,'Final':typing.Final,'Callable':typing.Callable,'COMPLETION_HTTP_FALLBACK_SECONDS':600.0}
  exec(compile(ast.Module(body=[cls],type_ignores=[]),str(args.timeout_source),'exec'),ns)
  resolve=ns['CompletionTimeout'].resolve
  self.assertEqual(resolve(None,{'request_timeout':1},'openai',global_timeout=1,supports_httpx_timeout=lambda _:True),1.0)
  for ms in [1000,30000]:
   body=json.loads(GatewayProxyRecipe().expected(self.projection(),ms)[0]);body['request_timeout']=1
   self.assertEqual(resolve(None,body,'openai',global_timeout=1,supports_httpx_timeout=lambda _:True),ms/1000)
 def test_real_coordinator_fresh_callback_is_contracterror_and_no_socket_bytes(self):
  class Capture(BoundAdapter):
   def send_with_context(self, prepared, timeout_ms, expected, context):
    self.context=context
    return super().send_with_context(prepared,timeout_ms,expected,context)
  with tempfile.TemporaryDirectory() as tmp:
   store=SQLiteStore(Path(tmp)/'db');adapter=Capture();trusted=copy.deepcopy(FIXTURE['trusted_context']);identity={'token':trusted}
   coordinator=Coordinator(store,identity,public_destination(FIXTURE),copy.deepcopy(FIXTURE['prompt_blocks']),copy.deepcopy(FIXTURE['allowed_lineages']),PlanAuthority(Ed25519PrivateKey.generate(),proxy_policy(FIXTURE)),adapter,copy.deepcopy(FIXTURE['retention']),copy.deepcopy(FIXTURE['classification']),GatewayProxyRecipe(),trusted_source_labels=copy.deepcopy(FIXTURE['trusted_source_labels']))
   try:
    status,reply=coordinator.submit(copy.deepcopy(REQUEST),trusted,3000,credential='token');self.assertEqual(status,200)
    identity['token']={**trusted,'context_id':trusted['context_id']+'.revoked'}
    context=adapter.context
    with self.assertRaises(ContractError) as err:context['fresh_check']()
    self.assertEqual(err.exception.code,'PLAN_INVALID_OR_STALE')
    async def probe():
     a,b=socket.socketpair();a.setblocking(False);b.setblocking(False)
     auth=LocalSendAuthority();item=Invocation(**context);item.committed=item.released=True;item.authority_epoch=auth.snapshot_epoch()
     stream=OwnedSocketStream(a,auth);token=ACTIVE.set(item)
     try:
      with self.assertRaises(ContractError):await stream.write(b'NO_PROVIDER_REQUEST',1)
      self.assertFalse(item.first_bytes_accepted)
      self.assertEqual(b.recv(1),b'')
     finally:ACTIVE.reset(token);await stream.aclose();b.close()
    asyncio.run(probe())
   finally:coordinator.pool.shutdown(wait=True);store.close()
 def test_synthetic_domain_rejection_with_valid_semantics_passes(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d);self.assertEqual(run_verifier(d)['queued_receiver_arrivals'],0)
 def test_synthetic_guard_rejection_with_valid_semantics_passes(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d,'GuardRejected');self.assertEqual(run_verifier(d)['queued_receiver_arrivals'],0)
 def test_unknown_or_missing_terminal_reason_rejects(self):
  for reason in [None,'INTERNAL_UNAVAILABLE']:
   with tempfile.TemporaryDirectory() as t:
    d=Path(t);synthetic_fixture(d);edit_obj(d,'choice-b-freshness-queued-status',lambda v:v.update(terminal_error_code=reason))
    with self.assertRaises(AssertionError):run_verifier(d)
 def test_different_internal_error_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d,'ValueError')
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_queued_send_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);_,q=synthetic_fixture(d)
   edit_rows(d,'choice-b-freshness-send-events',lambda rr:next(r for r in rr if r['attempt_id']==q).update(first_bytes_accepted_by_local_socket=True))
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_held_timeout_does_not_become_accepted_positive(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d);edit_obj(d,'choice-b-freshness-hold-status',lambda v:v.update(submission_state='outcome_unknown',candidate_access='not_yet_available'))
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_one_second_effective_hold_timeout_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);h,_=synthetic_fixture(d)
   edit_rows(d,'choice-b-freshness-receipts',lambda rr:next(r for r in rr if r['attempt_id']==h)['receipt']['timeout_seconds'].update(read=1.0))
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_widened_ordinary_timeout_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d)
   edit_rows(d,'choice-b-freshness-receipts',lambda rr:rr[0]['receipt']['timeout_seconds'].update(read=30.0))
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_missing_receiver_release_control_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d)
   edit_rows(d,'choice-b-freshness-receiver-controls',lambda rr:rr.pop())
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_missing_receipt_rejects(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);synthetic_fixture(d);edit_rows(d,'choice-b-freshness-receipts',lambda rr:rr.pop())
   with self.assertRaises(AssertionError):run_verifier(d)
 def test_original_run_still_fails_without_rewriting_it(self):
  before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.runtime.iterdir() if p.is_file()}
  with self.assertRaises(AssertionError):run_verifier(args.runtime)
  after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.runtime.iterdir() if p.is_file()}
  self.assertEqual(before,after)

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+remaining,verbosity=2)
