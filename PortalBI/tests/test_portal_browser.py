"""Teste do JavaScript publicado em Chrome oculto, com dados ficticios."""
import re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[2]
REPO = RAIZ if (RAIZ / "index.html").is_file() else RAIZ / "portal-bi-granjabrasilia"
html = (REPO / "index.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I)
options = Options()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
driver = webdriver.Chrome(options=options)
try:
 for script in scripts:
  if script.strip():
   driver.execute_script("new Function(arguments[0]);", script)
 print("OK: sintaxe de todos os scripts do portal")
 main = next(s for s in scripts if "async function loadUpdateStatus()" in s)
 progress = main[main.index("function renderUpdateProgress("):main.index("async function loadUpdateStatus()")]
 ids = ["updateProgressPanel", "updateProgressBar", "updateProgressTitle", "updateProgressText", "updateProgressTime",
        "updateApiBanner", "updateReportsBody", "updateModule"]
 driver.execute_script("document.body.innerHTML = arguments[0]", "".join(f'<div id="{x}"></div>' for x in ids))
 resultado = driver.execute_script("""
 window.loadUpdateBatch=()=>[1,2,3,4];
 window.saveUpdateBatch=()=>{};
 window.formatDateTimeUpdate=x=>x;
 """ + progress + """
 renderUpdateProgress([
  {id:1,status:'executando'},{id:2,status:'executando'},
  {id:3,status:'executando'},{id:4,status:'aguardando'}
 ]);
 return document.getElementById('updateProgressTitle').textContent;
 """)
 assert "3 trabalho(s) em andamento" in resultado, resultado
 print("OK: tres trabalhos simultaneos exibidos")
 load = main[main.index("async function loadUpdateStatus()"):]
 esc = main[main.index("function escTicket(v)"):main.index("function currentEmail()")]
 driver.set_script_timeout(10)
 result = driver.execute_async_script("""
 const done=arguments[arguments.length-1];
 window.apiUpdate=async()=>({jobs:[{id:1,robo_id:1,status:'erro',erro:'<img src=x onerror=alert(1)> download incompleto'}]});
 window.robotsForModule=()=>[{id:1,nome:'Teste',codigo:'pcp_desperdicio'}];
 window.latestJobByRobot=jobs=>new Map([[1,jobs[0]]]);
 window.statusBadgeUpdate=()=> 'Erro';
 window.formatDurationUpdate=()=> '';
 window.periodDescriptionFromJob=()=> '';
 window.renderUpdateProgress=()=>{};
 window.renderUpdateTerminal=()=>{};
 """+esc+load+"""
 loadUpdateStatus().then(()=>done({
   details:!!document.querySelector('#updateReportsBody details'),
   text:document.querySelector('#updateReportsBody pre')?.textContent,
   injected:!!document.querySelector('#updateReportsBody img')
 })).catch(e=>done({error:String(e)}));
 """)
 assert result.get("details") and not result.get("injected") and "download incompleto" in result.get("text",""),result
 print("OK: erro completo expansivel e texto escapado")
 # Testa que os tratamentos recebem os IDs apenas das extracoes do proprio modulo.
 run = main[main.index("async function runModuleUpdate()"):main.index("function renderUpdateTerminal(")]
 result = driver.execute_async_script("""
 const done=arguments[arguments.length-1];
 const modulo=document.getElementById('updateModule'); modulo.value='pcp';
 let select=document.createElement('select'); select.id='updateTreatmentMode';
 select.innerHTML='<option value="incremental">Incremental</option>'; document.body.appendChild(select);
 window.robotsForModule=()=>[{id:1,modulo:"pcp"},{id:2,modulo:"comercial"},{id:3,modulo:"pcp",tratamento:true}];
 window.updatePayload=()=>({modo:'auto'});
 window.getUpdateModuleLabel=()=> 'PCP';
 window.periodDescriptionUpdate=()=> 'Automatico';
 window.confirm=()=>true; window.showToast=()=>{}; window.saveUpdateBatch=()=>{};
 window.loadUpdateStatus=async()=>{};
 const chamadas=[];
 window.createRobotJob=async(robo,params)=>{chamadas.push({robo:robo.id,params});return {id:robo.id+100};};
 """+run+"""
 runModuleUpdate().then(()=>done(chamadas)).catch(e=>done({error:String(e)}));
 """)
 assert isinstance(result,list) and result[2]["params"]["dependencias"] == [101],result
 print("OK: tratamento enviado com as dependencias do lote")
finally:
 driver.quit()
