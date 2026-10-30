/* Funcoes reais do HTML, com DOM, relogio e API simulados. */
async function testFormsImportClient(html) {
  let checks = 0;
  const assert = (value, message) => { if (!value) throw new Error(message); checks++; };
  const start = html.indexOf('let ticketFormsImportState = null;');
  const end = html.indexOf('function configureTicketsView()', start);
  const controller = html.slice(start, end);
  const script = `
    let currentUser={id:41,role:'sector'}, token='offline', enabled=true, imported=0;
    const requests=[],toasts=[],timers=new Map();let timerId=0,late=null;
    const getPortalToken=()=>token;
    const document={visibilityState:'visible',getElementById:id=>({hidden:false,classList:{contains:()=>true}})};
    const setTimeout=fn=>{timers.set(++timerId,fn);return timerId};
    const clearTimeout=id=>timers.delete(id);
    class AbortController{constructor(){this.signal={aborted:false}}abort(){this.signal.aborted=true}}
    const showToast=message=>toasts.push(message);
    const resetTicketDriveUpload=()=>{},renderTicketDriveUpload=()=>{},setTicketDriveTargets=()=>{};
    const console={warn:()=>{}};
    async function portalApiRequest(path,options){
      requests.push({path,options});
      if(path.endsWith('/session'))return {ok:true,enabled,context:enabled?'signed-context':null};
      if(late)return new Promise(resolve=>{late.resolve=resolve});
      return {ok:true,imported};
    }
    ${controller}
    const next=async()=>{const entry=timers.entries().next().value;if(entry){timers.delete(entry[0]);await entry[1]();}};
    return {
      prepare:prepareTicketFormsImport,schedule:scheduleTicketFormsImport,stop:stopTicketFormsImport,next,
      requests,toasts,timers,document,
      login:value=>{currentUser=value?{id:41}:null;token=value?'offline':''},
      disable:()=>{enabled=false},value:n=>{imported=n},
      hold:()=>{late={};return late;}
    };`;
  const client = new Function(script)();
  client.login(false);client.schedule();
  assert(client.requests.length===0&&client.timers.size===0,'Sem login iniciou importacao');
  client.login(true);
  await client.prepare();
  client.schedule([1,2,3]);
  await client.next();await client.next();await client.next();
  assert(client.requests.filter(r=>r.path.endsWith('/import')).length===3,'Retentativas limitadas');
  assert(client.timers.size===0,'Criou polling ocioso');
  assert(!client.requests.some(r=>r.path==='/api/chamados'),'Comum carregou lista');
  assert(client.requests.filter(r=>r.path.endsWith('/import')).every(r=>
    JSON.stringify(JSON.parse(r.options.body))==='{"context":"signed-context"}'),'Cliente enviou identidade/linhas');
  client.value(1);client.schedule([1,2,3]);await client.next();
  assert(client.toasts.length===1&&client.timers.size===0,'Sucesso nao encerrou tentativas');
  client.document.visibilityState='hidden';const count=client.requests.length;client.schedule();
  assert(client.requests.length===count&&client.timers.size===0,'Aba oculta importou');
  client.document.visibilityState='visible';
  const late=client.hold();client.schedule([1,2,3]);const pending=client.next();
  for(let i=0;i<8;i++)await Promise.resolve();
  client.login(false);client.stop(true);late.resolve({ok:true,imported:1});await pending;
  assert(client.toasts.length===1&&client.timers.size===0,'Logout reativou importacao');
  const off=new Function(script)();off.disable();await off.prepare();off.schedule();await off.next();
  assert(off.requests.every(r=>r.path.endsWith('/session')),'Integracao desabilitada consultou Google');
  assert(html.includes("url.searchParams.set('entry.1258827024', email)") &&
    !html.includes("url.searchParams.set('entry.455859597'"),'Preencheu o segundo E-mail em vez do solicitante');
  const wrapper=html.match(/^async function fetchJsonWithTimeout\([^\n]*\) ?\{[\s\S]*?^\}/m)[0];
  let listener,signal,removed=false;
  class Controller{constructor(){this.signal={aborted:false}}abort(){this.signal.aborted=true}}
  const request=new Function('AbortController','fetch','setTimeout','clearTimeout',
    wrapper+'\nreturn fetchJsonWithTimeout;')(Controller,async(url,options)=>{
      signal=options.signal;return{json:async()=>({ok:true})};},()=>1,()=>{});
  const waiting=request('offline',{signal:{aborted:false,addEventListener:(name,fn)=>{listener=fn},
    removeEventListener:()=>{removed=true}}});
  listener();assert(signal.aborted,'Cancelamento externo nao chegou ao fetch');await waiting;
  assert(removed,'Listener de cancelamento nao removido');
  return checks;
}

if(typeof module!=='undefined') {
  module.exports={testFormsImportClient};
  if(require.main===module) {
    const fs=require('fs'),path=require('path');
    const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
    testFormsImportClient(html).then(checks=>console.log({checks}))
      .catch(error=>{console.error(error);process.exitCode=1;});
  }
}
