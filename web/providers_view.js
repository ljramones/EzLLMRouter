"use strict";
// Connection views read persisted records. Only named probe buttons make network requests.
const providerOrigins={openai:"https://api.openai.com",anthropic:"https://api.anthropic.com",
  google:"https://generativelanguage.googleapis.com",xai:"https://api.x.ai",
  deepseek:"https://api.deepseek.com"};
const providerAdapters=[
  ["openai.responses.v1","OpenAI · Responses v1"],
  ["anthropic.messages.2023-06-01","Anthropic · Messages 2023-06-01"],
  ["gemini.developer.v1beta","Google Gemini · Developer v1beta"],
  ["vllm.openai-compatible.v1","vLLM · compatible inventory v1"],
  ["xai.responses.v1","xAI · Responses v1 (operations pending)"],
  ["deepseek.chat.v1","DeepSeek · chat v1 (operations pending)"]];
const providerId=adapter=>({openai:"openai",anthropic:"anthropic",gemini:"google",vllm:"vllm",xai:"xai",deepseek:"deepseek"})[adapter.split(".")[0]];
function providerForm(adapter=null,options={}){
  if(!adapter){const choose=crudForm("Select provider API",[{name:"adapter_id",label:"Versioned API adapter",options:providerAdapters}],
      "Continue",()=>render(),async v=>{providerForm(v.adapter_id,options);});
    // The next form replaces this selector; the helper must not redraw the list.
    choose.box.querySelector("form").onsubmit=event=>{event.preventDefault();providerForm(choose.box.querySelector("select").value,options);};
    crudOpen(choose);return;}
  const provider=providerId(adapter),hosted=provider==="vllm",location=options.location||(hosted?"office_lab":"commercial"),
    originRoute=window.location.hash;let created=null;
  const fields=[
    {name:"display_name",label:"API setup name (for example, Production or Testing)"},
    {name:"funding_kind",label:"Funding / environment",options:[["personal_testing","Personal · live testing"],
      ["organization","Organization"],["controlled","Controlled synthetic test"]]},
    {name:"connection_id",label:"Advanced · stable setup ID (conn.…)",value:"conn."},
    {name:"site",label:location==="office_lab"?"Office lab site / pool":
      location==="private_cloud"?"Private installation / site":"Account or project label",
      value:options.site||(location==="office_lab"?"Office lab":location==="private_cloud"?"Private installation":"Primary")},
    {name:"origin",label:hosted?"Advanced · HTTPS engine origin":"Advanced · approved provider origin",type:"url",
      value:providerOrigins[provider]||"https://"},
    {name:"owner",label:"Responsible owner ID",value:"owner.local"}];
  if(provider==="openai")fields.push({name:"project",label:"Project ID (optional)",required:false});
  if(provider==="anthropic")fields.push({name:"workspace",label:"Workspace label (metadata only; key selects access)",required:false});
  if(hosted)fields.push({name:"engine_version",label:"Engine version",value:"vllm.v1"},
    {name:"ca_pem",label:"TLS trust certificate (PEM; public certificate only)",textarea:true,maxLength:8192});
  const title=location==="private_cloud"?"Register private installation":
    location==="office_lab"?"Register office lab serving connection":"Set up "+provider+" API access";
  const form=crudForm(title,fields,"Create draft",()=>{
    if(options.returnToSource){sourceGo(created?sourceConnectionRoute(created):originRoute);return;}
    state.view="providers";render();},
    async(v,operation)=>{const settings={origin:v.origin,location,site:v.site};
      for(const key of ["project","workspace","engine_version","ca_pem"])if(v[key])settings[key]=v[key];
      await crudMutation("create_connection",v.connection_id,0,
        {display_name:v.display_name,adapter_id:adapter,settings,owner:v.owner,
          funding_kind:v.funding_kind},operation);
      created={connection_id:v.connection_id,provider_id:provider,settings};});
  form.box.insertBefore(node("p",`Source: ${location.replaceAll("_"," ")} · ${adapter}. Approved provider defaults are prefilled. Personal testing uses the existing owner.local identity for Larry Mitchell. Saving creates a draft API setup without a credential, model permission, user grant or paid authorization. Add and test the credential on the setup page.`,"scope-note"),form.box.querySelector("form"));
  crudOpen(form);
}
function providerAccessStatus(connection,observations=[]){
  if(connection.credential_state!=="present")return {label:"Not set up",detail:"No credential saved"};
  const latest=observations.filter(item=>item.operation==="access"&&
    item.connection_revision===connection.revision&&item.credential_version===connection.credential_version)
    .sort((a,b)=>b.observed_at.localeCompare(a.observed_at))[0];
  if(!latest)return {label:"Key saved—not checked",detail:"Test API access to check model-listing permission"};
  if(new Date(latest.expires_at).getTime()<=Date.now()||latest.state==="stale")
    return {label:"Needs attention",detail:"Last access observation is stale · "+latest.observed_at};
  if(latest.state==="observed")return {label:"API access verified",detail:"Model listing only · "+latest.observed_at};
  const reason={credential_rejected:"Credential rejected",access_forbidden:"Access forbidden for model listing",
    timeout:"Service timeout",network_or_tls_failure:"Service unreachable or TLS failed",
    rate_limited:"Provider rate limited",operation_not_implemented:"Access check unsupported",
    credential_unavailable:"Credential unavailable"}[latest.reason]||latest.reason.replaceAll("_"," ");
  return {label:"Needs attention",detail:reason+" · "+latest.observed_at};
}
async function providers(){
  const root=$("view-content"),reply=await api("/operator/v1/connections"),items=reply.items;
  if(state.role==="registry_admin")root.append(crudActions(crudButton("Add provider",()=>providerForm(),"action")));
  const details=await Promise.all(items.map(c=>api("/operator/v1/connections/"+encodeURIComponent(c.connection_id))));
  const info=panel("API setups · named accounts and projects");info.append(node("p","Each setup has its own credential and access observation. Inventory and checks run only when explicitly requested; access verification does not grant inference.","scope-note"));
  if(items.length)info.append(table(["API setup","Provider / API","Location","Credential check","State","Actions"],items.map((c,index)=>[
    namedButton(c.display_name,c.connection_id,()=>providerDetail(c.connection_id)),
    c.provider_name+" · "+c.adapter_id,c.settings.location+" · "+c.settings.site,
    providerAccessStatus(c,details[index].observations).label+" · "+providerAccessStatus(c,details[index].observations).detail,
    badge(c.status),crudActions(crudButton("View",()=>providerDetail(c.connection_id)))])));
  else info.append(node("p","No connections registered. Add one to configure an API protocol; this does not grant access or send model work.","empty"));
  root.append(info);
}
function providerObservationLine(item,connection){
  const stale=item.connection_revision!==connection.revision||item.credential_version!==connection.credential_version||
    new Date(item.expires_at).getTime()<=Date.now();
  const ageMinutes=Math.max(0,Math.floor((Date.now()-new Date(item.observed_at).getTime())/60000));
  const result=node("div");result.append(badge(stale?"stale":item.state),
    node("small",item.reason.replaceAll("_"," "),"secondary-line"),
    node("small",`Age ${ageMinutes} min · expires ${new Date(item.expires_at).toLocaleTimeString()}`,"secondary-line"));
  return [item.operation.replaceAll("_"," ")+" · "+item.scope.replaceAll("_"," "),
    new Date(item.observed_at).toLocaleString(),result,
    item.models?.length?item.models.slice(0,8).join(", ")+(item.models.length>8?" …":""):"No models",item.connection_revision];
}
async function providerDetail(id){
  const root=$("view-content");clean(root);$("view-title").textContent="Provider connection";
  try{const reply=await api("/operator/v1/connections/"+encodeURIComponent(id)),c=reply.connection,
      spec=(await api("/operator/v1/providers")).adapters[c.adapter_id];
    root.append(crudButton("← API setups",()=>{state.view="providers";render();}));
    const access=providerAccessStatus(c,reply.observations);
    root.append(node("p",access.label+" · "+access.detail,"scope-note"));
    const info=panel(c.display_name);info.append(definition([["Provider",c.provider_name],["API adapter",c.adapter_id],
      ["Connection",c.connection_id],["State",c.status],["Location",c.settings.location],
      ["Site / account",c.settings.site],["HTTPS origin",c.settings.origin],["Owner",c.owner],
      ["Network policy",c.network_policy],
      ["Credential",c.credential_state==="present"?"Stored · version "+c.credential_version:"Not stored"],
      ["Revision",c.revision],["Inference",spec.inference||"Not implemented for this adapter"],
      ["Scheduled checks",c.checks_scheduled?c.scheduled_operation+" every "+c.check_interval_seconds+" seconds":"Off"],
      ["Provider incident status","Unknown · no status feed connected"],
      ["User eligibility","Inspect an exact configuration and grant in Users & Access"]]));root.append(info);
    const actions=crudActions();root.append(actions);
    if(state.role==="registry_admin"&&c.status!=="archived"){
      actions.append(crudButton("Edit label",()=>{const form=crudForm("Edit connection label",[
        {name:"display_name",label:"Connection name",value:c.display_name}],"Save",()=>providerDetail(id),
        (v,op)=>crudMutation("edit_connection",id,c.revision,{display_name:v.display_name},op));crudOpen(form);}));
      actions.append(crudButton("API setup",()=>{sourceUi.tabs.set(c.connection_id,"api_setup");
        sourceGo(sourceConnectionRoute(c));}));
      actions.append(crudButton(c.credential_state==="present"?"Replace credential":"Set up API access",()=>providerCredentialForm(c,"replace")));
      if(c.credential_state==="present")actions.append(crudButton("Remove credential",()=>providerCredentialForm(c,"remove")));
      for(const operation of ["access","inventory","readiness"]){const fixed=spec[operation],button=crudButton(
        operation==="access"?"Test API access":operation==="inventory"?"Discover models":"Check readiness",async()=>{
          if(!window.confirm(`Run ${fixed[0]} ${fixed[1]} against ${c.settings.origin}? This is a non-generation probe.`))return;
          button.disabled=true;try{await api("/operator/v1/provider-probe",{method:"POST",csrf:true,body:{
            operation_id:crypto.randomUUID(),connection_id:id,expected_revision:c.revision,operation}});
            await providerDetail(id);}catch(error){if(error.staleView)return;message("Probe failed: "+error.message,true);}finally{button.disabled=false;}});
        if(!fixed){button.disabled=true;button.title="No documented operation implemented for this adapter.";}
        actions.append(button);}
      if(c.status!=="disabled")actions.append(crudButton("Disable",()=>providerState(c,"disabled")));
      if(c.status!=="active"&&c.credential_state==="present")actions.append(
        crudButton("Activate connection",()=>providerState(c,"active")));
      if(c.checks_scheduled)actions.append(crudButton("Stop scheduled checks",async()=>{
        try{await registryChange("probe_schedule",id,c.revision,{enabled:false,operation:null,interval_seconds:null});
          await providerDetail(id);}catch(error){if(error.staleView)return;message("Schedule change failed: "+error.message,true);}}));
      else if(["draft","active"].includes(c.status)&&["access","inventory","readiness"].some(op=>spec[op]))
        actions.append(crudButton("Schedule checks…",()=>providerScheduleForm(c,spec)));
      actions.append(crudButton("Archive…",()=>providerState(c,"archived")));
      actions.append(crudButton("Associate model",()=>providerAssociationForm(c)));
    }
    const deployments=panel("Models · exact associations");deployments.append(reply.deployments.length?
      table(["Model","Serving ID","Site","Approval","Configuration / action"],reply.deployments.map(d=>[
        d.model_ref,d.serving_id,d.site,d.execution_approved?"Approved":"Not approved",
        d.configuration_ref?namedButton(d.configuration_ref,d.deployment_id,()=>catalogueModelDetail(d.configuration_ref)):
          state.role==="registry_admin"&&c.status==="active"&&c.adapter_id==="openai.responses.v1"?
          crudButton("Create execution configuration",()=>providerConfigurationForm(c,d)):
          d.deployment_id+" · no execution configuration"])):
      node("p","No model associations. Inventory never creates an approved deployment or grant.","empty"));root.append(deployments);
    if(state.role==="registry_admin"&&c.adapter_id==="openai.responses.v1"){
      const validation=panel("Explicit provider validation");validation.append(node("p",
        "A validation sends one fixed text request through admission, the isolated worker and trusted sender. It requires an active connection, approved configuration, current price and an explicit grant to the test service. Input tokens may be billed; there is no automatic retry.","scope-note"));
      const available=reply.deployments.filter(d=>d.configuration_ref);
      validation.append(available.length?table(["Configuration","Approval","Action"],available.map(d=>[
        d.configuration_ref,d.execution_approved?"Approved":"Not approved",
        (()=>{const button=crudButton("Validate one request…",()=>providerValidationForm(c,d));
          button.disabled=!d.execution_approved||c.status!=="active"||c.credential_state!=="present";
          if(button.disabled)button.title="Approve the deployment and activate the connection first.";
          return button;})()] )):
        node("p","No selected execution configuration is associated with this connection.","empty"));
      root.append(validation);
    }
    const observations=panel("API setup observations");observations.append(reply.observations.length?
      table(["Operation / scope","Observed","Result / expiry","Model IDs (sample)","Connection revision"],
        reply.observations.map(o=>providerObservationLine(o,c))):
      node("p","No checks recorded. Missing evidence is unknown.","empty"));root.append(observations);
    const history=panel("Change history");history.append(reply.history.length?
      table(["Action","Actor","Time","Before","After"],reply.history.map(h=>[h.action,h.actor,h.at,
        crudAuditFacts(h.before),crudAuditFacts(h.after)])):
      node("p","No changes recorded.","empty"));root.append(history);
    root.append(await sourceConnectionCost(c));
    message("");
  }catch(error){if(error.staleView)return;message("Connection unavailable: "+error.message,true);}
}
async function providerValidationForm(connection,deployment,campaign=null){
  try{
    const ref=deployment.configuration_ref,model=(await api("/operator/v1/models/"+encodeURIComponent(ref))).model;
    const explain=await api("/operator/v1/access/explain?"+new URLSearchParams({
      principal_id:campaign?.principal_id||"svc.demo",configuration_ref:ref,purpose:"execution",task_class:"class.demo"}));
    if(!explain.allowed){message("The test service is not eligible: "+explain.reason.replaceAll("_"," ")+". Configure the exact grant first.",true);return;}
    let outcome=null;
    const form=crudForm("Validate "+model.display_name+" once",[
      {name:"max_output_tokens",label:"Maximum output tokens for this one request (1–32)",
        type:"number",min:1,value:String(Math.min(16,campaign?.max_output_tokens||16))},
      {name:"acknowledge_external_send",type:"checkbox",value:false,
        label:"I authorize one provider request and possible input/output token charges"}],
      "Send one request",async()=>{if(campaign)await sourceDetail();else await providerDetail(connection.connection_id);
        if(outcome?.live_candidate){
          const candidate=outcome.live_candidate,usage=candidate.usage?.revision||{},cost=usage.cost||{},
            elapsed=Math.max(0,
              new Date(outcome.updated_at).getTime()-new Date(outcome.created_at).getTime()),
            output=candidate.output_blocks.filter(b=>b.kind==="assistant_text").map(b=>b.text).join("\n"),
            box=panel("Live test result · this page only");
          const detail=await api("/operator/v1/activity/"+encodeURIComponent(outcome.submission_id));
          const count=name=>detail.usage.counts?.[name]??
            (detail.usage.knowledge?.[name]==="not_applicable"?"Not applicable":
             "Unknown ("+(detail.usage.knowledge?.[name]||"not reported")+")");
          const current=campaign?await api("/operator/v1/personal-campaign"):null;
          const attempt=current?.attempts?.find(item=>item.attempt_id===candidate.attempt_id);
          box.append(definition([["Attempt",candidate.attempt_id],["Submission",outcome.submission_id],
            ["Elapsed",(elapsed/1000).toFixed(2)+" seconds"],
            ["Reported served model",outcome.provider_model_reported||"Unknown · price remains unverified"],
            ["Total reported input",count("input_total")],
            ["Ordinary input",count("input_uncached")],
            ["Cached reads (reported billing category)",count("input_cache_read")],
            ["30-minute priced writes",count("input_cache_write_30m")],
            ["Total reported output",count("output_total")],
            ["Output text",count("output_text")],
            ["Reasoning (included in output)",count("output_reasoning")],
            ["Calculated amount",cost.status==="calculated"?cost.currency+" "+cost.amount_decimal:
              "Unknown · reserved exposure retained"],["Price version",usage.price_version||"Unknown"],
            ["Usage contract",detail.usage.contract_version||detail.usage.usage_semantics_version||"Unknown"],
            ["Reserved exposure",attempt?current.currency+" "+attempt.bound_decimal:"Unavailable"],
            ["Remaining allowance",current?current.currency+" "+current.available_decimal:"Unavailable"]]));
          if(output)box.append(node("p",output,"scope-note"));
          box.append(node("p","Output is shown for this immediate response under the admitted retention rules. The amount is calculated from provider-reported usage at the approved rate, not reconciled to an invoice.","scope-note"));
          $("view-content").append(box);
        }
        if(outcome)message("Validation "+outcome.state.replaceAll("_"," ")+" · "+
          (outcome.submission_id||outcome.operation_id)+
          (outcome.state==="outcome_unknown"?" · Check Activity; this action will not retry.":""),
          outcome.state!=="completed");},
      async(v,operation)=>{
        const limit=Number(v.max_output_tokens);
        if(!Number.isInteger(limit)||limit<1||limit>32||
            (campaign&&limit>campaign.max_output_tokens)||v.acknowledge_external_send!==true)
          throw new Error("Select an output allowance and acknowledge the provider request.");
        outcome=await api("/operator/v1/provider-validation",{method:"POST",csrf:true,body:{
          operation_id:operation,connection_id:connection.connection_id,
          connection_revision:connection.revision,configuration_ref:ref,
          configuration_revision:model.revision,max_output_tokens:limit,
          acknowledge_external_send:true}});
      });
    form.box.insertBefore(node("p",campaign?
      `One fixed 'Say hello.' text request via ${connection.display_name} and ${model.display_name}. Caller ${campaign.principal_id}. Billing ${campaign.currency}; per-request ceiling ${campaign.per_request_decimal}, available ${campaign.available_decimal}. The server reserves the exact admitted upper bound before sending; this action permits one attempt only.`:
      "One fixed 'Say hello.' text request, no tools or streaming. The exact grant and provider price must already be approved; this output cap is not a currency spending cap.","scope-note"),form.box.firstChild);
    crudOpen(form);
  }catch(error){if(error.staleView)return;message("Validation setup unavailable: "+error.message,true);}
}
function providerScheduleForm(c,spec){
  const options=["access","inventory","readiness"].filter(op=>spec[op]).map(op=>[op,
    op==="access"?"Credential access check":op==="inventory"?"Inventory listing":"Service reachability"]);
  const form=crudForm("Opt in to bounded non-generation checks",[
    {name:"operation",label:"Fixed operation",options},
    {name:"interval_seconds",label:"Interval in seconds (300–86400)",type:"number",min:300,value:"3600"}],
    "Schedule",()=>providerDetail(c.connection_id),
    (v,operation)=>crudMutation("probe_schedule",c.connection_id,c.revision,
      {enabled:true,operation:v.operation,interval_seconds:Number(v.interval_seconds)},operation));
  crudOpen(form);
}
function providerCredentialForm(c,mode,after=()=>providerDetail(c.connection_id)){
  const fields=mode==="replace"?[{name:"secret",label:"Outbound API credential (write only)",type:"password",maxLength:4096}]:[];
  if(mode==="replace")fields.push({name:"test_access",label:"Save and test API access (one explicit non-generation model-listing check)",type:"checkbox",value:false,required:false});
  if(mode==="remove"&&!window.confirm("Remove the stored outbound credential? Unsent work will be invalidated."))return;
  if(mode==="remove"){
    api("/operator/v1/provider-credential",{method:"POST",csrf:true,body:{operation_id:crypto.randomUUID(),
      connection_id:c.connection_id,expected_revision:c.revision,mode,secret:null}})
      .then(after).catch(error=>message("Credential removal failed: "+error.message,true));return;}
  const form=crudForm(c.credential_state==="present"?"Replace API credential":"Set up API access",fields,"Save API credential",after,
    async(v,operation)=>{const saved=await api("/operator/v1/provider-credential",{method:"POST",csrf:true,body:{
      operation_id:operation,connection_id:c.connection_id,expected_revision:c.revision,mode,secret:v.secret}});
      v.secret="";
      if(v.test_access){await api("/operator/v1/provider-probe",{method:"POST",csrf:true,body:{
        operation_id:crypto.randomUUID(),connection_id:c.connection_id,expected_revision:saved.record.revision,operation:"access"}});}});crudOpen(form);
}
async function providerState(c,status,after=()=>providerDetail(c.connection_id)){
  if(!window.confirm(`${status==="archived"?"Archive":status==="active"?"Activate":"Disable"} ${c.display_name}? Authority changes invalidate queued work; history remains.`))return;
  try{await registryChange("connection_state",c.connection_id,c.revision,{status,reason:"Administrator lifecycle change"});
    await after();}catch(error){if(error.staleView)return;message("State change failed: "+error.message,true);}
}
function providerConfigurationForm(connection,deployment){
  const form=crudForm("Create selected Responses configuration",[
    {name:"configuration_ref",label:"Stable configuration reference (cfg.provider.…)",value:"cfg.provider."},
    {name:"display_name",label:"Execution configuration name"},
    {name:"owner",label:"Responsible owner ID",value:"owner.local"},
    {name:"purposes",label:"Purposes (comma separated)",value:"execution"},
    {name:"task_classes",label:"Task classes (comma separated)",value:"class.demo"}],
    "Create draft",()=>providerDetail(connection.connection_id),
    (v,operation)=>crudMutation("create_provider_configuration",v.configuration_ref,0,{
      display_name:v.display_name,deployment_id:deployment.deployment_id,owner:v.owner,
      purposes:listValue(v.purposes),task_classes:listValue(v.task_classes)},operation));
  crudOpen(form);
}
async function providerAssociationForm(c,after=()=>providerDetail(c.connection_id)){
  const models=(await api("/operator/v1/models")).items.filter(m=>m.kind==="real_catalogue"&&m.status==="catalogued");
  if(!models.length){message("No catalogued real models available to associate.",true);return;}
  const form=crudForm("Associate catalogued model",[
    {name:"deployment_id",label:"Stable deployment ID"},
    {name:"model_ref",label:"Catalogue model",options:models.map(m=>[m.configuration_ref,m.display_name+" · "+m.configuration_ref])},
    {name:"serving_id",label:"Exact provider serving ID"},
    {name:"site",label:"Region or site",value:c.settings.site}],"Associate",after,
    (v,operation)=>crudMutation("associate_deployment",c.connection_id,c.revision,{...v,status:"catalogued"},operation));
  crudOpen(form);
}

if(typeof screenFunction==="function"){
  providerDetail=screenFunction("Provider connection",providerDetail);
}
