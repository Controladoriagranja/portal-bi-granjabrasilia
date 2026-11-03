"""Chrome local, HTTP bloqueado, DOM e fetch simulados. Não abre o portal real."""
import json
from pathlib import Path
import re
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

ROOT = Path(__file__).resolve().parents[1]


def main():
    drivers=list((Path.home()/'.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
    if not drivers: raise RuntimeError('Requer Chrome/driver local; nenhum download permitido.')
    options=Options();options.binary_location=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    for arg in ('--headless=new','--disable-background-networking','--disable-extensions','--disable-sync','--no-first-run'):
        options.add_argument(arg)
    options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
    driver=webdriver.Chrome(service=Service(str(max(drivers,key=lambda p:tuple(map(int,p.parent.name.split('.'))))),log_output=subprocess.DEVNULL),options=options)
    checks=0
    def check(value,message):
        nonlocal checks
        if not value: raise AssertionError(message)
        checks+=1
    try:
        driver.execute_cdp_cmd('Network.enable',{})
        driver.execute_cdp_cmd('Network.setBlockedURLs',{'urls':['http://*','https://*']})
        driver.get('about:blank')
        driver.execute_script("""
          document.body.innerHTML=['eu','newUser'].map(p=>`<select id="${p==='eu'?'euRole':'newUserRole'}"><option value="sector">Setor</option><option value="admin">Admin</option><option value="director">Diretor</option></select><div id="${p}OperationPermissions"></div>`).join('');
          window.fixtureRole='sector';window.pending=[];
          window.portalApiRequest=path=>new Promise(resolve=>pending.push({path,resolve}));
        """)
        driver.execute_script((ROOT/'assets/js/zootecnico-access.js').read_text(encoding='utf-8'))
        js=driver.execute_script
        check(js("return !!document.getElementById('euZooMode')"),'Modal montado')
        js("loadZootecnicoAccessForm('eu',41)")
        check(js("return pending[0].path.endsWith('/41/zootecnico-access')"),'ID permanente no cadastro')
        js("pending.shift().resolve({ok:true,access:{mode:'proprio',technicianIds:['t1']},technicians:[{id:'t1',nome:'Técnico A',ativo:true},{id:'t2',nome:'Técnico B',ativo:true}]})")
        check(js("return readZootecnicoAccessForm('eu').technicianIds.join()==='t1'"),'Vínculo próprio carregado')
        js("document.getElementById('euZooMode').value='equipe';document.getElementById('euZooMode').dispatchEvent(new Event('change'));for(const o of document.getElementById('euZooIds').options)o.selected=!!o.value")
        check(js("return readZootecnicoAccessForm('eu').technicianIds.length===2"),'Equipe com dois técnicos')
        js("document.getElementById('euRole').value='director';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return document.getElementById('euZooMode').disabled && readZootecnicoAccessForm('eu').mode==='todos'"),'Gestor visão geral')
        js("document.getElementById('euRole').value='sector';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return readZootecnicoAccessForm('eu').mode==='none'"),'Rebaixamento não herda acesso geral')
        js("loadZootecnicoAccessForm('eu',42);loadZootecnicoAccessForm('eu',43)")
        js("pending[1].resolve({ok:true,access:{mode:'proprio',technicianIds:['t2']},technicians:[{id:'t2',nome:'Técnico B',ativo:true}]})")
        js("pending[0].resolve({ok:true,access:{mode:'todos',technicianIds:[]},technicians:[]});pending=[]")
        check(js("return readZootecnicoAccessForm('eu').technicianIds.join()==='t2'"),'Resposta antiga não troca usuário')
        js("loadZootecnicoAccessForm('eu',44);pending.shift().resolve({ok:false})")
        check(js("return readZootecnicoAccessForm('eu')===undefined"),'Falha preserva permissão existente')
        # Layout real dos dois grupos nas larguras de telefone/tablet/PC.
        for width in (390,768,1366):
            driver.set_window_size(width,900)
            check(js("return document.documentElement.scrollWidth<=innerWidth"),f'Sem rolagem horizontal em {width}px')
        api_source=(ROOT/'integrations/zootecnico/frontend/assets/js/api.js').read_text(encoding='utf-8')
        bootstrap="""
          const APP_CONFIG={API_URL:'https://offline.invalid',endpoints:{desempenho:'/api/bi/zootecnico/resumo',detalhes:'/api/bi/zootecnico/detalhes'}};
          let mockToken='first';getPortalToken=()=>mockToken;
          let optionsSeen;fetch=async(url,options)=>{optionsSeen=options;return {ok:true,json:async()=>({ok:true})}};
        """
        result=driver.execute_async_script(api_source+'\n'+bootstrap+"""
          const done=arguments[arguments.length-1];
          requestApi('/api/bi/lotes-abertos/filtros',{}, {cache:'force-cache'}).then(()=>done({cache:optionsSeen.cache,credentials:optionsSeen.credentials,authorization:optionsSeen.headers.Authorization})).catch(e=>done({error:e.message}));
        """)
        check(result.get('cache')=='no-store','Respostas pessoais nunca usam cache HTTP')
        check(result.get('credentials')=='omit','Não envia cookies/Basic pelo frontend')
        check(result.get('authorization')=='Bearer first','Sessão em cabeçalho')
        result=driver.execute_async_script(api_source+'\n'+bootstrap+"""
          const done=arguments[arguments.length-1];
          fetch=async()=>{mockToken='second';return {ok:true,json:async()=>({ok:true})}};
          requestApi('/api/bi/lotes-abertos/filtros').then(()=>done('leak')).catch(e=>done(e.code));
        """)
        check(result=='SESSION_CHANGED','Resposta antiga descartada após troca de sessão')
        result=driver.execute_async_script(api_source+'\n'+bootstrap+"""
          const done=arguments[arguments.length-1];
          fetch=async()=>({ok:true,json:async()=>{mockToken='';return {ok:true}}});
          requestApi('/api/bi/lotes-abertos/filtros').then(()=>done('leak')).catch(e=>done(e.code));
        """)
        check(result=='SESSION_CHANGED','Logout durante leitura JSON descarta dados')
        # Compilar todos os scripts inline sem executá-los (sem login/polling).
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        clear_token=re.search(r'(?m)^function clearPortalToken\(\) \{[\s\S]*?^\}',html).group()
        result=js("""
          document.body.insertAdjacentHTML('beforeend','<div id="modalOverlay" class="open"></div><iframe id="reportIframe"></iframe>');
          let portalSessionGeneration=0,neonSessionToken='mock',exited=false;
          const stopTicketFormsImport=()=>{},stopCentralTicketSync=()=>{},stopUpdateMonitor=()=>{};
          const exitReportFullscreen=()=>{exited=true};
        """+clear_token+"""
          clearPortalToken();return {blank:document.getElementById('reportIframe').src==='about:blank',closed:!document.getElementById('modalOverlay').classList.contains('open'),generation:portalSessionGeneration,exited};
        """)
        check(result['blank'] and result['closed'] and result['generation']==1,'Perda de sessão descarta iframe e incrementa geração')
        check(result['exited'],'Logout encerra fullscreen pelo helper existente')
        for script in re.findall(r'<script\b[^>]*>([\s\S]*?)</script>',html,re.I):
            if script.strip(): js('new Function(arguments[0])',script)
        check(True,'JavaScript do portal compila')
        errors=[item['message'] for item in driver.get_log('browser') if item['level']=='SEVERE']
        check(not errors,'Sem erro de console: '+json.dumps(errors,ensure_ascii=False))
        print(json.dumps({'checks':checks,'network':'blocked','live_services':False},ensure_ascii=False))
    finally:
        driver.quit()


if __name__=='__main__':main()
