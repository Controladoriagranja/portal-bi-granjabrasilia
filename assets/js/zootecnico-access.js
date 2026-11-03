/* Cadastro único de usuários: identidade própria e equipe de usuários do portal. */
(() => {
  const states = new Map();
  const field = (p,n) => document.getElementById(p+'Zoo'+n);
  const role = p => document.getElementById(p==='eu'?'euRole':'newUserRole')?.value;
  const manager = p => ['admin','director'].includes(role(p));
  const name = p => document.getElementById(p==='eu'?'euName':'newUserName')?.value.trim() || '';
  const email = p => document.getElementById(p==='eu'?'euEmail':'newUserEmail')?.value.trim() || '';
  const labels = {vw_desempenho_acerto_portal:'Desempenho — Lotes Fechados',base_dinamica:'GPD por Fase',mortalidade_peso_abertos:'Lotes em Criação',vw_historico_lotes_criacao_portal:'Histórico de Lotes',acerto_lote_resultado_geral:'Carga do Desempenho (auxiliar)',mortalidade_peso_fechados:'Carga do Histórico (auxiliar)'};
  function stop(s) {clearTimeout(s.timer);s.generation++;}
  function state(p) {
    if(!states.has(p))states.set(p,{uid:0,loaded:false,dirty:false,users:[],userIds:[],resolutions:{},expanded:new Set(),generation:0,valid:false});
    return states.get(p);
  }
  function status(p,text) {field(p,'Status').textContent=text;}
  function raw(p) {
    const s=state(p),mode=manager(p)?'todos':field(p,'Mode').value;
    return {formVersion:2,mode,userIds:mode==='equipe'?[...s.userIds]:[],resolutions:['proprio','equipe'].includes(mode)?s.resolutions:{},allowPending:true};
  }
  function sync(p) {
    const s=state(p),select=field(p,'Mode');
    if(manager(p)){select.disabled=true;select.value='todos';}
    else if(select.disabled){select.disabled=false;select.value='none';}
    const mode=select.value;
    field(p,'Links').hidden=mode!=='equipe';field(p,'Check').hidden=!['proprio','equipe'].includes(mode);
    if(!['proprio','equipe'].includes(mode)){
      stop(s);s.valid=true;field(p,'Matches').replaceChildren();
      status(p,manager(p)?'Admin e Diretor têm visão geral, conforme o perfil do portal.':'O acesso do Comercial permanece independente.');
    }
  }
  function team(p) {
    const s=state(p),search=(field(p,'Search').value || '').toLocaleLowerCase();
    field(p,'Users').replaceChildren();
    for(const user of s.users.filter(u=>!search || (u.name+' '+u.email).toLocaleLowerCase().includes(search))){
      const label=document.createElement('label');label.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 0;font-size:12px';
      const input=document.createElement('input');input.type='checkbox';input.value=String(user.id);input.checked=s.userIds.includes(user.id);
      input.disabled=!user.active&&!input.checked;input.style.cssText='width:16px;height:16px;flex-shrink:0';
      input.addEventListener('change',()=>{
        s.userIds=input.checked?[...new Set([...s.userIds,user.id])]:s.userIds.filter(id=>id!==user.id);
        for(const key of Object.keys(s.resolutions))if(!s.userIds.includes(Number(key)))delete s.resolutions[key];
        s.dirty=true;team(p);schedule(p);
      });
      label.append(input,document.createTextNode(user.name+(user.active?'':' (inativo — remover da equipe)')+' · '+user.email));
      field(p,'Users').append(label);
    }
  }
  function fingerprint(p) {return JSON.stringify([name(p),email(p),role(p),raw(p)]);}
  function matches(p,data) {
    const s=state(p);field(p,'Matches').replaceChildren();
    for(const person of data.persons || []){
      const row=document.createElement('div');row.style.cssText='margin-top:10px;font-size:12px';
      const title=document.createElement('div');title.textContent=person.name+' — '+(person.ready?(Object.values(person.labels).some(v=>v.length)?'Identificado':'Sem dados liberados'):'Correspondência pendente');row.append(title);
      if(person.error){const error=document.createElement('div');error.textContent=person.error;error.style.color='var(--accent, #c0392b)';row.append(error);}
      const detail=document.createElement('details');detail.open=!person.ready||s.expanded.has(person.key);
      const summary=document.createElement('summary');summary.textContent=person.ready?'Conferir correspondências':'Resolver aqui';summary.style.cursor='pointer';detail.append(summary);
      detail.addEventListener('toggle',()=>{if(detail.open)s.expanded.add(person.key);else s.expanded.delete(person.key);});
      const choice=s.resolutions[person.key] || {};
      for(const [source,text] of Object.entries(labels)){
        const group=document.createElement('div');group.style.marginTop='9px';
        const label=document.createElement('label');label.textContent=text;
        const select=document.createElement('select');select.multiple=true;select.size=3;select.style.cssText='width:100%;max-width:100%;font-size:12px';select.dataset.source=source;
        if(Object.hasOwn(choice.selections || {},source))select.dataset.changed='true';
        const values=person.labels[source] || [];
        for(const value of [...new Set([...(data.options[source] || []),...values])]){
          const option=new Option(value,value);option.selected=values.includes(value);select.add(option);
        }
        const none=document.createElement('input');none.type='checkbox';none.dataset.without=source;none.style.cssText='width:15px;height:15px';
        none.checked=(choice.withoutData || []).includes(source)||!(data.options[source] || []).length;
        select.disabled=none.checked;
        const noLabel=document.createElement('label');noLabel.style.cssText='display:flex;align-items:center;gap:6px;font-size:11px';noLabel.append(none,document.createTextNode('Sem registros identificados nesta fonte — manter sem acesso'));
        group.append(label,select,noLabel);detail.append(group);
      }
      const confirm=document.createElement('input');confirm.type='checkbox';confirm.dataset.confirm='true';confirm.checked=choice.confirmed===true;confirm.style.cssText='width:16px;height:16px';
      const confirmLabel=document.createElement('label');confirmLabel.style.cssText='display:flex;align-items:flex-start;gap:7px;margin-top:10px;font-size:12px';
      confirmLabel.append(confirm,document.createTextNode('Confirmo que os valores selecionados pertencem a '+person.name+'.'));detail.append(confirmLabel);
      function gather(){
        const selections={},withoutData=[];
        for(const select of detail.querySelectorAll('select[data-source]')){
          const source=select.dataset.source,none=detail.querySelector(`input[data-without="${source}"]`);
          select.disabled=none.checked;
          const values=[...select.selectedOptions].map(o=>o.value);
          if(none.checked)withoutData.push(source);
          else if(values.length||select.dataset.changed)selections[source]=values;
        }
        s.resolutions[person.key]={selections,withoutData,confirmed:confirm.checked};s.dirty=true;s.valid=false;
      }
      detail.addEventListener('change',event=>{
        if(event.target.matches('select'))event.target.dataset.changed='true';
        if(event.target!==confirm)confirm.checked=false;
        gather();
        if(confirm.checked)schedule(p);
        else status(p,'Confira e confirme a correspondência para concluir o vínculo.');
      });
      row.append(detail);field(p,'Matches').append(row);
    }
  }
  function schedule(p,delay=350,retry=false){
    const s=state(p);stop(s);sync(p);
    if(!['proprio','equipe'].includes(field(p,'Mode').value))return;
    s.valid=false;
    if(!s.loaded){void load(p,s.uid,true);return;}
    if(field(p,'Mode').value==='proprio'&&!name(p)){status(p,'Informe o nome completo do usuário.');return;}
    if(field(p,'Mode').value==='equipe'&&!s.userIds.length){status(p,'Selecione os usuários da equipe.');return;}
    const generation=s.generation,signature=fingerprint(p);let attempts=0;
    status(p,'Conferindo a identificação. Você pode salvar o usuário com vínculo pendente, sem acesso a registros.');
    async function run(){
      if(states.get(p)!==s||generation!==s.generation||signature!==fingerprint(p)||document.visibilityState==='hidden'||field(p,'Mode').offsetParent===null)return;
      try{
        const data=await portalApiRequest('/api/admin/zootecnico/preview',{method:'POST',body:JSON.stringify({uid:s.uid,name:name(p),email:email(p),access:raw(p),retry:retry&&attempts===0})});
        if(states.get(p)!==s||generation!==s.generation||signature!==fingerprint(p))return;
        if(data.pending){
          if(++attempts>=45)throw new Error('A identificação demorou. Clique em Conferir novamente.');
          s.timer=setTimeout(run,1000);return;
        }
        if(data.ok!==true)throw new Error(data.erro||'Não foi possível validar.');
        s.valid=data.ready===true;s.signature=signature;s.validatedAt=Date.now();matches(p,data);
        status(p,s.valid?'Correspondência validada. Os vínculos serão gravados ao salvar o usuário.':(data.warning?data.warning+' ':'')+'Correspondência pendente. Resolva aqui ou salve o usuário sem liberar registros.');
      }catch(error){if(states.get(p)===s&&generation===s.generation){s.valid=false;status(p,(error.message||'Não foi possível consultar o catálogo.')+' Você pode salvar com vínculo pendente, sem acesso a registros.');}}
    }
    s.timer=setTimeout(run,delay);
  }
  async function load(p,uid=0,preserve=false){
    mount(p);let s=state(p);
    if(!preserve){stop(s);s={uid,loaded:false,dirty:false,users:[],userIds:[],resolutions:{},expanded:new Set(),generation:s.generation+1,valid:false};states.set(p,s);field(p,'Mode').disabled=false;field(p,'Mode').value='none';field(p,'Matches').replaceChildren();}
    const nonce={};s.loadNonce=nonce;status(p,'Carregando permissões…');
    try{
      const data=await portalApiRequest(`/api/admin/usuarios/${Number(uid)||0}/zootecnico-access`);
      if(states.get(p)!==s||s.loadNonce!==nonce)return;
      if(data.ok!==true||!Array.isArray(data.users))throw new Error('Não foi possível carregar os usuários.');
      s.loaded=true;s.users=data.users;
      if(!preserve&&!s.dirty){field(p,'Mode').value=data.access.mode;s.userIds=data.access.userIds || [];}
      team(p);sync(p);schedule(p);
      if(data.access.pending)status(p,'Usuário salvo com vínculo pendente. Nenhum registro foi liberado. Confira a correspondência para concluir.');
    }catch(error){if(states.get(p)===s){status(p,(error.message||'Não foi possível carregar.')+' As permissões atuais serão preservadas.');}}
  }
  function mount(p){
    if(field(p,'Mode'))return;
    const anchor=document.getElementById(p+'OperationPermissions');if(!anchor)return;
    const group=document.createElement('div');group.className='form-group';group.style.cssText='border-top:1px solid var(--border);padding-top:14px;min-width:0';
    group.innerHTML=`<label for="${p}ZooMode">Dados da Integração — Zootécnico</label><select id="${p}ZooMode"><option value="none">Sem acesso aos dados</option><option value="proprio">Somente seus dados</option><option value="equipe">Equipe — selecionar usuários</option><option value="todos">Todos os dados — autorização administrativa</option></select><div id="${p}ZooLinks" hidden style="margin-top:10px"><label for="${p}ZooSearch">Usuários da equipe</label><input type="search" id="${p}ZooSearch" placeholder="Pesquisar nome ou e-mail"><div id="${p}ZooUsers" class="checkgroup" style="max-height:180px;overflow:auto;margin-top:6px"></div></div><small id="${p}ZooStatus" role="status" aria-live="polite" style="display:block;margin-top:6px;color:var(--text-muted)"></small><button id="${p}ZooCheck" type="button" class="btn-sm" style="margin-top:8px" hidden>Conferir novamente</button><div id="${p}ZooMatches"></div>`;
    anchor.before(group);state(p);
    field(p,'Mode').addEventListener('change',()=>{const s=state(p);s.dirty=true;s.resolutions={};field(p,'Matches').replaceChildren();schedule(p);});
    field(p,'Search').addEventListener('input',()=>team(p));field(p,'Check').addEventListener('click',()=>schedule(p,0,true));
    document.getElementById(p==='eu'?'euRole':'newUserRole')?.addEventListener('change',()=>{state(p).dirty=true;sync(p);schedule(p);});
    for(const id of p==='eu'?['euName','euEmail']:['newUserName','newUserEmail'])document.getElementById(id)?.addEventListener('input',()=>{
      if(field(p,'Mode').value==='proprio'){const s=state(p);s.dirty=true;s.resolutions={};schedule(p);}
    });
    sync(p);
  }
  window.loadZootecnicoAccessForm=load;
  window.readZootecnicoAccessForm=p=>{
    const s=state(p);if(!s.dirty)return undefined;
    const value=raw(p);
    if(value.mode==='equipe'&&!value.userIds.length)throw new Error('Selecione os usuários da equipe.');
    return value;
  };
  window.resetZootecnicoAccessForm=p=>{const s=state(p);stop(s);states.delete(p);field(p,'Mode').disabled=false;field(p,'Mode').value='none';field(p,'Matches').replaceChildren();field(p,'Users').replaceChildren();state(p);sync(p);};
  const initialize=()=>{mount('eu');mount('newUser');};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});else initialize();
})();
