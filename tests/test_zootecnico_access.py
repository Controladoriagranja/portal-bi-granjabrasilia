"""Testes locais. Sem importar app, abrir banco, rede, servidor ou executar o ZIP.

O ZIP é lido só para compilar os helpers puros de composição SQL já existentes.
"""
import ast
import asyncio
from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from zipfile import ZipFile

from flask import Flask
from psycopg import sql
from starlette.requests import Request
from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
import zootecnico_access as portal

spec = importlib.util.spec_from_file_location('zootecnico_acesso', ROOT / 'integrations/zootecnico/api/zootecnico_acesso.py')
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)


def install_sql_helpers():
    archive = Path.home() / 'Downloads/api_zootecnico(3).zip'
    if not archive.is_file():
        raise unittest.SkipTest('Disponibilize o ZIP de referência para os testes de composição SQL.')
    with ZipFile(archive) as zipped:
        tree = ast.parse(zipped.read('api_zootecnico/bi_generic/sql_utils.py').decode('utf-8-sig'))
    helper = ModuleType('bi_generic.sql_utils')
    helper.sql = sql
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {'texto', 'date_texto'}:
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'sql_utils (funções puras)', 'exec'), helper.__dict__)
    package = ModuleType('bi_generic'); package.__path__ = []
    sys.modules['bi_generic'] = package
    sys.modules['bi_generic.sql_utils'] = helper


def payload(mode='proprio', ids=None, aliases=None):
    return dict(ok=True, allowed=True, resource='zootecnico', reportId=13, userId=41,
                mode=mode, technicianIds=ids if ids is not None else (['t1'] if mode != 'todos' else []),
                aliases=aliases if aliases is not None else [dict(fonte='base_dinamica', valor='JOÃO', entidade_id='t1')])


def request(path='/api/bi/zootecnico/resumo', headers=None):
    return Request(dict(type='http', method='GET', path=path, raw_path=path.encode(),
                        query_string=b'', headers=[(k.lower().encode(), v.encode()) for k,v in (headers or {}).items()],
                        scheme='https', server=('offline.invalid', 443), client=('127.0.0.1', 1234)))


class AuthorizationTests(unittest.TestCase):
    def test_valid_user_single_and_team(self):
        self.assertEqual(api.validate_access(payload()).user_id, 41)
        self.assertEqual(api.validate_access(payload('equipe', ['t1', 't2'])).mode, 'equipe')

    def test_general_explicit(self):
        self.assertEqual(api.validate_access(payload('todos', aliases=[])).mode, 'todos')

    def test_no_role_or_browser_identity_override(self):
        for change in ({'ok':False}, {'allowed':False}, {'reportId':12}, {'resource':'comercial'},
                       {'userId':True}, {'userId':'41'}, {'mode':'none'}, {'mode':'seller'},
                       {'technicianIds':[]}, {'technicianIds':['t1','t2']}, {'technicianIds':[{}]},
                       {'technicianIds':['t1','t1']}, {'technicianIds':["1' OR TRUE"]}):
            with self.subTest(change=change), self.assertRaises(api.HTTPException):
                api.validate_access({**payload(), **change, 'role':'admin', 'tecnico':'qualquer'})

    def test_aliases_must_be_exact_unique_and_authorized(self):
        for aliases in ([dict(fonte='base_dinamica', valor='X', entidade_id='t2')],
                        [dict(fonte='galpoes', valor='X', entidade_id='t1')],
                        [dict(fonte='base_dinamica', valor=' X ', entidade_id='t1')],
                        payload()['aliases']*2):
            with self.subTest(aliases=aliases), self.assertRaises(api.HTTPException):
                api.validate_access(payload(aliases=aliases))

    def test_no_token_no_http(self):
        with patch.object(api.OPENER, 'open') as opened, self.assertRaises(api.HTTPException) as error:
            api.resolve_access(request(headers={'Authorization':'Basic not-a-portal-session'}))
        self.assertEqual(error.exception.status_code,401)
        opened.assert_not_called()

    def test_upstream_failure_does_not_grant_access(self):
        for status, expected in ((401,401),(403,403),(500,503)):
            with patch.object(api.OPENER,'open',side_effect=HTTPError('offline.invalid',status,'mock',{},None)):
                with self.assertRaises(api.HTTPException) as error:
                    api.resolve_access(request(headers={'x-portal-authorization':'Bearer mock-only'}))
                self.assertEqual(error.exception.status_code,expected)

    def test_permissions_are_resolved_again_on_every_request(self):
        with patch.object(api.OPENER,'open',side_effect=[io.BytesIO(json.dumps(payload()).encode()),io.BytesIO(json.dumps({**payload(),'mode':'none'}).encode())]) as opened:
            api.resolve_access(request(headers={'x-portal-authorization':'Bearer mock-only'}))
            with self.assertRaises(api.HTTPException):
                api.resolve_access(request(headers={'x-portal-authorization':'Bearer mock-only'}))
            self.assertEqual(opened.call_count,2)

    def test_dispatch_authorizes_direct_endpoints_and_resets_context(self):
        async def next_(req):
            self.assertEqual(api.CURRENT.get().user_id,41)
            return JSONResponse({'ok':True})
        with patch.object(api,'resolve_access',return_value=api.validate_access(payload())):
            for path in ('/api/bi/zootecnico/resumo','/api/bi/gpd-fases/filtros',
                         '/api/bi/lotes-abertos/detalhes','/api/bi/historico-abertos/resumo',
                         '/api/bi/historico-fechados/resumo','/api/zootecnico/dados/base_dinamica'):
                result=asyncio.run(api.dispatch(request(path),next_))
                self.assertEqual(result.status_code,200)
                self.assertIn('no-store',result.headers['cache-control'])
                self.assertIsNone(api.CURRENT.get())

    def test_generic_shared_cache_and_rxp_cannot_bypass_restrictions(self):
        with patch.object(api,'resolve_access',return_value=api.validate_access(payload())):
            for path in ('/api/portal/zootecnico/dados/base_dinamica',
                         '/api/zootecnico/resumo','/api/bi/rxp/resumo','/api/bi/formulas/atualizacao'):
                next_=Mock()
                self.assertEqual(asyncio.run(api.dispatch(request(path),next_)).status_code,403)
                next_.assert_not_called()

    def test_other_modules_do_not_query_central(self):
        async def next_(req): return JSONResponse({'ok':True})
        with patch.object(api,'resolve_access') as central:
            result=asyncio.run(api.dispatch(request('/api/comercial-html/painel'),next_))
        self.assertEqual(result.status_code,200); central.assert_not_called()

    def test_shared_catalog_keeps_other_modules_when_no_zootecnico_grant(self):
        async def next_(req):
            self.assertFalse(api.catalog_general())
            return JSONResponse({'modulos':['matrizes']})
        with patch.object(api,'resolve_access',side_effect=api.HTTPException(403,'mock')):
            result=asyncio.run(api.dispatch(request('/api/portal/modulos',{'x-portal-authorization':'Bearer mock'}),next_))
        self.assertEqual(result.status_code,200)


class CatalogTests(unittest.TestCase):
    def test_catalog_hides_zootecnico_before_counting_and_separates_cache(self):
        tree=ast.parse((ROOT/'integrations/zootecnico/api/portal_router.py').read_text(encoding='utf-8'))
        @contextmanager
        def banco(): yield None
        ns=dict(banco=banco,descobrir_schemas=lambda _:['zootecnico','matrizes'],
                ESQUEMAS={'zootecnico':'Zootécnico','matrizes':'Matrizes'},
                ESQUEMAS_POR_MODULO={'zootecnico':('zootecnico',),'matrizes':('matrizes',)},
                catalog_general=api.catalog_general,schemas_do_modulo=lambda m,c:(m,))
        counted=[]
        def resumo_schema(c,s):
            counted.append(s)
            return [dict(registros=10,ultima_carga=None)]
        ns['resumo_schema']=resumo_schema
        ns['resumo_cache']=Mock()
        ns['resumo_cache'].get.side_effect=lambda key,loader:loader()
        for name in ('carregar_modulos','modulos'):
            node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
            node.decorator_list=[]
            exec(compile(ast.Module(body=[node],type_ignores=[]),'portal catalog (AST)','exec'),ns)
        for access, expected in ((api.Access(0,'none'),False),(api.Access(41,'todos'),True)):
            token=api.CURRENT.set(access)
            try:
                counted.clear();result=ns['modulos']()
                self.assertEqual('zootecnico' in counted,expected)
                self.assertEqual('zootecnico' in result['esquemas'],expected)
                self.assertIn('matrizes',counted)
                self.assertEqual(ns['resumo_cache'].get.call_args.args[0],('modulos',expected))
            finally:api.CURRENT.reset(token)

    def test_cached_loader_thread_keeps_authorization_context(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from copy import deepcopy
        from threading import Lock
        from time import monotonic
        tree=ast.parse((ROOT/'integrations/zootecnico/api/portal_router.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ResumoCache')
        ns=dict(copy_context=copy_context,deepcopy=deepcopy,monotonic=monotonic,HTTPException=api.HTTPException)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'ResumoCache (AST)','exec'),ns)
        cache=object.__new__(ns['ResumoCache'])
        cache.ttl=60;cache.lock=Lock();cache.values={};cache.pending={};cache.retry_after={}
        cache.pool=ThreadPoolExecutor(max_workers=1)
        token=api.CURRENT.set(api.Access(41,'proprio'))
        try:
            self.assertFalse(cache.get(('modulos',False),api.catalog_general))
        finally:
            api.CURRENT.reset(token);cache.pool.shutdown(wait=True)


class SqlBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): install_sql_helpers()

    def setUp(self): self.access=api.validate_access(payload())

    def test_all_sources_are_scoped_before_aggregation_and_pagination(self):
        for source in api.SOURCES:
            with self.subTest(source=source):
                access=api.Access(41,'proprio',((source,'JOÃO','t1'),))
                query=api.scope_query(sql.SQL('SELECT count(*) FROM {} LIMIT %s').format(sql.Identifier('zootecnico',source)),access)
                self.assertIn('"za_scope_'+source+'" AS (SELECT s.*',query)
                self.assertIn('IS NOT NULL',query)
                self.assertTrue(query.endswith('LIMIT %s'))

    def test_unknown_alias_is_not_fallback_to_all(self):
        result=api.scope_query('SELECT * FROM zootecnico.base_dinamica',api.Access(41,'proprio'))
        self.assertIn('WHERE FALSE',result)
        self.assertNotIn('ILIKE',result)

    def test_snapshot_conflict_guard_includes_other_owners_and_unknowns(self):
        result=api.scope_query('SELECT * FROM zootecnico.base_dinamica',self.access)
        self.assertIn('NOT EXISTS (SELECT 1 FROM "za_conflicts_base_dinamica" p',result)
        self.assertIn('BOOL_OR(za_owner IS NULL) OR COUNT(DISTINCT za_owner)>1',result)
        for key in ('cod_prod','galpao','lote','data_de_alojamento'): self.assertIn(key,result)
        self.assertIn('make_date',result) # helper real do pacote, nenhuma data adivinhada

    def test_house_only_is_not_used_as_identity(self):
        for source in ('mortalidade_peso_abertos','mortalidade_peso_fechados','vw_historico_lotes_criacao_portal'):
            access=api.Access(41,'proprio',((source,'JOÃO','t1'),))
            result=api.scope_query('SELECT * FROM zootecnico.'+source,access)
            for key in ('codigo_granja','galp','num_lote'): self.assertIn(key,result)
            self.assertIn('COUNT(DISTINCT za_owner)>1',result)

    def test_display_name_and_ambiguity_do_not_expand_access(self):
        access=api.Access(41,'proprio',(('vw_desempenho_acerto_portal','JOÃO','t1'),))
        result=api.scope_query('SELECT * FROM zootecnico.vw_desempenho_acerto_portal',access)
        self.assertIn('candidatos_tecnico',result); self.assertIn('tecnico_exibicao',result)
        self.assertIn("->>'tecnico'",result)

    def test_portal_view_does_not_require_optional_counter_column(self):
        access=api.Access(41,'proprio',(('vw_desempenho_acerto_portal','JOÃO','t1'),))
        result=api.scope_query('SELECT * FROM zootecnico.vw_desempenho_acerto_portal',access)
        self.assertIn("COALESCE(to_jsonb(s)->>'candidatos_tecnico','1')",result)
        self.assertNotIn('s.candidatos_tecnico',result)
        self.assertNotIn('s."candidatos_tecnico"',result)

    def test_existing_with_recursive_and_nested_cte(self):
        for prefix in ('WITH old AS (SELECT 1)', 'WITH RECURSIVE old AS (SELECT 1)'):
            result=api.scope_query(prefix+' SELECT * FROM zootecnico.base_dinamica',self.access)
            self.assertEqual(result.upper().count('WITH '),1)
            self.assertIn(', old AS (SELECT 1)',result)

    def test_multiple_sources_are_all_guarded(self):
        result=api.scope_query('SELECT * FROM zootecnico.base_dinamica d JOIN "zootecnico"."mortalidade_peso_abertos" a ON TRUE',self.access)
        self.assertIn('"za_scope_base_dinamica" d JOIN "za_scope_mortalidade_peso_abertos" a',result)

    def test_literals_and_comments_are_preserved(self):
        query="SELECT 'zootecnico.base_dinamica' AS nome FROM zootecnico.base_dinamica -- zootecnico.galpoes"
        result=api.scope_query(query,self.access)
        self.assertIn("SELECT 'zootecnico.base_dinamica' AS nome",result)
        self.assertTrue(result.endswith('-- zootecnico.galpoes'))

    def test_sql_injection_in_authorized_alias_is_escaped(self):
        value="O'BRIEN % '; DROP TABLE x; --"
        access=api.Access(41,'proprio',(('base_dinamica',value,'t1'),))
        result=api.scope_query('SELECT * FROM zootecnico.base_dinamica',access,bound_params=True)
        self.assertIn("O''BRIEN %% ''",result)

    def test_general_is_unchanged_and_unmapped_source_is_denied(self):
        raw='SELECT * FROM zootecnico.galpoes'
        self.assertEqual(api.scope_query(raw,api.Access(41,'todos')),raw)
        with self.assertRaises(api.HTTPException): api.scope_query(raw,self.access)

    def test_other_route_cannot_read_zootecnico_via_database_factory(self):
        with self.assertRaises(api.HTTPException):
            api.scope_query('SELECT * FROM zootecnico.base_dinamica',api.Access(0,'none'))

    def test_unrelated_sql_and_parameter_order_preserved(self):
        raw='SELECT * FROM comercial_html.faturamento_cfop_atual WHERE vendedor=%s'
        self.assertEqual(api.scope_query(raw,self.access),raw)
        conn=Mock();conn.execute=Mock()
        # as_string não precisa conexão para identificadores e literais psycopg.
        conn.pgconn = None
        query='SELECT * FROM zootecnico.base_dinamica WHERE cod_prod=%s LIMIT %s'
        # A conexão simulada não é passada ao adaptador de literais.
        with patch.object(api,'scope_query',wraps=lambda q,a,c,b: api_scope(q,a,None,b)):
            api.ScopedConnection(conn,self.access).execute(query,['12',20])
        self.assertEqual(conn.execute.call_args.args[1],['12',20])

    def test_cursor_bypass_is_closed(self):
        with self.assertRaises(api.HTTPException): api.ScopedConnection(Mock(),self.access).cursor()

    def test_psycopg_placeholder_parser_accepts_generated_sql(self):
        from psycopg.adapt import Transformer
        from psycopg._queries import PostgresQuery
        access=api.Access(41,'proprio',(('base_dinamica',"O'BRIEN %",'t1'),))
        raw=api.scope_query('SELECT count(*) FROM zootecnico.base_dinamica WHERE cod_prod=%s LIMIT %s',access,bound_params=True)
        query=PostgresQuery(Transformer())
        query.convert(raw,['12',20])
        self.assertEqual(len(query.params),2)
        self.assertTrue(query.query.endswith(b'WHERE cod_prod=$1 LIMIT $2'))


api_scope = api.scope_query


class Result:
    def __init__(self,value): self.value=value
    def scalar(self): return self.value
    def mappings(self): return self
    def scalars(self): return self
    def first(self): return self.value
    def __iter__(self): return iter(self.value)


class Engine:
    ready=True;allowed=True;mode='proprio';ids=['t1']
    def connect(self): return self
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,query,params=None):
        query=str(query)
        if 'to_regclass' in query:return Result(self.ready)
        if 'SELECT EXISTS' in query:return Result(self.allowed)
        if 'AS requested_mode' in query:return Result(None)
        if 'SELECT escopo' in query:return Result(dict(escopo=self.mode,ativo=True))
        if 'SELECT v.entidade_id' in query:return Result(self.ids)
        if 'SELECT a.fonte' in query:return Result(payload()['aliases'])
        if 'SELECT role,perfil' in query:return Result(dict(role='sector',perfil='setor'))
        if 'SELECT id,nome,email,ativo,role,perfil' in query:return Result([dict(id=41,nome='Técnico fictício',email='offline@example.invalid',ativo=True,role='sector',perfil='setor')])
        if 'SELECT identificador AS id' in query:return Result([dict(id='t1',nome='Técnico fictício',ativo=True)])
        raise AssertionError(query)


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.user=dict(usuario_id=41,role='sector',perfil='setor',ativo=True)
        self.engine=Engine()
        self.app=Flask(__name__)
        portal.register_routes(self.app,self.engine,lambda:self.user,lambda u:u['role']=='admin')
        self.client=self.app.test_client()

    def test_authenticated_report_permission_and_scope_required(self):
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').json['mode'],'proprio')
        self.engine.allowed=False
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').status_code,403)
        self.user=None
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').status_code,401)

    def test_missing_migration_fails_only_new_feature(self):
        self.engine.ready=False
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').status_code,503)

    def test_existing_and_new_managers_have_general_by_explicit_role_policy(self):
        for role in ('admin','director'):
            self.user=dict(usuario_id=41,role=role,ativo=True)
            data=self.client.get('/api/auth/zootecnico-access').json
            self.assertEqual(data['mode'],'todos');self.assertEqual(data['aliases'],[])

    def test_managers_remain_general_even_before_auxiliary_migration(self):
        self.engine.ready=False
        for role in ('admin','director'):
            self.user=dict(usuario_id=41,role=role,ativo=True)
            result=self.client.get('/api/auth/zootecnico-access')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['mode'],'todos')

    def test_existing_general_scope_does_not_require_any_technician(self):
        self.engine.mode='todos';self.engine.ids=[]
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').json['mode'],'todos')

    def test_commercial_general_does_not_authorize_integration(self):
        self.user['commercial_access']={'mode':'general'}
        self.engine.mode='none'; self.engine.ids=[]
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').json['mode'],'none')

    def test_query_parameters_cannot_impersonate_a_user_or_grant_general(self):
        result=self.client.get('/api/auth/zootecnico-access?usuario_id=99&role=admin&tecnico=OUTRO')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['userId'],41)
        self.assertEqual(result.json['mode'],'proprio')

    def test_team_and_individual_validation(self):
        for mode,ids in (('proprio',[]),('proprio',['a','b']),('equipe',[]),('todos',['a']),('none',['a'])):
            with self.subTest(mode=mode,ids=ids),self.assertRaises(ValueError):
                portal.normalize_access(dict(mode=mode,technicianIds=ids))
        self.assertEqual(portal.normalize_access(dict(mode='equipe',technicianIds=['a','b']))['technicianIds'],['a','b'])

    def test_admin_catalog_is_not_available_to_ordinary_user(self):
        self.assertEqual(self.client.get('/api/admin/usuarios/41/zootecnico-access').status_code,403)
        self.user['role']='admin'
        self.assertEqual(self.client.get('/api/admin/usuarios/41/zootecnico-access').status_code,200)

    def test_no_store_and_permission_revocation(self):
        result=self.client.get('/api/auth/zootecnico-access')
        self.assertIn('no-store',result.headers['Cache-Control'])
        self.engine.mode='none'; self.engine.ids=[]
        self.assertEqual(self.client.get('/api/auth/zootecnico-access').json['mode'],'none')


class WiringTests(unittest.TestCase):
    def test_original_basic_and_other_modules_preserved(self):
        source=(ROOT/'integrations/zootecnico/api/servico_zootecnico.py').read_text(encoding='utf-8')
        self.assertIn('validar_acesso,',source)
        self.assertIn('await zootecnico_dispatch(request, call_next)',source)
        self.assertIn('yield scoped_connection(conn)',source)
        for marker in ('criar_router_comercial_html(banco)','criar_router_suprimentos(banco)','criar_router_logistica(banco)'):
            self.assertIn(marker,source)
        docker=(ROOT/'integrations/zootecnico/api/Dockerfile.zootecnico').read_text(encoding='utf-8')
        self.assertIn('COPY API/api_zootecnico/zootecnico_acesso.py .',docker)
        self.assertIn('"servico_zootecnico:app"',docker)

    def test_user_crud_writes_scope_in_same_transaction_and_omission_preserves(self):
        tree=ast.parse((ROOT/'api/app.py').read_text(encoding='utf-8-sig'))
        for name in ('api_admin_usuario_patch','api_admin_usuario_create'):
            function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            code=ast.unparse(function)
            self.assertIn("'zootecnicoAccess' in body",code)
            self.assertIn('if zootecnico_access is not None:',code)
            self.assertIn('replace_zootecnico_access(conn, usuario_id, zootecnico_access',code)


if __name__=='__main__': unittest.main()
