"""Offline audit: isolated AST functions, fake HTTP/SQL/executor/time. No app import."""
import ast
import contextlib
import io
import hmac
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

ROOT=Path(__file__).resolve().parents[2]
API=ast.parse((ROOT/'api/app.py').read_text(encoding='utf-8-sig'))
AGENT=ast.parse((ROOT/'PortalBI/api/portal_bi_agent.py').read_text(encoding='utf-8-sig'))

def functions(tree, names, namespace):
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
 assert len(nodes)==len(names)
 for node in nodes: node.decorator_list=[]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'<isolated audited functions>','exec'),namespace)
 return namespace

class AuditTests(unittest.TestCase):
 def test_signal_health_no_database_and_shared_atomic_file(self):
  engine=Mock()
  engine.connect.side_effect=AssertionError('Database forbidden')
  engine.begin.side_effect=AssertionError('Database forbidden')
  key='fake-agent-key-for-offline-test-only-1234'
  class Response:
   def __init__(self,payload): self.payload=payload;self.headers={}
  ns={'engine':engine,'hmac':hmac,'os':os,'uuid':__import__('uuid'),
      'request':SimpleNamespace(headers={'X-Agent-Key':key}), 'jsonify':lambda value:Response(value),
      'APP_VERSION':'mock', 'log':Mock()}
  with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'PORTAL_BI_AGENT_KEY':key}):
   ns['_JOB_SIGNAL_PATH']=Path(folder)/'signal'
   functions(API,{'_agent_autorizado','_resposta_agent_nao_autorizado','_job_signal','_notify_agents','api_agent_jobs_signal','api_health'},ns)
   initial=ns['api_agent_jobs_signal']()
   self.assertEqual(initial.payload['signal'],'')
   ns['_notify_agents']();first=ns['api_agent_jobs_signal']().payload['signal']
   ns['_notify_agents']();second=ns['api_agent_jobs_signal']()
   self.assertTrue(first and second.payload['signal']!=first)
   self.assertEqual(second.headers['Cache-Control'],'no-store, max-age=0')
   self.assertTrue(ns['api_health']().payload['ok'])
   ns['request'].headers['X-Agent-Key']='wrong'
   self.assertEqual(ns['api_agent_jobs_signal']()[1],401)
   engine.connect.assert_not_called();engine.begin.assert_not_called()

 def test_notifications_follow_commit_and_connections_are_scoped(self):
  for name in ['api_criar_job','api_agent_finish_job']:
   fn=next(n for n in API.body if isinstance(n,ast.FunctionDef) and n.name==name)
   signals=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_notify_agents']
   transactions=[n for n in ast.walk(fn) if isinstance(n,ast.With)]
   self.assertEqual(len(signals),1)
   self.assertTrue(any(t.end_lineno<signals[0].lineno for t in transactions))
  # Every checkout found in the production API is a with-managed context.
  parents={child:parent for parent in ast.walk(API) for child in ast.iter_child_nodes(parent)}
  checkouts=[n for n in ast.walk(API) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
             and isinstance(n.func.value,ast.Name) and n.func.value.id=='engine' and n.func.attr in {'connect','begin'}]
  self.assertGreater(len(checkouts),20)
  for call in checkouts:
   self.assertIsInstance(parents[call],ast.withitem)

 def test_authentication_still_reads_each_time_and_returns_connection_on_error(self):
  engine=MagicMock();conn=engine.connect.return_value.__enter__.return_value
  query=conn.execute.return_value.mappings.return_value.first
  query.side_effect=[{'usuario_id':1,'role':'admin'}, {'usuario_id':1,'role':'sector'}, None]
  ns={'engine':engine,'text':lambda value:value,'_auth_serializer':lambda:SimpleNamespace(loads=lambda *a,**k:{'uid':1}),
      'AUTH_TOKEN_MAX_AGE':3600,'SignatureExpired':type('SignatureExpired',(Exception,),{}),'BadSignature':type('BadSignature',(Exception,),{})}
  functions(API,{'_usuario_por_token'},ns)
  self.assertEqual(ns['_usuario_por_token']('fake')['role'],'admin')
  self.assertEqual(ns['_usuario_por_token']('fake')['role'],'sector')
  self.assertIsNone(ns['_usuario_por_token']('fake'))
  self.assertEqual(engine.connect.call_count,3)
  self.assertEqual(engine.connect.return_value.__exit__.call_count,3)
  self.assertIn('u.ativo = TRUE',conn.execute.call_args.args[0])
  conn.execute.side_effect=RuntimeError('Fake SQL failure')
  with self.assertRaises(RuntimeError):ns['_usuario_por_token']('fake')
  self.assertEqual(engine.connect.return_value.__exit__.call_count,4)

 def run_agent(self, signal_values, times, claims=None, error=None, complete_at=None):
  class Future:
   def done(self): return complete_at is not None and clock.now>=complete_at
   def result(self): return None
  class Executor:
   def __init__(self,**kwargs): pass
   def __enter__(self): return self
   def __exit__(self,*args): pass
   def submit(self,*args):
    return Future()
  class Clock:
   def __init__(self):self.now=0;self.tick=0
   def monotonic(self):return self.now
   def sleep(self,seconds):
    self.tick+=1
    if self.tick>=len(times):raise KeyboardInterrupt
    self.now=times[self.tick]
  clock=Clock();claims=claims or Mock(return_value=None)
  class RequestException(Exception): pass
  exception=RequestException('signal offline')
  if error==404: exception.response=SimpleNamespace(status_code=404)
  signal=Mock(side_effect=signal_values) if not error else Mock(side_effect=exception)
  ns={'time':clock,'requests':SimpleNamespace(RequestException=RequestException),
      'consultar_sinal':signal,'claim_job':claims,'executar_job':Mock(side_effect=AssertionError('forbidden')),
      'POLL_SECONDS':5,'IDLE_RESYNC_SECONDS':3600,'ACTIVE_RESYNC_SECONDS':120}
  functions(AGENT,{'executar_fila_paralela'},ns)
  fake=SimpleNamespace(ThreadPoolExecutor=Executor,wait=Mock(),FIRST_COMPLETED=object())
  with patch.dict('sys.modules',{'concurrent.futures':fake}),contextlib.redirect_stdout(io.StringIO()):
   ns['executar_fila_paralela'](3)
  return claims

 def test_agent_idle_signal_does_not_claim_every_five_seconds(self):
  claims=self.run_agent(['same']*5,[0,5,10,15,20])
  self.assertEqual(claims.call_count,1) # backlog at startup only

 def test_agent_signal_change_claims_immediately(self):
  claims=self.run_agent(['a','a','b','b'],[0,5,10,15])
  self.assertEqual(claims.call_count,2)

 def test_agent_lost_signal_fallback(self):
  claims=self.run_agent(['a']*4,[0,5,3599,3600])
  self.assertEqual(claims.call_count,2)
  claims=self.run_agent([], [0,5,3599,3600],error=True)
  self.assertEqual(claims.call_count,2)

 def test_agent_missing_route_uses_minute_fallback_not_five_seconds(self):
  claims=self.run_agent([], [0,5,59,60],error=404)
  self.assertEqual(claims.call_count,2)

 def test_agent_active_fallback_and_completion_without_running_robots(self):
  claims=Mock(side_effect=[{'id':123},None,None])
  self.run_agent(['a']*8,[0,5,120],claims=claims)
  self.assertEqual(claims.call_count,3)
  claims=Mock(side_effect=[{'id':123},None,None])
  self.run_agent(['a']*8,[0,5,10],claims=claims,complete_at=5)
  self.assertEqual(claims.call_count,3)

 def test_agent_heartbeat_is_kept_during_execution(self):
  stop=Mock();stop.wait.side_effect=[False,False,True]
  heartbeat=Mock()
  ns={'heartbeat_job':heartbeat,'HEARTBEAT_SECONDS':60,'AGENT_ID':'fake','requests':SimpleNamespace(RequestException=Exception)}
  functions(AGENT,{'_loop_heartbeat'},ns)
  with contextlib.redirect_stdout(io.StringIO()):ns['_loop_heartbeat'](123,stop)
  self.assertEqual(heartbeat.call_count,2)
  stop.wait.assert_called_with(60)

if __name__=='__main__':unittest.main()
