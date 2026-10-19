"""Testes offline: AST isolada, SQL/HTTP/processos falsos; nao importa app/.env."""
import ast
import os
import re
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def isolated(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return tree, namespace


class UpdateScopeTests(unittest.TestCase):
    def setUp(self):
        self.tree, self.api = isolated(ROOT / "api/app.py")
        self.codes = next(ast.literal_eval(n.value) for n in self.tree.body
                          if isinstance(n, ast.Assign) and any(
                              isinstance(t, ast.Name) and t.id == "UPDATE_ROBOT_CODES" for t in n.targets))
        self.conn = Mock()
        self.engine = Mock()
        self.engine.begin.return_value.__enter__ = Mock(return_value=self.conn)
        self.engine.begin.return_value.__exit__ = Mock(return_value=False)
        self.api.update(os=os, UPDATE_ROBOT_CODES=self.codes, engine=self.engine,
                        text=lambda sql: sql, jsonify=lambda data: data,
                        request=SimpleNamespace(get_json=lambda **kw: {"robo_id": 51}, headers={}),
                        _usuario_autenticado=lambda: {"usuario_id": 1, "email": "mock"},
                        _resposta_jobs_admin=lambda user: None, log=Mock(),
                        _notify_agents=Mock(), _job_publico=lambda job: job,
                        _agent_autorizado=lambda: True, _interromper_jobs_sem_heartbeat=Mock())
        import json
        self.api["json"] = json
        self.env = patch.dict(os.environ, {"PORTAL_BI_AGENT_ENABLED": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_catalogs_match_exactly(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        catalog = html.split("const UPDATE_ROBOTS = [", 1)[1].split("\n];", 1)[0]
        self.assertEqual(set(re.findall(r"codigo:'([^']+)'", catalog)), set(self.codes))
        selector = html.split('<select id="updateModule"', 1)[1].split('</select>', 1)[0]
        self.assertEqual(set(re.findall(r'value="([^"]+)"', selector)), {"logistica", "suprimentos", "todos"})
        agent_tree = ast.parse((ROOT / "PortalBI/api/portal_bi_agent.py").read_text(encoding="utf-8-sig"))
        whitelist = next(n.value for n in agent_tree.body if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == "ROBOS" for t in n.targets))
        self.assertEqual({ast.literal_eval(k) for k in whitelist.keys}, set(self.codes))
        bat = (ROOT / "Atualizador_BI_Granja.bat").read_text(encoding="utf-8")
        jobs = re.findall(r"\(Job '([^']+)'", bat)
        self.assertEqual((jobs.count("Logistica"), jobs.count("Suprimentos"), len(jobs)), (10, 8, 18))

    def test_pause_never_opens_database(self):
        os.environ["PORTAL_BI_AGENT_ENABLED"] = "false"
        self.api["_resposta_jobs_pausados"] = lambda: ("paused", 503)
        self.assertEqual(self.api["api_criar_job"]()[1], 503)
        self.assertEqual(self.api["api_agent_claim_job"]()[1], 503)
        self.engine.begin.assert_not_called()

    def test_enabled_by_default(self):
        os.environ.pop("PORTAL_BI_AGENT_ENABLED", None)
        self.assertTrue(self.api["_agent_jobs_habilitados"]())

    def test_other_sectors_cannot_be_created(self):
        for code in ("comercial_faturamento_cfop", "tratar_comercial", "pcp_desperdicio", "tratar_zootecnico"):
            self.conn.reset_mock()
            self.conn.execute.return_value.mappings.return_value.first.return_value = {
                "id": 51, "codigo": code, "ativo": True}
            result = self.api["api_criar_job"]()
            self.assertEqual(result[1], 403)
            self.assertEqual(self.conn.execute.call_count, 1)  # SELECT only; no INSERT.
        self.api["_notify_agents"].assert_not_called()

    def test_allowed_job_is_created_and_notified(self):
        self.conn.execute.return_value.mappings.return_value.first.return_value = {
            "id": 51, "codigo": self.codes[0], "ativo": True}
        self.conn.execute.return_value.mappings.return_value.one.return_value = {"id": 999}
        self.assertEqual(self.api["api_criar_job"]()[1], 201)
        self.assertEqual(self.conn.execute.call_count, 2)
        self.api["_notify_agents"].assert_called_once_with()

    def test_permission_denied_before_job_sql(self):
        self.api["_resposta_jobs_admin"] = lambda user: ({"ok": False}, 403)
        self.assertEqual(self.api["api_criar_job"]()[1], 403)
        self.engine.begin.assert_not_called()

    def test_claim_scope_preserves_global_count(self):
        self.conn.execute.return_value.mappings.return_value.first.return_value = None
        self.assertIsNone(self.api["api_agent_claim_job"]()["job"])
        sql, params = self.conn.execute.call_args.args
        candidates, rest = sql.split("ativos AS (", 1)
        active = rest.split("dependencias AS (", 1)[0]
        self.assertIn("r.codigo = ANY(CAST(:codigos_permitidos AS text[]))", candidates)
        self.assertNotIn("codigos_permitidos", active)  # ALL active jobs count.
        self.assertIn("COUNT(*) FROM ativos WHERE LEFT(codigo, 7) <> 'tratar_') < 3", sql)
        self.assertEqual(set(params["codigos_permitidos"]), set(self.codes))

    def test_agent_commands_and_clean_environment(self):
        tree, agent = isolated(ROOT / "PortalBI/api/portal_bi_agent.py")
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                try:
                    agent[n.targets[0].id] = ast.literal_eval(n.value)
                except (ValueError, TypeError):
                    pass
        agent.update(ROBOS=dict.fromkeys(self.codes), os=os, sys=SimpleNamespace(executable="python"),
                     date=date, datetime=datetime, timedelta=timedelta)
        for code in self.codes:
            cmd, info = agent["montar_comando"](code, Path("mock.py"), {})
            if code.startswith("tratar_"):
                self.assertIn("--sem-pausa", cmd)
        with self.assertRaises(ValueError):
            agent["montar_comando"]("tratar_comercial", Path("mock.py"), {})
        with patch.dict(os.environ, {"AGROSYS_DATA_INICIO": "old", "AGROSYS_DATA_FIM": "old",
                                     "AGROSYS_SOLICITACOES_PARTICAO": "old"}):
            env = agent["montar_ambiente"]({"modo": "auto", "inicio": None, "fim": None})
        self.assertNotIn("AGROSYS_DATA_INICIO", env)
        self.assertNotIn("AGROSYS_DATA_FIM", env)
        self.assertNotIn("AGROSYS_SOLICITACOES_PARTICAO", env)
        self.assertEqual((agent["POLL_SECONDS"], agent["IDLE_RESYNC_SECONDS"], agent["HEARTBEAT_SECONDS"]), (5, 3600, 60))


if __name__ == "__main__":
    unittest.main()
