"""Short local browser tests with fake time/fetch; no Render/Neon connections."""
import re
import tempfile
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

ROOT=Path(__file__).resolve().parents[2]
html=(ROOT/'index.html').read_text(encoding='utf-8').replace('await initApp();','/* offline test */')
html=re.sub(r'<link\b[^>]*>', '', html, flags=re.I)
html=re.sub(r'<script\b[^>]*\bsrc=[^>]*>\s*</script>', '', html, flags=re.I)
options=Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1200,900')
driver=webdriver.Chrome(options=options)
try:
 driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument',{'source':"window.fetch=()=>Promise.reject(new Error('Real network disabled'));window.__errors=[];addEventListener('error',e=>__errors.push(e.message));"})
 driver.execute_cdp_cmd('Network.enable',{})
 driver.execute_cdp_cmd('Network.setBlockedURLs',{'urls':['http://*','https://*']})
 with tempfile.TemporaryDirectory() as folder:
  page=Path(folder)/'index.html';page.write_text(html,encoding='utf-8');driver.get(page.as_uri())
 driver.set_script_timeout(10)
 scenarios=(ROOT/'PortalBI/tests/neon_sync_scenarios.js').read_text(encoding='utf-8-sig')
 result=driver.execute_async_script(scenarios+"\nconst done=arguments[arguments.length-1];runNeonSyncTests().then(results=>done({results})).catch(e=>done({error:e.stack}));")
 assert 'error' not in result,result.get('error')
 for line in result['results']: print('OK:',line)
 errors=driver.execute_script('return window.__errors')
 assert not errors,errors
 print('OK: nenhum erro JavaScript; nenhum acesso a API/banco real')
finally:
 driver.quit()
