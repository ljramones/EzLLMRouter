"use strict";
// External observation transport: every invocation sends at most one HTTP request.
const schemas={"1":require("./integration_schema.json").$defs,
  "2":require("./integration_schema_v2.json").$defs,
  "3":require("./integration_schema_v3.json").$defs};
const {strictDecode}=require("./successor.cjs");
const crypto=require("node:crypto");
const own=(v,k)=>Object.hasOwn(v,k);
function valid(v,s,schema=schemas["1"]){
  if(s.$ref){const kind=s.$ref.split("/").at(-1);
    if(kind==="utc")return typeof v==="string"&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/u.test(v)&&
      Number(v.slice(0,4))>0&&
      !Number.isNaN(Date.parse(v))&&new Date(v).toISOString().replace(/\.000Z$/u,"Z")===v;
    return valid(v,schema[kind],schema);}
  if(s.oneOf)return s.oneOf.filter(x=>valid(v,x,schema)).length===1;
  if(own(s,"const")&&v!==s.const||s.enum&&!s.enum.includes(v))return false;
  if(s.type==="object")return v!==null&&typeof v==="object"&&!Array.isArray(v)&&
    (s.required||[]).every(k=>own(v,k))&&(s.additionalProperties!==false||
      Object.keys(v).every(k=>own(s.properties,k)))&&
    Object.entries(v).every(([k,x])=>!own(s.properties,k)||valid(x,s.properties[k],schema));
  if(s.type==="array")return Array.isArray(v)&&v.length>=(s.minItems||0)&&
    v.length<=(s.maxItems||Infinity)&&(!s.uniqueItems||new Set(v.map(JSON.stringify)).size===v.length)&&
    v.every(x=>valid(x,s.items,schema));
  if(s.type==="integer")return Number.isSafeInteger(v)&&v>=(s.minimum??-Infinity)&&v<=(s.maximum??Infinity);
  if(s.type==="string")return typeof v==="string"&&(!s.pattern||new RegExp(s.pattern,"u").test(v))&&
    !/[\u0000-\u001f\u007f]/u.test(v);
  return true;
}
function eventValid(e){
  const schema=schemas[e?.integration_version];
  if(!schema||!valid(e,schema.event,schema))return false;
  if(["activity","attempt_started"].includes(e.kind)&&
      ((e.root_run_id===e.run_id)===own(e,"parent_run_id")||e.parent_run_id===e.run_id))return false;
  if(["2","3"].includes(e.integration_version)){
    if(e.kind==="activity"&&e.activity_kind==="outcome"&&!own(e,"outcome"))return false;
    if(e.kind==="attempt_started"&&((e.model_identity_state==="known")!==own(e,"model_id")||
      (["retry","fallback"].includes(e.attempt_role))!==own(e,"predecessor_attempt_id")))return false;
    if(e.kind==="decision"&&(["verified","stale","denied"].includes(e.eligibility_evidence.status))!==
      own(e.eligibility_evidence,"eligibility_id"))return false;
    if(e.integration_version==="3"&&e.kind==="decision"&&
      ((e.selection_kind==="known_model")!==own(e,"selected_model_id")||
       e.capability!==(e.operation_family==="speech_input"?"transcription":
         e.operation_family==="speech_output"?"synthesis":e.operation_family)))return false;
    if(e.kind==="usage"){
      const units=e.native_units||[], knownUnits=e.usage_state==="known", knownCost=e.cost_state==="known";
      const fields=["currency","amount_decimal","cost_basis","price_ref","price_version"];
      if(new Set(units.map(x=>x.unit)).size!==units.length||
        knownUnits!==(own(e,"native_units")&&own(e,"usage_provenance"))||
        !knownUnits&&(own(e,"native_units")||own(e,"usage_provenance"))||
        knownCost!==fields.every(k=>own(e,k))||!knownCost&&fields.some(k=>own(e,k))||
        knownCost&&((Number(e.amount_decimal)===0)!==own(e,"zero_basis"))||
        !knownCost&&own(e,"zero_basis"))return false;
    }
  }else if(e.kind==="usage"&&e.usage_state==="known"&&
      (new Set(e.native_units.map(x=>x.unit)).size!==e.native_units.length||
       (Number(e.amount_decimal)===0)!==own(e,"zero_basis")))return false;
  return true;
}
function canonical(value){
  if(Array.isArray(value))return value.map(canonical);
  if(value!==null&&typeof value==="object")return Object.fromEntries(
    Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
  return value;
}
function snapshotValid(s){
  const schema=schemas[s?.integration_version];
  if(!schema||!["2","3"].includes(s.integration_version))return false;
  if(!valid(s,schema.snapshot,schema))return false;
  const key=s.snapshot_kind==="feature"?"features":"selected_action";
  if((s.status==="captured")!==own(s,key)||own(s,key==="features"?"selected_action":"features")||
     s.source_at>s.available_at||s.available_at>s.retention_until||
     (own(s,"source_expires_at")&&s.retention_until>s.source_expires_at))return false;
  if(s.snapshot_kind==="decision"&&own(s,"selected_action")){
    const e=s.selected_action.eligibility_evidence;
    if((["verified","stale","denied"].includes(e.status))!==own(e,"eligibility_id"))return false;
    const action=s.selected_action;
    if(s.integration_version==="3"&&((action.selection_kind==="known_model")!==
      own(action,"selected_model_id")||action.capability!==(action.operation_family==="speech_input"?
        "transcription":action.operation_family==="speech_output"?"synthesis":action.operation_family)))return false;
  }
  return true;
}
function receiptValid(value,datasetId,eventId,kind,digest){
  return value?.dataset_id===datasetId&&value.event_id===eventId&&
    ["activity","attempt_started","decision","result","usage","lineage","account_resolution"].includes(value.kind)&&
    (kind===undefined||value.kind===kind)&&
    (digest===undefined||value.event_digest===digest)&&
    /^sha256:[0-9a-f]{64}$/.test(value.event_digest)&&
    ["included","excluded_before_activation","pending_start"].includes(value.membership_at_receipt);
}
class IntegrationClientError extends Error{
  constructor(code,httpStatus=null,retryGuidance="never"){super(code);
    this.code=code;this.httpStatus=httpStatus;this.retryGuidance=retryGuidance;}
}
class IntegrationClient{
  constructor(baseUrl,token,{fetchImpl=globalThis.fetch,version="1"}={}){
    const u=new URL(baseUrl);
    if(!["http:","https:"].includes(u.protocol)||u.username||u.password||u.pathname!=="/"||u.search||u.hash||
      typeof token!=="string"||!token||typeof fetchImpl!=="function"||!schemas[version])throw TypeError("invalid integration client");
    this.baseUrl=u.origin;this.token=token;this.fetchImpl=fetchImpl;
    this.version=version;this.schema=schemas[version];this.basePath="/integration/v"+version;
  }
  async _request(method,path,body,expected){
    const headers={Authorization:"Bearer "+this.token,"EzLLMRouter-Integration-Version":this.version,
      "Accept-Encoding":"identity"};
    if(body!==undefined)headers["Content-Type"]="application/json";
    let response;
    try{response=await this.fetchImpl(this.baseUrl+path,{method,headers,
      body:body===undefined?undefined:JSON.stringify(body),redirect:"error",cache:"no-store"});}
    catch{throw new IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN",null,"query_first");}
    let value;
    try{value=strictDecode(Buffer.from(await response.arrayBuffer()),16777216);}
    catch{throw new IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN",response.status,"query_first");}
    if(response.headers.get("EzLLMRouter-Integration-Version")!==this.version||value?.integration_version!==this.version)
      throw new IntegrationClientError("UNSUPPORTED_VERSION",response.status);
    if(!response.ok){
      if(!value.error||typeof value.error.code!=="string")
        throw new IntegrationClientError("TRANSPORT_OUTCOME_UNKNOWN",response.status,"query_first");
      throw new IntegrationClientError(value.error.code,response.status,value.error.retry_guidance||"never");
    }
    if(!expected.includes(response.status))throw new IntegrationClientError("PROTOCOL_INVALID",response.status,"query_first");
    return value;
  }
  createDataset(body){if(!valid(body,this.schema.dataset,this.schema))throw TypeError("invalid dataset");
    return this._request("POST",this.basePath+"/datasets",body,[200,201]);}
  registerAccount(body){if(!valid(body,this.schema.account,this.schema))throw TypeError("invalid account");
    return this._request("POST",this.basePath+"/accounts",body,[200,201]);}
  setAccountState(id,body){if(!valid(id,this.schema.id,this.schema)||!valid(body,this.schema.account_state,this.schema))throw TypeError("invalid account state");
    return this._request("POST",this.basePath+"/accounts/"+encodeURIComponent(id)+"/state",body,[200]);}
  setAccountPermissions(id,body){if(this.version!=="3"||!valid(id,this.schema.id,this.schema)||
      !valid(body,this.schema.account_permissions,this.schema))throw TypeError("invalid account permissions");
    return this._request("POST",this.basePath+"/accounts/"+encodeURIComponent(id)+"/permissions",body,[200]);}
  async submitObservation(event){if(event?.integration_version!==this.version||!eventValid(event))throw TypeError("invalid observation");
    const snapshot=structuredClone(event);
    const digest="sha256:"+crypto.createHash("sha256").update(JSON.stringify(canonical(snapshot))).digest("hex");
    const reply=await this._request("POST",this.basePath+"/events",snapshot,[200,201]);
    if(!receiptValid(reply,snapshot.dataset_id,snapshot.event_id,snapshot.kind,digest))
      throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    return reply;}
  async recoverReceipt(datasetId,eventId){if(!valid(datasetId,this.schema.id,this.schema)||!valid(eventId,this.schema.id,this.schema))
      throw TypeError("invalid receipt selector");
    const reply=await this._request("GET",this.basePath+"/events/"+encodeURIComponent(eventId)+"/receipt?dataset_id="+
      encodeURIComponent(datasetId),undefined,[200]);
    if(!receiptValid(reply,datasetId,eventId))throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    return reply;}
  async eligibility(datasetId,accountId,modelId){
    if(this.version==="3")return this.operationEligibility(datasetId,accountId,
      {operation_family:"generation",capability:"generation",selection_kind:"known_model",model_id:modelId});
    if(![datasetId,accountId,modelId].every(x=>valid(x,this.schema.id,this.schema)))
      throw TypeError("invalid eligibility selector");
    const reply=await this._request("GET",this.basePath+"/accounts/"+encodeURIComponent(accountId)+
      "/eligibility?dataset_id="+encodeURIComponent(datasetId)+"&model_id="+encodeURIComponent(modelId),undefined,[200]);
    if(reply.dataset_id!==datasetId||reply.account_id!==accountId||reply.model_id!==modelId||
      !Number.isSafeInteger(reply.account_revision)||reply.account_revision<1||typeof reply.usable!=="boolean"||
      !["usable","account_disabled","model_not_permitted"].includes(reply.reason)||
      reply.usable!==(reply.reason==="usable"))throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    if(this.version==="2"&&(!valid(reply.eligibility_id,this.schema.id,this.schema)||
      !valid(reply.evaluated_at,this.schema.utc,this.schema)||
      !/^sha256:[0-9a-f]{64}$/u.test(reply.eligibility_digest)))
      throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    if(this.version==="2"){
      const {eligibility_digest,...signed}=reply;
      if("sha256:"+crypto.createHash("sha256").update(JSON.stringify(canonical(signed))).digest("hex")!==eligibility_digest)
        throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    }
    return reply;}
  async operationEligibility(datasetId,accountId,selector){
    if(this.version!=="3"||![datasetId,accountId].every(x=>valid(x,this.schema.id,this.schema))||
      !selector||typeof selector!=="object"||!
      ["known_model","provider_selected","not_applicable"].includes(selector.selection_kind)||
      !["speech_input","speech_output"].includes(selector.operation_family)&&selector.selection_kind!=="known_model"||
      selector.capability!==(selector.operation_family==="speech_input"?"transcription":
        selector.operation_family==="speech_output"?"synthesis":selector.operation_family)||
      (selector.selection_kind==="known_model")!==own(selector,"model_id")||
      own(selector,"model_id")&&!valid(selector.model_id,this.schema.id,this.schema))
      throw TypeError("invalid operation eligibility selector");
    const query=new URLSearchParams({dataset_id:datasetId,operation_family:selector.operation_family,
      capability:selector.capability,selection_kind:selector.selection_kind});
    if(own(selector,"model_id"))query.set("model_id",selector.model_id);
    const reply=await this._request("GET",this.basePath+"/accounts/"+encodeURIComponent(accountId)+
      "/eligibility?"+query,undefined,[200]);
    if(reply.dataset_id!==datasetId||reply.account_id!==accountId||
      !["operation_family","capability","selection_kind"].every(k=>reply[k]===selector[k])||
      reply.model_id!==selector.model_id||!valid(reply.provider_id,this.schema.id,this.schema)||
      !valid(reply.credential_ref,this.schema.id,this.schema)||
      !Number.isSafeInteger(reply.account_revision)||reply.account_revision<1||
      typeof reply.usable!=="boolean"||
      !["usable","account_disabled","model_not_permitted","operation_not_permitted"].includes(reply.reason)||
      reply.usable!==(reply.reason==="usable")||
      !valid(reply.eligibility_id,this.schema.id,this.schema)||
      !valid(reply.evaluated_at,this.schema.utc,this.schema)||
      !/^sha256:[0-9a-f]{64}$/u.test(reply.eligibility_digest))
      throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    const {eligibility_digest,...signed}=reply;
    if("sha256:"+crypto.createHash("sha256").update(JSON.stringify(canonical(signed))).digest("hex")!==eligibility_digest)
      throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
    return reply;}
  report(datasetId){if(!valid(datasetId,this.schema.id,this.schema))throw TypeError("invalid dataset");
    return this._request("GET",this.basePath+"/reports/usage?dataset_id="+encodeURIComponent(datasetId),undefined,[200]);}
  submitSnapshot(snapshot){if(!["2","3"].includes(this.version)||snapshot?.integration_version!==this.version||!snapshotValid(snapshot))
      throw TypeError("invalid snapshot");
    const digest="sha256:"+crypto.createHash("sha256").update(JSON.stringify(canonical(snapshot))).digest("hex");
    return this._request("POST",this.basePath+"/snapshots",snapshot,[200,201]).then(reply=>{
      if(reply.snapshot_id!==snapshot.snapshot_id||reply.snapshot_digest!==digest)
        throw new IntegrationClientError("PROTOCOL_INVALID",null,"query_first");
      return reply;});}
  snapshot(datasetId,snapshotId){if(!["2","3"].includes(this.version)||![datasetId,snapshotId].every(x=>valid(x,this.schema.id,this.schema)))
      throw TypeError("invalid snapshot selector");
    return this._request("GET",this.basePath+"/snapshots/"+encodeURIComponent(snapshotId)+
      "?dataset_id="+encodeURIComponent(datasetId),undefined,[200]);}
  exportDataset(datasetId){if(!["2","3"].includes(this.version)||!valid(datasetId,this.schema.id,this.schema))
      throw TypeError("invalid dataset selector");
    return this._request("GET",this.basePath+"/reports/dataset?dataset_id="+encodeURIComponent(datasetId),undefined,[200]);}
}
module.exports=Object.freeze({IntegrationClient,IntegrationClientError,eventValid,snapshotValid});
