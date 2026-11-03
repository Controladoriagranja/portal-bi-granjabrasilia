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
        from test_zootecnico_canonical import seed_catalog
        seed=seed_catalog();identities=[]
        for entity in seed['entidades']:
            aliases={}
            for alias in seed['aliases']:
                if alias['entidade_id']==entity['id']:aliases.setdefault(alias['fonte'],[]).append(alias['valor'])
            identities.append(dict(id=entity['id'],name=entity['nome'],aliases=aliases,aliasCount=sum(map(len,aliases.values())),missingSources=[]))
        ids={i['name']:i['id'] for i in identities}
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        helpers='\n'.join(re.search(r'(?m)^function '+name+r'\([^\n]*(?:[\s\S]*?^\}|$)',html).group() for name in ('normalizeAccessSearch','filterAccessLinks'))
        driver.execute_script("""
          document.body.innerHTML=['eu','newUser'].map(p=>`<input id="${p==='eu'?'euName':'newUserName'}" value="Conta de teste"><input id="${p==='eu'?'euEmail':'newUserEmail'}" value="offline@example.invalid"><select id="${p==='eu'?'euRole':'newUserRole'}"><option value="sector">Setor</option><option value="admin">Admin</option><option value="director">Diretor</option></select><div id="${p}OperationPermissions"></div>`).join('');
          window.pending=[];window.requests=[];window.accessLinkRows={};
          window.portalApiRequest=(path,options)=>{requests.push({path,options});return new Promise(resolve=>pending.push({path,resolve}));};
        """+helpers+"""
          window.normalizeAccessSearch=normalizeAccessSearch;window.filterAccessLinks=filterAccessLinks;
          window.identities=arguments[0];window.ids=arguments[1];
          window.users=[{id:41,name:'Pessoa Um',email:'one@example.invalid',active:true,identityId:ids['CRISTIANO VALADARES BARRETO']},{id:42,name:'Pessoa Dois',email:'two@example.invalid',active:true,identityId:ids['MARIANA LEMAR CARDOSO']},{id:43,name:'Bloqueado',email:'blocked@example.invalid',active:false,identityId:null}];
        """,identities,ids)
        driver.execute_script((ROOT/'assets/js/zootecnico-access.js').read_text(encoding='utf-8'))
        js=driver.execute_script
        check(js("return !!document.getElementById('euZooMode')"),'Modal montado')
        js("loadZootecnicoAccessForm('eu',41);pending.shift().resolve({ok:true,access:{mode:'todos',userIds:[],identityId:null},identities,users})")
        check(js("return readZootecnicoAccessForm('eu')===undefined && document.getElementById('euZooMode').value==='todos'"),'Acesso geral anterior preservado ao editar outros campos')
        js("document.getElementById('euZooMode').value='proprio';document.getElementById('euZooMode').dispatchEvent(new Event('change'));document.getElementById('euZooSearch').value='CVB';document.getElementById('euZooSearch').dispatchEvent(new Event('input'))")
        check(js("return readZootecnicoAccessForm('eu').identityId===ids['CRISTIANO VALADARES BARRETO']"),'Cristiano selecionado uma vez por código confirmado')
        check(js("return document.getElementById('euZooCode').hidden && document.getElementById('euZooMatches').textContent.includes('Selecionado automaticamente')"),'Pesquisa reutiliza o comportamento do Comercial')
        check(js("return !document.querySelector('select[multiple]') && !document.querySelector('[data-source]')"),'Sem listas múltiplas por fonte')
        check(js("return !('resolutions' in readZootecnicoAccessForm('eu')) && !('technicianIds' in readZootecnicoAccessForm('eu'))"),'Payload contém somente a identidade canônica')
        check(js("return document.getElementById('euZooAliases').textContent.includes('CVB - CRISTIANO')"),'Resumo recupera aliases confirmados')
        js("document.getElementById('euZooSearch').value='JDS';document.getElementById('euZooSearch').dispatchEvent(new Event('input'))")
        check(js("return readZootecnicoAccessForm('eu').identityId===ids['JOELMIR DIVINO DOS SANTOS']"),'Troca por Joelmir sem alterar nome da conta')
        js("document.getElementById('euZooSearch').value='MLC';document.getElementById('euZooSearch').dispatchEvent(new Event('input'))")
        check(js("return readZootecnicoAccessForm('eu').identityId===ids['MARIANA LEMAR CARDOSO']"),'Mariana selecionada por sigla validada')
        check(js("return requests.every(r=>!r.options?.method || r.options.method==='GET')"),'Cadastro não depende da API especializada ou de polling')
        js("loadZootecnicoAccessForm('eu',41);pending.shift().resolve({ok:true,access:{mode:'proprio',identityId:ids['CRISTIANO VALADARES BARRETO'],userIds:[]},identities,users})")
        check(js("return document.getElementById('euZooCode').value===ids['CRISTIANO VALADARES BARRETO'] && readZootecnicoAccessForm('eu')===undefined"),'Reabrir recupera o vínculo salvo')
        js("document.getElementById('euZooMode').value='equipe';document.getElementById('euZooMode').dispatchEvent(new Event('change'));document.querySelector('#euZooUsers input[value=\"41\"]').click();document.querySelector('#euZooUsers input[value=\"42\"]').click()")
        check(js("return readZootecnicoAccessForm('eu').userIds.join()==='41,42'"),'Equipe usa usuários do portal')
        check(js("return document.querySelector('#euZooUsers input[value=\"43\"]').disabled"),'Usuário inativo não é selecionável')
        js("document.getElementById('euRole').value='director';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return document.getElementById('euZooMode').disabled && readZootecnicoAccessForm('eu').mode==='todos'"),'Diretor mantém visão geral')
        js("document.getElementById('euRole').value='sector';document.getElementById('euRole').dispatchEvent(new Event('change'))")
        check(js("return readZootecnicoAccessForm('eu').mode==='none'"),'Rebaixamento não herda geral')
        js("loadZootecnicoAccessForm('eu',42);loadZootecnicoAccessForm('eu',43);pending[1].resolve({ok:true,access:{mode:'proprio',identityId:ids['MARIANA LEMAR CARDOSO'],userIds:[]},identities,users});pending[0].resolve({ok:true,access:{mode:'todos',userIds:[]},identities,users});pending=[]")
        check(js("return document.getElementById('euZooCode').value===ids['MARIANA LEMAR CARDOSO']"),'Resposta atrasada não troca vínculo')
        js("loadZootecnicoAccessForm('eu',44);pending.shift().resolve({ok:false})")
        check(js("return readZootecnicoAccessForm('eu')===undefined"),'Falha mantém permissões atuais')
        js("loadZootecnicoAccessForm('newUser',0);pending.shift().resolve({ok:true,access:{mode:'none',userIds:[]},identities,users})")
        js("document.getElementById('newUserZooMode').value='proprio';document.getElementById('newUserZooMode').dispatchEvent(new Event('change'))")
        check(js("return readZootecnicoAccessForm('newUser').identityId===null && readZootecnicoAccessForm('newUser').allowPending"),'Ausência de seleção fica pendente, sem inferir por nome')
        js("document.body.insertAdjacentHTML('beforeend','<input id=fixtureCommercialSearch><select id=fixtureCommercialCode></select><small id=fixtureCommercialMatches></small>');accessLinkRows.fixture=[{code:'7',label:'7 - Pessoa Um'},{code:'8',label:'8 - Pessoa Dois'}];document.getElementById('fixtureCommercialSearch').value='7';filterAccessLinks('fixture')")
        check(js("return document.getElementById('fixtureCommercialCode').value==='7' && document.getElementById('fixtureCommercialCode').hidden"),'Comercial conserva os mesmos IDs e seleção automática')
        for width in (390,768,1366):
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
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
