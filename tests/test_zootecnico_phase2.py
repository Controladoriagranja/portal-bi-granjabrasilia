"""Validação offline com os builders originais. Não executa SQL/PostgreSQL/HTTP."""
import ast
import asyncio
import base64
import binascii
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import io
import json
import unittest
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from zootecnico_reference import Reference,ROUTE_CASES,route_query,expected_columns,DEFAULT_ARCHIVE,secondary_lookup_query

spec=importlib.util.spec_from_file_location('phase2_acl',ROOT/'integrations/zootecnico/api/zootecnico_acesso.py')
acl=importlib.util.module_from_spec(spec);sys.modules[spec.name]=acl;spec.loader.exec_module(acl)


class RealBuildersOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DEFAULT_ARCHIVE.is_file():raise unittest.SkipTest('ZIP da API de referência ausente.')

    def test_actual_route_builders_apply_scope_and_keep_placeholder_order(self):
        from psycopg.adapt import Transformer
        from psycopg._queries import PostgresQuery
        aliases=tuple((source,'TECNICO_FICTICIO','mock1') for source in acl.SOURCES)
        with Reference() as reference:
            for bi,action,params in ROUTE_CASES:
                with self.subTest(bi=bi,action=action,params=params):
                    captured=route_query(reference,acl,bi,action,params,acl.Access(41,'proprio',aliases))
                    self.assertIn('za_scope_',captured.scoped)
                    self.assertIn('TECNICO_FICTICIO',captured.scoped)
                    self.assertNotEqual(captured.original,captured.scoped)
                    original=PostgresQuery(Transformer());original.convert(captured.original,captured.params)
                    scoped=PostgresQuery(Transformer());scoped.convert(captured.scoped,captured.params)
                    self.assertEqual(len(original.params or []),len(scoped.params or []))

    def test_general_preserves_original_queries(self):
        with Reference() as reference:
            for bi,action,params in ROUTE_CASES:
                with self.subTest(bi=bi,action=action):
                    captured=route_query(reference,acl,bi,action,params,acl.Access(41,'todos'))
                    self.assertEqual(captured.original,captured.scoped)

    def test_technician_parameter_cannot_replace_authorized_alias(self):
        access=acl.Access(41,'proprio',tuple((source,'AUTORIZADO','mock1') for source in acl.SOURCES))
        with Reference() as reference:
            for bi in ('zootecnico','gpd-fases','lotes-abertos','historico-abertos'):
                captured=route_query(reference,acl,bi,'filtros',[('tecnico','OUTRO')],access)
                self.assertIn('AUTORIZADO',captured.scoped)
                self.assertNotIn("WHEN 'OUTRO' THEN",captured.scoped)
                # Filtro é somente parâmetro adicional; não troca a identidade.
                self.assertIn('za_conflicts_',captured.scoped)

    def test_forged_role_and_user_are_rejected_before_sql(self):
        with Reference() as reference:
            for bi in ('zootecnico','gpd-fases','lotes-abertos','historico-abertos'):
                with self.subTest(bi=bi),self.assertRaises(acl.HTTPException) as error:
                    route_query(reference,acl,bi,'resumo',[('role','admin'),('usuario_id','99')],acl.Access(41,'proprio'))
                self.assertEqual(error.exception.status_code,422)

    def test_column_contract_covers_all_six_sources_and_acl_fields(self):
        with Reference() as reference:
            contract=expected_columns(reference)
        self.assertEqual({source for source,column in contract},set(acl.SOURCES))
        for source in acl.SOURCES:self.assertIn((source,'tecnico'),contract)
        for column in ('tecnico_exibicao','chave_lote','codigo','gal','lote','dt_aloj'):
            self.assertIn(('vw_desempenho_acerto_portal',column),contract)
        self.assertFalse(contract['vw_desempenho_acerto_portal','candidatos_tecnico'][1])

    def test_secondary_dynamic_lookup_keeps_scope_and_bindings(self):
        from psycopg.adapt import Transformer
        from psycopg._queries import PostgresQuery
        access=acl.Access(41,'proprio',tuple((source,'AUTORIZADO','mock1') for source in acl.SOURCES))
        with Reference() as reference:captured=secondary_lookup_query(reference,acl,access)
        self.assertIn('za_scope_base_dinamica',captured.scoped)
        self.assertIn('za_conflicts_base_dinamica',captured.scoped)
        query=PostgresQuery(Transformer());query.convert(captured.scoped,captured.params)
        self.assertEqual(len(query.params),len(captured.params))

    def test_generated_diagnostics_are_read_only_and_explain_never_executes(self):
        import re
        import json
        directory=ROOT/'integrations/zootecnico/diagnostico'
        for path in directory.glob('*.sql'):
            code=re.sub(r'--[^\n]*','',path.read_text(encoding='utf-8'))
            self.assertNotRegex(code,r'(?i)\bEXPLAIN\s+(?:\([^)]*ANALYZE|ANALYZE)')
            for statement in code.split(';'):
                if statement.strip():self.assertRegex(statement.lstrip(),r'^(BEGIN READ ONLY|SET LOCAL|SELECT|WITH|EXPLAIN|ROLLBACK)\b')
        manifest=json.loads((directory/'referencias.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['sql_executed'])
        self.assertFalse(manifest['reference_is_official'])
        self.assertEqual(manifest['route_cases'],19)


class DirectApiMiddlewareTests(unittest.TestCase):
    def middleware(self,valid=True):
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        from starlette.concurrency import run_in_threadpool
        tree=ast.parse((ROOT/'integrations/zootecnico/api/servico_zootecnico.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Autenticacao')
        ns=dict(BaseHTTPMiddleware=BaseHTTPMiddleware,JSONResponse=JSONResponse,
                base64=base64,binascii=binascii,run_in_threadpool=run_in_threadpool,
                validar_acesso=lambda *args:valid,zootecnico_dispatch=acl.dispatch)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'Autenticacao (AST)','exec'),ns)
        return ns['Autenticacao'](app=lambda *args:None)

    def request(self,headers):
        from starlette.requests import Request
        return Request(dict(type='http',method='GET',path='/api/bi/zootecnico/resumo',
                            query_string=b'',headers=[(k.lower().encode(),v.encode()) for k,v in headers.items()]))

    def test_basic_alone_does_not_authorize_data(self):
        headers={'Authorization':'Basic '+base64.b64encode(b'admin:mock-pass').decode()}
        next_=Mock()
        with patch.object(acl.OPENER,'open') as central:
            result=asyncio.run(self.middleware().dispatch(self.request(headers),next_))
        self.assertEqual(result.status_code,401);central.assert_not_called();next_.assert_not_called()

    def test_invalid_basic_is_rejected_before_individual_authorization(self):
        next_=Mock()
        headers={'Authorization':'Basic '+base64.b64encode(b'admin:mock-pass').decode(), 'X-Portal-Authorization':'Bearer mock-session'}
        with patch.object(acl.OPENER,'open') as central:
            result=asyncio.run(self.middleware(False).dispatch(self.request(headers),next_))
        self.assertEqual(result.status_code,401);central.assert_not_called();next_.assert_not_called()

    def test_basic_and_verified_bearer_keep_scope_until_handler(self):
        from starlette.responses import JSONResponse
        headers={'Authorization':'Basic '+base64.b64encode(b'admin:mock-pass').decode(), 'X-Portal-Authorization':'Bearer mock-session'}
        data=dict(ok=True,allowed=True,resource='zootecnico',reportId=13,userId=41,
                  mode='proprio',technicianIds=['mock1'],aliases=[])
        async def next_(req):
            self.assertEqual(acl.CURRENT.get().user_id,41)
            self.assertEqual(acl.CURRENT.get().mode,'proprio')
            return JSONResponse({'mock':True})
        with patch.object(acl.OPENER,'open',return_value=io.BytesIO(json.dumps(data).encode())):
            result=asyncio.run(self.middleware().dispatch(self.request(headers),next_))
        self.assertEqual(result.status_code,200);self.assertIsNone(acl.CURRENT.get())


if __name__=='__main__':unittest.main()
