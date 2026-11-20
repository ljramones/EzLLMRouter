"use strict";
// Exact unpacked private CommonJS archive against the disposable retained HTTP fixture.
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const fs=require("node:fs");
const path=require("node:path");

async function main(output,installed){
  const ready=JSON.parse(fs.readFileSync(path.join(output,"READY.json"),"utf8"));
  const {EzLLMRouterClient,EzLLMRouterError}=require(path.join(installed,"index.cjs"));
  const successor=require(path.join(installed,"successor.cjs"));
  const installedSource=path.join(installed,"successor.cjs");
  const calls=[];
  for(const [label,token] of [["revoked","dev12.continue03.revoked.synthetic"],
                              ["renewed","dev12.continue03.renewed.synthetic"],
                              ["authenticated_foreign","dev12.continue03.foreign.synthetic"]]){
    const client=new EzLLMRouterClient({baseUrl:ready.origin,token});
    for(const query of [{submission_id:ready.submission_id},
                        {work_selector:ready.work_selector}]){
      const selector=Object.hasOwn(query,"submission_id")?"submission_id":"work_key";
      try{
        const value=await client.getSuccessorStatus(query);
        assert.equal(label,"renewed");
        assert.equal(value.handle.submission_id,ready.submission_id);
        assert.equal(value.attempts.length,1);
        calls.push({credential_state:label,selector,submission_id:value.handle.submission_id,
                    attempt_id:value.attempts[0].attempt_id});
      }catch(error){
        assert.notEqual(label,"renewed");
        assert(error instanceof EzLLMRouterError);
        assert.deepEqual([error.code,error.http_status,error.retry_guidance],label==="revoked"?
                         ["POLICY_DENIED",401,"never"]:["NOT_FOUND_OR_FORBIDDEN",404,"never"]);
        assert.deepEqual(error.selector,query.work_selector??query);
        calls.push({credential_state:label,selector,http_status:error.http_status,
                    code:error.code,retry_guidance:error.retry_guidance});
      }
    }
  }
  const base={contract_version:"0.3",code:"POLICY_DENIED",
              correlation_id:"error.synthetic",retry_guidance:"never"};
  const negatives={
    prior_wrong_401_intent:!successor.errorValid({...base,code:"INTENT_PERSIST_FAILED"},401,"status"),
    wrong_401_guidance:!successor.errorValid({...base,retry_guidance:"query_first"},401,"status"),
    wrong_401_extra:!successor.errorValid({...base,extra:true},401,"status"),
    wrong_403_status:!successor.errorValid(base,503,"status"),
    retained_403_policy:successor.errorValid(base,403,"status"),
    retained_403_expired_submit:successor.errorValid({...base,retry_guidance:"query_first"},403,"submit"),
    retained_404:successor.errorValid({...base,code:"NOT_FOUND_OR_FORBIDDEN"},404,"status"),
    retained_503:successor.errorValid({...base,code:"INTENT_PERSIST_FAILED",
      retry_guidance:"query_first"},503,"submit"),
  };
  assert(Object.values(negatives).every(Boolean));
  const evidence={kind:"dev12_completion02_continue03_exact_commonjs_auth_http_v1",status:"PASS",
    installed_source:installedSource,
    installed_successor_sha256:crypto.createHash("sha256").update(fs.readFileSync(installedSource)).digest("hex"),
    selected_submission_id:ready.submission_id,calls,protocol_controls:negatives,
    read_only_gets:calls.length,new_admissions_or_sends:0};
  fs.writeFileSync(path.join(output,"COMMONJS-HTTP.json"),JSON.stringify(evidence,null,2)+"\n",{flag:"wx"});
  process.stdout.write(JSON.stringify({status:"PASS",actual_http_gets:calls.length,
    protocol_controls:Object.keys(negatives).length,installed_package:true})+"\n");
}

main(process.argv[2],process.argv[3]).catch(error=>{console.error(error);process.exitCode=1;});
