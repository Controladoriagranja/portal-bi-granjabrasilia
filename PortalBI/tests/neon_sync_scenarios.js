/* Deterministic offline tests: fake clock and fetch, no waits or real API calls. */
window.runNeonSyncTests = async () => {
  const results = [];
  const check = (value, message) => { if (!value) throw new Error(message); };
  const clone = value => JSON.parse(JSON.stringify(value));
  const flush = async () => { for (let i=0;i<40;i++) await Promise.resolve(); };
  const deferred = () => { let resolve; const promise = new Promise(r => resolve=r); return {promise,resolve}; };
  const timers = new Map(); let timerId=0;
  window.setTimeout = (fn,delay) => { timers.set(++timerId,{fn,delay}); return timerId; };
  window.clearTimeout = id => timers.delete(id);
  window.clearInterval = window.clearTimeout;
  const polls = delay => [...timers.values()].filter(t=>t.delay===delay);
  const tick = delay => {
    const entry=[...timers].find(([,t])=>t.delay===delay);
    check(entry, `Missing timer ${delay}`); timers.delete(entry[0]); return entry[1].fn();
  };
  let visible=true;
  Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>visible?'visible':'hidden'});
  const visibility = async value => { visible=value;document.dispatchEvent(new Event('visibilitychange'));await flush(); };
  let requests=[], hook=null;
  let server={revision:1,managers:[{id:8,name:'Gestor'}],tickets:[{id:1,title:'Original',attachments:[],history:[]},{id:2,title:'Excluir em outro navegador'}]};
  const response=(data,status=200)=>({ok:status<400,status,json:async()=>clone(data)});
  window.fetch = async (url,options={}) => {
    const path=new URL(url,location.href).pathname;
    const request={path,method:options.method||'GET',body:options.body?JSON.parse(options.body):null,signal:options.signal};
    requests.push(request);
    if (hook) { const result=hook(request); if (result) return result; }
    if(path==='/api/chamados/usuarios') return response({usuarios:[{id:8,nome:'Gestor',email:'test@example.test'}]});
    if(path==='/api/chamados' && request.method==='GET') return response(server);
    if(path==='/api/chamados' && request.method==='PUT') {
      const changed=new Map(request.body.tickets.map(t=>[t.id,t]));
      server.tickets=server.tickets.map(t=>changed.get(t.id)||t);
      for(const t of request.body.tickets) if(!server.tickets.some(x=>x.id===t.id))server.tickets.push(t);
      if(request.body.managers)server.managers=request.body.managers;
      server.revision++;return response(server);
    }
    return response({ok:true,jobs:[]});
  };
  // Keep the real sync/persistence logic, stub presentation only.
  renderTickets=renderTicketAdmin=renderTicketProjects=updateTicketManagerInfo=renderPortalTicketUserSelects=renderTicketsAfterRemoteSync=()=>{};
  const authenticate = (role='admin',token='mock-token') => {
    currentUser={id:1,name:'Teste',email:'test@example.test',role,status:'active',ticketPanelAccess:false};
    setPortalToken(token);showScreen('portal');
  };
  const reset = async () => {
    stopCentralTicketSync();stopUpdateMonitor();await flush();hook=null;requests=[];timers.clear();
    visible=true;authenticate();switchView('reports',null);
    ticketStore=clone(server);markTicketStoreSynced(ticketStore);
  };
  const count = (path,method='GET')=>requests.filter(r=>r.path===path && r.method===method).length;

  currentUser=null;clearPortalToken();showScreen('login');
  await initCentralTicketSync();check(requests.length===0,'Login queried ticket API');
  authenticate();switchView('reports',null);await initCentralTicketSync();
  check(requests.length===0 && polls(10000).length===0,'Reports started polling');
  results.push('Login e Relatorios: zero consultas automaticas de chamados');

  switchView('tickets',null);await flush();
  check(count('/api/chamados/usuarios')===1 && count('/api/chamados')===1,'Entry did not fetch immediately');
  await initCentralTicketSync();await initCentralTicketSync();
  check(polls(10000).length===1 && count('/api/chamados')===1,'Duplicate entry/timer');
  await tick(10000);await flush();
  check(count('/api/chamados')===2 && count('/api/chamados/usuarios')===1 && polls(10000).length===1,'Periodic sync incorrect');
  results.push('Entrada imediata, ciclo de 10s e apenas um timer');

  const oldRead=deferred();hook=r=>r.path==='/api/chamados' && r.method==='GET'?oldRead.promise:null;
  const reading=tick(10000);await flush();
  const countBefore=count('/api/chamados');initCentralTicketSync();initCentralTicketSync();
  check(count('/api/chamados')===countBefore,'Overlapping periodic requests');
  const oldSignal=requests.at(-1).signal;
  switchView('reports',null);check(oldSignal.aborted,'Leaving did not abort read');
  const stale={revision:999,tickets:[{id:999,title:'Resposta antiga'}],managers:[]};
  oldRead.resolve(response(stale));await reading;await flush();hook=null;
  check(!ticketStore.tickets.some(t=>t.id===999) && polls(10000).length===0,'Late read revived polling or overwrote state');
  results.push('Saida cancela leitura; resposta atrasada descartada sem timer novo');

  switchView('ticketadmin',null);await flush();await visibility(false);
  check(polls(10000).length===0,'Hidden tab kept timer');
  const beforeVisible=count('/api/chamados');
  server={revision:5,tickets:[{id:1,title:'Editado por outro usuario'}],managers:[{id:9,name:'Novo gestor'}]};
  await visibility(true);
  check(count('/api/chamados')===beforeVisible+1 && ticketStore.tickets.length===1 && ticketStore.managers[0].id===9,'Return did not recover remote changes/deletion');
  check(!requests.some(r=>r.path.includes('/merge')||r.method==='PUT'),'Cache uploaded automatically');
  results.push('Aba oculta suspende; retorno recupera edicoes, gestores e exclusoes sem merge');

  await reset();const oldUsers=deferred();let holdUsers=true;
  hook=r=>r.path==='/api/chamados/usuarios' && holdUsers?oldUsers.promise:null;
  switchView('tickets',null);await flush();switchView('reports',null);switchView('tickets',null);
  check(count('/api/chamados/usuarios')===1,'Concurrent user roster loads');
  holdUsers=false;oldUsers.resolve(response({usuarios:[]}));await flush();
  check(count('/api/chamados/usuarios')===2 && count('/api/chamados')===1 && polls(10000).length===1,'Rapid reentry lost sync or duplicated timer');
  results.push('Trocas rapidas aguardam leitura anterior e retomam uma unica sincronizacao');

  await reset();let rosterAttempts=0;
  hook=r=>r.path==='/api/chamados/usuarios' && ++rosterAttempts===1?response({erro:'Temporario'},500):null;
  switchView('tickets',null);await flush();await tick(10000);
  check(rosterAttempts===2 && portalTicketUsers[0].id===8,'Failed user roster did not recover');
  results.push('Falha temporaria no cadastro de responsaveis recuperada no ciclo seguinte');


  await reset();hook=r=>r.path==='/api/chamados/usuarios'?response({erro:'Bloqueado'},401):null;
  switchView('tickets',null);await flush();
  check(!currentUser && !getPortalToken() && polls(10000).length===0 && count('/api/chamados')===0,'401 did not invalidate authentication/stop polling');
  results.push('401/bloqueio encerra autenticacao e nao rearma timers');

  server={revision:10,tickets:[{id:1,title:'A',history:[],attachments:[]},{id:2,title:'Removido remotamente'}],managers:[{id:8}]};
  await reset();const firstWrite=deferred();let writes=0;
  hook=r=>r.method==='PUT' && ++writes===1?firstWrite.promise:null;
  ticketStore.tickets[0].title='Alterado';const save1=saveTicketStore();await flush();
  ticketStore.tickets.push({id:3,title:'Novo',history:[{text:'Criado'}],attachments:[{name:'teste.txt',data:'data:text/plain;base64,QQ=='}]});
  const save2=saveTicketStore();await flush();
  check(count('/api/chamados','PUT')===1,'Save queue sent concurrent writes');
  server={revision:11,tickets:[{id:1,title:'Alterado',history:[],attachments:[]}],managers:[{id:9}]};
  firstWrite.resolve(response(server));await save1;await save2;
  const payloads=requests.filter(r=>r.method==='PUT').map(r=>r.body);
  check(payloads.length===2 && payloads[0].tickets.length===1 && payloads[1].tickets.length===1 && payloads[1].tickets[0].id===3,'Queued snapshot reuploaded unchanged/deleted tickets');
  check(payloads[1].tickets[0].attachments[0].name==='teste.txt' && payloads[1].tickets[0].history[0].text==='Criado','Attachments/history lost');
  check(!('managers' in payloads[1]) && ticketStore.managers[0].id===9,'Old managers reuploaded');
  results.push('Fila serial preserva criacao, anexo/historico e nao restaura chamado excluido ou gestor antigo');

  await reset();const delayedPull=deferred();hook=r=>r.path==='/api/chamados' && r.method==='GET'?delayedPull.promise:null;
  const manualRead=pullTicketStoreFromServer();await flush();
  ticketStore.tickets[0].title='Alteracao durante GET';await saveTicketStore();
  delayedPull.resolve(response(stale));await manualRead;
  check(ticketStore.tickets[0].title==='Alteracao durante GET','Late GET overwrote mutation');
  results.push('GET iniciado antes de salvar nao sobrescreve alteracoes locais');

  await reset();const failedFirst=deferred();let failWrites=0;
  hook=r=>r.method==='PUT' && ++failWrites===1?failedFirst.promise:null;
  ticketStore.tickets[0].title='Primeira alteracao';const failedSave=saveTicketStore();await flush();
  ticketStore.tickets.push({id:4,title:'Segunda alteracao'});const retrySave=saveTicketStore();
  failedFirst.resolve(response({erro:'Falha temporaria simulada'},500));
  check(await failedSave===false,'Write failure was not reported');await retrySave;
  const retried=requests.filter(r=>r.method==='PUT')[1].body.tickets;
  check(retried.some(t=>t.id===1 && t.title==='Primeira alteracao') && retried.some(t=>t.id===4),'Later queued save lost unconfirmed edits');
  results.push('Falha de um salvamento nao perde as alteracoes na proxima tarefa da fila');

  await reset();switchView('tickets',null);await flush();
  const savingGate=deferred();hook=r=>r.method==='PUT'?savingGate.promise:null;
  ticketStore.tickets[0].title='Salvando';const saving=saveTicketStore();await flush();
  const readCount=count('/api/chamados');await tick(10000);
  check(count('/api/chamados')===readCount,'Periodic GET ran during pending save');
  savingGate.resolve(response({...clone(server),revision:99}));await saving;
  hook=null;window.dispatchEvent(new Event('pagehide'));
  check(polls(10000).length===0,'Pagehide kept poll timer');
  window.dispatchEvent(new Event('pageshow'));await flush();
  check(polls(10000).length===1 && count('/api/chamados')===readCount+1,'Pageshow did not resync');
  results.push('Polling aguarda salvamentos; pagehide suspende e pageshow recupera o servidor');


  await reset();const oldSession=deferred();hook=r=>r.path==='/api/chamados'?oldSession.promise:null;
  switchView('tickets',null);await flush();
  const oldCount=count('/api/chamados');const logoutTask=logout();
  check(!currentUser && polls(10000).length===0,'Logout waited for network to stop polling');
  hook=null;authenticate('admin','new-token');switchView('reports',null);
  oldSession.resolve(response(stale,401));await logoutTask;await flush();
  check(getPortalToken()==='new-token' && currentUser && polls(10000).length===0,'Old 401 logged out new session or reactivated timer');
  results.push('Logout imediato; resposta/401 da sessao antiga nao afeta novo login');

  await reset();const blockedWrite=deferred();hook=r=>r.method==='PUT'?blockedWrite.promise:null;
  ticketStore.tickets[0].title='Sessao antiga';const queued1=saveTicketStore();await flush();
  ticketStore.tickets[0].title='Segunda alteracao antiga';const queued2=saveTicketStore();
  await logout();authenticate('admin','another-token');switchView('reports',null);hook=null;
  blockedWrite.resolve(response(stale));await queued1;await queued2;
  check(count('/api/chamados','PUT')===1 && !ticketStore.tickets.some(t=>t.id===999),'Old queued save used new credentials');
  results.push('Fila de sessao encerrada nao envia alteracoes com credenciais do novo login');

  await reset();authenticate('sector');switchView('ticketadmin',null);await flush();
  check(!canSyncTickets() && requests.length===0,'Non-panel user started admin polling');
  authenticate('admin');switchView('tickets',null);await flush();
  sessionStorage.removeItem('granjabi_auth_token');await tick(10000);await flush();
  check(!ticketSyncActive && polls(10000).length===0,'Missing token kept lifecycle active');
  results.push('Permissoes de painel preservadas; token ausente interrompe ciclo');

  await reset();let statusReads=0;
  loadUpdateStatus=async()=>{statusReads++;updateLastJobs=[{status:'executando'}];};
  switchView('updates',null);await flush();
  check(statusReads===1 && polls(15000).length===1,'Active jobs interval changed');
  await visibility(false);check(polls(15000).length===0,'Hidden tab kept job polling');
  updateRequestInFlight=true;
  await visibility(true);
  check(statusReads===1 && polls(1000).length===1,'Resume overlapped previous status request');
  updateRequestInFlight=false;await tick(1000);
  check(statusReads===2 && polls(15000).length===1,'Visible jobs did not resume after old request');
  loadUpdateStatus=async()=>{statusReads++;updateLastJobs=[];};
  await tick(15000);check(polls(900000).length===1,'Idle jobs interval changed');
  switchView('reports',null);check(polls(900000).length===0,'Leaving updates kept polling');
  results.push('Jobs: status ativo 15s/ocioso 15min preservados; aba oculta/saida interrompem');
  check(!requests.some(r=>r.path.includes('/merge')),'Unexpected cache migration');
  return results;
};
