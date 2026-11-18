"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const [base,tokenFile,examplesFile,packageRoot,mode="seed"]=process.argv.slice(2);
const {IntegrationClient}=require(packageRoot);
const examples=JSON.parse(fs.readFileSync(examplesFile,"utf8"));
const token=fs.readFileSync(tokenFile,"utf8").trim();
async function run(){
  const client=new IntegrationClient(base,token);
  const dataset=examples.dataset.dataset_id,account=examples.account.account_id;
  if(mode==="seed"){
    assert.equal((await client.eligibility(dataset,account,"model.synthetic")).usable,true);
    for(const event of examples.events.slice(0,6))await client.submitObservation(event);
    const first=await client.submitObservation(examples.events[4]);
    const recovered=await client.recoverReceipt(dataset,examples.events[4].event_id);
    assert.deepEqual(first,recovered);
    let conflict=false;
    try{await client.submitObservation({...examples.events[4],occurred_at:"2026-10-27T00:00:22Z"});}
    catch(error){conflict=error.code==="EVENT_CONFLICT"&&error.httpStatus===409;}
    assert.equal(conflict,true);
  }else{
    assert.equal((await client.eligibility(dataset,account,"model.synthetic")).reason,"account_disabled");
    assert.equal((await client.recoverReceipt(dataset,examples.events[4].event_id)).kind,"usage");
  }
  console.log("installed Node client",mode,"PASS");
}
run().catch(error=>{console.error(error.code||error.message);process.exitCode=1;});
