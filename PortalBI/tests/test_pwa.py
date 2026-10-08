"""Quick PWA HTTP/browser checks; API responses are mocked, no production writes."""
import json
import struct
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '/portal-bi-granjabrasilia/'
class Handler(SimpleHTTPRequestHandler):
 def translate_path(self, path):
  if path.startswith(PREFIX): path = '/' + path[len(PREFIX):]
  return super().translate_path(path)
 def handle(self):
  try: super().handle()
  except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError): pass
 def copyfile(self, source, outputfile):
  try: super().copyfile(source, outputfile)
  except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError): pass
 def log_message(self, *args): pass

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1440,1000')
options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
driver = webdriver.Chrome(options=options)
try:
 driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': '''
 const originalFetch=window.fetch;
 window.fetch=(url,options)=>new URL(url,location.href).origin===location.origin
   ? originalFetch(url,options)
   : Promise.resolve(new Response(JSON.stringify({status:'ok'}),{status:200,headers:{'Content-Type':'application/json'}}));
 '''})
 for path in ['/', PREFIX]:
  page = base + path
  with urlopen(page) as response:
   assert response.status == 200
  manifest_url = urljoin(page,'./manifest.webmanifest')
  with urlopen(manifest_url) as response:
   manifest=json.loads(response.read().decode('utf-8-sig'))
  assert manifest['name']=='Portal BI Granja Brasília'
  assert manifest['display']=='standalone'
  assert urljoin(manifest_url,manifest['start_url']) == page
  assert urljoin(manifest_url,manifest['scope']) == page
  for icon in manifest['icons'] + [{'src':'assets/pwa/apple-touch-icon.png','sizes':'180x180'}]:
   with urlopen(urljoin(manifest_url,icon['src'])) as response:
    data=response.read()
   assert data[:8]==b'\x89PNG\r\n\x1a\n'
   size=struct.unpack('>II',data[16:24])
   assert 'x'.join(map(str,size))==icon['sizes']
 print('OK: manifesto, escopo, start_url e PNGs em / e no subcaminho GitHub Pages')
 driver.get(base+PREFIX)
 wait=WebDriverWait(driver,5)
 actual=driver.execute_cdp_cmd('Page.getAppManifest',{})
 assert not actual.get('errors'),actual
 assert json.loads(actual['data'].lstrip('\ufeff'))['short_name']=='Portal BI'
 print('OK: Chrome carregou e interpretou o manifesto sem erros')
 # Synthetic browser event verifies our click flow; it does not install an OS app.
 driver.execute_script('''
 window.__promptCount=0;
 window.__installEvent=new Event('beforeinstallprompt',{cancelable:true});
 __installEvent.prompt=async()=>{__promptCount++;};
 __installEvent.userChoice=Promise.resolve({outcome:'dismissed'});
 dispatchEvent(__installEvent);
 ''')
 assert driver.execute_script('return __installEvent.defaultPrevented && __promptCount===0')
 driver.find_element(By.CSS_SELECTOR,'.pwa-install-login').click()
 wait.until(lambda d:d.execute_script('return __promptCount===1'))
 assert not driver.find_element(By.CSS_SELECTOR,'.pwa-install-login').is_displayed()
 driver.execute_script('''
 const event=new Event('beforeinstallprompt',{cancelable:true});
 event.prompt=async()=>{__promptCount++;};event.userChoice=Promise.resolve({outcome:'accepted'});
 dispatchEvent(event);
 ''')
 driver.find_element(By.CSS_SELECTOR,'.pwa-install-login').click()
 wait.until(lambda d:d.execute_script("return localStorage.getItem('portal-bi-pwa-installed')==='1'"))
 driver.refresh()
 assert not driver.find_element(By.CSS_SELECTOR,'.pwa-install-login').is_displayed()
 print('OK: prompt apenas por clique, recusa, aceite e ocultacao apos instalacao')
 driver.execute_script('localStorage.clear()')
 driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
 driver.execute_cdp_cmd('Network.setUserAgentOverride',{'userAgent':'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'})
 driver.refresh()
 assert not driver.find_element(By.ID,'pwaInstallHelp').is_displayed()
 driver.find_element(By.CSS_SELECTOR,'.pwa-install-login').click()
 assert driver.find_element(By.ID,'pwaInstallHelp').is_displayed()
 assert 'Adicionar à Tela de Início' in driver.find_element(By.ID,'pwaInstallHelp').text
 driver.find_element(By.CSS_SELECTOR,'[data-pwa-close]').click()
 assert not driver.find_element(By.ID,'pwaInstallHelp').is_displayed()
 # Check the portal header in mobile dimensions independently of authentication.
 driver.execute_script("showScreen('portal')")
 button=driver.find_element(By.CSS_SELECTOR,'.topbar > [data-pwa-install]')
 assert button.is_displayed()
 box=button.rect
 assert box['x']>=0 and box['x']+box['width']<=390,box
 button.click()
 assert driver.find_element(By.ID,'pwaInstallHelp').is_displayed()
 driver.find_element(By.CSS_SELECTOR,'[data-pwa-close]').click()
 print('OK: iOS simulado, instrucoes por toque e botao mobile no cabecalho')
 # Standalone mode detection, including iOS navigator.standalone.
 driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':"Object.defineProperty(navigator,'standalone',{get:()=>true});"})
 driver.refresh()
 assert all(not b.is_displayed() for b in driver.find_elements(By.CSS_SELECTOR,'[data-pwa-install]'))
 assert driver.execute_script('return navigator.serviceWorker.getRegistrations().then(x=>x.length)') == 0
 assert driver.execute_script('return caches.keys().then(x=>x.length)') == 0
 logs=[x for x in driver.get_log('browser') if x['level']=='SEVERE']
 assert not logs,logs
 print('OK: standalone oculta a opcao; nenhum service worker/cache ou erro de console')
finally:
 driver.quit()
 server.shutdown()
 server.server_close()
