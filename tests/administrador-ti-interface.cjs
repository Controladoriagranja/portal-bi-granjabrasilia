const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=require('node:path').resolve(__dirname,'..');
const html=fs.readFileSync(root+'/index.html','utf8');
const js=fs.readFileSync(root+'/assets/js/user-management.js','utf8');
assert(!/managedUserCreate|createManagedUser|toggleManagedUserCreate|userAuditButton|userAuditPanel|loadUserAudit/.test(html+js));
for(const id of ['newUserOperationPermissions','euOperationPermissions']){
  const start=html.indexOf(`id="${id}"`);assert(start>=0);
  const form=html.slice(start,html.indexOf('</small>',start));
  assert(form.includes('data-operation-permission="usuarios.gerenciar"> Administrador TI'));
}
assert(html.includes('id="newUserName"') && html.includes('onclick="addUser(this)"'),'Cadastro normal preservado');
let renders=0;
const context={currentUser:{role:'sector',operationPermissions:['usuarios.gerenciar']},document:{getElementById(id){assert.equal(id,'usersArchivedLabel');return {style:{}};}},updatePendingBadge(){},renderAllUsersTable(){renders++;}};
vm.createContext(context);vm.runInContext(js,context);
assert(context.canManagePortalUsers());assert(context.isUserManagementOnly());
const render=html.match(/function renderUsersTable\(\) \{[\s\S]*?\n\}/)[0];
vm.runInContext(render+'\nrenderUsersTable();',context);assert.equal(renders,1);
context.currentUser={role:'admin'};vm.runInContext('renderUsersTable();',context);
assert(context.canManagePortalUsers());assert(!context.isUserManagementOnly());
context.currentUser={role:'sector',operationPermissions:[]};assert(!context.canManagePortalUsers());
for(const [i,match] of [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].entries()){
  if(match[1].trim())new vm.Script(match[1],{filename:`inline-${i}.js`});
}
console.log('PASS: formulário separado e logs removidos; flag nos dois formulários normais; gestão TI/Admin/usuário comum e sintaxe do HTML/JS conferidas.');
