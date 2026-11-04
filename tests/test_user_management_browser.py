"""Chrome offline: HTML real, eventos reais e API simulada. Sem endpoints reais."""
import json
from pathlib import Path
import re
import subprocess

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

ROOT=Path(__file__).resolve().parents[1]


def main():
    drivers=list((Path.home()/'.cache/selenium/chromedriver/win64').glob('*/chromedriver.exe'))
    if not drivers:raise RuntimeError('Requer ChromeDriver já instalado; não baixar dependências.')
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
        driver.execute_script("window.fetch=()=>Promise.reject(new Error('HTTP proibido neste teste'));")
        scripts=re.findall(r'<script>([\s\S]*?)</script>',html)
        for script in scripts+[ (ROOT/'assets/js/user-management.js').read_text(encoding='utf-8') ]:
            driver.execute_script("let s=document.createElement('script');s.textContent=arguments[0];document.head.appendChild(s)",script)
        driver.execute_script("""
          window.testCalls=[];window.testToasts=[];window.testConfirmation=true;
          window.confirm=()=>testConfirmation;
          showToast=(message,type)=>testToasts.push({message,type});
          portalApiRequest=async(path,options)=>{testCalls.push({path,options});return {ok:true,entries:[]};};
          db.users=[{id:1,dbId:1,name:'Admin',email:'admin@example.invalid',role:'admin',status:'active',sectors:[]},
            {id:2,dbId:2,name:'Operador',email:'operador@example.invalid',role:'sector',status:'active',sectors:[],operationPermissions:['usuarios.gerenciar']},
            {id:3,dbId:3,name:'Comum <img src=x onerror="window.xss=true">',email:'comum@example.invalid',role:'sector',status:'active',sectors:['integracao']},
            {id:4,dbId:4,name:'Excluído',email:'excluido@example.invalid',role:'sector',status:'blocked',sectors:[],deletedAt:'2026-11-04'}];
          db.reports=[{id:13,title:'BI',sector:'integracao',url:'https://not-used.invalid'}];
          db.sectors=['integracao'];db.sectorMeta={};syncSectors();currentUser=db.users[1];initPortal();
        """)
        checks=driver.execute_async_script("""
          const done=arguments[0];
          (async()=>{
            let count=0;function check(value,message){if(!value)throw new Error(message);count++;}
            check(document.querySelector('#view-users.active'),'Inicial em Usuários');
            for(const id of ['nav-reports','nav-tickets','nav-updates','nav-access','nav-ticketadmin','nav-reportsmgr','nav-sectors'])
              check(getComputedStyle(document.getElementById(id)).display==='none','Menu indevido '+id);
            check(getComputedStyle(document.getElementById('nav-users')).display!=='none','Menu usuários');
            check(getComputedStyle(document.getElementById('userAuditButton')).display==='none','Log só Admin');
            check(!document.querySelector('#allUsersTable button[onclick^="openEditUser"]'),'Sem edição delegada');
            check(!document.getElementById('allUsersTable').textContent.includes('excluido@example.invalid'),'Ocultar excluídos');
            check(!document.querySelector('#allUsersTable img'),'Escapar nome em HTML');
            check(!window.xss,'Nenhum script no nome');
            check(getUserReports().length===0,'Sem relatórios');
            check(!canSyncTickets(),'Sem polling chamados');
            switchView('updates');check(document.querySelector('#view-users.active'),'Bloquear rota updates');
            switchView('reports');check(document.querySelector('#view-users.active'),'Bloquear rota relatórios');
            check(testCalls.length===0,'Nenhuma consulta de negócio');
            toggleManagedUserCreate();check(!document.getElementById('managedUserCreate').hidden,'Abrir cadastro');
            check(document.querySelectorAll('#managedUserSectors input').length===1,'Setores no cadastro');
            document.getElementById('managedUserName').value='Novo';document.getElementById('managedUserEmail').value='novo@example.invalid';
            document.getElementById('managedUserPassword').value='fake-password-only';
            await createManagedUser({preventDefault(){}});
            const create=testCalls.pop();const payload=JSON.parse(create.options.body);
            check(create.path==='/api/admin/usuarios' && create.options.method==='POST','Cadastro oficial');
            check(payload.role==='sector' && payload.operationPermissions.length===0,'Sem elevação');
            check(document.getElementById('managedUserPassword').value==='','Limpar senha após sucesso');
            testConfirmation=false;await changeManagedUserStatus(1,'blocked');check(testCalls.length===0,'Cancelar bloqueio Admin');
            testConfirmation=true;await changeManagedUserStatus(1,'blocked');
            const block=testCalls.pop();check(block.path.endsWith('/1/status') && JSON.parse(block.options.body).confirmAdminBlock,'Confirmar bloqueio Admin');
            await deleteManagedUser(1);check(testCalls.length===0 && testToasts.at(-1).message.includes('não pode ser excluído'),'Aviso exclusão Admin');
            await deleteManagedUser(3);check(testCalls.pop().options.method==='DELETE','Exclusão comum');
            restoreManagementNavigation();check(document.getElementById('nav-reports').style.display!=='none','Restaurar navegação ao trocar sessão');
            currentUser=db.users[0];renderUsersTable();
            check(!!document.querySelector('#allUsersTable button[onclick^="openEditUser"]'),'Admin mantém edição');
            check(getComputedStyle(document.getElementById('userAuditButton')).display!=='none','Admin consulta logs');
            document.getElementById('usersArchived').checked=true;renderUsersTable();
            check(document.getElementById('allUsersTable').textContent.includes('excluido@example.invalid'),'Admin vê excluídos');
            check(!!document.querySelector('#allUsersTable button[onclick^="restoreManagedUser"]'),'Admin restaura');
            await loadUserAudit();check(testCalls.pop().path.endsWith('/auditoria'),'Log só sob demanda');
            done({count});
          })().catch(error=>done({error:error.message,stack:error.stack}));
        """)
        if checks.get('error'):raise AssertionError(json.dumps(checks,ensure_ascii=False))
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=True))
        mobile=driver.execute_script("currentUser=db.users[1];initPortal();return {users:!!document.querySelector('#view-users.active'),admin:getComputedStyle(document.getElementById('mnAdmin')).display,reports:getComputedStyle(document.getElementById('mnReports')).display,width:document.documentElement.scrollWidth,viewport:innerWidth};")
        assert mobile['users'] and mobile['admin']!='none' and mobile['reports']=='none',mobile
        assert mobile['width']<=mobile['viewport'],mobile
        errors=[entry for entry in driver.get_log('browser') if entry['level']=='SEVERE' and 'javascript' in entry.get('source','')]
        assert not errors,errors
        print(f"Chrome offline: {checks['count']} verificações desktop + navegação/largura mobile aprovadas; sem erros JavaScript.")
    finally:driver.quit()


if __name__=='__main__':main()
