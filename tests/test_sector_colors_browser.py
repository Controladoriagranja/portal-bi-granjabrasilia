"""Chrome offline: criação, edição, ponteiro, teclado e mobile com API simulada."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

ROOT=Path(__file__).resolve().parents[1]

def main():
    drivers=list((Path.home()/'.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
    if not drivers:raise RuntimeError('ChromeDriver local necessário; não baixar dependências.')
    options=Options();options.binary_location=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    for arg in ('--headless=new','--disable-background-networking','--disable-extensions','--disable-sync','--no-first-run'):
        options.add_argument(arg)
    options.set_capability('goog:loggingPrefs',{'browser':'ALL'})
    driver=webdriver.Chrome(service=Service(str(max(drivers,key=lambda p:tuple(map(int,p.parent.name.split('.'))))),log_output=subprocess.DEVNULL),options=options)
    try:
        driver.execute_cdp_cmd('Network.enable',{})
        driver.execute_cdp_cmd('Network.setBlockedURLs',{'urls':['http://*','https://*']})
        driver.get('data:text/html,<html><head></head><body></body></html>')
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        driver.execute_script('document.documentElement.innerHTML=arguments[0]',html)
        driver.execute_script("let style=document.createElement('style');style.textContent=arguments[0];document.head.appendChild(style);window.fetch=()=>Promise.reject(new Error('HTTP bloqueado'));",(ROOT/'assets/css/sector-colors.css').read_text(encoding='utf-8'))
        for source in re.findall(r'<script>([\s\S]*?)</script>',html)+[(ROOT/'assets/js/sector-colors.js').read_text(encoding='utf-8'),(ROOT/'assets/js/user-management.js').read_text(encoding='utf-8')]:
            driver.execute_script("let script=document.createElement('script');script.textContent=arguments[0];document.head.appendChild(script)",source)
        driver.execute_script("""
          db.users=[{id:1,dbId:1,name:'Admin',email:'offline@example.invalid',role:'admin',status:'active',sectors:['integracao']}];
          currentUser=db.users[0];db.sectors=['integracao'];db.sectorMeta={integracao:{label:'Integração',color:'#34d399'}};
          db.reports=[{id:13,title:'BI Integração',sector:'integracao',url:'https://not-used.invalid',desc:''}];syncSectors();
          window.testCalls=[];window.failSave=false;showToast=()=>{};
          portalApiRequest=async(path,options)=>{
            const body=JSON.parse(options.body);testCalls.push({path,method:options.method,body});
            if(failSave)throw new Error('Falha de teste');
            const data=JSON.parse(JSON.stringify(db));
            const code=options.method==='POST'?'fabrica_de_racao':decodeURIComponent(path.split('/').at(-1));
            if(!data.sectors.includes(code))data.sectors.push(code);
            data.sectorMeta[code]={label:body.name,color:body.color};return {ok:true,data};
          };
          document.querySelectorAll('.screen').forEach(el=>el.classList.remove('active'));
          document.getElementById('screen-portal').classList.add('active');
          document.querySelectorAll('.view').forEach(el=>el.classList.remove('active'));
          document.getElementById('view-sectors').classList.add('active');
          mountSectorColorPicker('newSectorColorPicker');renderSectorsList();
        """)
        result=driver.execute_async_script("""
          const done=arguments[0];(async()=>{
            let count=0;function check(value,message){if(!value)throw new Error(message);count++;}
            const picker=mountSectorColorPicker('newSectorColorPicker');
            check(getComputedStyle(document.querySelector('#newSectorColorPicker .sector-color-hue')).backgroundImage.includes('linear-gradient'),'Faixa de matiz visível apesar do tema');
            check(picker.get()==='#58A6FF','Cor inicial anterior preservada');
            for(const hex of ['#000000','#FFFFFF','#D84FA2','#123456','#34D399']){picker.set(hex);check(picker.get()===hex,'Cor arbitrária '+hex);}
            const input=document.querySelector('#newSectorColorPicker .sector-color-hex');
            input.value='abc';input.dispatchEvent(new Event('input'));input.dispatchEvent(new Event('blur'));
            check(picker.get()==='#AABBCC' && input.value==='#AABBCC','HEX curto normalizado');
            input.value='xyz';input.dispatchEvent(new Event('input'));
            check(input.getAttribute('aria-invalid')==='true','Validar entrada');
            document.getElementById('newSectorName').value='Fábrica de Ração';await addSector();
            check(testCalls.length===0,'Não enviar cor inválida');
            picker.set('#D84FA2');await addSector();
            check(testCalls[0].body.color==='#D84FA2','Criar com cor escolhida');
            check(db.sectorMeta.fabrica_de_racao.color==='#D84FA2','Cor carregada no catálogo');
            check(sectorTagStyle('fabrica_de_racao').includes('#D84FA222'),'Cor na etiqueta de novo setor');
            check(db.users[0].sectors[0]==='integracao' && db.reports[0].id===13,'Vínculos preservados');
            await editSector('integracao');
            check(document.getElementById('sectorEditDialog').open,'Abrir editor');
            check(document.getElementById('editSectorName').value==='Integração','Nome atual');
            check(mountSectorColorPicker('editSectorColorPicker').get()==='#34D399','Cor atual');
            document.getElementById('editSectorName').value='Outro nome';mountSectorColorPicker('editSectorColorPicker').set('#123456');
            closeSectorEditor();check(testCalls.length===1 && db.sectorMeta.integracao.label==='Integração','Cancelar sem gravar');
            openSectorEditor('integracao');document.getElementById('editSectorName').value='Integração renomeada';
            mountSectorColorPicker('editSectorColorPicker').set('#1B2C3D');
            await saveSectorEditor({preventDefault(){}});
            check(testCalls.at(-1).path.endsWith('/integracao'),'Código estável na edição');
            check(testCalls.at(-1).body.name==='Integração renomeada' && testCalls.at(-1).body.color==='#1B2C3D','Salvar nome e cor juntos');
            check(!document.getElementById('sectorEditDialog').open,'Fechar após sucesso');
            check(sectorLabel('integracao')==='Integração renomeada' && sectorColor('integracao')==='#1B2C3D','Atualizar nome e cor');
            openSectorEditor('integracao');failSave=true;document.getElementById('editSectorName').value='Não salvar';
            await saveSectorEditor({preventDefault(){}});
            check(document.getElementById('sectorEditDialog').open && document.getElementById('editSectorError').textContent.includes('Falha'),'Manter editor em falha');
            check(sectorLabel('integracao')==='Integração renomeada','Sem alteração local em falha');
            failSave=false;closeSectorEditor();
            const pad=document.querySelector('#newSectorColorPicker .sector-color-sv');picker.set('#123456');
            const old=picker.get();pad.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
            check(picker.get()!==old,'Teclado no seletor');
            done({count});
          })().catch(error=>done({error:error.message,stack:error.stack}));
        """)
        if result.get('error'):raise AssertionError(json.dumps(result,ensure_ascii=False))
        pad=driver.find_element(By.CSS_SELECTOR,'#newSectorColorPicker .sector-color-sv')
        old=driver.execute_script("return mountSectorColorPicker('newSectorColorPicker').get()")
        ActionChains(driver).move_to_element(pad).click_and_hold().move_by_offset(30,20).release().perform()
        assert driver.execute_script("return mountSectorColorPicker('newSectorColorPicker').get()")!=old,'Ponteiro deve alterar a cor'
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=True))
        driver.execute_script("openSectorEditor('integracao')")
        dims=driver.execute_script("const r=document.getElementById('sectorEditDialog').getBoundingClientRect();return {width:r.width,viewport:innerWidth,page:document.documentElement.scrollWidth}")
        assert dims['width']<=dims['viewport'] and dims['page']<=dims['viewport'],dims
        screenshot=Path(tempfile.gettempdir())/'portal-sector-color-mobile.png';driver.save_screenshot(str(screenshot))
        errors=[e for e in driver.get_log('browser') if e['level']=='SEVERE' and e.get('source')=='javascript']
        assert not errors,errors
        print(f"Chrome offline: {result['count']} verificações + ponteiro + largura mobile, sem erros JavaScript. Imagem: {screenshot}")
    finally:driver.quit()

if __name__=='__main__':main()
