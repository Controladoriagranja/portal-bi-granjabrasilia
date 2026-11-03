/* Mesmo padrão do Comercial: pesquisa + uma identidade canônica por usuário. */
(() => {
  const states=new Map();
  const field=(p,n)=>document.getElementById(p+'Zoo'+n);
  const role=p=>document.getElementById(p==='eu'?'euRole':'newUserRole')?.value;
  const manager=p=>['admin','director'].includes(role(p));
  const searchKey=v=>typeof normalizeAccessSearch==='function'?normalizeAccessSearch(v):String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
  const names={vw_desempenho_acerto_portal:'Desempenho — Lotes Fechados',base_dinamica:'GPD por Fase',mortalidade_peso_abertos:'Lotes em Criação',vw_historico_lotes_criacao_portal:'Histórico de Lotes',acerto_lote_resultado_geral:'Carga do Desempenho',mortalidade_peso_fechados:'Carga do Histórico'};
  function state(p){if(!states.has(p))states.set(p,{uid:0,dirty:false,loaded:false,identities:[],users:[],identityId:null,userIds:[]});return states.get(p);}
  function status(p,text){field(p,'Status').textContent=text;}
  function identity(p){const s=state(p);return s.identities.find(i=>i.id===s.identityId);}
  function raw(p){const s=state(p),mode=manager(p)?'todos':field(p,'Mode').value;return {formVersion:3,mode,identityId:mode==='proprio'?s.identityId:null,userIds:mode==='equipe'?[...s.userIds]:[],allowPending:true};}
  function choices(p){
    const s=state(p),select=field(p,'Code');
    accessLinkRows[p+'Zoo']=s.identities.map(i=>({code:i.id,label:i.name,searchText:i.name+' '+Object.values(i.aliases||{}).flat().join(' ')}));
    if(s.identityId&&!s.identities.some(i=>i.id===s.identityId))accessLinkRows[p+'Zoo'].push({code:s.identityId,label:s.identityId+' — vínculo salvo indisponível'});
    filterAccessLinks(p,s.identityId||'','Zoo');
    s.identityId=select.value||null;select.disabled=!s.loaded;field(p,'Search').disabled=!s.loaded;
    if(!s.loaded){select.replaceChildren(new Option('Carregando identidades...',''));field(p,'Matches').textContent='';}
  }
  function team(p){
    const s=state(p),terms=searchKey(field(p,'TeamSearch').value).trim().split(/\s+/).filter(Boolean);
    field(p,'Users').replaceChildren();
    for(const user of s.users.filter(u=>terms.every(t=>searchKey(u.name+' '+u.email).includes(t)))){
      const label=document.createElement('label');label.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 0;font-size:12px';
      const input=document.createElement('input');input.type='checkbox';input.value=String(user.id);input.checked=s.userIds.includes(user.id);input.disabled=!user.active&&!input.checked;input.style.cssText='width:16px;height:16px;flex-shrink:0';
      input.addEventListener('change',()=>{s.userIds=input.checked?[...new Set([...s.userIds,user.id])]:s.userIds.filter(id=>id!==user.id);s.dirty=true;sync(p);});
      const note=!user.active?' (inativo)':!user.identityId?' (identidade pendente)':'';
      label.append(input,document.createTextNode(user.name+' · '+user.email+note));field(p,'Users').append(label);
    }
  }
  function sync(p){
    const s=state(p),select=field(p,'Mode');
    field(p,'Reload').hidden=true;
    if(manager(p)){select.disabled=true;select.value='todos';}else if(select.disabled){select.disabled=false;select.value='none';}
    const mode=select.value;
    field(p,'IdentityField').hidden=mode!=='proprio';field(p,'Links').hidden=mode!=='equipe';
    field(p,'Aliases').replaceChildren();field(p,'Aliases').hidden=true;
    if(mode==='todos'){status(p,manager(p)?'Admin e Diretor mantêm visão geral pelo perfil do portal.':'Acesso geral autorizado pelo administrador.');return;}
    if(mode==='none'){status(p,'O acesso do Comercial permanece independente.');return;}
    if(mode==='equipe'){
      const selected=s.users.filter(u=>s.userIds.includes(u.id));
      const pending=selected.some(u=>!u.active||!u.identityId);
      status(p,!selected.length?'Selecione os usuários técnicos da equipe.':pending?'Há usuários sem identidade confirmada. Ao salvar, a equipe ficará pendente, sem liberar registros.':'A equipe receberá somente a união das identidades dos usuários selecionados.');return;
    }
    const selected=identity(p);
    if(!selected){status(p,'Selecione uma identidade confirmada. Sem seleção, o usuário será salvo com vínculo pendente e nenhum registro liberado.');return;}
    const missing=selected.missingSources||[];
    status(p,selected.name+' selecionado(a). '+(missing.length?'As fontes sem alias confirmado permanecem bloqueadas.':'Os aliases confirmados serão usados automaticamente ao salvar.'));
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Conferir aliases confirmados ('+selected.aliasCount+')';summary.style.cursor='pointer';details.append(summary);
    for(const [source,values] of Object.entries(selected.aliases||{})){
      const line=document.createElement('div');line.style.cssText='font-size:11px;margin-top:6px;overflow-wrap:anywhere';line.textContent=(names[source]||source)+': '+values.join(', ');details.append(line);
    }
    if(missing.length){const line=document.createElement('div');line.style.cssText='font-size:11px;margin-top:6px';line.textContent='Sem acesso aos registros de: '+missing.map(s=>names[s]||s).join(', ');details.append(line);}
    field(p,'Aliases').append(details);field(p,'Aliases').hidden=false;
  }
  async function load(p,uid=0,preserve=false){
    mount(p);let s=state(p);
    if(!preserve){s={uid,dirty:false,loaded:false,identities:[],users:[],identityId:null,userIds:[]};states.set(p,s);field(p,'Mode').disabled=false;field(p,'Mode').value='none';field(p,'Search').value='';field(p,'TeamSearch').value='';}
    const nonce={};s.nonce=nonce;choices(p);sync(p);status(p,'Carregando identidades confirmadas do portal...');
    try{
      const data=await portalApiRequest(`/api/admin/usuarios/${Number(uid)||0}/zootecnico-access`);
      if(states.get(p)!==s||s.nonce!==nonce)return;
      if(data.ok!==true||!Array.isArray(data.identities)||!Array.isArray(data.users))throw new Error('Não foi possível carregar o catálogo do portal.');
      s.loaded=true;s.identities=data.identities;s.users=data.users;
      if(!preserve&&!s.dirty){field(p,'Mode').value=data.access.mode;s.identityId=data.access.identityId||null;s.userIds=data.access.userIds||[];}
      choices(p);team(p);sync(p);
      if(data.access.pending&&!s.dirty)status(p,'Vínculo pendente: selecione uma identidade confirmada ou confira os membros da equipe. Nenhum registro foi liberado.');
    }catch(error){if(states.get(p)===s&&s.nonce===nonce){status(p,(error.message||'Catálogo indisponível.')+' As permissões atuais serão preservadas; novos vínculos podem ficar pendentes.');field(p,'Reload').hidden=false;}}
  }
  function mount(p){
    if(field(p,'Mode'))return;
    const anchor=document.getElementById(p+'OperationPermissions');if(!anchor)return;
    const group=document.createElement('div');group.className='form-group';group.style.cssText='border-top:1px solid var(--border);padding-top:14px;min-width:0';
    group.innerHTML=`<label for="${p}ZooMode">Dados da Integração — Zootécnico</label><select id="${p}ZooMode"><option value="none">Sem acesso aos dados</option><option value="proprio">Somente seus dados</option><option value="equipe">Equipe — selecionar usuários</option><option value="todos">Todos os dados — autorização administrativa</option></select><div id="${p}ZooIdentityField" hidden style="margin-top:10px"><label for="${p}ZooCode">Técnico vinculado</label><input type="search" id="${p}ZooSearch" placeholder="Pesquisar por nome, sigla ou código" aria-label="Pesquisar identidade técnica por nome, sigla ou código" aria-controls="${p}ZooCode" autocomplete="off" style="margin-bottom:8px"><select id="${p}ZooCode"><option value="">Selecione o técnico...</option></select><small id="${p}ZooMatches" style="display:block;margin-top:5px;color:var(--text-muted)"></small></div><div id="${p}ZooLinks" hidden style="margin-top:10px"><label for="${p}ZooTeamSearch">Usuários da equipe</label><input type="search" id="${p}ZooTeamSearch" placeholder="Pesquisar nome ou e-mail"><div id="${p}ZooUsers" class="checkgroup" style="max-height:180px;overflow:auto;margin-top:6px"></div></div><small id="${p}ZooStatus" role="status" aria-live="polite" style="display:block;margin-top:6px;color:var(--text-muted)"></small><button type="button" class="btn-sm" id="${p}ZooReload" style="margin-top:8px">Recarregar catálogo</button><div id="${p}ZooAliases" hidden style="margin-top:10px"></div>`;
    anchor.before(group);state(p);
    field(p,'Mode').addEventListener('change',()=>{const s=state(p);s.dirty=true;sync(p);if(!s.loaded&&['proprio','equipe'].includes(field(p,'Mode').value))void load(p,s.uid,true);});
    field(p,'Search').addEventListener('input',()=>{const s=state(p),previous=s.identityId;choices(p);if(previous!==s.identityId)s.dirty=true;sync(p);});
    field(p,'Code').addEventListener('change',()=>{const s=state(p);s.identityId=field(p,'Code').value||null;s.dirty=true;sync(p);});
    field(p,'TeamSearch').addEventListener('input',()=>team(p));
    field(p,'Reload').addEventListener('click',()=>{const s=state(p);void load(p,s.uid,true);});
    document.getElementById(p==='eu'?'euRole':'newUserRole')?.addEventListener('change',()=>{state(p).dirty=true;sync(p);});
    choices(p);sync(p);
  }
  window.loadZootecnicoAccessForm=load;
  window.readZootecnicoAccessForm=p=>{const s=state(p);if(!s.dirty)return undefined;const value=raw(p);if(value.mode==='equipe'&&!value.userIds.length)throw new Error('Selecione os usuários da equipe.');return value;};
  window.resetZootecnicoAccessForm=p=>{mount(p);states.delete(p);state(p);field(p,'Mode').disabled=false;field(p,'Mode').value='none';field(p,'Search').value='';field(p,'TeamSearch').value='';choices(p);team(p);sync(p);};
  const initialize=()=>{mount('eu');mount('newUser');};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});else initialize();
})();
