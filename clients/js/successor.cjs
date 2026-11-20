"use strict";

const bundle = require("./retrieval_schemas.json");
const {SUCCESSOR_RESPONSE_LIMIT} = require("./http.cjs");
const own = (value, key) => Object.hasOwn(value, key);

function scalar(value, freeText=false) {
  for (let i=0;i<value.length;i++) {
    const c=value.charCodeAt(i);
    if (c===0||!freeText&&(c<32||c===127)) return false;
    if (c>=0xd800&&c<=0xdbff) {
      const next=value.charCodeAt(++i);
      if (!(next>=0xdc00&&next<=0xdfff)) return false;
    } else if (c>=0xdc00&&c<=0xdfff) return false;
  }
  return true;
}

// Same bounded JSON grammar as the adopted A1 vectors; object keys retain
// duplicates until they can be rejected before a typed response is built.
function strictDecode(bytes, limit=SUCCESSOR_RESPONSE_LIMIT) {
  if (!Buffer.isBuffer(bytes)||bytes.length>limit) throw Error("response limit");
  let source;
  try { source=new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(bytes); }
  catch { throw Error("invalid UTF-8"); }
  if (Buffer.byteLength(source,"utf8")!==bytes.length) throw Error("UTF-8 byte mismatch");
  let position=0;
  const space=()=>{while(position<source.length&&" \t\r\n".includes(source[position]))position++;};
  function string() {
    const start=position++;let escaped=false;
    while(position<source.length){const char=source[position++];
      if(char==='"'&&!escaped){let value;
        try{value=JSON.parse(source.slice(start,position));}catch{throw Error("JSON string");}
        if(!scalar(value,true))throw Error("JSON scalar");return value;}
      if(char==='\\'&&!escaped)escaped=true;else escaped=false;}
    throw Error("unterminated JSON string");
  }
  function parse(depth) {
    if(depth>32)throw Error("JSON depth");space();
    if(source[position]==='"')return string();
    if(source[position]==='{'){position++;space();const out=Object.create(null);
      if(source[position]==='}'){position++;return out;}
      while(true){space();if(source[position]!=='"')throw Error("JSON object key");
        const key=string();if(own(out,key))throw Error("duplicate JSON key");
        space();if(source[position++]!==':')throw Error("JSON colon");
        const value=parse(depth+1);Object.defineProperty(out,key,
          {value,enumerable:true,writable:true,configurable:true});
        space();const end=source[position++];if(end==='}')return out;
        if(end!==',')throw Error("JSON object separator");}}
    if(source[position]==='['){position++;space();const out=[];
      if(source[position]===']'){position++;return out;}
      while(true){out.push(parse(depth+1));space();const end=source[position++];
        if(end===']')return out;if(end!==',')throw Error("JSON array separator");}}
    for(const [word,value] of [["true",true],["false",false],["null",null]])
      if(source.startsWith(word,position)){position+=word.length;return value;}
    const match=/^-?(?:0|[1-9][0-9]*)/.exec(source.slice(position));
    if(!match)throw Error("JSON number");position+=match[0].length;
    if(/[.eE]/.test(source[position]||""))throw Error("JSON noninteger");
    const number=Number(match[0]);if(!Number.isSafeInteger(number))throw Error("JSON unsafe integer");
    return number;
  }
  const value=parse(0);space();if(position!==source.length)throw Error("JSON trailing bytes");
  return value;
}

function schema(value, shape) {
  if (own(shape, "$ref")) {
    const match = /^#\/\$defs\/([A-Za-z][A-Za-z0-9]*)$/.exec(shape.$ref);
    if (!match || !own(bundle.$defs, match[1])) throw new Error("unresolved successor schema");
    return schema(value, bundle.$defs[match[1]]);
  }
  if (shape.oneOf) return shape.oneOf.filter(part => schema(value, part)).length === 1;
  if (own(shape, "const") && value !== shape.const) return false;
  if (shape.enum && !shape.enum.includes(value)) return false;
  if (shape.type === "object") {
    if (value === null || typeof value !== "object" || Array.isArray(value) ||
        (shape.required ?? []).some(key => !own(value, key))) return false;
    for (const [key, item] of Object.entries(value)) {
      if (!own(shape.properties ?? {}, key)) {
        if (shape.additionalProperties === false) return false;
      } else if (!schema(item, shape.properties[key])) return false;
    }
  } else if (shape.type === "array") {
    if (!Array.isArray(value) || value.length < (shape.minItems ?? 0) ||
        value.length > (shape.maxItems ?? Infinity) || value.some(item => !schema(item, shape.items))) return false;
  } else if (shape.type === "string") {
    if (typeof value !== "string" || !scalar(value) ||
        [...value].length < (shape.minLength ?? 0) || [...value].length > (shape.maxLength ?? Infinity) ||
        (shape.pattern && !new RegExp(shape.pattern, "u").test(value))) return false;
  } else if (shape.type === "integer") {
    if (!Number.isSafeInteger(value) || value < (shape.minimum ?? -Infinity) ||
        value > (shape.maximum ?? Infinity)) return false;
  } else if (shape.type === "boolean" && typeof value !== "boolean") return false;
  return true;
}

function named(value, name) { return schema(value, bundle.$defs[name]); }

function selectorMatches(handle, selector) {
  if (!named(handle, "Handle")) return false;
  if (own(selector, "submission_id")) return handle.submission_id === selector.submission_id;
  return ["task_id", "step_id", "step_revision", "execution_generation"].every(
    key => handle.work_key[key] === selector[key]);
}

function decimalParts(value) {
  const negative=value.startsWith("-"), [mantissa,exponent="0"]=value.replace(/^-/,"").toLowerCase().split("e");
  return {number:BigInt(mantissa.replace(".",""))*(negative?-1n:1n),
    exponent:Number(exponent)-(mantissa.split(".")[1]||"").length};
}
function compareDecimal(a,b) {
  const left=decimalParts(a),right=decimalParts(b),exp=Math.min(left.exponent,right.exponent);
  const x=left.number*10n**BigInt(left.exponent-exp),y=right.number*10n**BigInt(right.exponent-exp);
  return x<y?-1:x>y?1:0;
}
function decimalValid(value,score=false) {
  if(typeof value!=="string"||!/^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$/.test(value)||
      /^-0(?:\.0+)?(?:[eE][+-]?\d+)?$/.test(value))return false;
  const [mantissa,exponent="0"]=value.toLowerCase().split("e");
  if(mantissa.replace(/[-.]/g,"").replace(/^0+/,"").length>17||Math.abs(Number(exponent))>100)return false;
  return compareDecimal(value,"-1000000")>=0&&compareDecimal(value,"1000000")<=0&&
    (!score||compareDecimal(value,"0")>=0&&compareDecimal(value,"1")<=0);
}

function resultValid(result,attempt,request) {
  if(!named(result,"Result")||result.attempt_id!==attempt||
      request&&(result.operation.type!==request.operation.type||
        result.operation.version!==request.operation.version))return false;
  if(result.operation.type==="embedding.create"){
    if(result.vectors.some((vector,index)=>vector.input_index!==index||
        vector.values.length!==result.dimensions||vector.values.some(value=>!decimalValid(value))))return false;
    if(!request)return true;
    const profile=request.input.profile;
    return result.profile_id===profile.profile_id&&result.model_ref===profile.model_ref&&
      result.dimensions===profile.dimensions&&result.vectors.length===request.input.items.length&&
      result.vectors.every((vector,index)=>vector.item_id===request.input.items[index].item_id);
  }
  const ranking=result.results;
  if(ranking.some((item,index)=>item.rank!==index+1||!decimalValid(item.score,true)||
      index>0&&(compareDecimal(ranking[index-1].score,item.score)<0||
        compareDecimal(ranking[index-1].score,item.score)===0&&ranking[index-1].input_index>item.input_index))||
      new Set(ranking.map(item=>item.candidate_id)).size!==ranking.length)return false;
  if(!request)return true;
  return result.ranking_profile_id===request.input.ranking_profile_id&&
    ranking.length===request.input.top_k&&ranking.every(item=>item.input_index<request.input.candidates.length&&
      item.candidate_id===request.input.candidates[item.input_index].candidate_id);
}

const ERROR_HTTP=Object.freeze({UNSUPPORTED_VERSION:426,MALFORMED_JSON:400,SCHEMA_INVALID:400,
  LIMIT_EXCEEDED:413,SEMANTIC_INVALID:422,CAPABILITY_UNSUPPORTED:422,WORK_CONFLICT:409,
  WORK_VERSION_CONFLICT:409,NOT_FOUND_OR_FORBIDDEN:404,POLICY_DENIED:403,
  FINANCIAL_AUTH_REQUIRED:403,PLAN_INVALID_OR_STALE:409,FDC_REJECTED:409,
  INTENT_PERSIST_FAILED:503,RESULT_INVALID:502,USAGE_UNKNOWN:502});
function errorValid(value,httpStatus,kind) {
  if(!named(value,"ErrorResponse"))return false;
  if(httpStatus===401)return value.code==="POLICY_DENIED"&&value.retry_guidance==="never";
  if(ERROR_HTTP[value.code]!==httpStatus)return false;
  if(value.code==="INTENT_PERSIST_FAILED")return value.retry_guidance==="query_first";
  if(value.code==="WORK_CONFLICT"||value.code==="WORK_VERSION_CONFLICT")
    return value.retry_guidance==="never";
  if(value.code==="POLICY_DENIED"&&value.retry_guidance==="query_first")
    return kind==="submit";
  return true;
}
function nativeUsageValid(usage) {
  const component=usage.components[0];
  if(usage.cost_status==="unknown")return !own(usage,"amount_decimal");
  return component.presence==="known"&&component.evidence==="reported"&&
    Number.isSafeInteger(component.quantity)&&component.quantity>0&&own(usage,"amount_decimal");
}
function failedStatus(value) {
  if(value.failure_stage==="before_send")return value.error.code==="INTENT_PERSIST_FAILED"?503:
    ["FDC_REJECTED","PLAN_INVALID_OR_STALE"].includes(value.error.code)?409:null;
  return ["RESULT_INVALID","USAGE_UNKNOWN"].includes(value.error.code)?502:null;
}
function responseValid(value,kind,httpStatus,selector,request) {
  if(!named(value,kind)||!selectorMatches(value.handle,selector))return false;
  if(kind==="SubmitReply"){
    const expected={completed:200,pending:202,outcome_unknown:202}[value.state]??
      failedStatus(value);
    return httpStatus===expected&&(value.state!=="completed"||resultValid(value.result,value.attempt_id,request))&&
      (value.state!=="failed"||errorValid(value.error,httpStatus,"submit"));
  }
  if(httpStatus!==200||value.attempts.length!==1)return false;
  const item=value.attempts[0],usage=item.usage_revision;
  if(usage?(usage.attempt_id!==item.attempt_id||item.settlement_state!==usage.cost_status||
      !nativeUsageValid(usage)):
      item.settlement_state!=="pending")return false;
  if(own(item,"result")&&!resultValid(item.result,item.attempt_id))return false;
  if(value.submission_state==="completed")return item.delivery_state==="valid"&&
    (value.candidate_access==="present"&&own(item,"result")||
     value.candidate_access==="expired"&&!own(item,"result"));
  if(value.submission_state==="failed")return value.candidate_access==="unavailable_due_failure"&&
    own(item,"failure")&&!own(item,"result")&&["invalid","pending"].includes(item.delivery_state);
  if(value.submission_state==="unknown")return value.candidate_access==="unknown_outcome"&&
    item.dispatch_state==="possible_send"&&item.delivery_state==="unknown"&&!own(item,"result");
  return value.candidate_access==="not_yet_available"&&item.delivery_state==="pending"&&!own(item,"result");
}

module.exports = Object.freeze({ named, selectorMatches, strictDecode, responseValid, errorValid });
