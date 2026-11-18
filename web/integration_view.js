"use strict";
// Owner registration and external accounting. Provider metadata calls require an explicit click.
function connectionRegistration(root,datasetId,connections,refreshView){
  const box=panel("Provider connections");
  box.append(node("p","Connected means this key retrieved a model list. Saved permissions and Vega execution availability are shown separately; selecting a collection does not activate accounting."));
  if(state.principal!=="owner.local"||state.role!=="registry_admin"){
    box.append(node("p","Only the local owner can register or edit provider connections."));
    root.append(box);return;
  }
  const form=node("form");
  const providerWrap=node("label","Provider"),provider=node("select");
  for(const [value,label] of [["openai","OpenAI"],["anthropic","Anthropic (Claude)"],["xai","xAI (Grok)"]]){
    const option=node("option",label);option.value=value;provider.append(option);
  }
  providerWrap.append(provider);form.append(providerWrap);
  const keyWrap=node("label","API key"),key=node("input");key.type="password";key.required=true;key.autocomplete="new-password";
  keyWrap.append(key);form.append(keyWrap);
  const nameWrap=node("label","Friendly name (optional)"),name=node("input");name.maxLength=120;
  nameWrap.append(name);form.append(nameWrap);
  const connect=node("button","Connect","action");connect.type="submit";form.append(connect);
  form.onsubmit=async event=>{event.preventDefault();connect.disabled=true;try{
    await api("/operator/v1/integration/connections",{method:"POST",csrf:true,
      body:{dataset_id:datasetId,provider:provider.value,api_key:key.value,
        friendly_name:name.value,operation_id:"op."+crypto.randomUUID()}});
    key.value="";await refreshView();message("Connection check finished. Select permitted models or operations and Save.");
  }catch(error){key.value="";message("Connection check failed: "+error.message,true);connect.disabled=false;}};
  box.append(form);
  const normal=connections.filter(item=>!String(item.discovery?.reason||"").startsWith("controlled_fixture_"));
  const fixtures=connections.filter(item=>String(item.discovery?.reason||"").startsWith("controlled_fixture_"));
  const fixtureDetails=node("details",undefined,"connection-fixtures");
  fixtureDetails.append(node("summary","Controlled test connections ("+fixtures.length+")"));
  if(fixtures.length)box.append(fixtureDetails);
  for(const item of [...normal,...fixtures]){
    const fixture=fixtures.includes(item);
    const target=fixture?fixtureDetails:box;
    const detail=node("section",undefined,"panel");
    detail.classList.add("connection-card");
    detail.append(node("h3",item.friendly_name+" · "+item.provider+(fixture?" · Controlled test":"")));
    detail.append(node("p",item.state==="connected"?
      "Connected. Models retrieved; select the models this connection may use.":
      "Connection pending. Model discovery must succeed before selections can be saved."));
    detail.append(node("p","Saved policy: "+(item.selected_models?.length||0)+" models; "+
      (item.allowed_operations?.length?item.allowed_operations.join(", "):"no speech permissions")+". Vega execution: "+
      (fixture?"controlled test only":"inactive until a separate route and accounting activation")));
    const technical=node("details",undefined,"connection-technical");
    technical.append(node("summary","Technical details"));
    technical.append(definition([["Connection",item.account_id],["Credential reference",item.credential_ref],
      ["Credential version",item.selected_version||"Pending"],["Policy revision",item.policy_revision],
      ["Discovery",item.discovery.state+" · "+item.discovery.reason],
      ["Last checked",item.discovery.checked_at||"Never"]]));
    detail.append(technical);
    if(item.discovery.state!=="observed")detail.append(node("p",
      item.discovery.reason==="credential_rejected"?
        "The provider rejected this API key. Check that it is an ordinary inference API key for this provider, then Connect with a replacement. No models were enabled.":
        item.provider==="xai"&&item.discovery.reason==="provider_rejected_request"?
        "xAI rejected the model-list request. Confirm this is an ordinary xAI inference API key with access to GET /v1/models; use Connect with a replacement if its scope or validity is wrong. No models were enabled.":
        "Model discovery is unavailable. Check the connection and Refresh models; no model is inferred or enabled."));
    if(item.discovery.has_more)detail.append(node("p","The catalogue is incomplete. Refresh before saving selections."));
    const selected=new Set(item.selected_models||[]),available=new Set(item.discovery.models||[]);
    const chosen=new Set(selected);
    const missing=[...selected].filter(id=>!available.has(id));
    if(missing.length){detail.append(node("p","Selected models missing from the latest catalogue. Uncheck each one to remove it before saving a new policy:"));
      for(const id of missing){const label=node("label",undefined,"connection-choice"),input=node("input");input.type="checkbox";input.checked=true;
        input.onchange=()=>input.checked?chosen.add(id):chosen.delete(id);
        label.append(input,node("span",id+" · unavailable"));detail.append(label);}}
    const searchWrap=node("label","Search discovered models"),search=node("input");search.type="search";
    searchWrap.append(search);detail.append(searchWrap);
    const picker=node("div",undefined,"connection-models");detail.append(picker);
    const models=item.discovery.details?.length?item.discovery.details:item.discovery.models.map(id=>({id,name:id}));
    function draw(){picker.replaceChildren();const needle=search.value.toLowerCase();
      for(const model of models.filter(row=>(row.id+" "+row.name).toLowerCase().includes(needle))){
        const label=node("label",undefined,"connection-choice"),input=node("input");input.type="checkbox";input.checked=chosen.has(model.id);
        input.onchange=()=>input.checked?chosen.add(model.id):chosen.delete(model.id);
        const copy=node("span",undefined,"connection-choice-copy");
        copy.append(node("strong",model.name),node("small",model.id),node("small","Generation · listing only; execution separately qualified"));
        label.append(input,copy);picker.append(label);
      }
      if(!picker.childNodes.length)picker.append(node("p","No matching discovered models."));
    }
    search.oninput=draw;draw();
    const speech={};
    for(const [operation,label] of [["speech_input","Allow speech input"],["speech_output","Allow speech output"]]){
      const wrap=node("label",undefined,"connection-choice connection-speech"),input=node("input");input.type="checkbox";
      input.checked=item.allowed_operations.includes(operation);
      const copy=node("span",undefined,"connection-choice-copy");
      copy.append(node("strong",label),node("small",item.provider==="xai"?
        "Vega has an xAI speech route; connection permission is separate from activation.":
        "No qualified Vega speech route for "+item.provider+"; saved permission is not execution availability."));
      wrap.append(input,copy);detail.append(wrap);speech[operation]=input;
    }
    const actions=node("div",undefined,"actions");
    const save=node("button","Save selections","action");save.type="button";
    save.disabled=item.discovery.state!=="observed"||item.discovery.has_more||item.state==="disabled";
    save.onclick=async()=>{save.disabled=true;try{
      await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/save",
        {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision,
          selected_models:[...chosen],
          allowed_operations:Object.keys(speech).filter(op=>speech[op].checked)}});
      await refreshView();message("Selections saved. Restart Vega to adopt the new policy revision; execution remains separately gated.");
    }catch(error){message("Save failed: "+error.message,true);save.disabled=false;}};actions.append(save);
    const refresh=node("button","Refresh models","quiet");refresh.type="button";
    refresh.onclick=async()=>{refresh.disabled=true;try{
      await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/refresh",
        {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision}});
      await refreshView();message("Model listing refreshed. New models remain unselected.");
    }catch(error){message("Refresh failed: "+error.message,true);refresh.disabled=false;}};actions.append(refresh);
    if(item.state==="connected"){
      const replacement=node("input");replacement.type="password";replacement.autocomplete="new-password";
      replacement.placeholder="Replacement API key";actions.append(replacement);
      const replace=node("button","Replace API key","quiet");replace.type="button";
      replace.onclick=async()=>{replace.disabled=true;try{
        const result=await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/replace",
          {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision,api_key:replacement.value}});
        replacement.value="";await refreshView();message(result.replacement?.state!==undefined?
          "Replacement failed validation; the working key remains selected.":"Replacement validated. Restart Vega to adopt the new version.",
          result.replacement?.state!==undefined);
      }catch(error){replacement.value="";message("Replacement failed: "+error.message,true);replace.disabled=false;}};
      actions.append(replace);
      const disable=node("button","Disable","quiet");disable.type="button";
      disable.onclick=async()=>{disable.disabled=true;try{
        await api("/operator/v1/integration/connections/"+encodeURIComponent(item.account_id)+"/disable",
          {method:"POST",csrf:true,body:{dataset_id:datasetId,expected_revision:item.revision}});
        await refreshView();message("Connection disabled. New sends are denied.");
      }catch(error){message("Disable failed: "+error.message,true);disable.disabled=false;}};actions.append(disable);
    }
    detail.append(actions);target.append(detail);
  }
  root.append(box);
}
async function integrationView(){
  const root=$("view-content"), heading=panel("External platform accounting");
  heading.append(node("p","Registered accounting collections and EzLLMRouter-managed encrypted database credentials. A saved connection does not authorize a Vega model request."));
  root.append(heading);
  const list=await api("/operator/v1/integration/datasets");
  if(!list.items.length){root.append(node("p","No dataset is registered. An owner can create the first isolated collection through the versioned integration API; actual Vega activation is a later milestone.","empty"));return;}
  const controls=panel("Collection");
  const selector=node("select");selector.setAttribute("aria-label","Dataset");
  const ordered=list.items.slice().sort((a,b)=>String(b.activated_at||"").localeCompare(String(a.activated_at||"")));
  ordered.forEach(item=>{
    const kind=(item.dataset_id.startsWith("dataset.synthetic.")||item.environment_id.startsWith("environment.synthetic."))?"Synthetic test":
      item.dataset_id.startsWith("dataset.local.real.")?"Local real cohort":"Other collection";
    const option=node("option",kind+" · "+item.dataset_id+" · "+item.environment_id);
    option.value=item.dataset_id;selector.append(option);
  });
  const requested=new URLSearchParams(window.location.search).get("dataset_id");
  if(requested&&ordered.some(item=>item.dataset_id===requested))selector.value=requested;
  controls.append(selector);root.append(controls);
  const content=node("div");root.append(content);
  async function show(){
    clean(content);
    const id=selector.value,query=encodeURIComponent(id);
    const selected=ordered.find(item=>item.dataset_id===id);
    const statePanel=panel("Collection state");
    const synthetic=id.startsWith("dataset.synthetic.")||selected?.environment_id.startsWith("environment.synthetic.");
    statePanel.append(node("p",synthetic?
      "Synthetic accounting collection. These attempts are not real Vega accounting. Credential registrations here may be owner connections or controlled tests; inspect each connection below.":
      id.startsWith("dataset.local.real.")?
      "Local real cohort registered in EzLLMRouter. Check Vega's authenticated accounting diagnostics before treating recording as active.":
      "Collection type is not identified as the current local real cohort."));
    if(selected)statePanel.append(node("p","T0: "+selected.activated_at));
    content.append(statePanel);
    const [accounts,report,connections]=await Promise.all([
      api("/operator/v1/integration/accounts?dataset_id="+query),
      api("/operator/v1/integration/report?dataset_id="+query),
      state.principal==="owner.local"?api("/operator/v1/integration/connections?dataset_id="+query):
        Promise.resolve({items:[]})]);
    const summary=panel("Observed cost");
    const cards=node("div",undefined,"cards");
    cards.append(card("Attempts",report.attempt_count),card("Unknown cost",report.unknown_cost_attempts));
    for(const [currency,amount] of Object.entries(report.known_total_by_currency))
      cards.append(card("Known "+currency,amount));
    summary.append(cards);
    summary.append(node("p","Known amounts are a subtotal when unknown cost exists. External observations are not EzLLMRouter sends."));
    content.append(summary);
    const accountPanel=panel("Saved provider policies");
    const byId=new Map(connections.items.map(item=>[item.account_id,item]));
    const controlled=item=>String(byId.get(item.account_id)?.discovery?.reason||"").startsWith("controlled_fixture_");
    const rows=items=>table(["Connection","Provider","Selected models","Speech permissions","State"],
      items.map(item=>[byId.get(item.account_id)?.friendly_name||item.account_id,item.provider_id,
        item.allowed_models.join(", ")||"None",(item.allowed_operations||[]).join(", ")||"None",item.state]));
    const normalAccounts=accounts.items.filter(item=>!controlled(item));
    accountPanel.append(normalAccounts.length?rows(normalAccounts):
      node("p","No owner connection has a saved policy in this collection."));
    const testAccounts=accounts.items.filter(controlled);
    if(testAccounts.length){const extra=node("details",undefined,"connection-fixtures");
      extra.append(node("summary","Controlled test policies ("+testAccounts.length+")"),rows(testAccounts));
      accountPanel.append(extra);}
    content.append(accountPanel);
    connectionRegistration(content,id,connections.items,show);
    const attempts=panel("Attributed attempts");
    attempts.append(report.attempts.length?table(
      ["Attempt","Task / run","Executing actor","Account / model","Result / outcome","Usage revision","Cost"],
      report.attempts.map(item=>[item.attempt_id,item.task_id+" / "+item.run_id,
        item.actor_kind+" · "+item.actor_id,item.provider_account_id+" / "+item.model_id,
        item.result_state+" / "+item.task_outcome,item.usage_revision??"None",
        item.cost_status==="known"?item.currency+" "+item.amount_decimal:item.cost_status])):node("p","No included attempts yet.","empty"));
    content.append(attempts);
  }
  selector.onchange=()=>{
    const url=new URL(window.location.href);url.searchParams.set("dataset_id",selector.value);
    window.history.replaceState(null,"",url.toString());
    show().catch(error=>message("Collection unavailable: "+error.message,true));
  };
  await show();
}
