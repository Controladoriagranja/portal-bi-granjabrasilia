/* Sem navegador/rede. Executa funcoes reais do HTML contra DOM/API simulados.
 * Opcional, com Node instalado: node tests/operation_permissions_frontend.js
 */
async function testOperationPermissionsFrontend(html) {
  let checks = 0;
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
    checks++;
  };
  const source = name => {
    const match = html.match(new RegExp('^(?:async )?function ' + name + '\\([^\\n]*\\) ?\\{[\\s\\S]*?^\\}', 'm'));
    if (!match) throw new Error('Funcao ausente: ' + name);
    return match[0];
  };
  const permission = 'comercial.frete.editar';
  const groups = Object.fromEntries(['eu', 'newUser'].map(prefix => {
    const input = {dataset: {operationPermission: permission}, checked: false};
    return [prefix + 'OperationPermissions', {dataset: {}, querySelectorAll: () => [input]}];
  }));
  const document = {getElementById: id => groups[id]};
  const {set, read, payload} = new Function('document', [
    source('setOperationPermissionsForm'), source('readOperationPermissionsForm'), source('adminUserPayload'),
    'return {set:setOperationPermissionsForm, read:readOperationPermissionsForm, payload:adminUserPayload};'
  ].join('\n'))(document);
  const user = {id: 900, dbId: 41, name: 'Offline', role: 'admin', status: 'active',
    dataAccess: {mode: 'general'}, sectors: ['comercial'], reportIds: [1],
    reportAccessMode: 'specific', operationPermissions: [permission]};
  for (const prefix of ['eu', 'newUser']) {
    set(prefix);
    assert(read(prefix).length === 0, 'Sem escrita por padrao');
    set(prefix, [permission]);
    assert(groups[prefix + 'OperationPermissions'].querySelectorAll()[0].checked, 'Concessao nao recuperada');
    assert(read(prefix)[0] === permission, 'Concessao nao serializada');
    groups[prefix + 'OperationPermissions'].querySelectorAll()[0].checked = false;
    assert(read(prefix).length === 0, 'Revogacao nao explicita');
    set(prefix, [permission, 'comercial.futura.editar']);
    groups[prefix + 'OperationPermissions'].querySelectorAll()[0].checked = false;
    assert(read(prefix).join() === 'comercial.futura.editar', 'Frontend antigo apagaria permissao futura');
    set(prefix);
    assert(read(prefix).length === 0, 'Reset reutilizou concessao anterior');
  }
  for (const role of ['admin', 'director', 'sector']) {
    const data = payload({...user, role});
    assert(!('operationPermissions' in data), 'Edicao sem escolha reenviaria snapshot de permissoes');
    assert(data.dataAccess.mode === 'general' && data.reportIds[0] === 1, 'Contrato dos relatorios alterado');
  }
  assert(payload(user, {operationPermissions: []}).operationPermissions.length === 0, 'Revogacao perdida');
  assert(payload(user, {operationPermissions: [permission]}).operationPermissions[0] === permission, 'Concessao perdida');
  assert(source('openEditUser').includes("setOperationPermissionsForm('eu',u.operationPermissions)"), 'Modal sem recuperacao');
  assert(source('addUser').includes("readOperationPermissionsForm('newUser')"), 'Criacao sem permissoes');
  assert(source('saveEditUser').includes("readOperationPermissionsForm('eu')"), 'Edicao sem permissoes');

  let sent;
  const save = new Function('portalDbSnapshot', 'portalApiRequest', `
    let portalSaveQueue = Promise.resolve();
    const currentUser = {role:'admin'};
    const neonSessionToken = 'offline';
    const cachePortalDb = () => {};
    ${source('saveDB')}
    return saveDB;
  `)(() => ({users: [JSON.parse(JSON.stringify(user))]}), async (path, options) => {
    sent = JSON.parse(options.body);
    return {ok: true};
  });
  assert((await save()).ok, 'Falha no PUT simulado');
  assert(!('operationPermissions' in sent.users[0]), 'PUT de outra tela reenviou cache antigo');
  assert(user.operationPermissions[0] === permission, 'PUT alterou cadastro em memoria');

  // Parse de todos os scripts locais; nenhum e executado.
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (/\bsrc\s*=|\btype\s*=\s*["'](?:module|application\/)/i.test(match[1])) continue;
    new Function(match[2]);
  }
  assert(true, 'Sintaxe JavaScript');
  return {checks, result: 'OK — formularios, payloads, preservacao e sintaxe; sem rede.'};
}

if (typeof module !== 'undefined') {
  module.exports = testOperationPermissionsFrontend;
  if (require.main === module) {
    const fs = require('fs');
    const path = require('path');
    testOperationPermissionsFrontend(fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8'))
      .then(result => console.log(result)).catch(error => { console.error(error); process.exitCode = 1; });
  }
}
