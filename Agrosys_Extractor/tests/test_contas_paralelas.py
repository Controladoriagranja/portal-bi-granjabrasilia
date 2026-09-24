"""Testes offline: nenhuma conexao com Agrosys, Portal ou banco."""
import ast
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from Core.agrosys_contas import ReservaArquivo, ReservaExecucao, contas_configuradas


class ContasTests(unittest.TestCase):
    def test_completas_distintas_limite_e_ambiente(self):
        config = {
            "USUARIO_AGROSYS": "a", "SENHA_AGROSYS": "s",
            "USUARIO_AGROSYS_2": "A", "SENHA_AGROSYS_2": "s",
            "USUARIO_AGROSYS_3": "c", "SENHA_AGROSYS_3": "",
            "USUARIO_AGROSYS_4": "d", "SENHA_AGROSYS_4": "s",
        }
        self.assertEqual([c[0] for c in contas_configuradas(config, {})], [1, 4])
        env = {"AGROSYS_USUARIO_2": "b", "AGROSYS_SENHA_3": "s"}
        self.assertEqual([c[0] for c in contas_configuradas(config, env)], [1, 2, 3])
        self.assertEqual(contas_configuradas({"USUARIO_AGROSYS": "COLOQUE_USUARIO"}, {}), [])

    def test_tres_contas_exclusivas_e_reutilizacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            contas = [(i, f"teste{i}", "senha-ficticia") for i in range(1, 4)]
            reservas = [ReservaExecucao(contas, "https://teste", f"robo{i}", tmp) for i in range(4)]
            try:
                usados = [r.adquirir()[0] for r in reservas[:3]]
                self.assertEqual(len(set(usados)), 3)
                resultado = []
                worker = threading.Thread(target=lambda: resultado.append(reservas[3].adquirir(0.01)[0]))
                worker.start()
                time.sleep(0.05)
                self.assertFalse(resultado)
                reservas[1].liberar()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(resultado, [usados[1]])
            finally:
                for r in reservas:
                    r.liberar()

    def test_reserva_entre_processos_e_liberacao_apos_encerrar(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "conta.lock"
            codigo = (
                "import sys; from pathlib import Path; "
                "sys.path.insert(0, sys.argv[1]); "
                "from Core.agrosys_contas import ReservaArquivo; "
                "r=ReservaArquivo(sys.argv[2]); print(r.tentar(), flush=True); "
                "sys.stdin.readline()"
            )
            proc = subprocess.Popen(
                [sys.executable, "-B", "-u", "-c", codigo, str(RAIZ), str(lock)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            reserva = ReservaArquivo(lock)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "True")
                self.assertFalse(reserva.tentar())
                proc.terminate()
                proc.wait(timeout=5)
                self.assertTrue(reserva.tentar())
            finally:
                reserva.liberar()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.communicate(timeout=5)

    def test_mesmo_robo_aguarda_sem_ocupar_conta(self):
        with tempfile.TemporaryDirectory() as tmp:
            contas = [(1, "a", "s"), (2, "b", "s")]
            a = ReservaExecucao(contas, "url", "mesmo", tmp)
            b = ReservaExecucao(contas, "url", "mesmo", tmp)
            c = ReservaExecucao(contas, "url", "outro", tmp)
            try:
                self.assertEqual(a.adquirir()[0], "a")
                self.assertFalse(b.robo.tentar())
                self.assertEqual(c.adquirir()[0], "b")
                a.liberar()
                self.assertEqual(b.adquirir()[0], "a")
            finally:
                for r in (a, b, c):
                    r.liberar()


class FilaTests(unittest.TestCase):
    def test_tratamento_liberado_nao_espera_outros_modulos(self):
        arquivo = RAIZ.parent / "PortalBI" / "api" / "portal_bi_agent.py"
        arvore = ast.parse(arquivo.read_text(encoding="utf-8-sig"))
        funcao = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "executar_fila_paralela")
        eventos = []
        guarda = threading.Lock()
        jobs = iter([
            {"id": i, "robo_codigo": nome}
            for i, nome in enumerate(["a", "b", "c", "tratar_comercial", "tratar_logistica"], 1)
        ])
        def claim():
            try:
                return next(jobs)
            except StopIteration:
                raise KeyboardInterrupt
        liberado = threading.Event()
        def executar(job):
            nome = job["robo_codigo"]
            with guarda:
                eventos.append(("inicio", nome))
            if nome.startswith("tratar_"):
                liberado.set()
            else:
                self.assertTrue(liberado.wait(3))
            with guarda:
                eventos.append(("fim", nome))
        def heartbeat(job_id, parar):
            parar.wait()
        import types
        namespace = {
            "threading": threading, "time": time, "POLL_SECONDS": 0.001,
            "claim_job": claim, "executar_job": executar, "_loop_heartbeat": heartbeat,
            "requests": types.SimpleNamespace(RequestException=ConnectionError),
        }
        exec(compile(ast.Module(body=[funcao], type_ignores=[]), str(arquivo), "exec"), namespace)
        namespace["executar_fila_paralela"](3)
        for nome in ["a", "b", "c"]:
            self.assertLess(eventos.index(("inicio", "tratar_comercial")), eventos.index(("fim", nome)))
        rodando = pico = 0
        for evento, _ in eventos:
            rodando += 1 if evento == "inicio" else -1
            pico = max(pico, rodando)
        self.assertGreaterEqual(pico, 4)
        self.assertEqual(rodando, 0)



class IntegracaoTests(unittest.TestCase):
    def test_todos_os_extratores_do_agent_usam_runtime(self):
        from pathlib import PureWindowsPath
        agent = RAIZ.parent / "PortalBI/api/portal_bi_agent.py"
        tree = ast.parse(agent.read_text(encoding="utf-8-sig"))
        cadastro = next(n for n in tree.body if isinstance(n, ast.Assign)
                        and isinstance(n.value, ast.Dict)
                        and any(isinstance(t, ast.Name) and t.id == "ROBOS" for t in n.targets))
        extratores = 0
        for key, value in zip(cadastro.value.keys, cadastro.value.values):
            original = PureWindowsPath(ast.literal_eval(value.args[0]))
            p = RAIZ.parent.joinpath(*original.parts[original.parts.index("BI_Granja") + 1:])
            self.assertTrue(p.is_file(), ast.literal_eval(key))
            if "Agrosys_Extractor" not in original.parts:
                continue
            extratores += 1
            tree_robo = ast.parse(p.read_text(encoding="utf-8-sig"))
            imports = [n for n in ast.walk(tree_robo) if isinstance(n, ast.ImportFrom)]
            self.assertFalse(any(n.module == "config" for n in imports), p.name)
            nomes = {a.name for n in imports if n.module == "Core.agrosys_runtime" for a in n.names}
            self.assertTrue({"USUARIO_AGROSYS", "SENHA_AGROSYS", "PASTA_HTML", "PASTA_DOWNLOAD"} <= nomes, p.name)
            self.assertFalse(any(isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PASTA_DOWNLOAD" for t in n.targets
            ) for n in ast.walk(tree_robo)), p.name)
        self.assertEqual(extratores, 31)

    def test_runtime_preserva_credenciais_e_isola_pastas(self):
        import runpy
        config = {"BASE_AGROSYS": "https://teste", "USUARIO_AGROSYS": "a", "SENHA_AGROSYS": "s"}
        arquivo = RAIZ / "Core/agrosys_runtime.py"
        scripts = [
            RAIZ / "Suprimentos/suprimentos_notas_fiscais_item.py",
            RAIZ / "Suprimentos/suprimentos_notas_fiscais_item_HISTORICO_2025.py",
            RAIZ / "Logistica/logistica_frete.py",
        ]
        recursos = []
        pastas = []
        for script in scripts:
            with patch("Core.agrosys_contas.carregar_config", return_value=config), \
                 patch("Core.agrosys_contas.ReservaExecucao") as reserva, \
                 patch.object(sys, "argv", [str(script)]), patch.dict(os.environ, {}, clear=True):
                reserva.return_value.adquirir.return_value = ("selecionado", "senha-teste")
                resultado = {"__file__": str(arquivo)}
                exec(compile(arquivo.read_text(encoding="utf-8"), str(arquivo), "exec"), resultado)
                self.assertEqual(resultado["USUARIO_AGROSYS"], "selecionado")
                self.assertEqual(resultado["SENHA_AGROSYS"], "senha-teste")
                recursos.append(reserva.call_args.args[2])
                pastas.append(resultado["PASTA_DOWNLOAD"])
        self.assertEqual(recursos[0], recursos[1])
        self.assertNotEqual(recursos[0], recursos[2])
        self.assertEqual(len(set(pastas)), 3)


if __name__ == "__main__":
    unittest.main()
