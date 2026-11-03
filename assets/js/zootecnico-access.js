/* Configuração no modal existente. Não consulta dados analíticos nem altera o Comercial. */
(() => {
  const state = new Map();
  const manager = prefix => ['admin', 'director'].includes(document.getElementById(prefix === 'eu' ? 'euRole' : 'newUserRole')?.value);
  const field = (prefix, name) => document.getElementById(prefix + 'Zoo' + name);

  function mount(prefix) {
    const anchor = document.getElementById(prefix + 'OperationPermissions');
    if (!anchor || field(prefix, 'Mode')) return;
    const group = document.createElement('div');
    group.className = 'form-group';
    group.style.cssText = 'border-top:1px solid var(--border);padding-top:14px';
    group.innerHTML = `<label for="${prefix}ZooMode">Dados da Integração — Zootécnico</label>
      <select id="${prefix}ZooMode">
        <option value="none">Sem acesso aos dados da Integração</option>
        <option value="proprio">Técnico — somente seus dados</option>
        <option value="equipe">Supervisor — técnicos selecionados</option>
        <option value="todos">Geral — todos os dados da Integração</option>
      </select>
      <div id="${prefix}ZooLinks" hidden style="margin-top:10px">
        <label for="${prefix}ZooIds">Técnicos autorizados</label>
        <select id="${prefix}ZooIds" multiple size="5" aria-label="Técnicos autorizados"></select>
        <small>Para equipe, selecione um ou mais técnicos. No computador, use Ctrl/Cmd para selecionar vários.</small>
      </div>
      <small id="${prefix}ZooStatus" role="status" aria-live="polite" style="display:block;color:var(--text-muted);margin-top:6px"></small>`;
    anchor.before(group);
    field(prefix, 'Mode').addEventListener('change', () => {
      sync(prefix);
      if (!state.get(prefix)?.ready && field(prefix, 'Mode').value !== 'none') {
        void load(prefix, prefix === 'eu' ? state.get(prefix)?.uid : 0, true);
      }
    });
    document.getElementById(prefix === 'eu' ? 'euRole' : 'newUserRole')?.addEventListener('change', () => sync(prefix));
    sync(prefix);
  }

  function sync(prefix) {
    const mode = field(prefix, 'Mode');
    if (!mode) return;
    if (manager(prefix)) {
      // Remover o perfil geral nunca deve deixar uma concessão implícita para trás.
      mode.dataset.previous = 'none';
      mode.value = 'todos'; mode.disabled = true;
    } else if (mode.disabled) {
      mode.disabled = false; mode.value = mode.dataset.previous || 'none';
    }
    const restricted = ['proprio', 'equipe'].includes(mode.value);
    field(prefix, 'Links').hidden = !restricted;
    field(prefix, 'Ids').multiple = mode.value === 'equipe';
    field(prefix, 'Ids').size = mode.value === 'equipe' ? 5 : 1;
    if (manager(prefix)) field(prefix, 'Status').textContent = 'Admin e Diretor/Gestor têm acesso geral, conforme a política do portal.';
    else if (state.get(prefix)?.ready) field(prefix, 'Status').textContent = 'Independente do Comercial. A abertura do relatório continua definida acima.';
  }

  async function load(prefix, uid = 0, preserveMode = false) {
    mount(prefix);
    const nonce = {}, previousMode = field(prefix, 'Mode').value;
    state.set(prefix, {uid, nonce, ready: false});
    field(prefix, 'Ids').replaceChildren();
    field(prefix, 'Ids').disabled = true;
    if (!preserveMode) field(prefix, 'Mode').value = 'none';
    field(prefix, 'Status').textContent = 'Carregando vínculos da Integração…';
    try {
      const data = await portalApiRequest(`/api/admin/usuarios/${Number(uid) || 0}/zootecnico-access`);
      if (state.get(prefix)?.nonce !== nonce) return;
      if (data?.ok !== true || !data.access || !Array.isArray(data.technicians)) throw new Error('Resposta de permissões inválida.');
      const selected = new Set(data.access.technicianIds || []);
      const placeholder = new Option('Selecione um técnico…', '');
      field(prefix, 'Ids').add(placeholder);
      for (const technician of data.technicians) {
        const option = new Option(technician.nome + (technician.ativo ? '' : ' (inativo)'), technician.id);
        option.selected = selected.has(technician.id);
        option.disabled = !technician.ativo;
        field(prefix, 'Ids').add(option);
      }
      state.set(prefix, {uid, nonce, ready: true});
      field(prefix, 'Ids').disabled = false;
      field(prefix, 'Mode').disabled = false;
      field(prefix, 'Mode').value = preserveMode ? previousMode : data.access.mode;
      sync(prefix);
      if (!data.technicians.some(t => t.ativo) && !manager(prefix)) field(prefix, 'Status').textContent = 'Nenhum técnico cadastrado. Cadastre e confira os identificadores e aliases no Neon antes de liberar.';
    } catch (error) {
      if (state.get(prefix)?.nonce !== nonce) return;
      field(prefix, 'Status').textContent = (error?.message || 'Não foi possível carregar a Integração.') + ' As permissões existentes serão preservadas.';
      sync(prefix);
    }
  }

  window.loadZootecnicoAccessForm = load;
  window.readZootecnicoAccessForm = prefix => {
    if (!state.get(prefix)?.ready) {
      if (!manager(prefix) && field(prefix, 'Mode')?.value !== 'none') throw new Error('Aguarde o carregamento das permissões da Integração.');
      return undefined; // Frontend/backend antigos ou migração ausente: preservar.
    }
    const mode = manager(prefix) ? 'todos' : field(prefix, 'Mode').value;
    const ids = ['proprio', 'equipe'].includes(mode)
      ? [...field(prefix, 'Ids').selectedOptions].filter(x => !x.disabled && x.value).map(x => x.value) : [];
    if (mode === 'proprio' && ids.length !== 1) throw new Error('Selecione um técnico para acesso próprio à Integração.');
    if (mode === 'equipe' && !ids.length) throw new Error('Selecione os técnicos autorizados da equipe.');
    return {mode, technicianIds: ids};
  };
  window.resetZootecnicoAccessForm = prefix => {
    state.delete(prefix);
    field(prefix, 'Mode').value = 'none';
    field(prefix, 'Ids').replaceChildren();
    sync(prefix);
  };
  const initialize = () => { mount('eu'); mount('newUser'); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true});
  else initialize();
})();
