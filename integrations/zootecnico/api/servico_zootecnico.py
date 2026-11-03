import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from enum import Enum

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import base64
import binascii

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool

# Router genérico dos BIs.
from bi_generic.router import criar_router
from portal_router import criar_router_portal
from zootecnico_acesso import dispatch as zootecnico_dispatch, scoped_connection


def validar_acesso(usuario, senha):
    if usuario not in {"admin", "vitor", "granjabiadmin"} or not senha:
        return False

    try:
        with psycopg.connect(
            host=os.environ["PGHOST"],
            dbname=os.environ["PGDATABASE"],
            user=usuario,
            password=senha,
            connect_timeout=5,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=5000"
            ),
        ) as conn:
            conn.execute("SELECT 1")

        return True

    except psycopg.Error:
        return False


class Autenticacao(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        autorizado = False

        header = request.headers.get("authorization", "")

        if len(header) <= 4096:
            try:
                esquema, valor = header.split(" ", 1)

                if esquema.lower() == "basic":
                    usuario, senha = (
                        base64.b64decode(
                            valor,
                            validate=True,
                        )
                        .decode("utf-8")
                        .split(":", 1)
                    )

                    autorizado = await run_in_threadpool(
                        validar_acesso,
                        usuario,
                        senha,
                    )

            except (
                ValueError,
                UnicodeError,
                binascii.Error,
            ):
                pass

        if not autorizado:
            return JSONResponse(
                status_code=401,
                content={
                    "mensagem": (
                        "Informe o usuário e a senha usados no "
                        "Adminer (granjabiadmin, admin ou vitor)."
                    )
                },
                headers={
                    "WWW-Authenticate": (
                        'Basic realm="API Zootecnico", charset="UTF-8"'
                    ),
                    "Cache-Control": "no-store",
                },
            )

        response = await zootecnico_dispatch(request, call_next)
        response.headers["Cache-Control"] = "no-store"

        return response


app = FastAPI(
    title="Granja Brasília — Portal de Dados",
    description=(
        "Consultas de leitura exclusivamente dos esquemas zootecnico, matrizes e pcp do PostgreSQL."
    ),
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

# Rotas genéricas compartilhadas pelos BIs.
# Exemplo atual:
# /api/bi/zootecnico/filtros
# Registrado abaixo, após a definição da factory banco().

app.add_middleware(Autenticacao)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET"],
    allow_headers=[
        "Accept",
        "Content-Type",
        "Authorization",
    ],
)


class Tabela(str, Enum):
    base_dinamica = "base_dinamica"
    mortalidade_peso_abertos = "mortalidade_peso_abertos"
    mortalidade_peso_fechados = "mortalidade_peso_fechados"
    matrizes_acerto_produtor = "matrizes_acerto_produtor"


CONFIG = {
    "base_dinamica": (
        "lote",
        "produtor",
        "periodo_inicio",
        "periodo_fim",
        "carregado_em",
    ),
    "mortalidade_peso_abertos": (
        "num_lote",
        "nome_granja",
        "periodo_inicio",
        "periodo_fim",
        "carregado_em",
    ),
    "mortalidade_peso_fechados": (
        "num_lote",
        "nome_granja",
        "periodo_inicio",
        "periodo_fim",
        "carregado_em",
    ),
    "matrizes_acerto_produtor": (
        "lote",
        "granja",
        "data_referencia",
        "data_referencia",
        "atualizado_em",
    ),
}


@contextmanager
def banco():
    with psycopg.connect(
        host=os.environ["PGHOST"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        connect_timeout=5,
        options=(
            "-c default_transaction_read_only=on "
            "-c statement_timeout=15000"
        ),
        row_factory=dict_row,
    ) as conn:
        conn.execute(
            "SET TRANSACTION ISOLATION LEVEL "
            "REPEATABLE READ READ ONLY"
        )

        yield scoped_connection(conn)


app.include_router(criar_router(banco))
app.include_router(criar_router_portal(banco))


@app.exception_handler(psycopg.Error)
async def erro_banco(request: Request, exc):
    # Nova modifica??o de 27/10/2026: diagn?stico sem SQL, conex?o, senha ou traceback.
    state=getattr(exc,'sqlstate',None)
    primary=str(getattr(getattr(exc,'diag',None),'message_primary','') or '').lower()
    if state=='57014':
        timeout='statement timeout' in primary
        code='DB_QUERY_TIMEOUT' if timeout else 'DB_QUERY_CANCELED'
        message='A consulta ultrapassou o limite de tempo.' if timeout else 'A consulta foi cancelada pelo banco.'
    elif state in ('42P01','42703'):
        code='DB_STRUCTURE_ERROR';message='A consulta encontrou uma tabela ou coluna indispon?vel.'
    elif state=='42501':
        code='DB_PERMISSION_ERROR';message='O servi?o n?o tem permiss?o para consultar uma das fontes.'
    elif state and state.startswith('08'):
        code='DB_CONNECTION_ERROR';message='N?o foi poss?vel manter a conex?o com o banco.'
    else:
        code='DB_QUERY_ERROR';message='N?o foi poss?vel consultar os dados.'
    return JSONResponse(status_code=503,content={'mensagem':message,'codigo':code})


@app.exception_handler(RequestValidationError)
async def parametros_invalidos(
    request: Request,
    exc,
):
    return JSONResponse(
        status_code=422,
        content={
            "mensagem": (
                "Parâmetros inválidos. Confira a tabela, "
                "as datas e os limites na documentação."
            ),
            "campos": [
                str(e["loc"][-1])
                for e in exc.errors()
            ],
        },
    )


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def painel_teste():
    return FileResponse(
        Path(__file__).with_name("documentacao_zootecnico.html")
    )


@app.get("/docs", include_in_schema=False)
def documentacao():
    return FileResponse(
        Path(__file__).with_name(
            "documentacao_zootecnico.html"
        )
    )


@app.get(
    "/api/zootecnico/health",
    summary="Verificar conexão e tabelas",
)
def saude():
    with banco() as c:
        presentes = {
            t: (
                c.execute(
                    "SELECT to_regclass(%s) AS tabela",
                    ("zootecnico." + t,),
                )
                .fetchone()["tabela"]
                is not None
            )
            for t in CONFIG
        }

        return JSONResponse(
            status_code=(
                200
                if all(presentes.values())
                else 503
            ),
            content={
                "situacao": (
                    "conectado"
                    if all(presentes.values())
                    else "estrutura incompleta"
                ),
                "tabelas": presentes,
            },
        )


@app.get(
    "/api/zootecnico/resumo",
    summary=(
        "Consultar quantidades de registros "
        "e últimas cargas"
    ),
)
def resumo():
    result = {}

    with banco() as c:
        for (
            table,
            (
                lot,
                farm,
                start,
                end,
                updated,
            ),
        ) in CONFIG.items():

            query = sql.SQL(
                """
                SELECT
                    COUNT(*) AS registros,
                    COUNT(
                        DISTINCT NULLIF(
                            BTRIM({lote}),
                            ''
                        )
                    ) AS codigos_lote_distintos,
                    MIN({inicio}) AS primeira_data,
                    MAX({fim}) AS ultima_data,
                    MAX({atualizado}) AS ultima_carga
                FROM zootecnico.{tabela}
                """
            ).format(
                lote=sql.Identifier(lot),
                inicio=sql.Identifier(start),
                fim=sql.Identifier(end),
                atualizado=sql.Identifier(updated),
                tabela=sql.Identifier(table),
            )

            result[table] = (
                c.execute(query).fetchone()
            )

    return {
        "tabelas": result,
        "observacao": (
            "Contagens de registros, sem somar aves, "
            "pesos ou taxas. Um código de lote pode "
            "ocorrer em várias granjas; não equivale "
            "a uma quantidade de lotes únicos da operação."
        ),
    }


@app.get(
    "/api/zootecnico/estrutura/{tabela}",
    summary="Consultar colunas e tipos",
)
def estrutura(tabela: Tabela):
    with banco() as c:
        rows = c.execute(
            """
            SELECT
                column_name AS coluna,
                data_type AS tipo
            FROM information_schema.columns
            WHERE table_schema = 'zootecnico'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (tabela.value,),
        ).fetchall()

    return {
        "tabela": tabela.value,
        "colunas": rows,
    }


@app.get(
    "/api/zootecnico/dados/{tabela}",
    summary=(
        "Consultar registros com filtros "
        "e paginação"
    ),
)
def dados(
    tabela: Tabela,
    pagina: int = Query(
        1,
        ge=1,
        le=1000000,
    ),
    tamanho: int = Query(
        100,
        ge=1,
        le=500,
    ),
    lote: str | None = Query(
        None,
        max_length=200,
    ),
    granja: str | None = Query(
        None,
        max_length=200,
    ),
    data_inicio: date | None = None,
    data_fim: date | None = None,
):
    if (
        data_inicio
        and data_fim
        and data_inicio > data_fim
    ):
        raise HTTPException(
            422,
            detail=(
                "A data inicial deve ser menor "
                "ou igual à data final."
            ),
        )

    lot, farm, start, end, _ = (
        CONFIG[tabela.value]
    )

    conditions = []
    values = []

    for col, value in [
        (lot, lote),
        (farm, granja),
    ]:
        if value is not None:
            conditions.append(
                sql.SQL("{} = %s").format(
                    sql.Identifier(col)
                )
            )
            values.append(value)

    # Interseção com o período da exportação;
    # em matrizes, filtra a data de referência.
    for col, op, value in [
        (end, ">=", data_inicio),
        (start, "<=", data_fim),
    ]:
        if value is not None:
            conditions.append(
                sql.SQL(
                    "{} " + op + " %s"
                ).format(
                    sql.Identifier(col)
                )
            )
            values.append(value)

    where = (
        sql.SQL(" WHERE ")
        + sql.SQL(" AND ").join(conditions)
        if conditions
        else sql.SQL("")
    )

    table = sql.Identifier(
        "zootecnico",
        tabela.value,
    )

    with banco() as c:
        total = c.execute(
            sql.SQL(
                "SELECT COUNT(*) AS total FROM {}"
            ).format(table)
            + where,
            values,
        ).fetchone()["total"]

        rows = c.execute(
            sql.SQL(
                "SELECT * FROM {}"
            ).format(table)
            + where
            + sql.SQL(
                " ORDER BY id LIMIT %s OFFSET %s"
            ),
            values
            + [
                tamanho,
                (pagina - 1) * tamanho,
            ],
        ).fetchall()

    return {
        "tabela": tabela.value,
        "pagina": pagina,
        "tamanho": tamanho,
        "total": total,
        "total_paginas": (
            total + tamanho - 1
        )
        // tamanho,
        "dados": rows,
    }


# Endereços diretos para facilitar
# a integração com os painéis.
def rota_direta(tabela):
    def consultar(
        pagina: int = Query(
            1,
            ge=1,
            le=1000000,
        ),
        tamanho: int = Query(
            100,
            ge=1,
            le=500,
        ),
        lote: str | None = Query(
            None,
            max_length=200,
        ),
        granja: str | None = Query(
            None,
            max_length=200,
        ),
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ):
        return dados(
            tabela,
            pagina,
            tamanho,
            lote,
            granja,
            data_inicio,
            data_fim,
        )

    return consultar


for caminho, tabela in [
    (
        "base-dinamica",
        Tabela.base_dinamica,
    ),
    (
        "mortalidade-peso/abertos",
        Tabela.mortalidade_peso_abertos,
    ),
    (
        "mortalidade-peso/fechados",
        Tabela.mortalidade_peso_fechados,
    ),
    (
        "matrizes-acerto-produtor",
        Tabela.matrizes_acerto_produtor,
    ),
]:
    app.add_api_route(
        "/api/zootecnico/" + caminho,
        rota_direta(tabela),
        methods=["GET"],
        summary=(
            "Consultar "
            + tabela.value.replace("_", " ")
        ),
        name=(
            "consultar_"
            + tabela.value
        ),
    )


@app.get("/logo-granja.png", include_in_schema=False)
def logo_granja():
    return FileResponse(Path(__file__).with_name("logo_granja.png"))


# API PCP integrada: usa a autenticacao existente e consultas somente de leitura.
import sys as _pcp_sys
_pcp_sys.path.insert(0, str(Path(__file__).resolve().parent / "pcp_dados"))
from api_pcp import router as _pcp_router
app.include_router(_pcp_router)

# PCP mantém a conexão, autenticação e política de leitura do serviço existente.
from pcp_painel import criar_router_pcp
app.include_router(criar_router_pcp(banco))

@app.get("/pcp", include_in_schema=False)
@app.get("/pcp/", include_in_schema=False)
def pagina_pcp():
    return FileResponse(Path(__file__).with_name("documentacao_zootecnico.html"))

# Comparativo PCP: consulta somente leitura, mesma factory e autenticação.
from pcp_comparativo import criar_router_comparativo
app.include_router(criar_router_comparativo(banco))

# Comercial HTML: módulo independente do faturamento-nf existente.
from comercial_html import criar_router_comercial_html
app.include_router(criar_router_comercial_html(banco))

# Frete manual: router isolado, sem alterar a conexao de leitura ou outros BIs.
from frete_manual import criar_router_frete_manual
app.include_router(criar_router_frete_manual(banco))

# Suprimentos HTML: relatórios e fila de robôs com sessão CENTRAL.
from suprimentos_html import criar_router_suprimentos
app.include_router(criar_router_suprimentos(banco))


# Comparativo PM FOB: mesma factory banco() e autenticacao da API existente.
from bi_generic.comparativo_fob.routes import criar_router_comparativo_fob
app.include_router(criar_router_comparativo_fob(banco))

# Logística HTML: módulo independente, com o mesmo transporte autenticado.
from logistica_html import criar_router_logistica
app.include_router(criar_router_logistica(banco))
app.include_router(criar_router_logistica(banco,prefix='/api/suprimentos-html/logistica'))
