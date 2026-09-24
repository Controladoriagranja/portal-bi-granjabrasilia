"""Cria o lote diario do Portal BI de forma atomica e sem duplicar o dia."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from portal_bi_agent import ROBOS
from database import engine

AGENDA = "todos_diario_04h"


def planejar_lote(catalogo):
    ativos = {r["codigo"]: r for r in catalogo if r["ativo"]}
    faltantes = sorted(set(ativos) - set(ROBOS))
    if faltantes:
        raise RuntimeError("Robos ativos sem suporte no Agent: " + ", ".join(faltantes))
    ausentes = [c for c in ativos if not ROBOS[c].is_file()]
    if ausentes:
        raise RuntimeError("Scripts ausentes: " + ", ".join(ausentes))
    if not ativos:
        raise RuntimeError("Nenhum robo ativo no portal.")
    return sorted(ativos.values(), key=lambda r: (r["codigo"].startswith("tratar_"), r["id"]))


def criar_lote(conn, dia, verificar=False):
    catalogo = conn.execute(text("SELECT id, codigo, ativo FROM public.robos ORDER BY id")).mappings().all()
    plano = planejar_lote(catalogo)
    if verificar:
        return {"verificacao": True, "total": len(plano),
                "extratores": sum(not r["codigo"].startswith("tratar_") for r in plano),
                "tratamentos": sum(r["codigo"].startswith("tratar_") for r in plano)}
    # Mesmo dia, mesmo lote, inclusive se houver reinicio apos falha de rede.
    conn.execute(text("SELECT pg_advisory_xact_lock(742013, 4)"))
    existentes = conn.execute(text("""
        SELECT id FROM public.jobs
        WHERE parametros->>'agendamento' = :agenda
          AND parametros->>'data_agendamento' = :dia
        ORDER BY id
    """), {"agenda": AGENDA, "dia": dia}).scalars().all()
    if existentes:
        return {"criado": False, "dia": dia, "jobs": existentes}
    ids = []
    extracoes = []
    for robo in plano:
        parametros = {"modo": "auto", "tratamento_modo": "atualizar_tratar",
                      "agendamento": AGENDA, "data_agendamento": dia}
        if robo["codigo"].startswith("tratar_"):
            parametros["dependencias"] = list(extracoes)
        job_id = conn.execute(text("""
            INSERT INTO public.jobs (robo_id, solicitado_por, status, parametros)
            VALUES (:robo_id, NULL, 'aguardando', CAST(:parametros AS jsonb))
            RETURNING id
        """), {"robo_id": robo["id"], "parametros": json.dumps(parametros)}).scalar_one()
        ids.append(job_id)
        if not robo["codigo"].startswith("tratar_"):
            extracoes.append(job_id)
    return {"criado": True, "dia": dia, "jobs": ids, "extratores": len(extracoes),
            "tratamentos": len(ids) - len(extracoes)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verificar", action="store_true", help="Valida acesso e robos sem criar trabalhos.")
    args = parser.parse_args()
    # A tarefa do Windows usa o fuso Brasilia, verificado na instalacao.
    dia = datetime.now().date().isoformat()
    with engine.begin() as conn:
        resultado = criar_lote(conn, dia, verificar=args.verificar)
    print(json.dumps(resultado, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
