"""Chrome local, HTTP bloqueado, DOM e fetch simulados. Não abre o portal real."""
import json
from pathlib import Path
import re
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

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
          document.body.innerHTML=['eu','newUser'].map(p=>`<input id="${p==='eu'?'euName':'newUserName'}" value="Joelmir Divino dos Santos"><input id="${p==='eu'?'euEmail':'newUserEmail'}" value="offline@example.invalid"><select id="${p==='eu'?'euRole':'newUserRole'}"><option value="sector">Setor</option><option value="admin">Admin</option><option value="director">Diretor</option></select><div id="${p}OperationPermissions"></div>`).join('');
          window.pending=[];window.previews=[];
          window.previewResult={ok:true,ready:true,persons:[],options:{}};
          window.portalApiRequest=(path,options)=>{
            if(options?.method==='POST'){previews.push(JSON.parse(options.body));return Promise.resolve(previewResult);}
            return new Promise(resolve=>pending.push({path,resolve}));
          };
          window.users=[{id:41,name:'Joelmir Divino dos Santos',email:'offline@example.invalid',active:true},{id:42,name:'Outro técnico',email:'other@example.invalid',active:true},{id:43,name:'Bloqueado',email:'blocked@example.invalid',active:false}];
        """)
        driver.execute_script((ROOT/'assets/js/zootecnico-access.js').read_text(encoding='utf-8'))
        js=driver.execute_script
        check(js("return !!document.getElementById('euZooMode')"),'Modal montado')
        js("loadZootecnicoAccessForm('eu',41)")
        check(js("return pending[0].path.endsWith('/41/zootecnico-access')"),'ID permanente no cadastro')
        js("pending.shift().resolve({ok:true,access:{mode:'todos',userIds:[]},users})")
        check(js("return readZootecnicoAccessForm('eu')===undefined && document.getElementById('euZooMode').value==='todos'"),'Permissão anterior geral preservada ao editar outros campos')
        js("document.getElementById('euZooMode').value='proprio';document.getElementById('euZooMode').dispatchEvent(new Event('change'))")
        check(js("return readZootecnicoAccessForm('eu').allowPending===true"),'Novo vínculo permite cadastro pendente sem conceder registros')
        WebDriverWait(driver,3).until(lambda d:d.execute_script("return previews.length>0 && document.getElementById('euZooStatus').textContent.includes('validada')"))
        check(js("return !document.getElementById('euZooIds') && !('technicianIds' in readZootecnicoAccessForm('eu'))"),'Próprio sem segundo cadastro nem seleção do técnico')
        check(js("return previews.at(-1).name==='Joelmir Divino dos Santos'"),'Identificação utiliza o nome do próprio cadastro')
        js("document.getElementById('euZooMode').value='equipe';document.getElementById('euZooMode').dispatchEvent(new Event('change'));document.querySelector('#euZooUsers input[value=\"41\"]').click();document.querySelector('#euZooUsers input[value=\"42\"]').click()")
        WebDriverWait(driver,3).until(lambda d:d.execute_script("try{return readZootecnicoAccessForm('eu')?.userIds.length===2}catch(e){return false}"))
        check(js("return readZootecnicoAccessForm('eu').userIds.join()==='41,42'"),'Equipe seleciona dois usuários do portal')
        check(js("return document.querySelector('#euZooUsers input[value=\"43\"]').disabled"),'Bloqueado não é selecionável')
        js("document.getElementById('euRole').value='director';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return document.getElementById('euZooMode').disabled && readZootecnicoAccessForm('eu').mode==='todos'"),'Gestor visão geral')
        js("document.getElementById('euRole').value='sector';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return readZootecnicoAccessForm('eu').mode==='none'"),'Rebaixamento não herda acesso geral')
        js("loadZootecnicoAccessForm('eu',42);loadZootecnicoAccessForm('eu',43)")
        js("pending[1].resolve({ok:true,access:{mode:'proprio',userIds:[]},users})")
        js("pending[0].resolve({ok:true,access:{mode:'todos',userIds:[]},users});pending=[]")
        check(js("return readZootecnicoAccessForm('eu')===undefined && document.getElementById('euZooMode').value==='proprio'"),'Resposta antiga não troca usuário nem sobrescreve acesso')
        js("loadZootecnicoAccessForm('eu',44);pending.shift().resolve({ok:false})")
        check(js("return readZootecnicoAccessForm('eu')===undefined"),'Falha preserva permissão existente')
        js("""
          previewResult={ok:true,ready:false,persons:[{key:'self',userId:0,name:'Joelmir Divino dos Santos',ready:false,labels:{base_dinamica:[]}}],options:{base_dinamica:['JOELMIR DIVINO DOS SANTOS']}};
          loadZootecnicoAccessForm('newUser',0);pending.shift().resolve({ok:true,access:{mode:'none',userIds:[]},users});
        """)
        js("document.getElementById('newUserZooMode').value='proprio';document.getElementById('newUserZooMode').dispatchEvent(new Event('change'))")
        WebDriverWait(driver,3).until(lambda d:d.execute_script("return !!document.querySelector('#newUserZooMatches select')"))
        check(js("return readZootecnicoAccessForm('newUser').allowPending===true && document.getElementById('newUserZooStatus').textContent.includes('pendente')"),'Correspondência ambígua permite salvar mas continua pendente')
        js("""
          const select=document.querySelector('#newUserZooMatches select[data-source="base_dinamica"]');select.options[0].selected=true;select.dispatchEvent(new Event('change',{bubbles:true}));
        """)
        check(js("return readZootecnicoAccessForm('newUser').resolutions.self.confirmed===false"),'Seleção manual não é declarada confirmada')
        js("previewResult={ok:true,ready:true,persons:[],options:{}};document.querySelector('#newUserZooMatches input[data-confirm]').click()")
        WebDriverWait(driver,3).until(lambda d:d.execute_script("try{return readZootecnicoAccessForm('newUser')?.mode==='proprio'}catch(e){return false}"))
        check(js("return readZootecnicoAccessForm('newUser').resolutions.self.selections.base_dinamica[0]==='JOELMIR DIVINO DOS SANTOS'"),'Resolver no formulário envia somente o valor exato conferido')
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
    except Exception as error:
        detail=driver.execute_script("return {status:[...document.querySelectorAll('[id$=ZooStatus]')].map(e=>e.textContent),previews:window.previews,checked:[...document.querySelectorAll('#euZooUsers input:checked')].map(e=>e.value)}")
        raise AssertionError(json.dumps(detail,ensure_ascii=False)) from error
    finally:
        driver.quit()


if __name__=='__main__':main()
