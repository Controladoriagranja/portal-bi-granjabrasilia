"""Teste offline da tela Chamados: perfis, DOM, leituras e Forms simulado.

Nao importa backend, nao acessa endpoints reais e nao baixa dependencias/driver.
"""
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd34H86yRAsPvFXT0RIfg5jLMplPNejN4ZYD-tCAcUYMJfksw/viewform?embedded=true"


def main():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    names = ("isTicketAdmin", "isTicketsFormOnlyView", "finishTicketGoogleFormsLoad", "configureTicketsView",
             "openNewTicket", "closeNewTicket", "renderTickets", "visibleTicketsForCurrentUser", "ticketGoogleFormsPrefillUrl",
             "canSyncTickets", "stopCentralTicketSync", "initCentralTicketSync", "runCentralTicketSync",
             "refreshTicketsManually", "pullTicketStoreFromServer", "loadPortalTicketUsers", "switchView",
             "escTicket", "ticketTableSortValue", "ticketStatusClass", "ticketStatusText", "formatTicketDate",
             "resetTicketDriveUpload", "setTicketDriveTargets", "driveAttachmentUrl", "renderTicketDriveUpload",
             "changeTicketDriveTarget", "selectTicketDriveFiles", "removeTicketDriveFile", "sendTicketDriveFiles", "canImportTicketForms")
    source = "\n".join(re.search(r"(?m)^(?:async )?function " + name + r"\([^\n]*\) ?\{[\s\S]*?^\}", html).group()
                       for name in names)
    fixture = re.sub(r"<script\b[^>]*>[\s\S]*?</script>|<link\b[^>]*>", "", html, flags=re.I)
    fixture = fixture.replace("<head>", '<head><base href="' + ROOT.as_uri() + '/">', 1)
    output = Path(tempfile.mkdtemp(prefix="portal-chamados-"))
    page = output / "fixture.html"
    page.write_text(fixture, encoding="utf-8")
    drivers = list((Path.home() / ".cache/selenium/chromedriver/win64").glob("*/chromedriver.exe"))
    if not drivers:
        raise RuntimeError("Driver local necessario; nenhum download permitido.")
    options = Options()
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    for flag in ("--headless=new", "--disable-background-networking", "--disable-extensions", "--disable-sync", "--no-first-run"):
        options.add_argument(flag)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    driver = webdriver.Chrome(service=Service(str(max(drivers, key=lambda p: tuple(map(int, p.parent.name.split('.'))))),
                                               log_output=subprocess.DEVNULL), options=options)
    checks = 0

    def js(code, *args): return driver.execute_script(code, *args)
    def wait(code): WebDriverWait(driver, 3).until(lambda _: js(code))
    def check(condition, message):
        nonlocal checks
        if not condition: raise AssertionError(message)
        checks += 1

    bootstrap = """
      let currentUser = {id:41,role:'sector'};
      let ticketFormsOpen=false,ticketFormsOwner=null,portalSessionGeneration=0;
      let ticketSyncActive=false,ticketSyncGeneration=0,ticketSyncTimer=null,ticketSyncReadController=null,ticketSyncRunPromise=null;
      let ticketSaveInProgress=false,ticketDeleteInProgress=false,ticketPullInProgress=false,ticketMutationGeneration=0;
      let ticketApiOnline=false,ticketHasConnectedOnce=false,ticketConsecutiveFailures=0,ticketLastRemoteSignature='';
      const TICKET_SYNC_INTERVAL_MS=0;
      let portalTicketUsers=[];
      let ticketTableSort={key:'createdAt',dir:'asc'};
      const records=[{id:1,number:1,title:'Chamado local',project:'TI',type:'Ajuste',status:'development',createdAt:'2026-10-30',updatedAt:'2026-10-30'}];
      window.reads=0; window.calls=[];window.boardRenders=0;
      let ticketStore=new Proxy({tickets:records},{get(target,key){if(key==='tickets')window.reads++;return target[key];}});
      const getPortalToken=()=> 'offline'; const currentEmail=()=>'';
      const sectorLabel=code=>({ti:'TI',comercial:'Comercial'}[code]||code);
      const prepareTicketFormsImport=async()=>null;const stopTicketFormsImport=()=>{};
      const scheduleTicketFormsImport=()=>{};let ticketFormsImportState=null;
      let ticketDriveQueue=[],ticketDriveTargets=[],ticketDriveBusy=false,ticketDriveEpoch=0,ticketDriveController=null,ticketDriveNotice='';
      window.uploadCalls=[];
      async function portalApiRequest(path,options){
        window.uploadCalls.push({path,options});
        if(window.failUploadOnce){window.failUploadOnce=false;throw new Error('Falha simulada')}
        const reply={ok:true,attachment:{storage:'portal-drive',url:'https://drive.google.com/file/d/mockDriveFile1234/view'}};
        if(window.holdUpload)return new Promise(resolve=>window.releaseUpload=()=>resolve(reply));
        return reply;
      }
      const updateTicketSyncIndicator=()=>{};const stopUpdateMonitor=()=>{};const showToast=()=>{};
      const renderTicketAdmin=()=>{window.boardRenders++};
      const renderPortalTicketUserSelects=()=>{};const cacheTicketStore=()=>{};
      const normalizeTicketStore=x=>x; const ticketStoreSignature=x=>JSON.stringify(x);
      const markTicketStoreSynced=x=>{ticketLastRemoteSignature=ticketStoreSignature(x)};
      const renderTicketsAfterRemoteSync=()=>renderTickets();
      const comparePortalValues=(a,b,dir)=>String(a).localeCompare(String(b))*(dir==='desc'?-1:1);
      const sortableHeader=title=>'<th>'+title+'</th>'; const ticketDisplayNumber=t=>'#'+t.number;
      const viewMeta={tickets:{title:'Chamados',sub:''},reports:{title:'Relatorios',sub:''},ticketadmin:{title:'Painel',sub:''}};
      async function ticketApiRequest(path,options={}){
        window.calls.push(path);
        if(window.holdReads && path==='/api/chamados')return new Promise((resolve,reject)=>{
          options.signal?.addEventListener('abort',()=>reject(new DOMException('Cancelado','AbortError')));
        });
        return path.endsWith('/usuarios')?{usuarios:[]}:{tickets:records,managers:[]};
      }
    """
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["http://*", "https://*"]})
        driver.get(page.as_uri())
        js("const s=document.createElement('script');s.textContent=arguments[0];document.head.append(s)", bootstrap + source)
        js("document.querySelectorAll('.screen').forEach(e=>e.classList.remove('active'));document.getElementById('screen-portal').classList.add('active')")
        check(js("return document.getElementById('ticketGoogleFormsIframe').dataset.src") == FORM_URL, "URL incorreta")
        from urllib.parse import urlparse, parse_qs
        prefilled=js("currentUser={id:41,name:'Nome & Teste',email:'autor@example.invalid',sectors:['ti']};return ticketGoogleFormsPrefillUrl(arguments[0])", FORM_URL)
        query=parse_qs(urlparse(prefilled).query)
        check(query['entry.431207813']==['Nome & Teste'] and query['entry.1258827024']==['autor@example.invalid'], 'Nome/email nao preenchidos')
        check(query['entry.1132196072']==['TI'] and query['embedded']==['true'], 'Setor unico/iframe')
        check('entry.455859597' not in query, 'Preencheu e-mail de usuario solicitado')
        multiple=js("currentUser.sectors=['ti','comercial'];return ticketGoogleFormsPrefillUrl(arguments[0])", FORM_URL)
        check('entry.1132196072' not in parse_qs(urlparse(multiple).query), 'Escolheu setor arbitrario')
        check(js("return !document.getElementById('newTicketView')"), "Formulario antigo montado")
        check(js("const f=document.getElementById('ticketGoogleFormsIframe');return f.title==='Formulário de chamado'&&f.loading==='lazy'&&!['width','height','frameborder','marginheight','marginwidth'].some(a=>f.hasAttribute(a))"), "Contrato iframe")
        mock = '<!doctype html><meta charset="utf-8"><style>body{font:16px Arial;margin:24px;color:#334155}div{height:1000px}</style><h2>Formulário de chamado</h2><p>Conteúdo simulado para teste local.</p><div></div>'
        mock_url = "data:text/html;charset=utf-8;base64," + base64.b64encode(mock.encode()).decode()
        js("document.getElementById('ticketGoogleFormsIframe').dataset.src=arguments[0]", mock_url)
        for user in ({"id": 41, "role": "sector"}, {"id": 42, "role": "director"}, {"id": 43, "role": "sector", "ticketPanelAccess": True}):
            js("currentUser=arguments[0];window.calls=[];window.reads=0;switchView('tickets');renderTickets();refreshTicketsManually();loadPortalTicketUsers();pullTicketStoreFromServer();", user)
            check(js("return !document.getElementById('ticketGoogleFormsView').hidden"), "Comum sem Forms")
            check(js("return !document.querySelector('#view-tickets .ticket-kpi')&&!document.getElementById('ticketTable')&&!document.getElementById('ticketSearch')"), "Comum montou cards/lista")
            check(js("return document.getElementById('ticketFormsAdminToolbar').hidden"), "Comum tem Voltar/lista")
            check(js("return window.calls.length===0&&window.reads===0&&!canSyncTickets()"), "Comum consultou lista/usuarios/cache")
            js("openNewTicket();closeNewTicket()")
            check(js("return !document.getElementById('ticketTable')"), "Chamada manual abriu lista comum")
        wait("return document.getElementById('ticketGoogleFormsLoading').hidden")
        for user in ({"id": 1, "role": "admin"}, {"id": 2, "perfil": "admin"}, {"id": 3, "isAdmin": True}):
            js("stopCentralTicketSync();currentUser=arguments[0];window.calls=[];switchView('tickets')", user)
            wait("return !!document.getElementById('ticketTable')?.querySelector('tbody tr')")
            wait("return window.calls.includes('/api/chamados')")
            check(js("return !document.getElementById('ticketAdminListHost').hidden&&document.querySelectorAll('#view-tickets .ticket-kpi').length===4"), "Admin perdeu lista/cards")
            check(js("return window.calls.includes('/api/chamados')"), "Admin nao sincronizou")
            js("document.querySelector('#ticketAdminListHost .btn-sm.accent').click()")
            check(js("return !document.getElementById('ticketGoogleFormsView').hidden&&!document.getElementById('ticketFormsAdminToolbar').hidden&&!canSyncTickets()"), "Admin Abrir Chamado nao abriu Forms")
            check(js("return !document.getElementById('newTicketView')"), "Admin exibiu formulario antigo")
            js("document.querySelector('#ticketFormsAdminToolbar button').click()")
            wait("return !document.getElementById('ticketAdminListHost').hidden&&document.getElementById('ticketGoogleFormsView').hidden")
            check(js("return canSyncTickets()"), "Voltar nao retomou sincronizacao")
        js("currentUser={id:41,role:'sector'};window.calls=[];switchView('tickets')")
        for width, height, name in ((1440,1000,'pc'),(768,1024,'tablet'),(390,844,'celular'),(320,640,'pequeno')):
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<768})
            check(js("const f=document.getElementById('ticketGoogleFormsIframe').getBoundingClientRect();const v=document.getElementById('view-tickets').getBoundingClientRect();return Math.abs(f.width-v.width)<3&&f.width<=innerWidth&&f.height>=560"), name+": dimensoes/largura total")
            check(js("return document.documentElement.scrollWidth<=innerWidth+1"), name+": overflow horizontal")
            if name == 'celular':
                check(js("return document.getElementById('ticketGoogleFormsIframe').getBoundingClientRect().bottom<=innerHeight-70"), "Forms coberto pela navegacao movel")
            if name in ('pc','celular'): driver.save_screenshot(str(output/('forms-'+name+'.png')))
        # Arquivos em memória, envio HTTP simulado e nenhum acesso a contas Google.
        js("ticketFormsImportState={token:'offline',enabled:true,uploadsEnabled:true,context:'signed-test'};setTicketDriveTargets([{id:'7',number:1007,title:'Pedido de teste'}])")
        check(js("return document.getElementById('ticketDriveTarget').value==='7'&&!document.getElementById('ticketDriveFiles').disabled"), 'Anexos nao habilitados para pedido proprio')
        js("selectTicketDriveFiles([new File(['a'],'teste.pdf',{type:'application/pdf'})])")
        check(js("return ticketDriveQueue.length===1&&!document.getElementById('ticketDriveSend').disabled"), 'Selecao de arquivo')
        driver.execute_async_script("const done=arguments[0];sendTicketDriveFiles().then(done)")
        check(js("const c=window.uploadCalls[0];return c.path==='/api/chamados/google-forms/attachments'&&c.options.body instanceof FormData&&c.options.body.get('context')==='signed-test'&&c.options.body.get('ticketId')==='7'&&!c.options.body.has('nome')"), 'Multipart ou identidade incorreta')
        check(js("return ticketDriveQueue[0].attachment&&document.querySelector('#ticketDriveFileList a').rel.includes('noopener')&&document.getElementById('ticketDriveSend').disabled"), 'Arquivo nao confirmado/link seguro')
        driver.execute_async_script("const done=arguments[0];sendTicketDriveFiles().then(done)")
        check(js("return window.uploadCalls.length===1"), 'Reenviou arquivo ja confirmado')
        check(js("return !driveAttachmentUrl({storage:'portal-drive',url:'javascript:alert(1)'})"), 'Link externo inseguro')
        js("changeTicketDriveTarget();window.failUploadOnce=true;selectTicketDriveFiles([new File(['x'],'retentar.pdf')])")
        driver.execute_async_script("const done=arguments[0];sendTicketDriveFiles().then(done)")
        check(js("return !ticketDriveBusy&&!ticketDriveQueue[0].attachment&&document.getElementById('ticketDriveMessage').textContent==='Falha simulada'"), 'Falha perdeu arquivo ou bloqueou nova tentativa')
        js("window.retryKey=window.uploadCalls.at(-1).options.body.get('uploadId')")
        driver.execute_async_script("const done=arguments[0];sendTicketDriveFiles().then(done)")
        check(js("return ticketDriveQueue[0].attachment&&window.uploadCalls.at(-1).options.body.get('uploadId')===window.retryKey"), 'Nova tentativa mudou identidade do envio')
        js("changeTicketDriveTarget();selectTicketDriveFiles(Array.from({length:6},(_,i)=>new File(['x'],'f'+i+'.pdf'))) ")
        check(js("return ticketDriveQueue.length===5"), 'Limite de 5 arquivos')
        for width,height in ((1440,1000),(768,1024),(390,844),(320,640)):
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<768})
            js("document.getElementById('ticketDriveUpload').scrollIntoView({block:'center'})")
            check(js("return document.documentElement.scrollWidth<=innerWidth+1&&document.getElementById('ticketDriveUpload').getBoundingClientRect().width<=innerWidth"), 'Anexos com scroll horizontal')
            if width in (1440,390): driver.save_screenshot(str(output/('anexos-'+str(width)+'.png')))
        js("changeTicketDriveTarget();window.holdUpload=true;selectTicketDriveFiles([new File(['x'],'pendente.pdf')]);window.pendingUpload=sendTicketDriveFiles()")
        wait("return !!window.releaseUpload")
        js("window.oldSignal=window.uploadCalls.at(-1).options.signal;resetTicketDriveUpload();currentUser=null;ticketFormsImportState=null;window.releaseUpload()")
        wait("return !ticketDriveBusy")
        check(js("return window.oldSignal.aborted&&ticketDriveQueue.length===0&&!document.getElementById('ticketDriveFileList').textContent"), 'Logout manteve arquivo ou resposta anterior')
        # Manter o Painel de Chamados com permissao individual, fora desta tela.
        js("currentUser={id:43,role:'sector',ticketPanelAccess:true};switchView('ticketadmin')")
        wait("return canSyncTickets()")
        check(js("return window.boardRenders>0"), "Painel externo alterado")
        js("stopCentralTicketSync();currentUser={id:1,role:'admin'};window.holdReads=true;switchView('tickets')")
        wait("return ticketPullInProgress")
        js("currentUser={id:41,role:'sector'};window.calls=[];switchView('tickets')")
        wait("return !ticketPullInProgress")
        check(js("return !document.getElementById('ticketTable')&&window.calls.length===0"), "Leitura anterior reativou lista comum")
        errors=[e for e in driver.get_log('browser') if e['level']=='SEVERE' and ('Uncaught' in e['message'] or 'SyntaxError' in e['message'])]
        check(not errors, str(errors))
        print(json.dumps({'checks':checks,'result':'OK — perfis, DOM, leituras simuladas, retorno e responsividade','screenshots':str(output)},ensure_ascii=False))
    except Exception:
        driver.save_screenshot(str(output/'failure.png'))
        print('Diagnostico local:', output, driver.get_log('browser'))
        raise
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
