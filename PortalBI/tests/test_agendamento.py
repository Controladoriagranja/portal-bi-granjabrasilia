import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import agendar_atualizacoes as agenda


class Resultado:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return self.rows
    def scalar_one(self): return self.rows[0]


class Conexao:
    def __init__(self, existentes=()):
        self.existentes = list(existentes)
        self.inseridos = []
    def execute(self, sql, params=None):
        s = str(sql)
        if "FROM public.robos" in s:
            return Resultado([{"id":3,"codigo":"tratar_teste","ativo":True},
                              {"id":1,"codigo":"teste_a","ativo":True},
                              {"id":2,"codigo":"teste_b","ativo":True}])
        if "FROM public.jobs" in s: return Resultado(self.existentes)
        if "INSERT INTO" in s:
            self.inseridos.append(params)
            return Resultado([100 + len(self.inseridos)])
        return Resultado([])


class AgendaTests(unittest.TestCase):
    def setUp(self):
        arquivo = Path(__file__)
        self.patch = patch.dict(agenda.ROBOS, {c:arquivo for c in ["teste_a","teste_b","tratar_teste"]}, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
    def test_lote_com_dependencias_e_sem_usuario_falso(self):
        c = Conexao()
        r = agenda.criar_lote(c,"2026-09-25")
        self.assertEqual(r["jobs"],[101,102,103])
        self.assertEqual([x["robo_id"] for x in c.inseridos],[1,2,3])
        p = json.loads(c.inseridos[-1]["parametros"])
        self.assertEqual(p["dependencias"],[101,102])
        self.assertEqual(p["data_agendamento"],"2026-09-25")
    def test_mesmo_dia_nao_duplica(self):
        c = Conexao([101,102,103])
        r = agenda.criar_lote(c,"2026-09-25")
        self.assertFalse(r["criado"])
        self.assertFalse(c.inseridos)
    def test_verificacao_nao_cria_jobs(self):
        c = Conexao()
        r = agenda.criar_lote(c,"2026-09-25",verificar=True)
        self.assertEqual((r["extratores"],r["tratamentos"]),(2,1))
        self.assertFalse(c.inseridos)


if __name__ == "__main__":
    unittest.main()
