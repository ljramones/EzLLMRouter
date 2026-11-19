// Isolated DEV-12/A1 candidate-03 reference semantics. Never imports product code.
'use strict';
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
const sha=x=>'sha256:'+crypto.createHash('sha256').update(x).digest('hex');
const utf8=x=>Buffer.from(x,'utf8');
function scalar(s) {
  for(let i=0;i<s.length;i++) {
    const c=s.charCodeAt(i);
    if(c<32||c===127) return false;
    if(c>=0xd800&&c<=0xdbff) {const n=s.charCodeAt(++i);if(!(n>=0xdc00&&n<=0xdfff))return false;}
    else if(c>=0xdc00&&c<=0xdfff)return false;
  }
  return true;
}
function strictDecode(bytes) {
  if(!Buffer.isBuffer(bytes)||bytes.length>262144)throw Error('LIMIT_EXCEEDED');
  let s;try{s=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);}catch{throw Error('MALFORMED_JSON');}
  if(utf8(s).length!==bytes.length)throw Error('MALFORMED_JSON');
  let p=0;
  function ws(){while(p<s.length&&(' \t\r\n'.includes(s[p])))p++;}
  function str(){const start=p++;let escaped=false;while(p<s.length){const c=s[p++];if(c==='"'&&!escaped){
    let v;try{v=JSON.parse(s.slice(start,p));}catch{throw Error('MALFORMED_JSON');}
    if(!scalar(v))throw Error('MALFORMED_JSON');return v;}
    if(c==='\\'&&!escaped)escaped=true;else escaped=false;}
    throw Error('MALFORMED_JSON');}
  function parse(depth){if(depth>32)throw Error('LIMIT_EXCEEDED');ws();
    if(s[p]==='"')return str();
    if(s[p]==='{'){p++;ws();const out=Object.create(null);if(s[p]==='}'){p++;return out;}
      while(true){ws();if(s[p]!=='"')throw Error('MALFORMED_JSON');const k=str();
        if(own(out,k))throw Error('MALFORMED_JSON');ws();if(s[p++]!==':')throw Error('MALFORMED_JSON');
        const val=parse(depth+1);Object.defineProperty(out,k,{value:val,enumerable:true,writable:true,configurable:true});
        ws();const end=s[p++];if(end==='}')return out;if(end!==',')throw Error('MALFORMED_JSON');}}
    if(s[p]==='['){p++;ws();const out=[];if(s[p]===']'){p++;return out;}
      while(true){out.push(parse(depth+1));ws();const end=s[p++];if(end===']')return out;if(end!==',')throw Error('MALFORMED_JSON');}}
    for(const [token,value] of [['true',true],['false',false],['null',null]])if(s.startsWith(token,p)){p+=token.length;return value;}
    const m=/^-?(?:0|[1-9][0-9]*)/.exec(s.slice(p));if(!m)throw Error('MALFORMED_JSON');
    p+=m[0].length;if(/[.eE]/.test(s[p]||''))throw Error('MALFORMED_JSON');
    const n=Number(m[0]);if(!Number.isSafeInteger(n))throw Error('MALFORMED_JSON');return n;
  }
  const value=parse(0);ws();if(p!==s.length)throw Error('MALFORMED_JSON');return value;
}
function schemaValid(value,schema,bundle){
  if(own(schema,'$ref')){
    const m=/^#\/\$defs\/([A-Za-z][A-Za-z0-9]*)$/.exec(schema.$ref);
    if(!m||!own(bundle.$defs,m[1]))throw Error('unresolved local schema reference');
    return schemaValid(value,bundle.$defs[m[1]],bundle);
  }
  if(schema.oneOf)return schema.oneOf.filter(x=>schemaValid(value,x,bundle)).length===1;
  if(own(schema,'const')&&value!==schema.const)return false;
  if(schema.enum&&!schema.enum.includes(value))return false;
  if(schema.type==='object'){
    if(value===null||Array.isArray(value)||typeof value!=='object')return false;
    for(const k of schema.required||[])if(!own(value,k))return false;
    for(const [k,v] of Object.entries(value)){
      if(!own(schema.properties||{},k)){if(schema.additionalProperties===false)return false;}
      else if(!schemaValid(v,schema.properties[k],bundle))return false;
    }
  }
  if(schema.type==='array'){
    if(!Array.isArray(value)||value.length<(schema.minItems??0)||value.length>(schema.maxItems??Infinity))return false;
    if(value.some(x=>!schemaValid(x,schema.items,bundle)))return false;
  }
  if(schema.type==='string'){
    if(typeof value!=='string'||!scalar(value))return false;
    const n=[...value].length;if(n<(schema.minLength??0)||n>(schema.maxLength??Infinity))return false;
    if(schema.pattern&&!new RegExp(schema.pattern,'u').test(value))return false;
  }
  if(schema.type==='integer'){
    if(!Number.isSafeInteger(value)||value<(schema.minimum??-Infinity)||value>(schema.maximum??Infinity))return false;
  }
  if(schema.type==='boolean'&&typeof value!=='boolean')return false;
  return true;
}
function checkRefs(bundle){let n=0;function walk(v){if(Array.isArray(v))return v.forEach(walk);if(v&&typeof v==='object'){
  if(own(v,'$ref')){const m=/^#\/\$defs\/([A-Za-z][A-Za-z0-9]*)$/.exec(v.$ref);if(!m||!own(bundle.$defs,m[1]))throw Error('unresolved ref '+v.$ref);n++;}
  Object.values(v).forEach(walk);}}walk(bundle);return n;}
function canonical(x){if(Array.isArray(x))return '['+x.map(canonical).join(',')+']';
  if(x&&typeof x==='object')return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
  if(typeof x==='number'&&!Number.isSafeInteger(x))throw Error('unsafe canonical number');return JSON.stringify(x);}
const digest=(prefix,obj)=>sha(utf8(prefix+canonical(obj)));
function workProjection(req,ctx){return {schema_id:'duranki-work-v0.3',profile:req.capability_profile,
  work_key:{principal_id:ctx.identity.principal_id,...req.work_selector},operation:req.operation,
  input:req.input,metadata:req.metadata,trusted:ctx.identity,purpose:req.purpose,
  task_class:req.task_class,requested_configuration_ref:req.requested_configuration_ref,
  deadline:req.deadline,handling_profile:req.handling_profile};}
function workDigest(work){return digest('duranki-work-v0.3\n'+work.operation.type+'@'+work.operation.version+'\n',work);}
function utc(s){if(!/^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\dZ$/.test(s))return false;
  const d=new Date(s);return !Number.isNaN(d.valueOf())&&d.toISOString().replace('.000Z','Z')===s;}
function contentDigest(c){return sha(utf8('duranki-content-v1\n'+c.content_version+'\n'+c.text));}
function publicTextDigest(s){return sha(utf8('duranki-public-text-v1\n'+s));}
function configFor(req,regs){return regs.configurations.find(c=>c.configuration_ref===req.requested_configuration_ref);}
function priceFor(req,regs){const c=configFor(req,regs);if(!c)return null;
  const ref=req.operation.type==='rerank'?c.price_ref:c.role_price_refs?.[req.input.role];
  return regs.price_contracts.find(p=>p.price_ref===ref);}
function semanticRequest(req,ctx,regs){
  const m=req.metadata,i=ctx.identity,c=configFor(req,regs);
  if(!utc(req.deadline)||!utc(ctx.authenticated_at)||!utc(ctx.expires_at)||!(ctx.authenticated_at<ctx.expires_at)||req.deadline<=ctx.authenticated_at||req.deadline>ctx.expires_at)return false;
  if(req.handling_profile!==regs.handling_profile||!c||canonical(c.operation)!==canonical(req.operation))return false;
  if(m.root_workflow_id!==ctx.allowed_root_workflow_id||m.run_id!==ctx.authenticated_current_run_id)return false;
  if(own(m,'initiating_user_id')&&m.initiating_user_id!==ctx.allowed_initiating_user_id)return false;
  if(m.invocation_mode==='direct_human'&&(i.actor_kind!=='human'||i.actor_id!==m.initiating_user_id))return false;
  if(m.invocation_mode==='autonomous_service'&&(i.actor_kind!=='service'||own(m,'initiating_user_id')))return false;
  if(m.invocation_mode==='delegated_agent'){
    if(i.actor_kind!=='agent'||m.delegation.length<1||m.delegation[0].from_actor_id!==m.initiating_user_id)return false;
    const last=m.delegation.at(-1);if(last.to_actor_id!==i.actor_id||last.to_run_id!==m.run_id||last.from_run_id!==m.parent_run_id)return false;
    const seen=new Set([m.delegation[0].from_actor_id]);for(let n=0;n<m.delegation.length;n++){
      const x=m.delegation[n];if(n&&(x.from_actor_id!==m.delegation[n-1].to_actor_id||x.from_run_id!==m.delegation[n-1].to_run_id))return false;
      if(seen.has(x.to_actor_id))return false;seen.add(x.to_actor_id);}
  }
  const allowed=new Set(regs.allowed_public_text_sha256);
  if(req.operation.type==='embedding.create'){
    if(canonical(req.input.profile)!==canonical(c.embedding_profile)||req.input.role==='query'&&req.input.items.length!==1)return false;
    if(new Set(req.input.items.map(x=>x.item_id)).size!==req.input.items.length)return false;
    if(req.input.items.some(x=>!allowed.has(publicTextDigest(x.text))))return false;
  }else if(req.operation.type==='rerank'){
    if(req.input.ranking_profile_id!==c.ranking_profile_id||req.input.corpus_version!==c.corpus_version||req.input.index_version!==c.index_version)return false;
    if(req.input.top_k>req.input.candidates.length||new Set(req.input.candidates.map(x=>x.candidate_id)).size!==req.input.candidates.length)return false;
    if(!allowed.has(publicTextDigest(req.input.query)))return false;
    if(req.input.candidates.some(x=>!allowed.has(publicTextDigest(x.text))||x.content_digest!==contentDigest(x)))return false;
  }else return false;
  return Boolean(priceFor(req,regs));
}
function classifyRequest(req,ctx,regs,bundle){
  if(!schemaValid(req,bundle.$defs.RequestEnvelope,bundle))return 'SCHEMA_INVALID';
  if(req.contract_version!=='0.3')return 'UNSUPPORTED_VERSION';
  if(req.capability_profile!=='retrieval-synthetic@1'||!['embedding.create','rerank'].includes(req.operation.type)||req.operation.version!==1)return 'CAPABILITY_UNSUPPORTED';
  if(!schemaValid(req,bundle.$defs.SubmitRequest,bundle))return 'SCHEMA_INVALID';
  return semanticRequest(req,ctx,regs)?'ACCEPT':'SEMANTIC_INVALID';
}
function decimalParts(s){const neg=s.startsWith('-'),[m,exp='0']=s.replace(/^-/,'').toLowerCase().split('e');
  return {n:BigInt(m.replace('.',''))*(neg?-1n:1n),e:Number(exp)-(m.split('.')[1]||'').length};}
function decimalCompare(a,b){const x=decimalParts(a),y=decimalParts(b),e=Math.min(x.e,y.e),l=x.n*10n**BigInt(x.e-e),r=y.n*10n**BigInt(y.e-e);return l<r?-1:l>r?1:0;}
function decimalValid(s,score=false){if(typeof s!=='string'||!/^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$/.test(s)||/^-0(?:\.0+)?(?:[eE][+-]?\d+)?$/.test(s))return false;
  const [m,e='0']=s.toLowerCase().split('e');if(m.replace(/[-.]/g,'').replace(/^0+/,'').length>17||Math.abs(Number(e))>100)return false;
  return decimalCompare(s,'-1000000')>=0&&decimalCompare(s,'1000000')<=0&&(!score||decimalCompare(s,'0')>=0&&decimalCompare(s,'1')<=0);}
function resultValid(out,req,attempt,regs,bundle){if(!schemaValid(out,bundle.$defs.Result,bundle)||out.attempt_id!==attempt||canonical(out.operation)!==canonical(req.operation))return false;
  const c=configFor(req,regs);
  if(out.operation.type==='embedding.create'){
    const p=c.embedding_profile;if(out.profile_id!==p.profile_id||out.model_ref!==p.model_ref||out.dimensions!==p.dimensions||out.vectors.length!==req.input.items.length)return false;
    return out.vectors.every((v,n)=>v.input_index===n&&v.item_id===req.input.items[n].item_id&&v.values.length===p.dimensions&&v.values.every(x=>decimalValid(x)));
  }
  if(out.ranking_profile_id!==c.ranking_profile_id||out.results.length!==req.input.top_k)return false;
  const seen=new Set();return out.results.every((x,n)=>{if(x.rank!==n+1||x.input_index>=req.input.candidates.length||x.candidate_id!==req.input.candidates[x.input_index].candidate_id||seen.has(x.candidate_id)||!decimalValid(x.score,true))return false;
    seen.add(x.candidate_id);if(n){const prev=out.results[n-1],order=decimalCompare(prev.score,x.score);if(order<0||order===0&&prev.input_index>x.input_index)return false;}return true;});
}
const units=10n**10n;
function amount(raw){const whole=raw/10n,rem=raw%10n;return (whole+(rem>5n||rem===5n&&whole%2n===1n?1n:0n));}
function upper(raw){return (raw+9n)/10n;}
function format(n){return (n/1000000000n).toString()+'.'+(n%1000000000n).toString().padStart(9,'0');}
function tariff(req,price){let n=req.operation.type==='rerank'?req.input.candidates.length:req.input.items.length,raw,quantity;
  switch(price.schedule_kind){
    case 'tariff_a':quantity=Math.ceil(n/10);raw=BigInt(Math.max(50000000,30000000*quantity));break;
    case 'tariff_b':quantity=n;raw=BigInt(n)*BigInt(n<=10?3000005:4000005);break;
    case 'embedding_document':case 'embedding_query':quantity=n;raw=BigInt(n)*2000000n;break;
    default:throw Error('unknown tariff');}
  return {quantity,raw,settled:format(amount(raw)),bound:format(upper(raw))};}
function recipeFor(req,workDigestValue,config,descriptor){return {work_digest:workDigestValue,operation:req.operation,adapter_ref:config.adapter_ref,
  route:descriptor.route,handling_profile:req.handling_profile,timeout_ms:descriptor.timeout_ms};}
function planMessage(plan){const {signature,...unsigned}=plan;return utf8('duranki-plan-v1\n'+canonical(unsigned));}
function planValid(plan,req,ex,regs,bundle,allowUnderbound=false){
  if(!schemaValid(plan,bundle.$defs.SignedPlan,bundle))return false;
  const c=configFor(req,regs),p=priceFor(req,regs),d=plan.execution_descriptor,r=plan.reservation;
  if(!c||!p||plan.work_digest!==ex.work_digest||plan.admission_snapshot_digest!==ex.admission_snapshot_digest||canonical(plan.operation)!==canonical(req.operation))return false;
  if(plan.adapter_ref!==c.adapter_ref||plan.destination_ref!==c.destination_ref||plan.price_ref!==p.price_ref||plan.usage_ref!==p.usage_ref||plan.financial_owner_id!==ex.trusted_context.identity.charging_owner_id)return false;
  if(r.financial_owner_id!==plan.financial_owner_id||r.price_ref!==plan.price_ref||r.usage_ref!==plan.usage_ref||r.currency!==p.currency)return false;
  if(!allowUnderbound&&decimalCompare(r.max_exposure_decimal,tariff(req,p).bound)<0)return false;
  const route=req.operation.type==='rerank'?'/synthetic/v1/rerank':'/synthetic/v1/embeddings';
  if(d.route!==route||d.adapter_ref!==c.adapter_ref||d.handling_profile!==req.handling_profile||d.deadline!==req.deadline||d.host!=='synthetic.invalid'||d.method!=='POST'||d.timeout_ms!==5000||d.max_request_bytes!==262144||d.max_response_bytes!==65536||d.retention_seconds!==604800)return false;
  if(d.recipe_digest!==digest('duranki-preparation-v1\n',recipeFor(req,ex.work_digest,c,d)))return false;
  return utc(plan.expires_at)&&plan.expires_at<=req.deadline;
}
function assessmentValid(snapshot,ex,bundle){if(!schemaValid(snapshot,bundle.$defs.AdmissionSnapshot,bundle)||snapshot.work_digest!==ex.work_digest||!utc(snapshot.assessed_at))return false;
  const m=ex.request.metadata,links=m.delegation,indices=snapshot.delegation.verified_link_indices;
  if(new Set(indices).size!==indices.length||indices.some(i=>i>=links.length))return false;
  if(snapshot.delegation.coverage==='none'&&indices.length!==0||snapshot.delegation.coverage==='complete'&&indices.length!==links.length)return false;
  if(snapshot.commission.status==='verified'||snapshot.delegation.coverage!=='none'||indices.length)return false; // standalone has no verifier
  return true;}
// Execution eligibility is a present-tense decision. It is never used to read history.
function signatureValid(plan,key) {
  if(!key||!/^[-_A-Za-z0-9]{86}$/.test(plan.signature))return false;
  try {
    const sig=Buffer.from(plan.signature,'base64url');
    const der=Buffer.from(key.public_key_spki_base64,'base64');
    if(sig.length!==64||sig.toString('base64url')!==plan.signature||der.toString('base64')!==key.public_key_spki_base64)return false;
    const pub=crypto.createPublicKey({key:der,format:'der',type:'spki'});
    return pub.asymmetricKeyType==='ed25519'&&crypto.verify(null,planMessage(plan),pub,sig);
  }catch{return false;}
}
function executionEligible(plan,ex,regs,bundle,context) {
  if(!schemaValid(context,bundle.$defs.ExecutionEligibilityContext,bundle)||!planValid(plan,ex.request,ex,regs,bundle))return false;
  if(!assessmentValid(ex.admission_snapshot,ex,bundle)||
    digest('duranki-admission-v1\n',ex.admission_snapshot)!==ex.admission_snapshot_digest)return false;
  if(!utc(context.evaluation_time)||context.evaluation_time>=plan.expires_at||!context.send_permission||context.plan_revoked)return false;
  for(const [expected,actual] of [
    [context.expected_submission_id,plan.submission_id],[context.expected_attempt_id,plan.attempt_id],
    [context.expected_work_digest,plan.work_digest],[context.expected_admission_snapshot_digest,plan.admission_snapshot_digest],
    [context.expected_financial_owner_id,plan.financial_owner_id]])if(expected!==actual)return false;
  if(canonical(context.expected_reservation)!==canonical(plan.reservation)||
     canonical(context.expected_execution_context)!==canonical(plan.execution_context)||
     canonical(context.current_authority_revisions)!==canonical(plan.authority_revisions))return false;
  const tuples=new Set();for(const k of context.verification_keys){const tuple=k.key_id+'\0'+k.key_version;
    if(tuples.has(tuple))return false;tuples.add(tuple);}
  const key=context.verification_keys.find(k=>k.key_id===plan.key_id&&k.key_version===plan.key_version);
  return Boolean(key&&key.eligibility==='eligible'&&signatureValid(plan,key));
}
// A historical context is an independently accepted store record, not a current send grant.
function historicalContextValid(h,ex,plan,regs,bundle) {
  if(!schemaValid(h,bundle.$defs.HistoricalUsageContext,bundle)||!planValid(plan,ex.request,ex,regs,bundle,true))return false;
  if(canonical(workProjection(ex.request,ex.trusted_context))!==canonical(ex.canonical_work)||workDigest(ex.canonical_work)!==ex.work_digest)return false;
  if(!assessmentValid(ex.admission_snapshot,ex,bundle)||
    digest('duranki-admission-v1\n',ex.admission_snapshot)!==ex.admission_snapshot_digest)return false;
  const price=priceFor(ex.request,regs);
  return Boolean(price&&h.expected_submission_id===plan.submission_id&&h.expected_attempt_id===plan.attempt_id&&
    canonical(h.expected_work_key)===canonical(ex.canonical_work.work_key)&&h.expected_work_digest===ex.work_digest&&
    h.expected_admission_snapshot_digest===ex.admission_snapshot_digest&&
    h.stored_signed_plan_digest===digest('duranki-stored-plan-v1\n',plan)&&
    canonical(h.expected_reservation)===canonical(plan.reservation)&&
    h.expected_financial_owner_id===plan.financial_owner_id&&
    h.expected_price_ref===plan.price_ref&&h.expected_usage_ref===plan.usage_ref&&
    price.price_ref===plan.price_ref&&price.usage_ref===plan.usage_ref);
}
function usageCore(u,req,plan,regs,bundle) {
  if(!schemaValid(u,bundle.$defs.UsageRevision,bundle)||u.attempt_id!==plan.attempt_id||u.price_ref!==plan.price_ref||u.usage_semantics_ref!==plan.usage_ref)return false;
  const price=priceFor(req,regs);if(!price||price.price_ref!==plan.price_ref||price.usage_ref!==plan.usage_ref)return false;
  const calc=tariff(req,price),c=u.components[0];
  if(u.components.length!==1||c.component!==price.component)return false;
  if(u.cost_status==='unknown')return !own(u,'amount_decimal')&&!(c.presence==='known'&&c.evidence==='reported'&&c.quantity===calc.quantity);
  if(c.presence!=='known'||c.evidence!=='reported'||c.quantity!==calc.quantity||u.amount_decimal!==calc.settled)return false;
  const over=decimalCompare(u.amount_decimal,plan.reservation.max_exposure_decimal)>0;
  return u.cost_status===(over?'over_bound':'calculated');
}
function acceptedHistoryValid(h,ex,plan,regs,bundle) {
  if(!historicalContextValid(h,ex,plan,regs,bundle))return false;
  return h.accepted_revisions.every((row,i)=>usageCore(row,ex.request,plan,regs,bundle)&&
    row.revision===i+1&&(i===0?!own(row,'previous_revision'):row.previous_revision===i));
}
function usageValid(u,ex,plan,regs,bundle,history) {
  if(!acceptedHistoryValid(history,ex,plan,regs,bundle)||!history.usage_write_allowed||!usageCore(u,ex.request,plan,regs,bundle))return false;
  const n=history.accepted_revisions.length;
  if(u.revision!==n+1||(n===0?own(u,'previous_revision'):u.previous_revision!==n))return false;
  const prospective={...history,accepted_revisions:[...history.accepted_revisions,u]};
  return acceptedHistoryValid(prospective,ex,plan,regs,bundle);
}
function acceptUsage(u,ex,plan,regs,bundle,history) {
  if(!acceptedHistoryValid(history,ex,plan,regs,bundle)||!history.usage_write_allowed)return {decision:'rejected',history};
  const prior=history.accepted_revisions.find(x=>x.revision===u.revision);
  if(prior)return {decision:canonical(prior)===canonical(u)?'duplicate':'rejected',history};
  if(!usageValid(u,ex,plan,regs,bundle,history))return {decision:'rejected',history};
  return {decision:'accepted',history:{...history,accepted_revisions:[...history.accepted_revisions,u]}};
}
function latestUsage(history){return history.accepted_revisions.at(-1)||null;}
function effectiveTotals(records,regs,bundle) {
  const seen=new Set();let nano=0n,unknown=0;
  for(const {history:h,example:ex,plan} of records){
    if(!acceptedHistoryValid(h,ex,plan,regs,bundle)||!h.read_allowed)throw Error('unvalidated historical context');
    if(seen.has(h.expected_attempt_id))throw Error('duplicate attempt context');seen.add(h.expected_attempt_id);
    const u=latestUsage(h);if(!u||u.cost_status==='unknown'){unknown++;continue;}
    const [whole,fraction='']=u.amount_decimal.split('.');nano+=BigInt(whole)*1000000000n+BigInt(fraction.padEnd(9,'0'));
  }
  return {known_amount_decimal:format(nano),unknown_attempts:unknown,distinct_attempts:seen.size};
}
function replyValid(reply,ex,expectedSubmissionId,expectedAttemptId,regs,bundle) {
  if(!schemaValid(reply,bundle.$defs.SubmitReply,bundle)||reply.handle.submission_id!==expectedSubmissionId||
    reply.attempt_id!==expectedAttemptId||canonical(reply.handle.work_key)!==canonical(ex.canonical_work.work_key))return false;
  return reply.state!=='completed'||resultValid(reply.result,ex.request,expectedAttemptId,regs,bundle);
}
function retentionValid(retention,plan,bundle) {
  if(!schemaValid(retention,bundle.$defs.RetentionContext,bundle)||!retention.read_allowed||!retention.result_was_available)return false;
  if(retention.expected_submission_id!==plan.submission_id||retention.expected_attempt_id!==plan.attempt_id)return false;
  if(!utc(retention.origin_at)||!utc(retention.cutoff_at)||!utc(retention.observed_at))return false;
  const cutoff=new Date(Date.parse(retention.origin_at)+plan.execution_descriptor.retention_seconds*1000);
  return cutoff.toISOString().replace('.000Z','Z')===retention.cutoff_at;
}
function statusValid(status,ex,plan,regs,bundle,history,retention=null) {
  if(!acceptedHistoryValid(history,ex,plan,regs,bundle)||!history.read_allowed||
    !schemaValid(status,bundle.$defs.StatusSnapshot,bundle)||
    status.handle.submission_id!==history.expected_submission_id||
    canonical(status.handle.work_key)!==canonical(history.expected_work_key)||status.attempts.length!==1)return false;
  const a=status.attempts[0],attempt=history.expected_attempt_id;if(a.attempt_id!==attempt)return false;
  if(own(a,'result')&&!resultValid(a.result,ex.request,attempt,regs,bundle))return false;
  const effective=latestUsage(history);
  if(effective){if(!own(a,'usage_revision')||canonical(a.usage_revision)!==canonical(effective)||a.settlement_state!==effective.cost_status)return false;}
  else if(own(a,'usage_revision')||a.settlement_state!=='pending')return false;
  if(status.submission_state==='completed'){
    if(a.delivery_state!=='valid')return false;
    if(status.candidate_access==='expired')return !own(a,'result')&&retentionValid(retention,plan,bundle)&&retention.observed_at>=retention.cutoff_at;
    if(status.candidate_access!=='present'||!own(a,'result'))return false;
    return retention===null||retentionValid(retention,plan,bundle)&&retention.observed_at<retention.cutoff_at;
  }
  if(retention!==null)return false;
  if(status.submission_state==='failed')return status.candidate_access==='unavailable_due_failure'&&a.delivery_state==='invalid'&&own(a,'failure')&&!own(a,'result');
  if(status.submission_state==='unknown')return status.candidate_access==='unknown_outcome'&&a.dispatch_state==='possible_send'&&a.delivery_state==='unknown'&&!own(a,'result');
  return status.candidate_access==='not_yet_available'&&a.delivery_state==='pending'&&!own(a,'result');
}
module.exports={own,sha,utf8,strictDecode,schemaValid,checkRefs,canonical,digest,workProjection,workDigest,utc,contentDigest,publicTextDigest,
  configFor,priceFor,semanticRequest,classifyRequest,decimalCompare,decimalValid,resultValid,tariff,recipeFor,planMessage,planValid,
  signatureValid,executionEligible,historicalContextValid,usageCore,acceptedHistoryValid,usageValid,acceptUsage,latestUsage,effectiveTotals,
  assessmentValid,replyValid,retentionValid,statusValid};
