"""Regressao dos controles do portal em Chrome oculto, sem acesso a APIs reais."""
import re
import tempfile
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
html = (ROOT / 'index.html').read_text(encoding='utf-8')
# Keep the real DOM and handlers; skip authentication/bootstrap only.
html = html.replace('await initApp();', '/* offline fixture */')
options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1440,1000')
driver = webdriver.Chrome(options=options)
try:
 driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
 window.fetch=async()=>{throw new Error('Network disabled by UI test');};
 window.__errors=[];
 window.addEventListener('error',e=>window.__errors.push(e.message));
 '''})
 with tempfile.TemporaryDirectory() as folder:
  page=Path(folder)/'portal.html'
  page.write_text(html,encoding='utf-8')
  driver.get(page.as_uri())
 driver.set_window_size(390,844)
 for screen in ['login','pending']:
  driver.execute_script('showScreen(arguments[0])',screen)
  assert not driver.find_element(By.ID,'mobileNav').is_displayed(),screen
 driver.set_window_size(1440,1000)
 print('OK: nenhuma navegacao mobile no login ou acesso pendente')
 driver.execute_script('''
 SECTORS=['comercial','operacional'];
 db.users=[{id:1,name:'Admin Teste',email:'admin@example.test',role:'admin',status:'active',sectors:[...SECTORS]},
 {id:2,name:'Usuario Teste',email:'user@example.test',role:'sector',status:'active',sectors:['comercial'],reportAccessMode:'specific',reportIds:[101]}];
 db.reports=[{id:101,title:'Comercial Teste',sector:'comercial',url:'about:blank'},
 {id:102,title:'Operacional Teste',sector:'operacional',url:'about:blank'}];
 currentUser=db.users[0]; initPortal(); showScreen('portal');
 ''')
 # Every inline handler must compile and reference an existing global function.
 failures=driver.execute_script('''
 const failures=[];
 for(const el of document.querySelectorAll('*')) for(const a of el.attributes) {
 if(!/^on/.test(a.name)) continue;
 try {new Function('event',a.value);} catch(e){failures.push(a.value+': '+e.message);}
 const calls=[...a.value.matchAll(/(?<![.\\w])([A-Za-z_$][\\w$]*)\\s*\\(/g)];
 for(const [,name] of calls) if(!['if','for','while','switch','catch','function'].includes(name) && typeof window[name]!=='function') failures.push(name);
 }
 return [...new Set(failures)];
 ''')
 assert not failures, failures
 print('OK: handlers de todos os controles presentes compilam e existem')
 for view in ['reports','updates','tickets','ticketadmin','users','access','reportsmgr','sectors','changepass']:
  driver.find_element(By.ID,'nav-'+view).click()
  assert driver.find_element(By.ID,'view-'+view).is_displayed(),view
 print('OK: navegacao por todas as nove telas')
 driver.find_element(By.ID,'nav-users').click()
 driver.execute_script('openEditUser(2)')
 def label(group,value):
  return driver.find_element(By.CSS_SELECTOR,f'#{group} label:has(input[value="{value}"])')
 def selected(group,value):
  return driver.find_element(By.CSS_SELECTOR,f'#{group} input[value="{value}"]').is_selected()
 for _ in range(2):
  label('euSectorCheckGroup','operacional').click()
  assert selected('euSectorCheckGroup','operacional')
  assert 'checked' in label('euSectorCheckGroup','operacional').get_attribute('class')
  assert selected('euReportCheckGroup','101'), 'Existing page selection lost'
  label('euSectorCheckGroup','operacional').click()
  assert not selected('euSectorCheckGroup','operacional')
 assert selected('euReportCheckGroup','101')
 label('euSectorCheckGroup','operacional').click()
 # Nested text and native keyboard activation must toggle exactly once too.
 label('euReportCheckGroup','102').find_element(By.TAG_NAME,'strong').click()
 assert selected('euReportCheckGroup','102')
 driver.execute_script("document.querySelector('#euReportCheckGroup input[value=\"102\"]').focus()")
 driver.switch_to.active_element.send_keys(Keys.SPACE)
 assert not selected('euReportCheckGroup','102')
 label('euReportCheckGroup','102').click()
 driver.execute_script('''window.__saved=null; patchAdminUser=async(u,data)=>{window.__saved=data;Object.assign(u,data);};''')
 driver.find_element(By.ID,'saveEditUserBtn').click()
 saved=driver.execute_script('return window.__saved')
 assert saved['sectors']==['comercial','operacional'] and saved['reportIds']==[101,102],saved
 assert not driver.find_element(By.ID,'saveEditUserBtn').get_attribute('disabled')
 driver.execute_script('openEditUser(2)')
 assert selected('euSectorCheckGroup','operacional') and selected('euReportCheckGroup','102')
 driver.find_element(By.CSS_SELECTOR,'#editUserOverlay .modal-close').click()
 print('OK: selecao repetida, texto interno, teclado, salvamento e reabertura do usuario')
 driver.find_element(By.ID,'nav-access').click()
 driver.execute_script("document.getElementById('newUserRole').value='sector';toggleSectorField();document.getElementById('newUserReportMode').value='specific';toggleNewUserReportMode();")
 label('sectorCheckGroup','comercial').click()
 assert selected('sectorCheckGroup','comercial')
 label('newUserReportCheckGroup','101').click()
 label('sectorCheckGroup','operacional').click()
 assert selected('newUserReportCheckGroup','101')
 label('sectorCheckGroup','comercial').click()
 assert not driver.find_elements(By.CSS_SELECTOR,'#newUserReportCheckGroup input[value="101"]')
 print('OK: cadastro de acesso preserva paginas e remove as de setores desmarcados')
 # Open/cancel flows and board modes use real clicks, not direct handler calls.
 driver.find_element(By.ID,'nav-reportsmgr').click()
 driver.find_element(By.CSS_SELECTOR,'button[onclick="openAddReport()"]').click()
 assert driver.find_element(By.ID,'rFormPanel').is_displayed()
 driver.find_element(By.CSS_SELECTOR,'button[onclick="cancelReportForm()"]').click()
 assert not driver.find_element(By.ID,'rFormPanel').is_displayed()
 driver.find_element(By.ID,'nav-tickets').click()
 driver.find_element(By.CSS_SELECTOR,'button[onclick="openNewTicket()"]').click()
 assert driver.find_element(By.ID,'newTicketView').is_displayed()
 driver.find_element(By.CSS_SELECTOR,'#newTicketView button[onclick="closeNewTicket()"]').click()
 assert driver.find_element(By.ID,'ticketListView').is_displayed()
 driver.find_element(By.ID,'nav-ticketadmin').click()
 driver.find_element(By.ID,'chGanttBtn').click()
 assert 'active' in driver.find_element(By.ID,'chGanttPanel').get_attribute('class')
 driver.find_element(By.ID,'chBoardBtn').click()
 assert 'active' in driver.find_element(By.ID,'chBoardPanel').get_attribute('class')
 driver.find_element(By.CSS_SELECTOR,'button[onclick="openInternalDemandModal()"]').click()
 assert driver.find_element(By.ID,'internalDemandModal').is_displayed()
 driver.find_element(By.CSS_SELECTOR,'#internalDemandModal button[onclick="closeInternalDemandModal()"]').click()
 assert not driver.find_element(By.ID,'internalDemandModal').is_displayed()
 print('OK: abrir/cancelar relatorio, chamado, demanda interna e alternar Quadro/Gantt')
 driver.execute_script("showToast('Confirmacao visivel durante navegacao mobile','success')")
 driver.set_window_size(390,844)
 for button,view in [('mnReports','reports'),('mnPwd','changepass'),('mnAdmin','users'),('mnUpdates','updates')]:
  driver.find_element(By.ID,button).click()
  assert driver.find_element(By.ID,'view-'+view).is_displayed(),view
 print('OK: navegacao mobile incluindo Central de Atualizacoes para admin')
 driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',{'width':320,'height':740,'deviceScaleFactor':1,'mobile':True})
 for button in driver.find_elements(By.CSS_SELECTOR,'#mobileNav button'):
  if button.is_displayed():
   box=button.rect
   assert box['x']>=0 and box['x']+box['width']<=320,box
 for role in ['sector','director']:
  driver.execute_script("currentUser={...db.users[1],role:arguments[0],ticketPanelAccess:true};initPortal();showScreen('portal');",role)
  assert not driver.find_element(By.ID,'mnUpdates').is_displayed(),role
  assert driver.execute_script("return getComputedStyle(document.getElementById('nav-updates')).display")=='none'
  driver.execute_script("switchView('updates',null)")
  assert driver.find_element(By.ID,'view-reports').is_displayed(),role
 driver.execute_script("currentUser=db.users[0];initPortal();showScreen('portal');")
 driver.find_element(By.ID,'mnLogout').click()
 WebDriverWait(driver,5).until(lambda d:d.find_element(By.ID,'screen-login').is_displayed())
 assert not driver.find_element(By.ID,'mobileNav').is_displayed()
 driver.execute_script("switchView('updates',null)")
 assert 'active' not in driver.find_element(By.ID,'view-updates').get_attribute('class')
 print('OK: menu cabe em 320px; setor/diretor e usuario desconectado sem acesso a Atualizacoes')
 errors=driver.execute_script('return window.__errors')
 assert not errors, errors
 print('OK: nenhum erro JavaScript nas interacoes')
finally:
 driver.quit()
