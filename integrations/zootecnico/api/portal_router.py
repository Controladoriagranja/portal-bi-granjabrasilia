"""Catálogo dinâmico, somente leitura, preservando as rotas existentes.

Compatibilidade mantida:
- /api/portal/zootecnico/...
- /api/portal/matrizes/...
- /api/portal/bd_classif/...
- /api/portal/bd_aproveit/...
- /api/portal/bd_incubacao/...
- /api/portal/bd_eclosao/...
- /api/portal/bd_embrio/...

Além disso, quando o módulo é ``matrizes`` a rota de dados consegue resolver
as tabelas que fisicamente estão nos schemas auxiliares.
"""

from fastapi import APIRouter, HTTPException, Query
from psycopg import sql
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread
from time import monotonic
from copy import deepcopy
from contextvars import copy_context
from pathlib import Path
import json


class ResumoCache:
    """Contagens exatas; atualiza em segundo plano e preserva o último sucesso."""
    def __init__(self, ttl=60):
        self.ttl=ttl
        self.lock=Lock()
        self.values={}
        self.seed=Path('/app/portal_cache/modulos.json')
        if self.seed.exists():
            try:
                saved=json.loads(self.seed.read_text(encoding='utf-8'))
                self.values['modulos']=(monotonic()-ttl,saved['value'])
            except (ValueError,KeyError,OSError):pass
        self.pending={}
        self.retry_after={}
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='portal-resumo')

    def get(self, key, loader):
        with self.lock:
            entry=self.values.get(key)
            future=self.pending.get(key)
            if (entry is None or monotonic()-entry[0]>=self.ttl) and future is None and monotonic()>=self.retry_after.get(key,0):
                future=self.pool.submit(copy_context().run,self._load,key,loader)
                self.pending[key]=future
        if entry is not None:
            return deepcopy(entry[1])
        if future is None:
            raise HTTPException(503,'Resumo temporariamente indisponível. Tente novamente.')
        return deepcopy(future.result())

    def _load(self,key,loader):
        try:
            result=loader()
            if key=='modulos':
                try:
                    self.seed.parent.mkdir(parents=True,exist_ok=True)
                    temp=self.seed.with_suffix('.tmp')
                    temp.write_text(json.dumps({'key':key,'value':result},default=str),encoding='utf-8');temp.replace(self.seed)
                except OSError:pass
            with self.lock:
                self.values[key]=(monotonic(),result)
            return result
        except Exception:
            with self.lock:
                self.retry_after[key]=monotonic()+10
            raise
        finally:
            with self.lock:
                self.pending.pop(key,None)



ESQUEMAS = {
    "logistica_html": "Logística HTML",
    "zootecnico": "Zootécnico",
    "matrizes": "Matrizes",
    "pcp": "PCP",
    "comercial": "Comercial",
    "comercial_html": "Comercial HTML (novo)",
    "dados": "Dados",
    "ingestao": "Ingestão",
}

SCHEMAS_AUTORIZADOS = (
    "comercial_html",
    "comercial",
    "dados",
    "ingestao",
    "pcp",
    "zootecnico",
    "matrizes",
    "bd_classif",
    "bd_aproveit",
    "bd_incubacao",
    "bd_eclosao",
    "bd_embrio",
)

# Mantém o comportamento atual: ao abrir Matrizes, agrega também os schemas
# auxiliares usados pelas bases de classificação, aproveitamento, incubação,
# eclosão e embriodiagnóstico.
ESQUEMAS_POR_MODULO = {
    "comercial_html": ("comercial_html",),
    "comercial": ("comercial",),
    "dados": ("dados",),
    "ingestao": ("ingestao",),
    "pcp": ("pcp",),
    "zootecnico": ("zootecnico",),
    "matrizes": (
        "matrizes",
        "bd_classif",
        "bd_aproveit",
        "bd_incubacao",
        "bd_eclosao",
        "bd_embrio",
    ),
    # Compatibilidade com as URLs antigas que usam o schema como módulo.
    "bd_classif": ("bd_classif",),
    "bd_aproveit": ("bd_aproveit",),
    "bd_incubacao": ("bd_incubacao",),
    "bd_eclosao": ("bd_eclosao",),
    "bd_embrio": ("bd_embrio",),
}

# Tabelas técnicas/de apoio que já eram ocultadas do catálogo padrão.
# Continuam acessíveis diretamente em /dados/{tabela}.
TABELAS_AUXILIARES = {
    ("comercial_html", "cadastro_de_vendedores"),
    ("comercial_html", "clientes_cadastrados"),
    ("comercial_html", "faturamento_cfop"),
    ("comercial_html", "base_cadastro_comercial"),
    ("comercial_html", "metas"),
    ("comercial_html", "redes_compras"),
    ("comercial_html", "grupo_produto"),
    ("comercial_html", "fontes"), ("comercial_html", "cargas"), ("comercial_html", "colunas"), ("comercial_html", "arquivos_substituidos"),
    ("pcp", "cargas"), ("pcp", "colunas"), ("pcp", "metas"),
    ('matrizes', 'granja_cargas'), ('matrizes', 'inc_cargas'), ('matrizes', 'incubacao_cargas'), ('matrizes', 'eclosao_cargas'), ('matrizes', 'embrio_cargas'),
    ("matrizes", "lotes"),
    ("bd_classif", "granja_cargas"),
    ("bd_aproveit", "inc_cargas"),
    ("bd_incubacao", "incubacao_cargas"),
    ("bd_eclosao", "eclosao_cargas"),
    ("bd_embrio", "embrio_cargas"),
}

# Estrutura esperada informada para o projeto em 01/10/2026.
# Esta lista é usada somente para diagnóstico. Nada é criado/alterado no banco.
TABELAS_ESPERADAS = {
    "matrizes": {
        "acerto_produtor_producao",
        "acerto_produtor_recria",
        "lotes",
    },
    "bd_classif": {"granja", "granja_cargas"},
    "bd_aproveit": {"inc", "inc_cargas"},
    "bd_incubacao": {"incubacao", "incubacao_cargas"},
    "bd_eclosao": {"eclosao", "eclosao_cargas"},
    "bd_embrio": {"embrio", "embrio_cargas"},
}


from zootecnico_acesso import catalog_general


def criar_router_portal(banco):
    router = APIRouter(
        prefix="/api/portal",
        tags=["PostgreSQL — Portal de Dados"],
    )

    resumo_cache=ResumoCache()

    def descobrir_schemas(conn):
        return [r['table_schema'] for r in conn.execute("""
            SELECT DISTINCT table_schema FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
              AND table_schema !~ '^pg_'
              AND table_type IN ('BASE TABLE','VIEW')
            ORDER BY table_schema
        """).fetchall()]

    def schemas_do_modulo(modulo, conn):
        existentes=descobrir_schemas(conn)
        if modulo in ESQUEMAS_POR_MODULO:
            return tuple(s for s in ESQUEMAS_POR_MODULO[modulo] if s in existentes)
        if modulo in existentes:return (modulo,)
        raise HTTPException(404, 'Esquema não disponibilizado neste portal.')

    def catalogo_schema(conn, schema: str, incluir_auxiliares: bool = False):
        rows = conn.execute(
            """
            SELECT t.table_name, t.table_type, c.column_name, c.data_type
              FROM information_schema.tables t
              JOIN information_schema.columns c
                ON c.table_schema = t.table_schema
               AND c.table_name = t.table_name
             WHERE t.table_schema = %s
               AND t.table_type IN ('BASE TABLE','VIEW')
             ORDER BY t.table_name, c.ordinal_position
            """,
            (schema,),
        ).fetchall()

        result = {}
        for row in rows:
            if schema=="logistica_html" and row["table_name"] in ("fatos_atual","cargas","versao","registros","pallets_d1","financeiro_d1"):continue
            if not incluir_auxiliares and (schema, row["table_name"]) in TABELAS_AUXILIARES:
                continue
            result.setdefault(row["table_name"], []).append(row)
        return result

    def resumo_schema(conn, schema: str):
        result = []
        for tabela, columns in catalogo_schema(conn, schema).items():
            if schema=='logistica_html':
                carga=conn.execute("SELECT c.concluido_em ultima_carga,c.validacao FROM logistica_html.cargas c JOIN logistica_html.versao v ON v.carga_id=c.id").fetchone()
                fonte={'controle_frete_atual':'cargas','fretes_notas_atual':'fretes','devolucoes_atual':'devolucoes','ocorrencias_atual':'ocorrencias','pallets_atual':'pallets','titulos_frete_atual':'financeiro','pesagens_atual':'pesagem','diferenca_frete_atual':'diferenca_frete'}.get(tabela)
                n=carga['validacao'].get(fonte,{}).get('carregadas',0)if carga else 0
                result.append({'esquema':schema,'tabela':tabela,'tipo':'visao','registros':n,'ultima_carga':carga['ultima_carga']if carga else None})
                continue
            if schema=='comercial_html' and tabela.endswith('_atual'):
                fonte=tabela.removesuffix('_atual')
                # Group version keys before applying replacement rules; keep the exact view count.
                if tabela == 'faturamento_cfop_atual':
                    row=conn.execute("""WITH grupos AS MATERIALIZED (
 SELECT t._carga_id,t.arquivo_origem,t._data_referencia,t._unidade_contexto,count(*) n
 FROM comercial_html.faturamento_cfop t
 JOIN comercial_html.cargas c ON c.id=t._carga_id AND c.status='OK'
 JOIN comercial_html.fontes f ON f.fonte='faturamento_cfop' AND c.id>=f.carga_base
 GROUP BY t._carga_id,t.arquivo_origem,t._data_referencia,t._unidade_contexto
) SELECT coalesce(sum(g.n),0)::bigint registros FROM grupos g
WHERE NOT EXISTS(SELECT 1 FROM comercial_html.cargas n WHERE n.fonte='faturamento_cfop' AND n.status='OK' AND n.modo='PERIODO'AND n.id>g._carga_id AND g._data_referencia BETWEEN n.inicio AND n.fim AND g._unidade_contexto=n.contexto)
AND NOT EXISTS(SELECT 1 FROM comercial_html.arquivos_substituidos a WHERE a.fonte='faturamento_cfop'AND a.arquivo=g.arquivo_origem AND a.carga_id>g._carga_id)""").fetchone()
                else:
                    row=conn.execute(sql.SQL('SELECT count(*) AS registros FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(tabela))).fetchone()
                carga=conn.execute("SELECT max(concluido_em) AS ultima_carga FROM comercial_html.cargas WHERE fonte=%s AND status='OK'",(fonte,)).fetchone()
                result.append({'esquema':schema,'tabela':tabela,'tipo':'visao',**row,**carga})
                continue
            if schema=='suprimentos_html':
                carga=conn.execute("SELECT c.concluido_em AS ultima_carga,c.fontes FROM suprimentos_html.cargas c JOIN suprimentos_html.versao v ON v.id=c.id WHERE c.status='OK'").fetchone()
                fontes={f['fonte']:f['linhas'] for f in (carga or {}).get('fontes',[])}
                key=tabela.removesuffix('_atual')
                estimated=False
                if tabela.endswith('_atual') and key in fontes:
                    row={'registros':fontes[key]}
                elif tabela.startswith('dados_'):
                    # Physical tables include all revisions. Do not scan tens of millions of rows per refresh.
                    row=conn.execute("SELECT greatest(coalesce(s.n_live_tup,c.reltuples,0),0)::bigint registros FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid WHERE n.nspname=%s AND c.relname=%s",(schema,tabela)).fetchone()
                    estimated=True
                else:
                    row=conn.execute(sql.SQL('SELECT count(*) AS registros FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(tabela))).fetchone()
                result.append({'esquema':schema,'tabela':tabela,'tipo':'visao' if columns[0]['table_type']=='VIEW' else 'tabela',**row,'ultima_carga':(carga or {}).get('ultima_carga'),'contagem_estimada':estimated})
                continue
            if schema=='pcp':
                row=conn.execute(sql.SQL('SELECT count(*) AS registros FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(tabela))).fetchone()
                carga=conn.execute("SELECT max(atualizado_em) AS ultima_carga FROM pcp.cargas WHERE tabela=%s AND status='OK'",(tabela,)).fetchone()
                result.append({'esquema':schema,'tabela':tabela,**row,**carga})
                continue
            dated = {
                item["column_name"]
                for item in columns
                if item["data_type"]
                in (
                    "date",
                    "timestamp with time zone",
                    "timestamp without time zone",
                )
            }
            updated = next(
                (
                    name
                    for name in (
                        "atualizado_em",
                        "carregado_em",
                        "importado_em",
                        "updated_at",
                    )
                    if name in dated
                ),
                None,
            )
            ultima = (
                sql.SQL("max({})::timestamptz").format(sql.Identifier(updated))
                if updated
                else sql.SQL("NULL")
            )
            row = conn.execute(
                sql.SQL(
                    "SELECT count(*) AS registros, {} AS ultima_carga FROM {}.{}"
                ).format(
                    ultima,
                    sql.Identifier(schema),
                    sql.Identifier(tabela),
                )
            ).fetchone()
            result.append({"esquema": schema, "tabela": tabela, "tipo": "visao" if columns[0]["table_type"]=="VIEW" else "tabela", **row})
        return result

    def resolver_tabela(conn, modulo: str, tabela: str):
        """Descobre em qual schema autorizado a tabela está.

        Para ``matrizes`` procura no próprio schema e também nos cinco schemas
        auxiliares. Para as URLs antigas por schema, procura somente naquele
        schema, preservando o comportamento anterior.
        """
        encontrados = []
        for schema in schemas_do_modulo(modulo, conn):
            existe = conn.execute(
                """
                SELECT 1
                  FROM information_schema.tables
                 WHERE table_schema = %s
                   AND table_name = %s
                   AND table_type IN ('BASE TABLE','VIEW')
                """,
                (schema, tabela),
            ).fetchone()
            if existe:
                encontrados.append(schema)

        if not encontrados:
            raise HTTPException(404, "Tabela não encontrada no esquema informado.")

        if len(encontrados) > 1:
            raise HTTPException(
                409,
                "Nome de tabela ambíguo entre esquemas. Use a rota com o schema específico.",
            )

        return encontrados[0]

    def carregar_modulos():
        with banco() as conn:
            result = []
            existentes=descobrir_schemas(conn)
            if not catalog_general():
                existentes = [s for s in existentes if s != 'zootecnico']
            agrupados={s for grupo in ESQUEMAS_POR_MODULO.values() for s in grupo}
            nomes={**ESQUEMAS, **{s:s.replace('_',' ').title() for s in existentes if s not in agrupados}}
            for modulo, nome in nomes.items():
                if not catalog_general() and 'zootecnico' in ESQUEMAS_POR_MODULO.get(modulo, (modulo,)):
                    continue
                tables = []
                for schema in schemas_do_modulo(modulo, conn):
                    tables.extend(resumo_schema(conn, schema))

                cargas = [t["ultima_carga"] for t in tables if t["ultima_carga"]]
                result.append(
                    {
                        "id": modulo,
                        "nome": nome,
                        "tabelas": tables,
                        "registros": sum(t["registros"] for t in tables),
                        "ultima_carga": max(cargas) if cargas else None,
                    }
                )

        return {
            "modulos": result,
            "fonte": "PostgreSQL",
            "esquemas": existentes,
        }

    @router.get("/modulos")
    def modulos():
        return resumo_cache.get(('modulos', catalog_general()),carregar_modulos)

    @router.get("/catalogo-esperado")
    def catalogo_esperado():
        """Confere somente se as tabelas esperadas existem no PostgreSQL."""
        with banco() as conn:
            resultado = []
            for schema, tabelas in TABELAS_ESPERADAS.items():
                for tabela in sorted(tabelas):
                    presente = (
                        conn.execute(
                            "SELECT to_regclass(%s) AS tabela",
                            (f"{schema}.{tabela}",),
                        ).fetchone()["tabela"]
                        is not None
                    )
                    resultado.append(
                        {
                            "esquema": schema,
                            "tabela": tabela,
                            "presente": presente,
                        }
                    )
        return {"tabelas": resultado}

    def carregar_tabelas(modulo: str):
        with banco() as conn:
            result = []
            for schema in schemas_do_modulo(modulo, conn):
                result.extend(resumo_schema(conn, schema))
            return {"tabelas": result}

    @router.get("/{modulo}/tabelas")
    def tabelas(modulo: str):
        def load():
            return carregar_tabelas(modulo)
        return resumo_cache.get(('tabelas',modulo),load)

    @router.get("/{modulo}/dados/{tabela}")
    def dados(
        modulo: str,
        tabela: str,
        pagina: int = Query(1, ge=1, le=1_000_000),
        tamanho: int = Query(25, ge=1, le=500),
    ):

        with banco() as conn:
            schema = resolver_tabela(conn, modulo, tabela)
            columns = catalogo_schema(
                conn,
                schema,
                incluir_auxiliares=True,
            ).get(tabela)

            if columns is None:
                raise HTTPException(404, "Tabela não encontrada no esquema informado.")

            total = conn.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(
                    sql.Identifier(schema),
                    sql.Identifier(tabela),
                )
            ).fetchone()["n"]

            pages = (total + tamanho - 1) // tamanho
            pagina = min(pagina, max(1, pages))

            keys = conn.execute(
                """
                SELECT a.attname
                  FROM pg_index i
                  JOIN pg_class t ON t.oid = i.indrelid
                  JOIN pg_namespace n ON n.oid = t.relnamespace
                  JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, pos)
                    ON true
                  JOIN pg_attribute a
                    ON a.attrelid = t.oid
                   AND a.attnum = k.attnum
                 WHERE n.nspname = %s
                   AND t.relname = %s
                   AND i.indisprimary
                 ORDER BY k.pos
                """,
                (schema, tabela),
            ).fetchall()

            order = (
                sql.SQL(",").join(sql.Identifier(k["attname"]) for k in keys)
                if keys
                else sql.SQL("to_jsonb(q)::text")
            )

            rows = conn.execute(
                sql.SQL(
                    "SELECT * FROM {}.{} AS q ORDER BY {} LIMIT %s OFFSET %s"
                ).format(
                    sql.Identifier(schema),
                    sql.Identifier(tabela),
                    order,
                ),
                (tamanho, (pagina - 1) * tamanho),
            ).fetchall()

        return {
            "esquema": schema,
            "tabela": tabela,
            "colunas": [item["column_name"] for item in columns],
            "dados": rows,
            "total": total,
            "pagina": pagina,
            "tamanho": tamanho,
            "total_paginas": pages,
        }

    @router.on_event("startup")
    async def preparar_resumo():
        def warm():
            try:
                resumo_cache.get(('modulos', catalog_general()),carregar_modulos)
            except Exception:
                pass  # O próximo acesso tentará novamente; não bloqueia a inicialização.
        Thread(target=warm,daemon=True,name='portal-resumo-inicial').start()

    return router
