"use strict";
// Presentation uses the live registry API. Reference prices never enter dispatch accounting.
const catalogueState = {showTestModels:false, showTestUsers:false};
const isTestModel = model => model.kind !== "real_catalogue" && model.kind !== "provider_deployment";
const isTestUser = principal => principal.principal_id !== "owner.local";
const money = value => value === undefined || value === null ? "Unknown" : "$" + value;
const primaryRates = model => model.catalogue?.price_reference?.bands?.[0]?.rates_usd_per_1000000_tokens;
const smallLine = value => node("small", value, "secondary-line mono");
function conditionText(condition){
  const parts=[];
  if(condition.prompt_tokens_lte!==undefined)parts.push("Prompt ≤"+Number(condition.prompt_tokens_lte).toLocaleString()+" tokens");
  if(condition.prompt_tokens_gt!==undefined)parts.push("Prompt >"+Number(condition.prompt_tokens_gt).toLocaleString()+" tokens");
  if(condition.input_tokens_lte!==undefined)parts.push("Input ≤"+Number(condition.input_tokens_lte).toLocaleString()+" tokens");
  if(condition.input_tokens_gt!==undefined)parts.push("Input >"+Number(condition.input_tokens_gt).toLocaleString()+" tokens");
  if(condition.rate_period)parts.push(condition.rate_period==="off_peak"?"Off-peak":"Peak");
  if(condition.weekday_intervals)parts.push("UTC weekdays "+condition.weekday_intervals.join(", "));
  if(condition.exclude)parts.push("Excludes "+condition.exclude);
  if(condition.definition)parts.push(condition.definition);
  if(condition.publisher_date_through)parts.push("Published rate through "+condition.publisher_date_through);
  if(condition.cutover_timezone)parts.push("Cutover timezone: "+condition.cutover_timezone.replaceAll("_"," "));
  if(condition.calendar_and_exact_interval_boundary_resolution)parts.push("Exact calendar boundaries require provider billing semantics");
  return parts.length?parts.join(" · "):"Standard published reference";
}
function testToggle(label,count,value,callback){
  const row=node("label",undefined,"test-toggle"),box=node("input");box.type="checkbox";box.checked=value;
  box.addEventListener("change",()=>callback(box.checked));row.append(box,node("span",label+" ("+count+")"));return row;
}
function namedButton(label,subtitle,callback){
  const wrap=node("div",undefined,"named-cell"),button=node("button",label);button.type="button";button.onclick=callback;
  wrap.append(button,smallLine(subtitle));return wrap;
}
function copyControl(label,value){
  const row=node("div",undefined,"copy-row"),button=node("button","Copy","quiet");button.type="button";
  button.onclick=async()=>{try{await navigator.clipboard.writeText(value);message(label+" copied.");}catch(error){if(error.staleView)return;message("Copy unavailable: "+error.message,true);}};
  row.append(node("span",label+": "+value,"mono"),button);return row;
}
models = async function catalogueModels(){
  const root=$("view-content"),data=await api("/operator/v1/models"),all=data.items;
  const tests=all.filter(isTestModel).length,reals=all.length-tests;
  const tools=node("div",undefined,"catalogue-tools"),filter=node("label","Search names, vendors, API IDs or references"),search=node("input");
  search.type="search";search.value=state.modelSearch;search.oninput=draw;filter.append(search);
  tools.append(filter,testToggle("Show test fixtures",tests,catalogueState.showTestModels,value=>{catalogueState.showTestModels=value;draw();}));
  root.append(tools);const list=panel("Published model catalogue");root.append(list);
  function draw(){
    state.modelSearch=search.value;const needle=search.value.trim().toLowerCase();
    const found=all.filter(m=>(catalogueState.showTestModels||!isTestModel(m))&&
      [m.display_name,m.catalogue?.vendor,m.catalogue?.family,m.catalogue?.published_api_model_id,m.configuration_ref,
       m.destination?.model].join(" ").toLowerCase().includes(needle));
    clean(list);list.append(node("h2","Published model catalogue"),node("p",`Showing ${found.length} of ${reals} researched models${catalogueState.showTestModels?` and ${tests} test configurations`: `; ${tests} test configurations hidden`}. Published list rates are USD per 1,000,000 tokens.`,"scope-note"));
    if(!found.length){list.append(node("p","No matching records. Clear search or include test fixtures.","empty"));return;}
    list.append(table(["Model","Vendor / family","Input / 1M","Output / 1M","Cached input / 1M","Condition / checked","State"],found.map(m=>{
      const c=m.catalogue,rate=primaryRates(m),first=c?.price_reference?.bands?.[0];
      return [namedButton(m.display_name,c?c.published_api_model_id:m.configuration_ref,()=>catalogueModelDetail(m.configuration_ref)),
        c?c.vendor+" · "+c.family:"Synthetic test fixture",
        rate?money(rate.input_uncached):m.current_price?money(m.current_price.rates.input_uncached):"Unpriced",
        rate?money(rate.output):m.current_price?money(m.current_price.rates.output_text):"Unpriced",
        rate?money(rate.input_cached):"Unknown",
        c?first.label+(c.price_reference.bands.length>1?" · "+c.price_reference.bands.length+" bands":"")+" · checked "+c.price_reference.verified_on:"Synthetic fixture price",
        badge(c?(m.status==="catalogued"?"Catalogued · Not connected":m.status+" · Not connected"):"Test fixture · "+m.status)];})));
  }
  draw();
  if(state.role==="registry_admin"&&catalogueState.showTestModels){
    root.append(entryForm("Register a synthetic test configuration",[{name:"ref",label:"Configuration reference"},{name:"display_name",label:"Display name"},{name:"model",label:"Exact synthetic model",options:["model.demo","model.demo.alt"]},{name:"model_version",label:"Model version",value:"v1"},{name:"owner",label:"Owner",value:"owner.local"},{name:"capabilities",label:"Capabilities",value:"text,tools"},{name:"purposes",label:"Purposes",value:"execution"},{name:"task_classes",label:"Task classes",value:"class.demo"}],"Create draft",async v=>registryChange("create_model",v.ref,0,{display_name:v.display_name,model:v.model,model_version:v.model_version,owner:v.owner,capabilities:listValue(v.capabilities),purposes:listValue(v.purposes),task_classes:listValue(v.task_classes)})));
  }
};
async function catalogueModelDetail(ref){
  clean($("view-content"));$("view-title").textContent="Model & pricing detail";message("Loading catalogue record…");
  try{
    const data=await api("/operator/v1/models/"+encodeURIComponent(ref)),m=data.model,root=$("view-content"),c=m.catalogue;
    root.append(actionButton("← Models & Pricing",async()=>{state.view="models";}));
    if(c){
      const info=panel(m.display_name+" · "+c.vendor);info.append(node("p",m.status+" · Not connected. Published direct-provider API references; no live route, credential or active EzLLMRouter billing schedule.","scope-note"));
      info.append(definition([["Family",c.family],["Published API ID",c.published_api_model_id],["Configuration reference",m.configuration_ref],["Serving version",c.observed_serving_version||"Not established"],["Identifier status",c.identifier_pin_status],["Provider route basis",c.provider_route_basis],["Context advertised",c.provider_published_limits?.context_window_advertised||"Unknown"],["Maximum output advertised",c.provider_published_limits?.max_output_advertised||"Unknown"],["Research checked",c.price_reference.verified_on],["Price snapshot",c.price_reference.snapshot_id],["Runtime",data.readiness],["State",m.status]]));root.append(info);
      info.append(copyControl("Published API ID",c.published_api_model_id),copyControl("Configuration reference",m.configuration_ref),copyControl("Price snapshot",c.price_reference.snapshot_id));
      const pricing=panel("Published reference rates · USD per 1,000,000 tokens");
      pricing.append(table(["Band","Uncached input","Output","Cached input","Conditions"],c.price_reference.bands.map(b=>[b.label,money(b.rates_usd_per_1000000_tokens.input_uncached),money(b.rates_usd_per_1000000_tokens.output),money(b.rates_usd_per_1000000_tokens.input_cached),conditionText(b.conditions)])));
      for(const band of c.price_reference.bands){
        const extra=Object.entries(band.rates_usd_per_1000000_tokens).filter(([key])=>!["input_uncached","output","input_cached"].includes(key));
        if(extra.length)pricing.append(node("p",band.label+" additional published token rates: "+extra.map(([key,value])=>key.replaceAll("_"," ")+" "+money(value)).join(" · ")+" per 1,000,000 tokens.","scope-note"));
        if(band.additional_rates)pricing.append(node("p",band.label+" additional rates: "+Object.entries(band.additional_rates).map(([key,value])=>key.replaceAll("_"," ")+" "+money(value)).join(" · ")+".","scope-note"));
        if(band.calculation_basis)pricing.append(node("p",band.label+" calculation: "+band.calculation_basis,"scope-note"));
      }
      pricing.append(node("p","Cached input is a separate category. Cache writes, storage and tool charges are not folded into the three primary token columns. Rates are public list references, not customer invoices.","scope-note"));
      const future=c.price_reference.announced_future_reference;if(future)pricing.append(node("p","Announced later reference: "+JSON.stringify(future)+". No automatic price change is scheduled.","scope-note"));
      root.append(pricing);
      const sources=panel("Sources and notes");for(const source of m.source_links){const link=node("a",source.title+" · checked "+source.checked_on+" · "+source.url);link.href=source.url;link.target="_blank";link.rel="noopener noreferrer";sources.append(link,copyControl("Source URL",source.url));}for(const note of c.notes||[])sources.append(node("p",note));root.append(sources);
      if(state.role==="registry_admin")root.append(entryForm("Edit display name",[{name:"display_name",label:"Display name",value:m.display_name}],"Save display name",v=>registryChange("edit_model",ref,m.revision,{display_name:v.display_name})));
    }else{
      const info=panel(m.display_name+" · synthetic test fixture");info.append(definition([["Reference",m.configuration_ref],["Exact synthetic model",m.destination.model],["State",m.status],["Readiness",data.readiness],["Revision",m.revision]]));root.append(info);
      const prices=panel("Synthetic price history");prices.append(data.prices.length?table(["Version","Input / 1M","Output / 1M","Source"],data.prices.map(p=>[p.price_version,money(p.rates.input_uncached),money(p.rates.output_text),p.source])):node("p","Legacy fixture is unpriced.","empty"));root.append(prices);
      if(state.role==="registry_admin"){
        root.append(entryForm("Edit display name",[{name:"display_name",label:"Display name",value:m.display_name}],"Save display name",v=>registryChange("edit_model",ref,m.revision,{display_name:v.display_name})));
        root.append(entryForm("Publish synthetic price",[{name:"price_version",label:"Immutable price version"},{name:"input_uncached",label:"USD per million uncached input tokens",value:"2"},{name:"output_text",label:"USD per million output tokens",value:"8"}],"Publish price",v=>registryChange("publish_price",ref,m.revision,{price_version:v.price_version,currency:"USD",rates:{input_uncached:v.input_uncached,output_text:v.output_text},source:"synthetic fixture",usage_semantics_version:"synthetic.text.v1"})));
        const actions=node("div",undefined,"actions");for(const status of ["enabled","disabled","revoked"]){if(status===m.status||m.status==="revoked")continue;actions.append(actionButton(status==="enabled"?"Enable":status==="disabled"?"Disable":"Revoke",()=>registryChange("model_state",ref,m.revision,{status,reason:"Local administrator change"}),status==="enabled"?"":"Confirm "+status+" of "+ref+"?"));}root.append(actions);
      }
    }
    const history=panel("Change history");history.append(data.history.length?table(["Actor","Action","Authority","Time"],data.history.map(h=>[h.actor,h.action,h.authority_revision,h.at])):node("p","No changes recorded.","empty"));root.append(history);message("");
  }catch(error){if(error.staleView)return;message("Catalogue record unavailable: "+error.message,true);}
}
users = async function catalogueUsers(){
  const root=$("view-content"),data=await api("/operator/v1/principals"),all=data.items,tests=all.filter(isTestUser).length;
  const tools=node("div",undefined,"catalogue-tools"),filter=node("label","Search names or stable IDs"),search=node("input");search.type="search";search.value=state.userSearch;search.oninput=draw;filter.append(search);
  tools.append(filter,testToggle("Show test fixtures",tests,catalogueState.showTestUsers,value=>{catalogueState.showTestUsers=value;draw();}));root.append(tools);
  const list=panel("People and services");root.append(list);
  function draw(){state.userSearch=search.value;const needle=search.value.trim().toLowerCase();const found=all.filter(p=>(catalogueState.showTestUsers||!isTestUser(p))&&[p.display_name,p.principal_id,p.kind,p.role,p.status].join(" ").toLowerCase().includes(needle));
    clean(list);list.append(node("h2","People and services"),node("p",`Showing ${found.length} of ${all.length-tests} owner identities${catalogueState.showTestUsers?` and ${tests} test identities`: `; ${tests} test identities hidden`}.`,"scope-note"));
    list.append(found.length?table(["Name","Kind / role","Status","Granted models","Usability"],found.map(p=>{
      const active=(p.grant_summary||[]).filter(g=>g.status==="active");return [namedButton(p.display_name,p.principal_id,()=>catalogueUserDetail(p.principal_id)),
        p.kind+" · "+p.role,badge(p.status),active.length?active.map(g=>g.display_name).join(", "):"No active grants",
        active.length?active.every(g=>g.readiness==="synthetic_http1_ready")?"Synthetic transport ready":"Grant does not establish a connected route":"No granted route"];})):node("p","No matching identities. Clear search or include test fixtures.","empty"));
  }draw();
  if(state.role==="registry_admin"&&catalogueState.showTestUsers)root.append(entryForm("Register an unbound test identity",[{name:"id",label:"Stable principal ID"},{name:"display_name",label:"Display name"},{name:"kind",label:"Kind",options:["service","human"]},{name:"owner",label:"Responsible owner",value:"team.demo"}],"Create inactive identity",v=>registryChange("create_principal",v.id,0,{display_name:v.display_name,kind:v.kind,owner:v.owner})));
};
async function catalogueUserDetail(id){
  clean($("view-content"));$("view-title").textContent="User & access detail";message("Loading identity…");
  try{
    const data=await api("/operator/v1/principals/"+encodeURIComponent(id)),p=data.principal,root=$("view-content");root.append(actionButton("← Users & Access",async()=>{state.view="users";}));
    const info=panel(p.display_name);info.append(definition([["Stable ID",p.principal_id],["Kind",p.kind],["Role",p.role],["Status",p.status],["Credential",p.credential_state],["Owner",p.owner],["Revision",p.revision],["Record scope",id==="owner.local"?"Existing owner":"Test identity"]]));root.append(info);
    const grants=panel("Explicit grants and transport");grants.append(data.grants.length?table(["Model","Grant","Runtime","Scope"],data.grants.map(g=>[namedButton(g.display_name,g.configuration_ref,()=>catalogueModelDetail(g.configuration_ref)),g.status,g.readiness,g.purposes.join(", ")+" · "+g.task_classes.join(", ")])):node("p","No grants. Registration and display names do not confer access.","empty"));root.append(grants);
    const history=panel("Change history");history.append(data.history.length?table(["Actor","Action","Authority","Time"],data.history.map(h=>[h.actor,h.action,h.authority_revision,h.at])):node("p","No changes recorded.","empty"));root.append(history);
    const explain=entryForm("Explain access (read only)",[{name:"configuration_ref",label:"Configuration reference",value:data.grants[0]?.configuration_ref||"cfg.demo"},{name:"purpose",label:"Purpose",value:"execution"},{name:"task_class",label:"Task class",value:"class.demo"}],"Explain",async v=>{const q=new URLSearchParams({principal_id:id,...v});const result=await api("/operator/v1/access/explain?"+q);message((result.allowed?"Allowed":"Denied")+": "+result.reason+" · authority revision "+result.authority_revision);return false;});root.append(explain);
    if(state.role==="registry_admin"){
      root.append(entryForm("Edit display name",[{name:"display_name",label:"Display name",value:p.display_name}],"Save display name",v=>registryChange("edit_principal",id,p.revision,{display_name:v.display_name})));
      if(p.kind==="human")root.append(entryForm("Console role",[{name:"role",label:"Role",options:["ordinary","read_only_operator","registry_admin"]}],"Change role",v=>registryChange("set_role",id,p.revision,{role:v.role})));
      root.append(entryForm("Set exact model grant",[{name:"configuration_ref",label:"Configuration reference",value:"cfg.demo"},{name:"status",label:"Grant state",options:["active","removed"]},{name:"expected",label:"Current grant revision (0 if absent)",value:"0"},{name:"purposes",label:"Permitted purposes",value:"execution"},{name:"task_classes",label:"Task classes",value:"class.demo"}],"Commit grant",v=>registryChange("set_grant",id,Number(v.expected),{configuration_ref:v.configuration_ref,status:v.status,purposes:listValue(v.purposes),task_classes:listValue(v.task_classes)})));
      const actions=node("div",undefined,"actions");if(p.credential_state!=="local_operator"&&p.status!=="revoked"){
        const provision=node("button","Generate one-time credential","quiet");provision.type="button";provision.onclick=async()=>{if(!window.confirm("Replace the existing credential for "+id+"?"))return;provision.disabled=true;try{const result=await api("/operator/v1/provision",{method:"POST",csrf:true,body:{operation_id:crypto.randomUUID(),principal_id:id,expected_revision:p.revision}});if(result.one_time_credential){const output=node("p","One-time credential (copy to a private file now): "+result.one_time_credential,"credential-once mono");output.tabIndex=-1;root.append(output);output.focus();}}catch(error){if(error.staleView)return;message("Provisioning failed: "+error.message,true);}finally{provision.disabled=false;}};actions.append(provision);
      }
      for(const status of ["active","suspended","revoked"]){if(status===p.status||p.status==="revoked")continue;actions.append(actionButton(status==="active"?"Activate":status==="suspended"?"Suspend":"Revoke",()=>registryChange("principal_state",id,p.revision,{status,reason:"Local administrator change"}),status==="active"?"":"Confirm "+status+" for "+id+"?"));}root.append(actions);
    }
    message("");
  }catch(error){if(error.staleView)return;message("Identity unavailable: "+error.message,true);}
}
