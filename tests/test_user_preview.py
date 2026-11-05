"""Sessões simuladas; não usa credenciais, banco ou rede reais."""
import ast,copy,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask,jsonify,request
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from sqlalchemy import text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))
import user_preview,user_management

class Result:
 def __init__(self,row):self.row=row
 def mappings(self):return self
 def first(self):return copy.deepcopy(self.row)
class Engine:
 def __init__(self):
  self.users={1:dict(id=1,usuario_id=1,nome='Admin',email='admin@example.invalid',role='admin',perfil='admin',ativo=True,excluido_em=None),14:dict(id=14,usuario_id=14,nome='Geovane Antonio Teixeira',email='geovane@example.invalid',role='sector',perfil='usuario',ativo=True,excluido_em=None,commercial_access={'mode':'general'},operation_permissions=[]),45:dict(id=45,usuario_id=45,nome='Emerson Marcos da Cruz',email='emerson@example.invalid',role='sector',perfil='usuario',ativo=False,excluido_em=None)}
 def connect(self):return self
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def execute(self,sql,params):
  uid=params.get('id',params.get('usuario_id'));u=self.users.get(uid);s=str(sql)
  if 'ativo=TRUE'in s or 'u.ativo = TRUE'in s:
   if not u or not u['ativo']or u['excluido_em']:u=None
  return Result(u)

def fixture():
 engine=Engine();app=Flask(__name__);serializer=URLSafeTimedSerializer('fixture-preview-secret-only-local-not-production',salt='portal-bi-granja-brasilia-auth-v1')
 ns=dict(engine=engine,request=request,jsonify=jsonify,user_preview=user_preview,user_management=user_management,AUTH_TOKEN_MAX_AGE=43200,SignatureExpired=SignatureExpired,BadSignature=BadSignature,text=text,_auth_serializer=lambda:serializer)
 source=ast.parse((Path(__file__).resolve().parents[1]/'api'/'app.py').read_text(encoding='utf-8'))
 names={'_extrair_bearer_token','_usuario_por_token','_usuario_autenticado','bloquear_alteracoes_em_visualizacao'}
 for node in source.body:
  if isinstance(node,ast.FunctionDef)and node.name in names:
   node.decorator_list=[];exec(compile(ast.Module(body=[node],type_ignores=[]),'<app auth>','exec'),ns)
 app.before_request(ns['bloquear_alteracoes_em_visualizacao'])
 user_preview.register_routes(app,engine,ns['_usuario_autenticado'],lambda:serializer,lambda *a:None)
 @app.get('/api/auth/me')
 def me():
  u=ns['_usuario_autenticado']()
  if not u:return jsonify(ok=False),401
  return jsonify(ok=True,user={**u,'id':u['usuario_id'],'name':u['nome'],'isAdmin':u['role']=='admin','sessionPreview':u.get('session_preview')})
 @app.post('/api/example-mutation')
 def mutate():return jsonify(ok=True)
 return app,engine,serializer,ns

class PreviewTests(unittest.TestCase):
 def setUp(self):self.app,self.engine,self.serializer,self.ns=fixture();self.client=self.app.test_client();self.admin=self.serializer.dumps({'uid':1})
 def headers(self,token):return {'Authorization':'Bearer '+token}
 def issue(self,uid=14,token=None):return self.client.post('/api/admin/usuarios/'+str(uid)+'/preview',headers=self.headers(token or self.admin))
 def test_admin_issues_target_session(self):
  r=self.issue();self.assertEqual(r.status_code,200);d=r.get_json();self.assertIn('no-store',r.headers['Cache-Control'])
  u=self.client.get('/api/auth/me',headers=self.headers(d['token'])).get_json()['user'];self.assertEqual(u['id'],14);self.assertEqual(u['role'],'sector');self.assertEqual(u['name'],'Geovane Antonio Teixeira');self.assertTrue(u['sessionPreview']['readOnly']);self.assertFalse(u['isAdmin'])
 def test_sector_and_director_cannot_issue(self):
  for role in ['sector','director']:
   self.engine.users[14]['role']=role
   self.assertEqual(self.issue(token=self.serializer.dumps({'uid':14})).status_code,403)
 def test_missing_session_denied(self):self.assertEqual(self.client.post('/api/admin/usuarios/14/preview').status_code,401)
 def test_blocked_target_denied(self):self.assertEqual(self.issue(45).status_code,409)
 def test_deleted_target_denied(self):
  self.engine.users[14]['excluido_em']='2026-11-05';self.assertEqual(self.issue().status_code,404)
 def test_missing_target_denied(self):self.assertEqual(self.issue(999).status_code,404)
 def test_all_mutations_denied(self):
  token=self.issue().get_json()['token']
  for path in ['/api/example-mutation','/api/auth/change-password','/api/admin/usuarios/1/preview']:
   self.assertEqual(self.client.post(path,headers=self.headers(token)).status_code,403)
 def test_actor_block_revokes_preview(self):
  token=self.issue().get_json()['token'];self.engine.users[1]['ativo']=False
  self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(token)).status_code,401)
 def test_actor_demotion_revokes_preview(self):
  token=self.issue().get_json()['token'];self.engine.users[1].update(role='sector',perfil='usuario')
  self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(token)).status_code,401)
 def test_target_block_revokes_preview(self):
  token=self.issue().get_json()['token'];self.engine.users[14]['ativo']=False
  self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(token)).status_code,401)
 def test_preview_expiration(self):
  token=self.issue().get_json()['token'];future=time.time()+user_preview.MAX_AGE+1
  with patch('itsdangerous.timed.time.time',return_value=future):self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(token)).status_code,401)
 def test_regular_session_not_shortened(self):
  with patch('itsdangerous.timed.time.time',return_value=time.time()+user_preview.MAX_AGE+1):self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(self.admin)).status_code,200)
 def test_tampering_denied(self):self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(self.issue().get_json()['token']+'x')).status_code,401)
 def test_false_preview_flag_denied(self):self.assertEqual(self.client.get('/api/auth/me',headers=self.headers(self.serializer.dumps({'uid':14,'actor':1,'preview':False}))).status_code,401)
 def test_admin_primary_session_preserved(self):
  self.issue();u=self.client.get('/api/auth/me',headers=self.headers(self.admin)).get_json()['user'];self.assertEqual(u['id'],1);self.assertIsNone(u['sessionPreview'])
if __name__=='__main__':unittest.main()
