/* Gestão exclusiva de usuários. Nenhum polling de listagem/auditoria. */
function canManagePortalUsers() {
  return !!currentUser && (currentUser.role === 'admin' ||
    (currentUser.operationPermissions || []).includes('usuarios.gerenciar'));
}
function isUserManagementOnly() {
  return canManagePortalUsers() && currentUser.role !== 'admin';
}
function hasManagementGrant(prefix) {
  return !!document.querySelector(`#${prefix}OperationPermissions [data-operation-permission="usuarios.gerenciar"]:checked`);
}
function restoreManagementNavigation() {
  document.querySelectorAll('[data-management-display]').forEach(el => {
    el.style.display = el.dataset.managementDisplay;
    delete el.dataset.managementDisplay;
  });
}
function initManagementPortal() {
  stopCentralTicketSync();
  stopTicketFormsImport(true);
  stopUpdateMonitor();
  restoreManagementNavigation();
  document.querySelectorAll('.sidebar .nav-item, nav.sidebar .sidebar-section, #mobileNav .mob-nav-btn').forEach(el => {
    if (['nav-users','nav-changepass','mnAdmin','mnPwd','mnLogout','adminSection'].includes(el.id)) return;
    el.dataset.managementDisplay = el.style.display;
    el.style.display = 'none';
  });
  // A sidebar usa também a classe .sidebar diretamente no elemento nav.
  ['nav-users','adminSection','mnAdmin'].forEach(id => document.getElementById(id)?.style.setProperty('display', id === 'adminSection' ? 'block' : 'flex'));
  document.getElementById('mnAdmin')?.querySelector('span')?.replaceChildren('Usuários');
  document.getElementById('userRoleBadge').textContent = 'Gestão de usuários';
  document.getElementById('view-users').style.removeProperty('display');
  renderUsersTable();
  switchView('users', document.getElementById('nav-users'));
  setMobNav('mnAdmin');
}

function toggleManagedUserCreate() {
  if (!canManagePortalUsers()) return;
  const panel = document.getElementById('managedUserCreate');
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    document.getElementById('managedUserSectors').innerHTML = SECTORS.map(s =>
      `<label class="check-item"><input type="checkbox" value="${escTicket(s)}"> ${escTicket(sectorLabel(s))}</label>`).join('');
    document.getElementById('managedUserName').focus();
  }
}
async function createManagedUser(event) {
  event.preventDefault();
  if (!canManagePortalUsers()) return;
  const button = document.getElementById('managedUserSubmit');
  setButtonBusy(button, true, 'Criando...');
  try {
    const result = await portalApiRequest('/api/admin/usuarios', {method:'POST', body:JSON.stringify({
      name:document.getElementById('managedUserName').value.trim(),
      email:document.getElementById('managedUserEmail').value.trim(),
      password:document.getElementById('managedUserPassword').value,
      role:'sector', status:'active', reportAccessMode:'sector', reportIds:[],
      sectors:[...document.querySelectorAll('#managedUserSectors input:checked')].map(el => el.value),
      commercialAccess:{mode:'none'}, operationPermissions:[], ticketPanelAccess:false
    })});
    if (result.data) applyPortalDataResponse(result.data);
    document.getElementById('managedUserForm').reset();
    document.getElementById('managedUserCreate').hidden = true;
    renderUsersTable();
    showToast('Usuário criado. Permissões de dados adicionais podem ser configuradas pelo Admin.', 'success');
  } catch (error) {
    showToast(error.message || 'Não foi possível criar o usuário.', 'error');
  } finally { setButtonBusy(button, false); }
}

async function changeManagedUserStatus(id, status, button) {
  if (!canManagePortalUsers()) return;
  const user = db.users.find(u => u.id === id);
  if (!user || user.deletedAt) return;
  let confirmAdminBlock = false;
  if (user.role === 'admin' && status === 'blocked') {
    confirmAdminBlock = confirm(`Bloquear o Admin ${user.name}?\n\nNão há proteção do último Admin ativo. Se não restar outra conta ativa com permissão para desbloquear, o acesso precisará ser recuperado diretamente no Neon.`);
    if (!confirmAdminBlock) return;
  } else if (status === 'blocked' && !confirm(`Bloquear o acesso de ${user.name}?`)) return;
  setButtonBusy(button, true, 'Salvando...');
  try {
    const result = await portalApiRequest(`/api/admin/usuarios/${Number(user.dbId || user.id)}/status`, {
      method:'POST', body:JSON.stringify({status, confirmAdminBlock})
    });
    if (result.data) applyPortalDataResponse(result.data);
    if (currentUser?.status !== 'active') { await logout(); return; }
    renderUsersTable();
    showToast(status === 'blocked' ? 'Usuário bloqueado.' : 'Usuário reativado.', 'success');
  } catch (error) { showToast(error.message || 'Não foi possível alterar o status.', 'error'); }
  finally { setButtonBusy(button, false); }
}

async function deleteManagedUser(id, button) {
  if (!canManagePortalUsers()) return;
  const user = db.users.find(u => u.id === id);
  if (!user) return;
  if (user.role === 'admin') {
    showToast('Admin não pode ser excluído por enquanto. Use Bloquear, mediante confirmação.', 'error'); return;
  }
  if (!confirm(`Excluir ${user.name}?\n\nA conta perderá o acesso e sairá da lista principal. Chamados, anexos e histórico serão preservados. Somente Admin poderá restaurá-la.`)) return;
  setButtonBusy(button, true, 'Excluindo...');
  try {
    const result = await portalApiRequest(`/api/admin/usuarios/${Number(user.dbId || user.id)}`, {method:'DELETE'});
    if (result.data) applyPortalDataResponse(result.data);
    renderUsersTable(); showToast('Usuário excluído; histórico preservado.', 'success');
  } catch (error) { showToast(error.message || 'Não foi possível excluir.', 'error'); }
  finally { setButtonBusy(button, false); }
}
async function restoreManagedUser(id, button) {
  if (currentUser?.role !== 'admin') return;
  const user = db.users.find(u => u.id === id);
  if (!user || !confirm(`Restaurar ${user.name}? A conta permanecerá bloqueada até você reativá-la.`)) return;
  setButtonBusy(button, true, 'Restaurando...');
  try {
    const result = await portalApiRequest(`/api/admin/usuarios/${Number(user.dbId || user.id)}/restaurar`, {method:'POST'});
    if (result.data) applyPortalDataResponse(result.data);
    renderUsersTable(); showToast('Conta restaurada, ainda bloqueada.', 'success');
  } catch (error) { showToast(error.message || 'Não foi possível restaurar.', 'error'); }
  finally { setButtonBusy(button, false); }
}
async function loadUserAudit(button) {
  if (currentUser?.role !== 'admin') return;
  setButtonBusy(button, true, 'Carregando...');
  const panel = document.getElementById('userAuditPanel');
  panel.hidden = false;
  try {
    const result = await portalApiRequest('/api/admin/usuarios/auditoria', {method:'GET'});
    panel.innerHTML = '<h3 style="padding:12px">Últimas 200 ações</h3><table><thead><tr><th>Data</th><th>Autor</th><th>Ação</th><th>Usuário afetado</th></tr></thead><tbody>' +
      result.entries.map(row => `<tr><td>${escTicket(new Date(row.ocorrido_em).toLocaleString('pt-BR'))}</td><td>${escTicket(row.autor_email || 'Operação no banco')}</td><td>${escTicket(row.acao)}</td><td>${escTicket(row.usuario_nome || '')}<br>${escTicket(row.usuario_email || '')}</td></tr>`).join('') + '</tbody></table>';
  } catch (error) { panel.textContent = error.message || 'Não foi possível consultar os logs.'; }
  finally { setButtonBusy(button, false); }
}
