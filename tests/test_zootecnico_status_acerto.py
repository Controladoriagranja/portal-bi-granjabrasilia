"""Verificação offline da trava por escopo: sem rede nem banco real."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from test_zootecnico_access import api, install_sql_helpers, request
from starlette.responses import JSONResponse


class StatusAcertoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_sql_helpers()

    def test_proprio_overrides_all_status_params_and_keeps_other_filters(self):
        for path in ('resumo', 'detalhes', 'filtros', 'exportar'):
            req = request('/api/bi/zootecnico/'+path)
            req.scope['query_string'] = b'ano=2026&mes=1&mes=2&status_acerto=Manual&status_acerto=Todos'
            self.assertEqual(req.query_params.getlist('status_acerto'), ['Manual', 'Todos'])
            async def next_(req):
                self.assertEqual(req.query_params.getlist('status_acerto'), ['Não Manual'])
                self.assertEqual(req.query_params.getlist('mes'), ['1', '2'])
                self.assertEqual(req.query_params['ano'], '2026')
                return JSONResponse({'ok': True})
            with patch.object(api, 'resolve_access', return_value=api.Access(41, 'proprio')):
                res = asyncio.run(api.dispatch(req, next_))
            self.assertEqual(res.headers['X-Zootecnico-Status-Acerto'], 'nao_manual')
            self.assertIsNone(api.CURRENT.get())

    def test_default_is_applied_without_param(self):
        async def next_(req):
            self.assertEqual(req.query_params.getlist('status_acerto'), ['Não Manual'])
            return JSONResponse({})
        with patch.object(api, 'resolve_access', return_value=api.Access(41, 'proprio')):
            asyncio.run(api.dispatch(request(), next_))

    def test_general_team_and_other_screens_keep_existing_filters(self):
        for mode, path in [('todos','zootecnico'), ('equipe','zootecnico'), ('proprio','lotes-abertos'), ('proprio','gpd-fases')]:
            req = request('/api/bi/'+path+'/filtros')
            req.scope['query_string'] = b'status_acerto=Manual'
            async def next_(req):
                self.assertEqual(req.query_params['status_acerto'], 'Manual')
                return JSONResponse({})
            with patch.object(api, 'resolve_access', return_value=api.Access(41, mode)):
                res = asyncio.run(api.dispatch(req, next_))
            self.assertNotIn('X-Zootecnico-Status-Acerto', res.headers)

    def test_source_guard_precedes_aggregation_and_preserves_technician_guard(self):
        source = 'vw_desempenho_acerto_portal'
        raw = 'SELECT SUM(mort) FROM zootecnico.'+source
        for mode in ('proprio', 'equipe', 'todos'):
            access = api.Access(41, mode, ((source,'CVB - CRISTIANO','t1'),))
            result = api.scope_query(raw, access)
            if mode == 'proprio':
                self.assertIn("BTRIM(to_jsonb(s)->>'status_acerto') = 'Não Manual'", result)
                self.assertIn("->>'tecnico'", result)
                self.assertIn('CVB - CRISTIANO', result)
                self.assertIn('NOT EXISTS', result)
                self.assertLess(result.index("->>'status_acerto'"), result.index('SELECT SUM(mort)'))
            else:
                self.assertNotIn("->>'status_acerto'", result)


if __name__ == '__main__':
    unittest.main()
