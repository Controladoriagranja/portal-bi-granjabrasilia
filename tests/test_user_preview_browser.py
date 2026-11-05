"""Chrome isolado, tokens fictícios e consultas de orçamento somente leitura."""
import sys,json,threading,functools
from pathlib import Path
from urllib.parse import urlsplit,unquote
from contextlib import contextmanager
from unittest.mock import patch
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from flask import jsonify,request
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).parent))
from test_user_preview import fixture
sys.path.insert(0,r"C:\BI_Granja\API\api_zootecnico")
sys.path.insert(0,r"X:\BI_Granja\Agrosys_Extractor\Robo Banco\PCP\infra")
import orcamento_html as budget
from banco_pcp import configuracao
import psycopg
from psycopg.rows import dict_row
ROOT=Path(__file__).resolve().parents[1];OUT=Path(r"C:\BI_Granja\Logs\Visualizar_Portal_Usuario_20261105");OUT.mkdir(exist_ok=True)
app,engine,serializer,ns=fixture();central=app.test_client();conf=dict(configuracao());conf['dbname']=conf.pop('name');conf['host']='127.0.0.1'if conf['host']=='localhost'else conf['host']
@contextmanager
def banco():
 with psycopg.connect(**conf,row_factory=dict_row,options='-c default_transaction_read_only=on -c statement_timeout=20000')as c:yield c
api=FastAPI();api.include_router(budget.criar_router_orcamento(banco));reports_api=TestClient(api)
def public_user(u):return dict(id=u['id'],dbId=u['id'],name=u['nome'],email=u['email'],role=u['role'],status='active'if u['ativo']else'blocked',sectors=['orcamento']if u['id']==14 else ['comercial'],reportAccessMode='sector',reportIds=[],pageIds=[],operationPermissions=[],dataAccess={'mode':'general'},commercialAccess={'mode':'general'},ticketPanelAccess=False,allowUpdates=False)
def data():return dict(users=[public_user(u)for u in engine.users.values()],reports=[dict(id=19,dbId=19,title='Bi - Orçamento',sector='orcamento',url=base+'/bi-Orcamento/',desc='Orçamento por área'),dict(id=4,dbId=4,title='Comercial exclusivo Admin',sector='comercial',url='https://example.invalid/report',desc='Outro relatório')],sectors=['orcamento','comercial'],sectorMeta={})
@app.get('/api/auth/bootstrap')
def bootstrap():
 u=ns['_usuario_autenticado']()
 if not u:return jsonify(ok=False),401
 return jsonify(ok=True,user={**public_user(u),'sessionPreview':u.get('session_preview')},portalData=data())
@app.get('/api/portal-data')
def portal_data():return jsonify(ok=True,data=data())
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*a):pass
 def translate_path(self,path):
  route=unquote(urlsplit(path).path)
  if route.startswith('/bi-Orcamento/'):
   return str(Path(r"C:\Users\asalvino\Documents\GitHub\bi-Orcamento")/(route[len('/bi-Orcamento/'):]or'index.html'))
  return super().translate_path(path)
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT)));base='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
admin_token=serializer.dumps({'uid':1});observed=[];errors=[]
def auth_for_request(r):
 token=r.headers.get('x-portal-authorization','').removeprefix('Bearer ')
 with app.test_request_context('/api/auth/me',headers={'Authorization':'Bearer '+token}):
  u=ns['_usuario_por_token'](token)
  if not u:raise budget.HTTPException(401,'Sessao invalida')
  return {**u,'id':u['id'],'name':u['nome'],'isAdmin':u['role']=='admin','ativo':True,'sessionPreview':u.get('session_preview')}
try:
 with patch.object(budget,'identity',side_effect=auth_for_request),patch.object(budget,'conferir_relatorio'),sync_playwright()as p:
  browser=p.chromium.launch(channel='chrome',headless=True);context=browser.new_context(viewport={'width':1500,'height':950})
  def central_route(route):
   u=urlsplit(route.request.url);path=u.path+('?' +u.query if u.query else '')
   if u.path=='/api/health':route.fulfill(status=200,json={'ok':True});return
   token=route.request.headers.get('authorization','').removeprefix('Bearer ')
   observed.append((u.path,token))
   if u.path in ['/api/auth/bootstrap','/api/auth/me','/api/portal-data']or u.path.endswith('/preview'):
    response=central.open(path,method=route.request.method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},data=route.request.post_data)
    route.fulfill(status=response.status_code,body=response.data,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'});return
   route.fulfill(status=200,json={'ok':True,'jobs':[],'items':[],'users':[],'tickets':[],'managers':[],'projects':[],'data':{'tickets':[],'managers':[],'projects':[]}})
  context.route('https://portal-bi-granjabrasilia.onrender.com/**',central_route)
  def budget_route(route):
   u=urlsplit(route.request.url);response=reports_api.get(u.path+('?' +u.query if u.query else ''),headers={'x-portal-authorization':route.request.headers.get('authorization','')})
   route.fulfill(status=response.status_code,body=response.content,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'})
  context.route('https://api-bi-granja.controladoriagb05.workers.dev/**',budget_route)
  page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.add_init_script('sessionStorage.setItem("granjabi_auth_token",'+json.dumps(admin_token)+')')
  page.goto(base+'/');page.wait_for_function("currentUser?.role==='admin' && document.querySelector('#screen-portal').classList.contains('active')",timeout=30000)
  page.click('#nav-users');row=page.locator('#allUsersTable tbody tr').filter(has_text='Geovane Antonio Teixeira');assert row.count()==1
  with page.expect_popup()as popup_info:row.get_by_role('button',name='Visualizar portal').click()
  child=popup_info.value;child.on('pageerror',lambda e:errors.append(str(e)))
  child.wait_for_function("typeof currentUser!=='undefined' && currentUser?.id===14 && !!portalPreviewSession",timeout=30000)
  assert child.locator('#userPreviewBanner').is_visible();assert 'Geovane Antonio Teixeira'in child.locator('#userPreviewBanner').inner_text()
  assert child.locator('#allReportGrid .report-card').count()==1
  assert 'Comercial exclusivo Admin'not in child.locator('#allReportGrid').inner_text()
  assert page.evaluate('currentUser.id')==1 and page.evaluate('getPortalToken()')==admin_token
  preview_token=child.evaluate('getPortalToken()');assert preview_token!=admin_token and 'user-preview'not in child.url and preview_token not in child.url
  assert child.evaluate('window.opener===null')
  child.screenshot(path=str(OUT/'portal_como_geovane.png'),full_page=True)
  child.locator('#allReportGrid .btn-open').click()
  frame=child.frame_locator('#reportIframe');frame.locator('#responsavel + .budget-select .budget-select-trigger').wait_for(timeout=30000)
  child.wait_for_function("document.querySelector('#reportIframe').contentWindow.document.querySelector('#carregando').hidden",timeout=30000)
  assert frame.locator('#responsavel').input_value()=='Geovane Teixeira';assert frame.locator('#responsavel + .budget-select .budget-select-trigger').is_disabled()
  codes=frame.locator('#areas [data-area]').evaluate_all("els=>els.map(e=>e.dataset.area).filter(x=>x!=='GERAL')");assert set(codes)=={'13','14','19','22','27','44','50','53','64','66'}
  child.screenshot(path=str(OUT/'orcamento_como_geovane.png'),full_page=True)
  assert central.post('/api/example-mutation',headers={'Authorization':'Bearer '+preview_token}).status_code==403
  child.reload();child.wait_for_function("typeof currentUser!=='undefined' && currentUser?.id===14 && !!portalPreviewSession",timeout=30000)
  assert page.evaluate('currentUser.id')==1 and page.evaluate('getPortalToken()')==admin_token
  with child.expect_event('close',timeout=10000):child.get_by_role('button',name='Encerrar visualização').click()
  assert page.evaluate('getPortalToken()')==admin_token
  issued=next(i for i,(path,token)in enumerate(observed)if path.endswith('/preview'))
  assert all(token==preview_token for path,token in observed[issued+1:]if path=='/api/auth/bootstrap')
  assert not errors,errors
  result={'sessao_admin_preservada':True,'relatorios_restritos':True,'filtros_reais_geovane':True,'areas':codes,'sem_token_na_url':True,'recarga_preserva_visualizacao':True,'alteracoes_bloqueadas':True,'encerrar_fecha_so_aba_visualizacao':True,'sem_erros_js':True}
  OUT.joinpath('validacao_browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result),flush=True);browser.close()
finally:server.shutdown()
