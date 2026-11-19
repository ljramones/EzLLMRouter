// Pure, offline DEV-12/A1 candidate-03 contract checker. No product imports or sockets.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const r=require('./reference.cjs'),root=path.resolve(__dirname,'..');
const read=n=>JSON.parse(fs.readFileSync(path.join(root,n),'utf8'));
const s=read('schemas.json'),v=read('vectors.json'),t=read('tariffs.json'),g=read('registrations.json');
let checks=0;const ok=(x,m)=>{assert.ok(x,m);checks++},eq=(a,b,m)=>{assert.deepEqual(a,b,m);checks++};
const clone=x=>structuredClone(x),example=id=>v.examples.find(x=>x.id===id);
function setPath(x,path,value){const a=path.split('.');let p=x;for(const k of a.slice(0,-1))p=p[k];Object.defineProperty(p,a.at(-1),{value,writable:true,enumerable:true,configurable:true});}
function delPath(x,path){const a=path.split('.');let p=x;for(const k of a.slice(0,-1))p=p[k];delete p[a.at(-1)];}
function rejection(fn,label){let rejected=false;try{fn()}catch{rejected=true}ok(rejected,label);}
check();
function check(){
 ok(r.checkRefs(s)>50,'all local refs resolve');
 ok(r.schemaValid(g,s.$defs.RegistryFixture,s),'complete fixed public registry');
 eq(g.configurations.length,3,'three immutable synthetic configurations');eq(g.price_contracts.length,4,'four operation prices');
 for(const x of v.examples){
  ok(r.schemaValid(x.request,s.$defs.SubmitRequest,s),x.id+' request shape');
  ok(r.schemaValid(x.trusted_context,s.$defs.TrustedContext,s),x.id+' trusted shape');
  eq(r.classifyRequest(x.request,x.trusted_context,g,s),'ACCEPT',x.id+' semantics');
  const work=r.workProjection(x.request,x.trusted_context);
  eq(work,x.canonical_work,x.id+' independent projection');
  eq(Buffer.from(r.canonical(work),'utf8').toString('base64'),x.canonical_bytes_base64,x.id+' canonical bytes');
  eq(Buffer.byteLength(r.canonical(work)),x.canonical_byte_length,x.id+' byte length');
  eq(r.workDigest(work),x.work_digest,x.id+' domain digest');
  ok(r.schemaValid(x.admission_snapshot,s.$defs.AdmissionSnapshot,s),x.id+' assessment shape');
  ok(r.assessmentValid(x.admission_snapshot,x,s),x.id+' assessment semantics');
  eq(r.digest('ezllmrouter-admission-v1\n',x.admission_snapshot),x.admission_snapshot_digest,x.id+' assessment digest');
 }
 const direct=example('DIRECT_DOCUMENT'),explicit=example('EXPLICIT_DIRECT_OMISSION');
 ok(!r.own(direct.request.metadata,'commission')&&!r.own(direct.canonical_work.metadata,'commission'),'absence remains absent');
 ok(r.own(explicit.request.metadata,'commission'),'explicit caller reason retained');
 eq(r.canonical(direct.canonical_work.work_key),r.canonical(explicit.canonical_work.work_key),'same key');
 ok(direct.work_digest!==explicit.work_digest,'distinct asserted work conflicts at same key');
 const improved=clone(direct.admission_snapshot);improved.assessed_at='2030-01-01T00:00:02Z';
 eq(r.workDigest(r.workProjection(direct.request,direct.trusted_context)),direct.work_digest,'server reassessment does not alter work');
 ok(r.digest('ezllmrouter-admission-v1\n',improved)!==direct.admission_snapshot_digest,'assessment separately changes');
 for(const x of v.result_examples){const e=example(x.request_case);ok(r.resultValid(x.value,e.request,x.value.attempt_id,g,s),x.id+' correlated result');}
 const rr=v.result_examples.find(x=>x.id==='RERANK_RESULT');
 for(const field of ['attempt_id','ranking_profile_id']){const bad=clone(rr.value);bad[field]='wrong';ok(!r.resultValid(bad,example(rr.request_case).request,'attempt.rank',g,s),'result '+field+' mismatch');}
 const er=v.result_examples.find(x=>x.id==='EMBEDDING_RESULT');
 for(const field of ['profile_id','model_ref','dimensions']){const bad=clone(er.value);bad[field]=field==='dimensions'?4:'wrong';ok(!r.resultValid(bad,direct.request,'attempt.doc',g,s),'result '+field+' mismatch');}
 const p=v.plan_fixture,e=example(p.request_case),plan=p.signed_plan;
 ok(r.schemaValid(plan,s.$defs.SignedPlan,s),'complete signed plan shape');
 ok(r.planValid(plan,e.request,e,g,s),'complete plan semantics');
 eq(r.recipeFor(e.request,e.work_digest,r.configFor(e.request,g),plan.execution_descriptor),p.preparation_recipe,'preparation recipe');
 eq(r.planMessage(plan).toString('base64'),p.signing_message_base64,'full canonical signing bytes');
 eq(r.sha(r.planMessage(plan)),p.signing_message_sha256,'signing digest');
 const key=v.execution_eligibility_context.verification_keys[0],authority=v.execution_eligibility_context;
 ok(r.schemaValid(authority,s.$defs.ExecutionEligibilityContext,s),'independent execution context shape');
 ok(r.signatureValid(plan,key),'specified full-plan Ed25519 signature');
 ok(r.executionEligible(plan,e,g,s,authority),'full signed execution eligibility');
 for(const [field,value] of [
  ['work_digest','sha256:'+'0'.repeat(64)],['admission_snapshot_digest','sha256:'+'0'.repeat(64)],
  ['submission_id','submission.other'],['attempt_id','attempt.other'],['destination_ref','destination.other'],
  ['financial_owner_id','other'],['price_ref','other@1'],['expires_at','2030-01-01T00:20:00Z'],
  ['authority_revisions.grant',2],['authority_revisions.key_eligibility',2],
  ['execution_context',{state:'tagged_fixture',epoch:'epoch.synthetic.2'}],
  ['key_id','synthetic.other.key'],['key_version','v2'],
  ['reservation.reservation_id','reservation.other'],['reservation.budget_account_id','budget.other'],
  ['reservation.max_exposure_decimal','0.000900003'],
  ['execution_descriptor.route','/synthetic/v1/embeddings'],['execution_descriptor.max_request_bytes',1]
 ]){
  const bad=clone(plan);setPath(bad,field,value);
  ok(r.schemaValid(bad,s.$defs.SignedPlan,s),'schema-valid signed mutation '+field);
  ok(!r.signatureValid(bad,key),'signature covers '+field);
  ok(!r.executionEligible(bad,e,g,s,authority),'mutation cannot execute '+field);
 }
 const rotated=clone(authority);rotated.active_minting_key={key_id:'synthetic.test.key',key_version:'v2'};
 ok(r.signatureValid(plan,key)&&r.executionEligible(plan,e,g,s,rotated),'same v1 plan remains eligible after minting rotation');
 const revokedKey=clone(rotated);revokedKey.verification_keys[0].eligibility='revoked';
 ok(r.signatureValid(plan,key)&&!r.executionEligible(plan,e,g,s,revokedKey),'same signed plan denied after bound-key revocation');
 const revokedPlan=clone(authority);revokedPlan.plan_revoked=true;
 ok(r.signatureValid(plan,key)&&!r.executionEligible(plan,e,g,s,revokedPlan),'same signed plan denied after plan revocation');
 for(const field of Object.keys(plan.authority_revisions)){const changed=clone(authority);changed.current_authority_revisions[field]++;
  ok(!r.executionEligible(plan,e,g,s,changed),'current '+field+' revision mismatch');}
 for(const [label,change] of [
  ['unknown bound tuple',c=>{c.verification_keys=[]}],['unknown key eligibility',c=>{c.verification_keys[0].eligibility='unknown'}],
  ['wrong public key',c=>{c.verification_keys[0].public_key_spki_base64=crypto.generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'der'}).toString('base64')}],
  ['no send permission',c=>{c.send_permission=false}],['wrong assessment context',c=>{c.expected_admission_snapshot_digest='sha256:'+'0'.repeat(64)}],
  ['wrong submission context',c=>{c.expected_submission_id='submission.other'}],['wrong attempt context',c=>{c.expected_attempt_id='attempt.other'}],
  ['wrong budget context',c=>{c.expected_reservation.budget_account_id='budget.other'}],
  ['wrong owner context',c=>{c.expected_financial_owner_id='team.other'}],
  ['wrong activation context',c=>{c.expected_execution_context={state:'tagged_fixture',epoch:'epoch.other'}}],
  ['at expiry',c=>{c.evaluation_time=plan.expires_at}],['after expiry',c=>{c.evaluation_time='2030-01-01T00:30:01Z'}]
 ]){const changed=clone(authority);change(changed);ok(!r.executionEligible(plan,e,g,s,changed),label+' denies execution');}
 const before=clone(authority);before.evaluation_time='2030-01-01T00:29:59Z';ok(r.executionEligible(plan,e,g,s,before),'one second before expiry eligible');
 const tagged=v.activation_tagged_fixture;
 eq(r.sha(r.planMessage(tagged.signed_plan)),tagged.signing_message_sha256,'tagged activation signed bytes');
 ok(r.executionEligible(tagged.signed_plan,e,g,s,tagged.execution_eligibility_context),'independent tagged activation epoch positive');
 const wrongEpoch=clone(tagged.execution_eligibility_context);wrongEpoch.expected_execution_context.epoch='epoch.synthetic.2';
 ok(!r.executionEligible(tagged.signed_plan,e,g,s,wrongEpoch),'tagged activation epoch mismatch denied');
 const duplicateKey=clone(authority);duplicateKey.verification_keys.push(clone(duplicateKey.verification_keys[0]));
 ok(!r.executionEligible(plan,e,g,s,duplicateKey),'ambiguous duplicate bound key tuple denied');
 const malformedContext=clone(authority);malformedContext.send_permission='true';
 ok(!r.executionEligible(plan,e,g,s,malformedContext),'context boolean type enforced');
 const malformed=clone(plan);malformed.signature='A'.repeat(86);ok(!r.signatureValid(malformed,key),'malformed/invalid original signature rejected');
 const wrongLen=clone(plan);wrongLen.signature='x';ok(!r.signatureValid(wrongLen,key),'signature length and encoding enforced');
 const testKey=crypto.generateKeyPairSync('ed25519');
 const fresh=clone(plan);fresh.key_id='synthetic.test.fresh';fresh.signature=crypto.sign(null,r.planMessage(fresh),testKey.privateKey).toString('base64url');
 const freshContext=clone(authority);freshContext.verification_keys=[{key_id:fresh.key_id,key_version:fresh.key_version,public_key_spki_base64:testKey.publicKey.export({format:'der',type:'spki'}).toString('base64'),eligibility:'eligible'}];
 ok(r.signatureValid(fresh,freshContext.verification_keys[0])&&r.executionEligible(fresh,e,g,s,freshContext),'fresh trusted synthetic signature positive');
 for(const [label,change] of [
  ['submission',x=>{x.submission_id='submission.other'}],['attempt',x=>{x.attempt_id='attempt.other'}],
  ['budget',x=>{x.reservation.budget_account_id='budget.other'}],['reservation',x=>{x.reservation.reservation_id='reservation.other'}]
 ]){const signed=clone(fresh);change(signed);signed.signature=crypto.sign(null,r.planMessage(signed),testKey.privateKey).toString('base64url');
  ok(r.signatureValid(signed,freshContext.verification_keys[0]),'properly signed '+label+' mutation');
  ok(!r.executionEligible(signed,e,g,s,freshContext),'independent admitted '+label+' rejects');}
 const slowFixture=v.nonconforming_timeout_fixture,slow=slowFixture.signed_plan;
 const slowKey={public_key_spki_base64:slowFixture.public_key_spki_base64};
 eq(r.sha(r.planMessage(slow)),slowFixture.signing_message_sha256,'nonconforming timeout full signing bytes');
 eq(slow.execution_descriptor.recipe_digest,r.digest('ezllmrouter-preparation-v1\n',r.recipeFor(e.request,e.work_digest,r.configFor(e.request,g),slow.execution_descriptor)),'nonconforming timeout recipe recomputed');
 ok(r.signatureValid(slow,slowKey),'internally consistent non-5000 plan is correctly signed');
 const slowContext=clone(authority);slowContext.verification_keys=[{key_id:slow.key_id,key_version:slow.key_version,public_key_spki_base64:slowFixture.public_key_spki_base64,eligibility:'eligible'}];
 ok(!r.schemaValid(slow,s.$defs.SignedPlan,s)&&!r.planValid(slow,e.request,e,g,s)&&!r.executionEligible(slow,e,g,s,slowContext),'fixed 5000 ms timeout enforced');
 const empty=v.historical_contexts.EMPTY,known=v.usage_fixtures.find(x=>x.id==='RERANK_B_REPORTED').value,
  unknown=v.usage_fixtures.find(x=>x.id==='RERANK_B_MISSING').value,second=v.usage_fixtures.find(x=>x.id==='RERANK_B_REVISION_2').value;
 for(const [name,h] of Object.entries(v.historical_contexts))ok(r.acceptedHistoryValid(h,e,plan,g,s),name+' accepted history');
 for(const x of v.usage_fixtures){const h=v.historical_contexts[x.history_context];
  ok(r.schemaValid(x.value,s.$defs.UsageRevision,s),x.id+' usage shape');
  ok(r.usageValid(x.value,e,plan,g,s,h),x.id+' history-backed usage semantics');
 }
 for(const x of v.protocol_fixtures){ok(r.schemaValid(x.value,s.$defs[x.schema],s),x.id+' protocol shape');
  if(x.schema==='SubmitReply')ok(r.replyValid(x.value,e,plan.submission_id,plan.attempt_id,g,s),x.id+' reply correlation');
  if(x.schema==='StatusSnapshot'){
   const hp=x.plan_fixture==='historical_underbound'?v.historical_underbound.signed_plan:plan;
   const h=x.history_context==='UNDERBOUND_OBSERVED'?v.historical_underbound.historical_context_observed:v.historical_contexts[x.history_context];
   const retention=x.retention_context?v[x.retention_context]:null;
   ok(r.statusValid(x.value,e,hp,g,s,h,retention),x.id+' status correlation and effective usage');
  }}
 const completed=v.protocol_fixtures.find(x=>x.id==='COMPLETED');
 const wrong=clone(completed.value);wrong.result.attempt_id='attempt.doc';ok(!r.replyValid(wrong,e,plan.submission_id,plan.attempt_id,g,s),'outer-result attempt mismatch');
 const wrongReplySub=clone(completed.value);wrongReplySub.handle.submission_id='submission.other';
 ok(!r.replyValid(wrongReplySub,e,plan.submission_id,plan.attempt_id,g,s),'right work/attempt with wrong reply submission rejected');
 const status=v.protocol_fixtures.find(x=>x.id==='STATUS_VALID_UNKNOWN_COST').value,wrongStatusSub=clone(status);
 wrongStatusSub.handle.submission_id='submission.other';
 ok(!r.statusValid(wrongStatusSub,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1),'right work/attempt with wrong status submission rejected');
 const wrongUsage=clone(known);wrongUsage.attempt_id='other';ok(!r.usageValid(wrongUsage,e,plan,g,s,empty),'plan-usage attempt mismatch');
 for(const x of v.negative_cases){if(x.target==='raw'){const raw=x.raw_bytes_base64?Buffer.from(x.raw_bytes_base64,'base64'):Buffer.from(x.raw,'utf8');rejection(()=>r.strictDecode(raw),x.id);continue;}
  const resultFixture=x.target==='result'?v.result_examples.find(z=>z.id===x.base):null;
  const base=example(resultFixture?resultFixture.request_case:x.base),obj=clone(x.target==='request'?base.request:x.target==='result'?resultFixture.value:base.trusted_context);
  if(r.own(x,'delete_path'))delPath(obj,x.delete_path);else setPath(obj,x.path,x.value);
  let got;if(x.target==='request')got=r.classifyRequest(obj,base.trusted_context,g,s);
  else if(x.target==='result')got=!r.schemaValid(obj,s.$defs.Result,s)?'SCHEMA_INVALID':r.resultValid(obj,base.request,resultFixture.value.attempt_id,g,s)?'ACCEPT':'RESULT_INVALID';
  else got=r.schemaValid(obj,s.$defs.TrustedContext,s)?'ACCEPT':'SCHEMA_INVALID';
  eq(got,x.expect,x.id);
 }
 const hostile=clone(direct.request);Object.defineProperty(hostile,'__proto__',{value:'x',enumerable:true});
 ok(!r.schemaValid(hostile,s.$defs.SubmitRequest,s),'own __proto__ rejected');
 for(const key of ['constructor','toString']){const h=clone(direct.request);h[key]='x';ok(!r.schemaValid(h,s.$defs.SubmitRequest,s),'own '+key+' rejected');}
 for(const raw of ['{"__proto__":1}','{"constructor":1}','{"toString":1}']){const decoded=r.strictDecode(Buffer.from(raw));ok(r.own(decoded,Object.keys(JSON.parse(raw))[0]),'hostile own key decoded without prototype mutation');}
 rejection(()=>r.strictDecode(Buffer.from([0xc3,0x28])),'invalid UTF-8');
 rejection(()=>r.strictDecode(Buffer.from('\ufeff{}')),'BOM');
 rejection(()=>r.strictDecode(Buffer.alloc(262145,0x20)),'byte ceiling');
 rejection(()=>r.strictDecode(Buffer.from('['.repeat(33)+'0'+']'.repeat(33))),'depth ceiling');
 ok(r.strictDecode(Buffer.from(' '.repeat(4)+'{"n":9007199254740991}')).n===9007199254740991,'safe integer/JSON whitespace boundary');
 for(const [label,change] of [
  ['wrong quantity',u=>{u.components[0].quantity=2}],['wrong component',u=>{u.components[0].component='search_units'}],
  ['wrong amount',u=>{u.amount_decimal='0.000900003'}],['wrong price',u=>{u.price_ref='tariff.synthetic.a@1'}],
  ['wrong semantics',u=>{u.usage_semantics_ref='wrong@1'}],['missing amount',u=>{delete u.amount_decimal}],
  ['duplicate component',u=>{u.components.push(clone(u.components[0]))}],['wrong predecessor',u=>{u.revision=2;u.previous_revision=3}]
 ]){const u=clone(known);change(u);ok(!r.usageValid(u,e,plan,g,s,empty),label+' rejected');}
 const unknownWithAmount=clone(unknown);unknownWithAmount.amount_decimal='0.000000000';ok(!r.usageValid(unknownWithAmount,e,plan,g,s,empty),'unknown cannot carry invented zero');
 const under=v.historical_underbound,over=under.usage;
 ok(r.signatureValid(under.signed_plan,{public_key_spki_base64:under.public_key_spki_base64}),'historical underbound stored plan signed');
 ok(!r.planValid(under.signed_plan,e.request,e,g,s),'historical underbound does not qualify new admission');
 ok(r.usageValid(over,e,under.signed_plan,g,s,under.historical_context),'actual historical charge above bound remains visible');
 ok(!r.usageValid(known,e,under.signed_plan,g,s,under.historical_context),'overbound may not be mislabeled calculated');
 const first=r.acceptUsage(unknown,e,plan,g,s,empty);
 eq(first.decision,'accepted','unknown revision 1 accepted');
 const next=r.acceptUsage(second,e,plan,g,s,first.history);
 eq(next.decision,'accepted','observed revision 2 replaces unknown');
 const firstRecord={history:next.history,example:e,plan};
 eq(r.effectiveTotals([firstRecord],g,s),{known_amount_decimal:'0.000900002',unknown_attempts:0,distinct_attempts:1},'one effective contribution');
 eq(r.effectiveTotals([{history:first.history,example:e,plan}],g,s),{known_amount_decimal:'0.000000000',unknown_attempts:1,distinct_attempts:1},'unknown effective row stays unknown');
 eq(r.acceptUsage(second,e,plan,g,s,next.history).decision,'duplicate','identical duplicate is no-op');
 const conflict=clone(second);conflict.components[0].source_ref='receiver.other';
 eq(r.acceptUsage(conflict,e,plan,g,s,next.history).decision,'rejected','conflicting same ordinal rejected');
 const foreign=clone(unknown);foreign.attempt_id='attempt.foreign';
 const foreignHistory=clone(empty);foreignHistory.accepted_revisions=[foreign];
 ok(!r.acceptedHistoryValid(foreignHistory,e,plan,g,s),'complete foreign predecessor not accepted history');
 ok(!r.usageValid(second,e,plan,g,s,foreignHistory),'foreign predecessor cannot authorize revision 2');
 const fabricated=clone(empty);fabricated.accepted_revisions=[{revision:1,price_ref:plan.price_ref,usage_semantics_ref:plan.usage_ref}];
 ok(!r.usageValid(second,e,plan,g,s,fabricated),'three-field predecessor stub rejected');
 const fabricatedPlan=clone(plan);fabricatedPlan.price_ref='tariff.synthetic.fabricated@1';fabricatedPlan.reservation.price_ref=fabricatedPlan.price_ref;
 fabricatedPlan.signature=crypto.sign(null,r.planMessage(fabricatedPlan),testKey.privateKey).toString('base64url');
 const fabricatedUsage=clone(known);fabricatedUsage.price_ref=fabricatedPlan.price_ref;
 const fabricatedContext=clone(empty);fabricatedContext.expected_price_ref=fabricatedPlan.price_ref;
 fabricatedContext.expected_reservation=clone(fabricatedPlan.reservation);
 fabricatedContext.stored_signed_plan_digest=r.digest('ezllmrouter-stored-plan-v1\n',fabricatedPlan);
 ok(!r.usageValid(fabricatedUsage,e,fabricatedPlan,g,s,fabricatedContext),'matching fabricated plan/usage refs cannot replace registered price');
 const changedStoredPlan=clone(plan);changedStoredPlan.reservation.budget_account_id='budget.other';
 ok(!r.usageValid(known,e,changedStoredPlan,g,s,empty),'stored plan digest and budget remain independently anchored');
 for(const [label,change] of [
  ['missing history',x=>{}],['stale revision',x=>{x.revision=1}],['skipped revision',x=>{x.revision=3;x.previous_revision=2}],
  ['self predecessor',x=>{x.previous_revision=2}],['future predecessor',x=>{x.previous_revision=3}],
  ['changed price',x=>{x.price_ref='tariff.synthetic.a@1'}],['changed semantics',x=>{x.usage_semantics_ref='other@1'}]
 ]){const u=clone(second);change(u);const h=label==='missing history'?empty:first.history;
  ok(!r.usageValid(u,e,plan,g,s,h),label+' history rejection');}
 const forgedLatest=clone(v.protocol_fixtures.find(x=>x.id==='STATUS_REVISION_2_CALCULATED').value);
 forgedLatest.attempts[0].usage_revision.revision=100;forgedLatest.attempts[0].usage_revision.previous_revision=99;
 ok(!r.statusValid(forgedLatest,e,plan,g,s,next.history),'status cannot fabricate revision 100');
 const secondPlan=clone(plan);secondPlan.attempt_id='attempt.rank.second';secondPlan.reservation.reservation_id='reservation.synthetic.2';
 secondPlan.key_id='synthetic.test.second';secondPlan.signature=crypto.sign(null,r.planMessage(secondPlan),testKey.privateKey).toString('base64url');
 const secondHistory=clone(empty);secondHistory.expected_attempt_id=secondPlan.attempt_id;secondHistory.expected_reservation=clone(secondPlan.reservation);
 secondHistory.stored_signed_plan_digest=r.digest('ezllmrouter-stored-plan-v1\n',secondPlan);
 const secondCall=clone(known);secondCall.attempt_id=secondPlan.attempt_id;
 ok(r.acceptedHistoryValid(secondHistory,e,secondPlan,g,s),'second independently stored attempt context');
 const secondAccepted=r.acceptUsage(secondCall,e,secondPlan,g,s,secondHistory);
 eq(secondAccepted.decision,'accepted','second distinct attempt accepted');
 eq(r.effectiveTotals([firstRecord,{history:secondAccepted.history,example:e,plan:secondPlan}],g,s),{known_amount_decimal:'0.001800004',unknown_attempts:0,distinct_attempts:2},'two attempts counted once each');
 rejection(()=>r.effectiveTotals([firstRecord,firstRecord],g,s),'duplicate attempt context cannot double count');
 const revokedHistory=clone(next.history);revokedHistory.usage_write_allowed=false;
 ok(r.statusValid(v.protocol_fixtures.find(x=>x.id==='STATUS_REVISION_2_CALCULATED').value,e,plan,g,s,revokedHistory),'historical read survives send/key revocation and write denial');
 ok(!r.usageValid(second,e,plan,g,s,revokedHistory),'late usage still respects independent write access');
 ok(!r.executionEligible(plan,e,g,s,revokedKey)&&r.usageValid(second,e,plan,g,s,first.history),'late observed usage can settle after key revocation under separate write access');
 // A bounded history append must return a context that remains readable and reducible.
 {
  const capacity=s.$defs.HistoricalUsageContext.properties.accepted_revisions.maxItems;
  let bounded=clone(empty);const decisions=[];
  for(let revision=1;revision<=capacity;revision++){
   const row=clone(revision===capacity?known:unknown);row.revision=revision;
   if(revision>1)row.previous_revision=revision-1;else delete row.previous_revision;
   if(revision===capacity)ok(r.acceptedHistoryValid(bounded,e,plan,g,s),'history immediately below capacity remains valid');
   const appended=r.acceptUsage(row,e,plan,g,s,bounded);decisions.push(appended.decision);bounded=appended.history;
  }
  eq(decisions,Array(capacity).fill('accepted'),'valid revisions through capacity are accepted');
  ok(r.acceptedHistoryValid(bounded,e,plan,g,s),'history at capacity remains valid');
  eq(bounded.accepted_revisions.length,capacity,'last permitted append reaches exact capacity');
  const last=clone(r.latestUsage(bounded)),before=clone(bounded),beforeBytes=r.canonical(bounded);
  const totals=r.effectiveTotals([{history:bounded,example:e,plan}],g,s);
  eq(totals,{known_amount_decimal:known.amount_decimal,unknown_attempts:0,distinct_attempts:1},'last permitted revision replaces unknown once');
  const boundaryStatus=clone(v.protocol_fixtures.find(x=>x.id==='STATUS_EXPIRED_CALCULATED').value);
  boundaryStatus.attempts[0].usage_revision=clone(last);
  ok(r.statusValid(boundaryStatus,e,plan,g,s,bounded,v.retention_context),'financial status remains readable at capacity');
  const overflow=clone(known);overflow.revision=capacity+1;overflow.previous_revision=capacity;
  ok(!r.usageValid(overflow,e,plan,g,s,bounded),'append exceeding context capacity is ineligible');
  const rejected=r.acceptUsage(overflow,e,plan,g,s,bounded);
  eq(rejected.decision,'rejected','capacity overflow cannot return accepted');
  eq(rejected.history,before,'capacity rejection preserves exact prior history');
  eq(r.canonical(bounded),beforeBytes,'capacity rejection does not mutate input history');
  ok(r.acceptedHistoryValid(rejected.history,e,plan,g,s),'rejected append leaves valid history');
  eq(r.latestUsage(rejected.history),last,'rejected append leaves latest effective row unchanged');
  eq(r.effectiveTotals([{history:rejected.history,example:e,plan}],g,s),totals,'rejected append preserves once-only totals');
  ok(r.statusValid(boundaryStatus,e,plan,g,s,rejected.history,v.retention_context),'rejected append preserves authorized historical status');
  const duplicate=r.acceptUsage(last,e,plan,g,s,bounded);
  eq(duplicate.decision,'duplicate','identical duplicate remains no-op at capacity');
  eq(duplicate.history,before,'duplicate at capacity preserves history');
  eq(r.effectiveTotals([{history:duplicate.history,example:e,plan}],g,s),totals,'duplicate at capacity cannot add cost');
  const conflicting=clone(last);conflicting.components[0].source_ref='receiver.boundary.conflict';
  const conflicted=r.acceptUsage(conflicting,e,plan,g,s,bounded);
  eq(conflicted.decision,'rejected','conflicting duplicate at capacity remains rejected');
  eq(conflicted.history,before,'conflicting duplicate preserves prior state');
 }
 const expiredCalculated=v.protocol_fixtures.find(x=>x.id==='STATUS_EXPIRED_CALCULATED').value;
 const expiredUnknown=v.protocol_fixtures.find(x=>x.id==='STATUS_EXPIRED_UNKNOWN_COST').value;
 const expiredOver=v.protocol_fixtures.find(x=>x.id==='STATUS_EXPIRED_OVER_BOUND').value;
 const retention=v.retention_context;
 ok(r.statusValid(expiredCalculated,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,retention),'expired content retains calculated amount');
 ok(r.statusValid(expiredUnknown,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1,retention),'expired content retains unknown cost');
 ok(r.statusValid(expiredOver,e,under.signed_plan,g,s,under.historical_context_observed,retention),'expired content retains unclamped over-bound amount');
 eq(expiredOver.attempts[0].usage_revision.amount_decimal,'0.000900002','expiry preserves actual over-bound amount');
 const expiredWithResult=clone(expiredCalculated);expiredWithResult.attempts[0].result=clone(rr.value);
 ok(!r.statusValid(expiredWithResult,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,retention),'expired status with result rejected');
 const presentNoResult=clone(expiredCalculated);presentNoResult.candidate_access='present';
 ok(!r.statusValid(presentNoResult,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,retention),'present status without result rejected');
 const early=clone(retention);early.observed_at='2030-01-08T00:00:59Z';
 ok(!r.statusValid(expiredCalculated,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,early),'expiry before cutoff rejected');
 ok(!r.statusValid(expiredCalculated,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1),'expiry without independent context rejected');
 const wrongCutoff=clone(retention);wrongCutoff.cutoff_at='2030-01-09T00:01:00Z';
 ok(!r.statusValid(expiredCalculated,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,wrongCutoff),'false retention cutoff rejected');
 const noPriorContent=clone(retention);noPriorContent.result_was_available=false;
 ok(!r.statusValid(expiredCalculated,e,plan,g,s,v.historical_contexts.CALCULATED_REVISION_1,noPriorContent),'unsupported expiry assertion rejected');
 const available=v.protocol_fixtures.find(x=>x.id==='STATUS_VALID_UNKNOWN_COST').value;
 ok(r.statusValid(available,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1,early),'present content before cutoff');
 ok(!r.statusValid(available,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1,retention),'present content at cutoff rejected');
 const unknownOverLabel=clone(expiredUnknown);unknownOverLabel.attempts[0].settlement_state='over_bound';
 ok(!r.statusValid(unknownOverLabel,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1,retention),'unknown usage cannot claim over-bound');
 const overUnknownLabel=clone(expiredOver);overUnknownLabel.attempts[0].settlement_state='unknown';
 ok(!r.statusValid(overUnknownLabel,e,under.signed_plan,g,s,under.historical_context_observed,retention),'over-bound usage cannot claim unknown');
 const pendingWithHistory=clone(v.protocol_fixtures.find(x=>x.id==='STATUS_PENDING_NO_USAGE').value);
 ok(!r.statusValid(pendingWithHistory,e,plan,g,s,v.historical_contexts.UNKNOWN_REVISION_1),'pending means no effective usage row yet');
 const noRead=clone(v.historical_contexts.CALCULATED_REVISION_1);noRead.read_allowed=false;
 ok(!r.statusValid(expiredCalculated,e,plan,g,s,noRead,retention),'current historical read permission required');
 for(const x of v.cross_cases){
  if(x.id==='ABSENT_VS_EXPLICIT'){eq(r.canonical(direct.canonical_work.work_key),r.canonical(explicit.canonical_work.work_key),x.id+' key');ok(direct.work_digest!==explicit.work_digest,x.id+' digest');}
  if(x.id==='OBJECT_KEY_ORDER_EQUIVALENT'){const reordered={...direct.request,metadata:{...direct.request.metadata}};eq(r.workDigest(r.workProjection(reordered,direct.trusted_context)),direct.work_digest,x.id);}
  if(x.id==='ORDERED_INPUT_CHANGE'){const changed=clone(direct.request);changed.input.items.reverse();ok(r.workDigest(r.workProjection(changed,direct.trusted_context))!==direct.work_digest,x.id);}
  if(x.id==='SERVER_ASSESSMENT_CHANGE'){eq(r.workDigest(r.workProjection(direct.request,direct.trusted_context)),direct.work_digest,x.id+' work');ok(r.digest('ezllmrouter-admission-v1\n',improved)!==direct.admission_snapshot_digest,x.id+' assessment');}
  if(x.id==='CHANGED_CALLER_ASSERTION'){const changed=clone(direct.request);changed.metadata.commission={kind:'omitted',reason:'caller_declared'};eq(r.canonical(r.workProjection(changed,direct.trusted_context).work_key),r.canonical(direct.canonical_work.work_key),x.id+' key');ok(r.workDigest(r.workProjection(changed,direct.trusted_context))!==direct.work_digest,x.id+' conflict predicate');}
  if(x.id==='CROSS_VERSION_SAME_WORK_KEY'){const changed=clone(direct.request);changed.contract_version='0.2';eq(r.canonical(r.workProjection(changed,direct.trusted_context).work_key),r.canonical(direct.canonical_work.work_key),x.id+' key');ok(changed.contract_version!==direct.request.contract_version,x.id+' version-conflict predicate');}
 }
 const base=clone(direct.request);for(const [field,val] of [['model_ref','other'],['profile_id','other'],['parameter_digest','sha256:'+'0'.repeat(64)],['dimensions',4],['normalization','unit_l2'],['corpus_version','other'],['index_version','other']]){const bad=clone(base);bad.input.profile[field]=val;eq(r.classifyRequest(bad,direct.trusted_context,g,s),'SEMANTIC_INVALID','embedding '+field+' mismatch');}
 const rb=clone(e.request);rb.input.candidates[0].content_digest='sha256:'+'0'.repeat(64);eq(r.classifyRequest(rb,e.trusted_context,g,s),'SEMANTIC_INVALID','content digest domain');
 for(const row of t.rows){const n=row.documents;
  const a=Math.max(5000000,Math.ceil(n/10)*3000000), b=n*(n<=10?0.0003000005:0.0004000005);
  eq(row.tariff_a.settled_usd,(a/1e9).toFixed(9),n+' A settled');
  ok(Math.abs(Number(row.tariff_b.raw_usd)-b)<1e-12,n+' B raw');
  const raw=BigInt(n)*BigInt(n<=10?3000005:4000005),whole=raw/10n,rem=raw%10n;
  const settled=whole+(rem>5n||rem===5n&&whole%2n===1n?1n:0n),bound=(raw+9n)/10n;
  eq(row.tariff_b.settled_usd,(Number(settled)/1e9).toFixed(9),n+' B settled');
  eq(row.tariff_b.request_bound_usd,(Number(bound)/1e9).toFixed(9),n+' B bound');
 }
 for(const row of t.embedding_document_rows){const n=row.items,amount=n*0.0002;eq(row.settled_usd,amount.toFixed(9),n+' document embedding');eq(row.request_bound_usd,amount.toFixed(9),n+' document bound');}
 eq(t.embedding_query_row.settled_usd,'0.000200000','query embedding');eq(t.embedding_query_row.request_bound_usd,'0.000200000','query bound');
 eq(t.schedule_a.maximum_domain_bound_usd,'0.009000000','A maximum');eq(t.schedule_b.maximum_domain_bound_usd,'0.010000013','B maximum');
 eq(t.embedding_document.maximum_domain_bound_usd,'0.005000000','embedding maximum');
 for(const x of v.examples){const c=r.configFor(x.request,g),price=r.priceFor(x.request,g),calc=r.tariff(x.request,price);
  ok(c&&price&&calc.quantity>=1,x.id+' operation price binding');
  const syntheticPlan={attempt_id:'test',price_ref:price.price_ref,usage_ref:price.usage_ref,reservation:{max_exposure_decimal:calc.bound}};
  const u={attempt_id:'test',revision:1,usage_semantics_ref:price.usage_ref,price_ref:price.price_ref,components:[{component:price.component,presence:'known',quantity:calc.quantity,evidence:'reported',source_ref:'test'}],cost_status:'calculated',amount_decimal:calc.settled};
  ok(r.usageCore(u,x.request,syntheticPlan,g,s),x.id+' exact typed operation price');
  const absent=clone(u);absent.components=[{component:price.component,presence:'absent'}];absent.cost_status='unknown';delete absent.amount_decimal;
  ok(r.usageCore(absent,x.request,syntheticPlan,g,s),x.id+' unknown distinct from zero');
 }
 console.log('DEV-12/A1 candidate-03 offline conformance: '+checks+' checks passed');
}
