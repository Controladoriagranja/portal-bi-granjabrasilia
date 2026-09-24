"""Valida a regra SQL com dados ficticios e SELECT, sem alterar tabelas."""
import ast
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "PortalBI/api"))
from dotenv import load_dotenv
load_dotenv(RAIZ / "PortalBI/api/.env")
from database import engine
from sqlalchemy import text

REPO = RAIZ if (RAIZ / "index.html").is_file() else RAIZ / "portal-bi-granjabrasilia"
source = (REPO / "api/app.py").read_text(encoding="utf-8")
inicio = source.index("                WITH candidatos", source.index("def api_agent_claim_job():"))
fim = source.index("                UPDATE public.jobs j", inicio)
sql = source[inicio:fim].strip()
sql = sql.replace("WITH candidatos", ", candidatos", 1)
sql = sql.replace("public.jobs", "test_jobs").replace("public.robos", "test_robos")
sql = sql.replace("FOR UPDATE OF j SKIP LOCKED", "")
prefixo = """
WITH test_jobs AS (
 SELECT * FROM jsonb_to_recordset(CAST(:jobs AS jsonb))
 AS x(id bigint, robo_id bigint, status text, parametros jsonb)
), test_robos AS (
 SELECT * FROM jsonb_to_recordset(CAST(:robos AS jsonb))
 AS x(id bigint, codigo text, ativo boolean)
)
"""
consulta = text(prefixo + sql + " SELECT id FROM proximo")
robos = [
 {"id": 1, "codigo": "pcp_desperdicio", "ativo": True},
 {"id": 2, "codigo": "pcp_devolucao", "ativo": True},
 {"id": 3, "codigo": "pcp_estoque_online", "ativo": True},
 {"id": 4, "codigo": "tratar_pcp", "ativo": True},
 {"id": 5, "codigo": "comercial_faturamento_cfop", "ativo": True},
 {"id": 6, "codigo": "tratar_comercial", "ativo": True},
 {"id": 7, "codigo": "indice_zootecnico_base_dinamica", "ativo": True},
 {"id": 8, "codigo": "tratar_zootecnico", "ativo": True},
]
def job(i, robo, status, params=None):
 return {"id": i, "robo_id": robo, "status": status, "parametros": {} if params is None else params}

casos = [
 ("tratamento com tres extracoes de outro modulo", [job(1,1,"executando"),job(2,2,"executando"),job(3,3,"executando"),job(4,6,"aguardando",{"dependencias":[]})], 4),
 ("dependencias antigas de outro modulo ignoradas", [job(1,5,"erro"),job(2,1,"concluido"),job(3,4,"aguardando",{"dependencias":[1,2]})], 3),
 ("outro tratamento nao bloqueia extracao", [job(1,6,"executando"),job(2,1,"aguardando")], 2),
 ("tratamentos distintos em paralelo", [job(1,6,"executando"),job(2,4,"aguardando",{"dependencias":[]})], 2),
 ("mesmo modulo ativo bloqueia mesmo sem dependencia", [job(1,1,"executando"),job(2,4,"aguardando",{"dependencias":[]})], None),
 ("tratamento nao consome conta", [job(1,6,"executando"),job(2,1,"executando"),job(3,2,"executando"),job(4,3,"aguardando")], 4),
 ("fila inicia extracao", [job(1,1,"aguardando")], 1),
 ("limite global tres", [job(1,1,"executando"),job(2,2,"executando"),job(3,3,"executando"),job(4,5,"aguardando")], None),
 ("nao duplica robo", [job(1,1,"executando"),job(2,1,"aguardando")], None),
 ("tratamento espera ativos", [job(1,1,"executando"),job(2,4,"aguardando",{"dependencias":[1]})], None),
 ("tratamento espera falha", [job(1,1,"erro"),job(2,4,"aguardando",{"dependencias":[1]})], None),
 ("recuperacao passa a frente", [job(1,1,"erro"),job(2,4,"aguardando",{"dependencias":[1]}),job(3,1,"aguardando")], 3),
 ("recuperacao libera tratamento", [job(1,1,"erro"),job(2,4,"aguardando",{"dependencias":[1]}),job(3,1,"concluido")], 2),
 ("periodo diferente nao libera", [job(1,1,"erro",{"dias":2}),job(2,4,"aguardando",{"dependencias":[1]}),job(3,1,"concluido",{"dias":3})], None),
 ("todas dependencias sucesso", [job(1,1,"concluido"),job(2,2,"concluido"),job(3,4,"aguardando",{"dependencias":[1,2]})], 3),
 ("dependencia inexistente bloqueia", [job(1,4,"aguardando",{"dependencias":[99]})], None),
 ("tratamento exclui extracoes", [job(1,4,"executando"),job(2,1,"aguardando")], None),
 ("jobs antigos PCP protegidos", [job(1,1,"erro"),job(2,4,"aguardando")], None),
 ("jobs antigos zootecnico protegidos", [job(1,7,"erro"),job(2,8,"aguardando")], None),
 ("outro setor nao bloqueia", [job(1,5,"erro"),job(2,1,"concluido"),job(3,4,"aguardando")], 3),
 ("ultimo historico prevalece", [job(1,1,"erro"),job(2,1,"concluido"),job(3,4,"aguardando")], 3),
]
with engine.connect() as conn:
 for nome, jobs, esperado in casos:
  atual = conn.execute(consulta, {"jobs":json.dumps(jobs), "robos":json.dumps(robos)}).scalar()
  assert atual == esperado, (nome, atual, esperado)
  print("OK:",nome)
print(f"{len(casos)} cenarios SQL aprovados; nenhuma tabela alterada.")
