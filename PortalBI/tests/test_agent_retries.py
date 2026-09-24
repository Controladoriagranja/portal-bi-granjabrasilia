"""Testes offline do Agent, sem executar robos nem acessar o portal."""
import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

RAIZ = Path(__file__).resolve().parents[2]
arquivo = RAIZ / "PortalBI/api/portal_bi_agent.py"
spec = importlib.util.spec_from_file_location("agent_testado", arquivo)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class RetryTests(unittest.TestCase):
    def rodar(self, codigos, erro_finish=False):
        processos = []
        for codigo in codigos:
            proc = Mock()
            proc.communicate.return_value = ("Conta reservada\nUnidade: REAL\nData: 21/09/2026\nErro: download incompleto", "")
            proc.returncode = codigo
            processos.append(proc)
        with patch.dict(agent.ROBOS, {"teste": arquivo}), \
             patch.object(agent, "montar_comando", return_value=(["python", "teste.py"], {})), \
             patch.object(agent, "montar_ambiente", return_value={}), \
             patch.object(agent, "_loop_heartbeat"), \
             patch.object(agent, "gravar_log_tentativa") as logs, \
             patch.object(agent.subprocess, "Popen", side_effect=processos) as popen, \
             patch.object(agent, "finish_job", side_effect=ConnectionError("offline") if erro_finish else None) as finish, \
             patch.object(agent.time, "sleep") as sleep:
            if erro_finish:
                with self.assertRaises(ConnectionError):
                    agent.executar_job({"id": 999, "robo_codigo": "teste"})
            else:
                agent.executar_job({"id": 999, "robo_codigo": "teste"})
            for chamada in popen.call_args_list:
                self.assertEqual(chamada.kwargs["stdin"], agent.subprocess.DEVNULL)
            return popen.call_count, finish.call_args, sleep.call_count, logs.call_count

    def test_falha_duas_vezes_e_conclui_sem_enter(self):
        n, finish, sleeps, logs = self.rodar([1, 1, 0])
        self.assertEqual((n, sleeps, logs), (3, 2, 3))
        self.assertEqual(finish.args, (999, "concluido"))

    def test_tres_falhas_mantem_causa(self):
        n, finish, sleeps, logs = self.rodar([1, 1, 1])
        self.assertEqual((n, sleeps, logs), (3, 2, 3))
        self.assertEqual(finish.args[:2], (999, "erro"))
        self.assertIn("download incompleto", finish.args[2])
        self.assertIn("REAL", finish.args[2])

    def test_falha_ao_enviar_sucesso_nao_repete_extracao(self):
        n, _, sleeps, logs = self.rodar([0], erro_finish=True)
        self.assertEqual((n, sleeps, logs), (1, 0, 1))

    def test_parametros_invalidos_nao_executam(self):
        with patch.dict(agent.ROBOS, {"teste": arquivo}), \
             patch.object(agent, "montar_comando", side_effect=ValueError("data invalida")), \
             patch.object(agent.subprocess, "Popen") as popen, \
             patch.object(agent, "finish_job") as finish:
            agent.executar_job({"id": 999, "robo_codigo": "teste"})
            popen.assert_not_called()
            self.assertIn("data invalida", finish.call_args.args[2])

    def test_robos_e_tratamentos_sem_input(self):
        total = 0
        for pasta in ("Agrosys_Extractor", "Python"):
            for p in (RAIZ / pasta).rglob("*.py"):
                if any(x in str(p).lower() for x in ("copia", "copy", "_old", "teste_puxar", "__pycache__", "\\tests\\", "/tests/")):
                    continue
                tree = ast.parse(p.read_text(encoding="utf-8-sig"))
                self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "input" for n in ast.walk(tree)), p.name)
                total += 1
        self.assertGreater(total, 30)


if __name__ == "__main__":
    unittest.main()
