"use strict";

const userRoles={registry_admin:"Administrator",read_only_operator:"Read-only",ordinary:"User"};
const userPermissionNames={"activity.read_all":"View all activity","activity.read_own":"View own activity",
  "reports.read_all":"View reports","registry.read":"View registered resources","settings.read":"View settings",
  "users.manage":"Manage users","registry.manage":"Manage identities and model grants",
  "connections.manage":"Manage connections","models.read_allowed":"View permitted models",
  "models.use_granted":"Use explicitly granted models"};
const originalIdentityUsers=users;
const accountUi={search:"",mustChange:false};

function accountChangePassword(required=false){
  invalidateView();document.title="Change password · EzLLMRouter";if($("skip-link"))$("skip-link").hidden=true;
  accountUi.mustChange=required;
  $("workspace").hidden=true;$("login-view").hidden=true;$("password-view").hidden=false;
  $("account-button").hidden=true;$("logout").hidden=false;
  $("password-cancel").hidden=required;
  $("password-note").textContent=required?
    "Change your temporary password before continuing. Choose 12 to 256 characters. You will sign in again afterward.":
    "Choose 12 to 256 characters. Updating your password signs out all your sessions.";
  $("password-error").hidden=true;
  for(const id of ["current-password","new-password","confirm-password"])$(id).value="";
  $("current-password").focus();
}

async function applyConsoleSession(reply){
  state.csrf=reply.csrf;state.role=reply.role;state.principal=reply.principal_id;
  state.username=reply.username;state.userManagement=reply.user_management;
  state.permissions=reply.permissions||[];
  if(reply.must_change_password){accountChangePassword(true);return;}
  accountUi.mustChange=false;
  const integrationOnly=window.location.pathname==="/integration",ordinary=reply.role==="ordinary";
  const allowed=integrationOnly?
    ordinary?["users"]:reply.role==="read_only_operator"?["accounting","local_connectors","diagnostics","users"]:[...integrationViews]:
    ordinary?["overview","activity","usage","models","users"]:
      Object.keys(titles).filter(view=>!["connections","accounting","diagnostics"].includes(view));
  const requested=integrationOnly?integrationRoute().view:sourceRoute()?.view;
  state.view=allowed.includes(requested)?requested:integrationOnly?
    ordinary?"users":reply.role==="read_only_operator"?"accounting":"connections":ordinary?"models":"source_providers";
  for(const button of document.querySelectorAll("#navigation button"))button.hidden=!allowed.includes(button.dataset.view);
  $("password-view").hidden=true;$("account-button").hidden=!state.userManagement;
  $("account-button").textContent="Change password · "+(reply.username||"Account");
  showWorkspace();await render();
}

function userAccountFields(record){return [
  {name:"username",label:"Username · 3–64 letters, digits, dots, underscores or hyphens",value:record?.username||"",maxLength:64},
  {name:"display_name",label:"Full name",value:record?.display_name||""},
  {name:"role",label:"Role",options:Object.entries(userRoles),value:record?.role||"ordinary"},
  {name:"status",label:"Account status",options:[["active","Enabled"],["suspended","Disabled"]],value:record?.status||"active"}];}

function userSecretFields(){return [
  {name:"password",label:"Temporary password · 12–256 characters",type:"password",minLength:12,maxLength:256},
  {name:"password_confirm",label:"Confirm temporary password",type:"password",minLength:12,maxLength:256}];}

function userAccountForm(record=null){
  let signInAgain=false;
  const back=saved=>saved&&signInAgain?showLogin("Account updated. Sign in again."):render();
  const form=crudForm(record?"Edit user":"Create user",[...userAccountFields(record),...(!record?userSecretFields():[])],
    record?"Save user":"Create user",back,async values=>{
      const data=Object.fromEntries(["username","display_name","role","status"].map(key=>[key,values[key]]));
      if(!record){
        if(values.password!==values.password_confirm)throw Error("Passwords do not match.");
        data.password=values.password;
      }else data.expected_revision=record.revision;
      await api("/operator/v1/users"+(record?"/"+encodeURIComponent(record.principal_id):""),
        {method:"POST",body:data,csrf:true});
      signInAgain=record?.principal_id===state.principal&&["username","role","status"].some(key=>values[key]!==record[key]);
    });
  form.box.append(node("p","New users receive only their role's permissions. Model use requires separate model grants. Temporary passwords must be changed at sign-in.","scope-note"));
  crudOpen(form);
}

function userResetPassword(record){
  if(record.principal_id===state.principal){accountChangePassword();return;}
  const form=crudForm("Reset password for "+record.username,userSecretFields(),"Reset password",()=>render(),async values=>{
    if(values.password!==values.password_confirm)throw Error("Passwords do not match.");
    await api("/operator/v1/users/"+encodeURIComponent(record.principal_id)+"/password",{method:"POST",csrf:true,
      body:{password:values.password,expected_revision:record.revision}});
  });
  form.box.append(node("p","This signs out the user's existing sessions. They must change this temporary password on their next sign-in.","scope-note"));
  crudOpen(form);
}

async function userDeleteAccount(record){
  if(!window.confirm(`Delete user ${record.username}? Sign-in and access will be revoked. Existing usage and audit history will be retained.`))return;
  try{
    await api("/operator/v1/users/"+encodeURIComponent(record.principal_id),{method:"DELETE",csrf:true,
      body:{expected_revision:record.revision}});
    if(record.principal_id===state.principal)showLogin("Your account was deleted.");
    else await render();
  }catch(error){if(error.staleView)return;message("Deletion failed: "+error.message,true);}
}

function userPermissions(record){
  const box=node("details"),summary=node("summary","Effective permissions");box.append(summary);
  const list=node("ul");for(const permission of record.permissions||[])
    list.append(node("li",userPermissionNames[permission]||permission));
  box.append(list);return box;
}

async function accountUsers(){
  if(!state.userManagement){await originalIdentityUsers();return;}
  const root=$("view-content");
  if(state.role!=="registry_admin"){
    const panelRoot=panel("Your account");panelRoot.append(definition([["Username",state.username],
      ["Role",userRoles[state.role]]]),userPermissions({permissions:state.permissions}),
      crudButton("Change password",()=>accountChangePassword()));root.append(panelRoot);return;
  }
  const listing=await api("/operator/v1/users"),items=listing.items;
  const toolbar=crudActions(crudButton("Create user",()=>userAccountForm(),"action"),
    crudButton("Service identities & model grants",async()=>{clean(root);await originalIdentityUsers();}));
  root.append(toolbar,node("p","Administrators manage accounts and permissions. Read-only users inspect reports and settings. Users see their own activity and explicitly permitted models.","scope-note"));
  const label=node("label","Search users"),search=node("input");search.type="search";search.value=accountUi.search;
  label.append(search);root.append(label);
  const list=panel("User accounts");root.append(list);
  const onlyAdmin=items.filter(user=>user.role==="registry_admin"&&user.status==="active").length===1;
  function draw(){
    clean(list);list.append(node("h2","User accounts"));const query=accountUi.search.toLowerCase();
    const found=items.filter(record=>[record.username,record.display_name,userRoles[record.role],record.status].join(" ").toLowerCase().includes(query));
    list.append(found.length?table(["Username","Full name","Role","Status","Permissions","Actions"],found.map(record=>{
      const last=onlyAdmin&&record.role==="registry_admin"&&record.status==="active";
      const remove=crudButton("Delete",()=>userDeleteAccount(record));remove.disabled=last;
      if(last)remove.title="The last active administrator must remain available.";
      return [record.username,record.display_name,userRoles[record.role],record.status==="active"?"Enabled":"Disabled",
        userPermissions(record),crudRowActions(crudButton("Edit",()=>userAccountForm(record)),
          crudButton(record.principal_id===state.principal?"Change password":"Reset password",()=>userResetPassword(record)),
          crudButton("Model access",async()=>{try{await crudGrantForm(record);}catch(error){if(error.staleView)return;message("Model access unavailable: "+error.message,true);}}),remove)];
    })):node("p","No matching users.","empty"));
  }
  search.oninput=()=>{accountUi.search=search.value;draw();};draw();
}
users=accountUsers;
titles.users="Users & Permissions";

$("account-button").addEventListener("click",()=>{if(crudConfirmLeave()){crudState.dirty=false;accountChangePassword();}});
$("password-cancel").addEventListener("click",()=>{
  if(accountUi.mustChange)return;
  for(const id of ["current-password","new-password","confirm-password"])$(id).value="";
  $("password-view").hidden=true;$("account-button").hidden=false;showWorkspace();document.title=$("view-title").textContent+" · EzLLMRouter";$("account-button").focus();if(state.view==="local_connectors")render();
});
$("password-form").addEventListener("submit",async event=>{
  event.preventDefault();const error=$("password-error");error.hidden=true;
  if($("new-password").value!==$("confirm-password").value){error.textContent="Passwords do not match.";error.hidden=false;return;}
  const button=$("password-form").querySelector("button[type=submit]");button.disabled=true;
  try{
    await api("/operator/v1/account/password",{method:"POST",csrf:true,body:{
      current_password:$("current-password").value,new_password:$("new-password").value}});
    showLogin("Password updated. Sign in with your new password.");
  }catch(failure){if(failure.staleView)return;
    error.textContent="Password change failed: "+failure.message;error.hidden=false;
  }finally{
    for(const id of ["current-password","new-password","confirm-password"])$(id).value="";
    button.disabled=false;
  }
});
