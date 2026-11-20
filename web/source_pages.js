"use strict";
// Source pages read stored inventory. Only named actions call discovery or change authority.
const sourceUi={tabs:new Map(),filters:new Map(),searches:new Map()};
const sourceSections={source_providers:"External Providers",source_private:"Private Hosting",source_labs:"Office Labs"};
const sourceVendor={openai:"OpenAI",anthropic:"Anthropic",google:"Google",xai:"xAI",deepseek:"DeepSeek"};
function sourceKind(connection){return connection.settings.location==="office_lab"?"source_labs":
  connection.settings.location==="private_cloud"?"source_private":"source_providers";}
function sourceRoute(hash=window.location.hash){
  if(!hash.startsWith("#/"))return null;
  const parts=hash.slice(2).split("/").map(value=>{try{return decodeURIComponent(value);}catch{return "";}});
  if(parts[0]==="local_connectors"&&parts.length<=2)return {view:"local_connectors",section:"local_connectors",item:parts[1]||null};
  if(parts.length===1&&titles[parts[0]])return {view:parts[0],section:parts[0]};
  if(parts[0]==="providers"&&parts[1]&&parts.length<=4&&
      (parts.length===2||(parts.length===4&&parts[2]==="connections")))
    return {view:"source_detail",section:"source_providers",provider:parts[1],connectionId:parts[3]||null};
  if(parts[0]==="private-hosting"&&parts[1]&&parts.length===2)
    return {view:"source_detail",section:"source_private",connectionId:parts[1]};
  if(parts[0]==="office-labs"&&parts[1]&&parts.length<=4&&
      (parts.length===2||(parts.length===4&&parts[2]==="connections")))
    return {view:"source_detail",section:"source_labs",site:parts[1],connectionId:parts[3]||null};
  return null;
}
function sourceGo(hash){
  if(!confirmViewLeave())return false;
  viewUi.notice=null;invalidateView();
  if(window.location.hash===hash){const route=window.location.pathname==="/integration"?integrationRoute():sourceRoute();state.view=route?.view||state.view;return render();}
  viewUi.approvedHash=hash;window.location.hash=hash;return true;
}
function sourceConnectionRoute(connection){const id=encodeURIComponent(connection.connection_id),kind=sourceKind(connection);
  return kind==="source_providers"?"#/providers/"+encodeURIComponent(connection.provider_id)+"/connections/"+id:
    kind==="source_private"?"#/private-hosting/"+id:
    "#/office-labs/"+encodeURIComponent(connection.settings.site)+"/connections/"+id;}
function sourceBreadcrumb(items){const row=node("nav",undefined,"source-breadcrumb");row.setAttribute("aria-label","Breadcrumb");
  items.forEach(([label,route],index)=>{if(index)row.append(node("span"," / "));
    if(route)row.append(crudButton(label,()=>sourceGo(route)));else row.append(node("strong",label));});return row;}
function sourceConnectionLink(connection){return namedButton(connection.display_name,connection.connection_id,
  ()=>sourceGo(sourceConnectionRoute(connection)));}
function sourceReferencePanel(models,provider){const matches=models.filter(m=>m.kind==="real_catalogue"&&
  m.catalogue?.vendor===sourceVendor[provider]);const box=panel("Reference catalogue · not authenticated discovery");
  box.append(node("p",`${matches.length} researched references. These records have no account credential, source permission or live readiness.`,"scope-note"));
  if(matches.length)box.append(table(["Model","Published API ID","Reference rates · USD / 1M tokens","Reference conditions / source"],matches.map(m=>[
    namedButton(m.display_name,m.configuration_ref,()=>catalogueModelDetail(m.configuration_ref)),
    m.catalogue.published_api_model_id,sourcePrice({reference_price:m.catalogue.price_reference}),
    m.catalogue.price_reference.bands[0].label+" · "+conditionText(m.catalogue.price_reference.bands[0].conditions)+
      " · "+m.catalogue.price_reference.snapshot_id+" · checked "+
      (m.catalogue.price_reference.verified_on||"unknown")])));return box;}
async function sourceIndex(){
  const root=$("view-content"),section=state.view,connections=(await api("/operator/v1/connections")).items;
  $("view-title").textContent=sourceSections[section];
  root.append(node("p","Choose an exact source. Inventory, permission and health are scoped to its connection; browsing never refreshes the provider API.","scope-note"));
  if(section==="source_providers"){
    if(state.role==="registry_admin")root.append(crudActions(crudButton("Add provider",()=>providerForm(null,{returnToSource:true}),"action")));
    const commercial=connections.filter(c=>sourceKind(c)===section),groups=new Map();
    const observed=await Promise.all(commercial.map(c=>api("/operator/v1/connections/"+
      encodeURIComponent(c.connection_id))));
    const access=new Map(commercial.map((c,index)=>[c.connection_id,
      providerAccessStatus(c,observed[index].observations)]));
    for(const c of commercial){const group=groups.get(c.provider_id)||[];group.push(c);groups.set(c.provider_id,group);}
    const references=(await api("/operator/v1/models")).items.filter(m=>m.kind==="real_catalogue");
    for(const [id,vendor] of Object.entries(sourceVendor))if(references.some(m=>m.catalogue?.vendor===vendor)){
      if(!groups.has(id))groups.set(id,[]);}
    const list=panel("Commercial providers");list.append(groups.size?table(["Provider","API setups","API access"],
      [...groups].sort(([a],[b])=>a.localeCompare(b)).map(([id,items])=>[
        namedButton(items[0]?.provider_name||sourceVendor[id]||id,id,()=>sourceGo("#/providers/"+encodeURIComponent(id))),
        items.length,items.length?items.map(c=>c.display_name+": "+access.get(c.connection_id).label).join(" · "):
          "Not set up · reference catalogue only"])):
      node("p","No commercial providers or reference records registered.","empty"));root.append(list);
  }else if(section==="source_private"){
    const items=connections.filter(c=>sourceKind(c)===section),list=panel("Private serving installations");
    if(state.role==="registry_admin")root.append(crudActions(crudButton("Register installation",()=>providerForm(
      "vllm.openai-compatible.v1",{location:"private_cloud",returnToSource:true}),"action")));
    list.append(items.length?table(["Installation","API profile","Site","State"],items.map(c=>[
      sourceConnectionLink(c),c.adapter_id,c.settings.site,badge(c.status)])):
      node("p","No private installation registered. Registration does not load a model or grant access.","empty"));root.append(list);
  }else{
    const labs=new Map();for(const c of connections.filter(c=>sourceKind(c)===section)){
      const items=labs.get(c.settings.site)||[];items.push(c);labs.set(c.settings.site,items);}
    if(state.role==="registry_admin")root.append(crudActions(crudButton("Register lab / serving connection",()=>providerForm(
      "vllm.openai-compatible.v1",{location:"office_lab",returnToSource:true}),"action")));
    const list=panel("Office lab sites");list.append(labs.size?table(["Lab site","Registered nodes / pools","Scope"],
      [...labs].sort(([a],[b])=>a.localeCompare(b)).map(([site,items])=>[
        namedButton(site,site,()=>sourceGo("#/office-labs/"+encodeURIComponent(site))),items.length,
        "Supported inventory is separate from loaded/running status"])):
      node("p","No lab site registered. No model download or network scan is performed.","empty"));root.append(list);
  }
}
function sourcePrice(item){if(item.price){const p=item.price,r=p.rates;
  if(p.usage_semantics_version==="openai.responses.text.cache.v2")return (
    money(r.input_uncached)+" ordinary input / "+money(r.input_cache_read)+" cached read / "+
    money(r.input_cache_write_30m)+" 30-minute write / "+money(r.output_text)+
    " total output · USD per 1M tokens · contract "+p.contract.version+" · price "+p.price_version);
  return money(r.input_uncached)+" input / "+money(r.output_text)+
    " output · USD per 1M tokens · historical two-rate schedule "+p.price_version+" · cache-aware paid testing unavailable";}
  if(item.reference_price){const rates=item.reference_price.bands[0].rates_usd_per_1000000_tokens;
    return "Reference only: "+money(rates.input_uncached)+" input / "+money(rates.output)+" output · USD per 1M tokens";}
  return "Unknown · no approved rate schedule";}
async function sourceSetPermission(connection,items,allowed){
  if(!items.length)return;
  if(items.length>100){message("Select at most 100 existing rows per change.",true);return;}
  const names=items.map(item=>item.serving_id).join(", ");
  if(!window.confirm(`${allowed?"Allow":"Disallow"} ${items.length} existing model(s) on ${connection.display_name} (${connection.connection_id})? ${names}. This does not grant a user or start model work.`))return;
  try{await crudMutation("set_source_permissions",connection.connection_id,0,{allowed,
    items:items.map(item=>({serving_id:item.serving_id,expected_revision:item.permission_revision}))},crypto.randomUUID());
    await render();message(`${allowed?"Allowed":"Disallowed"} ${items.length} model(s) on ${connection.display_name}. No user grant was created.`);
  }catch(error){if(error.staleView)return;message("Source permission rejected: "+error.message,true);}
}
function sourceModelsPanel(inventory,{compact=false}={}){
  const c=inventory.connection,box=panel(compact?c.display_name+" · models":"Models · "+c.display_name),key=c.connection_id;
  const discovery=inventory.discovery,when=discovery.observed_at?new Date(discovery.observed_at).toLocaleString():"Never";
  box.append(node("p",`${inventory.count} model IDs for this connection · discovery ${discovery.state.replaceAll("_"," ")} · last attempt ${when} · ${discovery.reason.replaceAll("_"," ")}. ${discovery.retained_snapshot_at?"Retained inventory from "+new Date(discovery.retained_snapshot_at).toLocaleString()+" ("+discovery.snapshot_completeness+(discovery.snapshot_current?"":", previous connection/credential revision")+").":"No authenticated inventory snapshot."} Manual associations are labelled separately. Loaded/running state is unknown without separate telemetry.`,"scope-note"));
  const controls=node("div",undefined,"catalogue-tools"),label=node("label","Search this connection's models"),search=node("input");
  search.type="search";search.value=sourceUi.searches.get(key)||"";label.append(search);
  const filterLabel=node("label","Permission"),filter=node("select");for(const [value,title] of [["all","All"],["allowed","Allowed"],["disallowed","Disallowed"]]){
    const option=node("option",title);option.value=value;filter.append(option);}filter.value=sourceUi.filters.get(key)||"all";filterLabel.append(filter);
  controls.append(label,filterLabel);box.append(controls);
  const selected=new Set(),list=node("div");box.append(list);
  function draw(){sourceUi.searches.set(key,search.value);sourceUi.filters.set(key,filter.value);selected.clear();clean(list);
    const needle=search.value.toLowerCase().trim(),rows=inventory.items.filter(item=>
      (filter.value==="all"||item.allowed===(filter.value==="allowed"))&&
      (item.display_name+" "+item.serving_id+" "+(item.model_ref||"")).toLowerCase().includes(needle));
    list.append(node("p",`Showing ${rows.length} of ${inventory.count} on ${c.connection_id}; permission is independent of readiness and user grants.`,"scope-note"));
    if(!rows.length){list.append(node("p","No matching models for this connection.","empty"));return;}
    const grid=table(["Select","Model / exact ID","Inventory / capability","Allow in EzLLMRouter","Readiness","Price basis","Grants / detail","Action"],rows.map(item=>{
      const check=node("input");check.type="checkbox";check.setAttribute("aria-label","Select "+item.serving_id+" on "+c.display_name);
      check.onchange=()=>check.checked?selected.add(item.serving_id):selected.delete(item.serving_id);
      const detail=item.configuration_ref?namedButton(item.display_name,item.serving_id,()=>catalogueModelDetail(item.configuration_ref)):
        item.model_ref?namedButton(item.display_name,item.serving_id,()=>catalogueModelDetail(item.model_ref)):
        namedButton(item.display_name,item.serving_id,()=>message("This discovered model has no managed deployment yet."));
      const grants=item.configuration_ref?crudButton(`${item.active_grants} active / ${item.grant_count} recorded · detail`,()=>catalogueModelDetail(item.configuration_ref)):
        node("span","No configuration · 0 grants");
      const button=crudButton(item.allowed?"Disallow":"Allow",()=>sourceSetPermission(c,[item],!item.allowed));
      if(state.role!=="registry_admin")button.hidden=true;
      return [check,detail,item.inventory_provenance.replaceAll("_"," ")+" · "+
        (item.capabilities?.join(", ")||"capabilities unknown")+" · "+(item.model_version||"version unknown"),
        badge(item.allowed?"Allowed":"Disallowed"),item.readiness.replaceAll("_"," ")+" · loaded/running unknown",sourcePrice(item),grants,button];}));
    grid.classList.add("source-model-table");list.append(grid);
  }
  search.oninput=draw;filter.onchange=draw;draw();
  if(state.role==="registry_admin"){
    const actions=crudActions(crudButton("Allow selected",()=>sourceSetPermission(c,inventory.items.filter(x=>selected.has(x.serving_id)),true)),
      crudButton("Disallow selected",()=>sourceSetPermission(c,inventory.items.filter(x=>selected.has(x.serving_id)),false)));
    box.append(actions);
  }
  return box;
}
async function sourceRefresh(connection){
  if(!window.confirm(`Refresh inventory for ${connection.display_name} (${connection.connection_id}) using ${connection.adapter_id}? This calls its documented listing API and does not generate model work.`))return;
  try{await api("/operator/v1/provider-probe",{method:"POST",csrf:true,body:{operation_id:crypto.randomUUID(),
    connection_id:connection.connection_id,expected_revision:connection.revision,operation:"inventory"}});
    await render();}catch(error){if(error.staleView)return;message("Inventory refresh rejected: "+error.message,true);}
}
function sourceConnectionSummary(inventory){const c=inventory.connection,box=panel("Connection & credentials · "+c.display_name);
  box.append(definition([["Connection",c.connection_id],["Provider / adapter",c.provider_name+" · "+c.adapter_id],
    ["Account or installation",c.settings.site],["Hosting",c.settings.location],["HTTPS origin",c.settings.origin],
    ["State",c.status],["Credential",c.credential_state==="present"?"Stored · version "+c.credential_version:"Absent"],
    ["Revision",c.revision],["Owner",c.owner],["Funding / environment",c.funding_kind||"Unspecified legacy"]]));
  const actions=crudActions(crudButton("Open connection management",()=>providerDetail(c.connection_id)));
  if(state.role==="registry_admin"&&c.status!=="archived"){
    actions.append(crudButton("Replace credential",()=>providerCredentialForm(c,"replace",()=>sourceDetail())),
      crudButton("Associate model",()=>providerAssociationForm(c,()=>sourceDetail())));
    if(c.credential_state==="present")actions.append(crudButton("Remove credential",()=>providerCredentialForm(c,"remove",()=>sourceDetail())));
    if(c.status==="active")actions.append(crudButton("Disable connection",()=>providerState(c,"disabled",()=>sourceDetail())));
    else if(c.credential_state==="present")actions.append(crudButton("Activate connection",()=>providerState(c,"active",()=>sourceDetail())));
  }box.append(actions);return box;}
async function sourceApiSetup(detail){
  const c=detail.connection,access=providerAccessStatus(c,detail.observations),box=panel("API setup · "+c.display_name);
  box.append(node("p",access.label+" · "+access.detail,"scope-note"));
  box.append(definition([["Provider / API",c.provider_name+" · "+c.adapter_id],
    ["Funding / environment",c.funding_kind==="personal_testing"?"Larry Mitchell · personal live testing":
      c.funding_kind||"Unspecified legacy"],["Owner identity",c.owner],
    ["Credential",c.credential_state==="present"?"Stored · version "+c.credential_version:"Not stored"],
    ["Lifecycle",c.status],["Inference", "Requires exact model permission, caller grant and an active finite allowance"]]));
  box.append(node("p","Save stores the key locally without contacting the provider. Test API access explicitly calls the documented non-generation listing operation; providers may apply quotas or charges. Discover models is a separate explicit listing request. Neither check qualifies paid inference.","scope-note"));
  if(state.role==="registry_admin"&&c.status!=="archived"){
    const actions=crudActions(crudButton(c.credential_state==="present"?"Replace key":"Set up API access",
      ()=>providerCredentialForm(c,"replace",()=>sourceDetail())));
    if(c.credential_state==="present")actions.append(crudButton("Remove key",
      ()=>providerCredentialForm(c,"remove",()=>sourceDetail())));
    actions.append(crudButton("Test API access",()=>sourceCheck(c,"access")),
      crudButton("Discover models",()=>sourceRefresh(c)));
    if(c.status==="active")actions.append(crudButton("Disable setup",()=>providerState(c,"disabled",()=>sourceDetail())));
    box.append(actions);
  }
  if(c.funding_kind==="personal_testing"&&state.principal!=="owner.local"){
    box.append(node("p","The personal testing allowance is managed by its owner.","scope-note"));
  }
  if(c.funding_kind==="personal_testing"&&state.principal==="owner.local"){
    const campaign=await api("/operator/v1/personal-campaign");
    const personal=panel("Personal testing · finite allowance");
    personal.append(node("p","Personally funded live activity is separate from synthetic tests and scripted demos. Activation alone sends nothing. Each run requires an explicit action and normal model permission and caller grant.","scope-note"));
    if(campaign.state!=="not_configured"&&campaign.connection_id===c.connection_id){
      const selected=detail.deployments.find(d=>d.configuration_ref===campaign.configuration_ref);
      personal.append(definition([["Campaign",campaign.effective_state.replaceAll("_"," ")],["Owner", "Larry Mitchell · "+campaign.owner],
        ["Model",selected?selected.serving_id+" · "+campaign.configuration_ref:campaign.configuration_ref],["Authorized caller",campaign.principal_id],
        ["Allowance",campaign.currency+" "+campaign.allowance_decimal],
        ["Recorded cost and accepted exposure",campaign.currency+" "+campaign.incurred_decimal],
        ["Outstanding exposure",campaign.currency+" "+campaign.outstanding_decimal],
        ["Available for another request",campaign.currency+" "+campaign.available_decimal],
        ["Requests",campaign.request_count+" / "+campaign.max_requests],
        ["Per-request ceiling",campaign.currency+" "+campaign.per_request_decimal],
        ["Expiry",campaign.expires_at],["Earlier campaigns retained",campaign.previous_campaigns]]));
      personal.append(node("p","Calculated amounts use provider-reported token counts and the approved EzLLMRouter rate, not an invoice. Unknown cost retains its full reservation. Acknowledging exposure counts the full reservation or higher recorded cost against this allowance; provider usage remains unchanged.","scope-note"));
      if(campaign.attempts.length){const rows=table(["Attempt","Submission","Reserved","Calculated","State","Recovery"],
        campaign.attempts.map(a=>[a.attempt_id,a.submission_id,a.bound_decimal,
          a.cost_decimal??"Unknown",a.state,
          state.role==="registry_admin"&&["paused","closed"].includes(campaign.state)&&["unknown","over_bound"].includes(a.state)?
            crudButton("Acknowledge exposure",()=>sourceAcknowledgeExposure(campaign,a)):"—"]));personal.append(rows);}
      if(campaign.unresolved_prior_attempts?.length){
        personal.append(node("h3","Unresolved exposure from earlier allowances"),table(
          ["Campaign","Attempt","Reserved","Recorded cost","State","Recovery"],
          campaign.unresolved_prior_attempts.map(a=>[a.campaign_id,a.attempt_id,a.bound_decimal,
            a.cost_decimal??"Unknown",a.state,state.role==="registry_admin"&&["unknown","over_bound"].includes(a.state)?
              crudButton("Acknowledge exposure",()=>sourceAcknowledgeExposure(
                {id:a.campaign_id,revision:a.campaign_revision,currency:campaign.currency},a)):"—"])));
      }
      if(state.role==="registry_admin"){
        const actions=crudActions();
        if(campaign.state==="draft"||campaign.state==="paused")actions.append(crudButton("Activate allowance",
          ()=>sourceCampaignAction("active")));
        if(campaign.state==="paused")actions.append(crudButton("Revalidate current setup",
          ()=>sourceCampaignAction("revalidate")));
        if(campaign.state==="active")actions.append(crudButton("Pause allowance",
          ()=>sourceCampaignAction("paused")));
        if(campaign.state!=="closed")actions.append(crudButton("Close allowance",
          ()=>sourceCampaignAction("closed")));
        if(campaign.attempts.length)actions.append(crudButton("Reconcile recorded usage",
          ()=>sourceCampaignAction("reconcile")));
        if(campaign.effective_state==="active"){
          const deployment=detail.deployments.find(d=>d.configuration_ref===campaign.configuration_ref);
          if(deployment)actions.append(crudButton("Run one live test",
            ()=>providerValidationForm(c,deployment,campaign)));
        }
        personal.append(actions);
      }
      if(campaign.state==="closed"&&state.role==="registry_admin")personal.append(
        crudActions(crudButton("Configure new allowance",()=>sourceCampaignForm(c,detail.deployments))));
    }else{
      personal.append(node("p",campaign.state==="not_configured"?"No allowance configured; paid requests are blocked.":
        "The one personal campaign belongs to another setup; this setup cannot bypass it.","empty"));
      if(state.role==="registry_admin"&&campaign.state==="not_configured")personal.append(
        crudActions(crudButton("Configure allowance",()=>sourceCampaignForm(c,detail.deployments))));
    }
    box.append(personal);
  }
  return box;
}
function sourceCampaignForm(connection,deployments){
  const choices=deployments.filter(d=>d.configuration_ref).map(d=>[d.configuration_ref,
    d.serving_id+" · "+d.configuration_ref]);
  if(!choices.length){message("Associate an exact deployment and approve its rate first.",true);return;}
  const form=crudForm("Configure finite personal testing allowance",[
    {name:"configuration_ref",label:"Exact model deployment",options:[["","Choose a model"],...choices]},
    {name:"currency",label:"Billing currency",options:[["","Choose currency"],["USD","USD · supported rate schedules"]]},
    {name:"allowance_decimal",label:"Total finite allowance · decimal amount"},
    {name:"per_request_decimal",label:"Maximum amount per request · decimal amount"},
    {name:"max_requests",label:"Maximum request count",type:"number",min:1},
    {name:"max_input_bytes",label:"Maximum serialized input bytes (1–4096)",type:"number",min:1},
    {name:"max_output_tokens",label:"Maximum output tokens, including reasoning (1–4096)",type:"number",min:1},
    {name:"expires_at",label:"Expiry in your local time",type:"datetime-local"}],
    "Save disabled allowance",()=>sourceDetail(),async v=>{
      await api("/operator/v1/personal-campaign",{method:"POST",csrf:true,body:{action:"configure",configuration:{
        connection_id:connection.connection_id,configuration_ref:v.configuration_ref,principal_id:"owner.local",
        currency:v.currency,allowance_decimal:v.allowance_decimal,per_request_decimal:v.per_request_decimal,
        max_requests:Number(v.max_requests),max_input_bytes:Number(v.max_input_bytes),
        max_output_tokens:Number(v.max_output_tokens),expires_at:new Date(v.expires_at).toISOString()}}});
    });
  form.box.insertBefore(node("p","This saves a draft only. Select the exact approved deployment, caller grant, currency and limits before activating. No provider call runs on save or activation.","scope-note"),form.box.firstChild);
  crudOpen(form);
}
function sourceAcknowledgeExposure(campaign,attempt){
  if(!window.confirm(`Count the unresolved charge for ${attempt.attempt_id} against ${campaign.id}? The full reservation (${campaign.currency} ${attempt.bound_decimal}) or higher recorded cost (${attempt.cost_decimal??"unknown"}) stays charged to this allowance. Provider usage remains unchanged; this sends no provider request.`))return;
  const form=crudForm("Acknowledge unresolved exposure",[{name:"reason",label:"Reason for accepting this exposure"}],
    "Acknowledge exposure",()=>sourceDetail(),async values=>{
      await api("/operator/v1/personal-campaign",{method:"POST",csrf:true,body:{
        action:"acknowledge_exposure",campaign_id:campaign.id,attempt_id:attempt.attempt_id,
        expected_revision:campaign.revision,reason:values.reason}});
    });
  form.box.append(node("p","The possible charge remains counted against this allowance. This records your reason and retains the attempt and its usage history.","scope-note"));
  crudOpen(form);
}
async function sourceCampaignAction(action){
  if(!window.confirm(`${action==="active"?"Activate":action==="paused"?"Pause":
    action==="reconcile"?"Reconcile recorded usage for":action==="revalidate"?"Revalidate":"Close"} this finite allowance? This operation sends no provider request; each live test needs a separate explicit action.`))return;
  try{await api("/operator/v1/personal-campaign",{method:"POST",csrf:true,body:{action}});
    await render();}catch(error){if(error.staleView)return;message("Allowance action rejected: "+error.message,true);}
}
async function sourceCheck(connection,operation){
  if(!window.confirm(`Run ${operation} check for ${connection.display_name} (${connection.connection_id}) via ${connection.adapter_id}? This makes an authenticated model-list GET, with possible provider quota or account effects. It performs no generation; EzLLMRouter records no model charge for it.`))return;
  try{await api("/operator/v1/provider-probe",{method:"POST",csrf:true,body:{operation_id:crypto.randomUUID(),
    connection_id:connection.connection_id,expected_revision:connection.revision,operation}});
    await render();}catch(error){if(error.staleView)return;message("Check rejected: "+error.message,true);}
}
function sourceHealth(detail){const box=panel("Health · stored observations");box.append(node("p","Provider incident status, credential acceptance, service reachability and model readiness are separate. Missing or stale telemetry is unknown.","scope-note"));
  box.append(detail.observations.length?table(["Operation / scope","State / reason","Observed","Expires"],
    detail.observations.map(o=>[o.operation+" · "+o.scope,o.state+" · "+o.reason.replaceAll("_"," "),
      o.observed_at,o.expires_at])):node("p","No scoped observations. Never run.","empty"));
  if(state.role==="registry_admin")box.append(crudActions(
    crudButton("Test access",()=>sourceCheck(detail.connection,"access")),
    crudButton("Check readiness",()=>sourceCheck(detail.connection,"readiness"))));return box;}
function sourceHistory(detail){const box=panel("History · connection and discovery");
  box.append(detail.history.length?table(["Action","Actor","Time","Authority"],detail.history.map(h=>[
    h.action,h.actor,h.at,h.authority_revision])):node("p","No management history.","empty"));
  box.append(detail.observations.length?table(["Discovery / check","Result","Time"],detail.observations.map(o=>[
    o.operation,o.state+" · "+o.reason,o.observed_at])):node("p","No discovery attempts.","empty"));return box;}
async function sourceConnectionPage(connectionId,compact=false){
  const [inventory,detail]=await Promise.all([api("/operator/v1/connections/"+encodeURIComponent(connectionId)+"/inventory"),
    api("/operator/v1/connections/"+encodeURIComponent(connectionId))]);
  const c=inventory.connection,root=$("view-content");
  if(compact){root.append(sourceModelsPanel(inventory,{compact:true}),crudActions(crudButton("Connection details & health",()=>sourceGo(sourceConnectionRoute(c)))));return;}
  $("view-title").textContent=c.display_name;
  const parent=sourceKind(c)==="source_providers"?"#/providers/"+encodeURIComponent(c.provider_id):
    sourceKind(c)==="source_labs"?"#/office-labs/"+encodeURIComponent(c.settings.site):"#/source_private";
  root.append(sourceBreadcrumb([[sourceSections[sourceKind(c)],"#/"+sourceKind(c)],
    ...(sourceKind(c)!=="source_private"?[[sourceKind(c)==="source_labs"?c.settings.site:c.provider_name,parent]]:[]),
    [c.display_name,null]]));
  const tabs=crudActions(),tab=sourceUi.tabs.get(connectionId)||
    (sourceKind(c)==="source_providers"?"api_setup":"models");
  for(const [key,label] of [["api_setup","API setup"],["models","Models"],["usage","Usage & Costs"],["connection","Connection & Credentials"],["health","Health"],["history","History"]]){
    const button=crudButton(label,()=>{if(!confirmViewLeave())return;sourceUi.tabs.set(connectionId,key);render();},key===tab?"action":"quiet");
    button.setAttribute("aria-current",key===tab?"page":"false");tabs.append(button);}root.append(tabs);
  if(tab==="api_setup")root.append(await sourceApiSetup(detail));
  else if(tab==="models"){
    root.append(sourceModelsPanel(inventory));
    if(state.role==="registry_admin")root.append(crudActions(crudButton("Refresh inventory",()=>sourceRefresh(c))));
  }else if(tab==="usage")root.append(await sourceConnectionCost(c));
  else if(tab==="connection")root.append(sourceConnectionSummary(inventory));
  else if(tab==="health")root.append(sourceHealth(detail));
  else root.append(sourceHistory(detail));
}
async function sourceDetail(){const route=sourceRoute(),root=$("view-content");clean(root);
  if(!route||route.view!=="source_detail")return;
  const connections=(await api("/operator/v1/connections")).items;
  if(route.section==="source_providers"){
    const own=connections.filter(c=>sourceKind(c)==="source_providers"&&c.provider_id===route.provider);
    if(route.connectionId){if(!own.some(c=>c.connection_id===route.connectionId))throw Error("Connection is outside this provider");
      return sourceConnectionPage(route.connectionId);}
    $("view-title").textContent=own[0]?.provider_name||sourceVendor[route.provider]||route.provider;
    root.append(sourceBreadcrumb([["Providers","#/source_providers"],[$("view-title").textContent,null]]));
    if(state.role==="registry_admin"){
      const adapter=own[0]?.adapter_id||providerAdapters.find(([id])=>providerId(id)===route.provider)?.[0];
      if(adapter)root.append(crudActions(crudButton("Add account / connection",()=>providerForm(adapter,
        {location:"commercial",returnToSource:true}),"action")));}
    const detail=await Promise.all(own.map(c=>api("/operator/v1/connections/"+encodeURIComponent(c.connection_id))));
    const box=panel("API setups · accounts and projects");box.append(own.length?table(["API setup","Account / project","API profile","Access check","State"],
      own.map((c,index)=>{const status=providerAccessStatus(c,detail[index].observations);return [sourceConnectionLink(c),
        c.settings.site+(c.settings.project?" · "+c.settings.project:""),c.adapter_id,status.label+" · "+status.detail,badge(c.status)];})):
      node("p","Not set up. Set up API access above; reference records below are not authenticated discovery.","empty"));root.append(box);
    root.append(await sourceProviderCost(route.provider));
    const models=(await api("/operator/v1/models")).items;root.append(sourceReferencePanel(models,route.provider));return;
  }
  if(route.section==="source_private"){
    const c=connections.find(item=>item.connection_id===route.connectionId&&sourceKind(item)==="source_private");
    if(!c)throw Error("Private installation unavailable");return sourceConnectionPage(c.connection_id);
  }
  const own=connections.filter(c=>sourceKind(c)==="source_labs"&&c.settings.site===route.site);
  if(route.connectionId){if(!own.some(c=>c.connection_id===route.connectionId))throw Error("Connection is outside this lab");
    return sourceConnectionPage(route.connectionId);}
  $("view-title").textContent=route.site;
  root.append(sourceBreadcrumb([["Office Labs","#/source_labs"],[route.site,null]]),
    node("p",`${own.length} registered nodes / pools at this lab. Each model and permission below belongs to its named connection. Supported inventory does not establish loaded or running state.`,"scope-note"));
  if(state.role==="registry_admin")root.append(crudActions(crudButton("Register serving connection",()=>providerForm(
    "vllm.openai-compatible.v1",{location:"office_lab",site:route.site,returnToSource:true}),"action")));
  for(const c of own)await sourceConnectionPage(c.connection_id,true);
}
