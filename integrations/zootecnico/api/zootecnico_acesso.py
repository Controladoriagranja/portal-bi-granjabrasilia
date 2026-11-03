"""Autorização da Integração. Sem conexão, chamadas HTTP ou caches ao importar.

Instalar junto de servico_zootecnico.py. A autenticação Basic da infraestrutura
continua sendo validada pelo middleware original; ela NÃO substitui a sessão.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from collections import defaultdict
import hashlib
import json
import re
import unicodedata
from urllib.error import HTTPError
from urllib.request import Request as HttpRequest, build_opener, ProxyHandler

from fastapi import HTTPException
from psycopg import sql
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

CENTRAL = "https://portal-bi-granjabrasilia.onrender.com/api/auth/zootecnico-access"
OPENER = build_opener(ProxyHandler({}))
CURRENT = ContextVar("zootecnico_scope", default=None)
SOURCES = frozenset({"vw_desempenho_acerto_portal", "acerto_lote_resultado_geral",
    "base_dinamica", "mortalidade_peso_abertos", "mortalidade_peso_fechados",
    "vw_historico_lotes_criacao_portal"})
PROTECTED_BIS = frozenset({"zootecnico", "gpd-fases", "lotes-abertos", "historico-abertos", "historico-fechados"})
REFERENCE_TABLES = frozenset({"metas"})  # Configuração comum, não registros de lotes.


@dataclass(frozen=True)
class Access:
    user_id: int
    mode: str
    aliases: tuple = ()  # (fonte, valor EXATO, identificador canônico)


def resolve_access(request):
    token = request.headers.get("x-portal-authorization", "")
    if not token.startswith("Bearer ") or len(token) > 4096:
        raise HTTPException(401, "Sessão do portal obrigatória.")
    try:
        with OPENER.open(HttpRequest(CENTRAL, headers={
            "Authorization": token, "Accept": "application/json", "Cache-Control": "no-store"
        }), timeout=15) as result:
            data = json.load(result)
    except HTTPError as error:
        status = error.code if error.code in {401, 403} else 503
        error.close()
        raise HTTPException(status,
                            "Não foi possível autorizar a Integração.") from None
    except Exception:
        raise HTTPException(503, "Serviço de autorização indisponível.") from None
    return validate_access(data)


def validate_access(data):
    if (not isinstance(data, dict) or data.get("ok") is not True or data.get("allowed") is not True
            or data.get("resource") != "zootecnico" or data.get("reportId") != 13
            or type(data.get("userId")) is not int or data["userId"] < 1):
        raise HTTPException(403, "Integração não autorizada.")
    mode = data.get("mode")
    if not isinstance(mode, str) or mode not in {"proprio", "equipe", "todos"}:
        raise HTTPException(403, "Usuário sem acesso aos dados da Integração.")
    ids = data.get("technicianIds")
    if (not isinstance(ids, list) or len(ids) > 100
            or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", x) for x in ids)
            or len(set(ids)) != len(ids)
            or (mode == "proprio" and len(ids) != 1) or (mode == "equipe" and not ids)
            or (mode == "todos" and ids)):
        raise HTTPException(403, "Vínculo técnico inválido.")
    aliases, seen = [], set()
    raw = data.get("aliases", [])
    if not isinstance(raw, list) or len(raw) > 10000:
        raise HTTPException(403, "Mapeamento técnico inválido.")
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(403, "Mapeamento técnico inválido.")
        source, value, identifier = (item.get(key) for key in ("fonte", "valor", "entidade_id"))
        if (not isinstance(source, str) or source not in SOURCES or not isinstance(value, str) or not value or value != value.strip()
                or len(value) > 500 or identifier not in ids or (source, value) in seen):
            raise HTTPException(403, "Mapeamento técnico inválido ou ambíguo.")
        seen.add((source, value)); aliases.append((source, value, identifier))
    return Access(data["userId"], mode, tuple(aliases))


def route_policy(path):
    parts = path.strip("/").split("/")
    if parts == ['api','zootecnico','acesso','opcoes']:
        return 'admin-options'
    if len(parts) >= 3 and parts[:2] == ["api", "bi"]:
        if parts[2] in PROTECTED_BIS:
            return "scoped"
        if parts[2] in {"rxp", "formulas"}:
            # Fora da nova filtragem: mantidos integrais SOMENTE para acesso geral.
            # O lookup compartilhado da base dinâmica não vira uma porta lateral.
            return "general"
    if parts[:2] == ["api", "zootecnico"]:
        return "scoped" if len(parts) == 4 and parts[2] == "dados" and parts[3] in SOURCES else "general"
    if parts[:2] == ["api", "portal"]:
        if len(parts) == 3 and parts[2] == 'modulos':
            return 'catalog'
        if len(parts) < 3 or parts[2] in {"zootecnico", "integracao"}:
            # Resumos compartilhados usam cache global e não são endpoints das telas.
            return "general"
    if parts[:2] == ["api", "exportacoes"] and (len(parts) < 3 or parts[2] in {"zootecnico", "modulos", "status"}):
        return "general"
    return "other"


async def dispatch(request, call_next):
    policy = route_policy(request.url.path)
    try:
        access = Access(0, 'none')
        if policy == 'admin-options':
            # Mesma validação de admin usada pelo catálogo de vendedores Comercial.
            from comercial_acesso import identity
            user = await run_in_threadpool(identity, request)
            if user.get('isAdmin') is not True:
                raise HTTPException(403, 'Somente administradores podem identificar técnicos.')
            access = Access(int(user['id']), 'todos')
        elif policy == 'catalog':
            # Preservar os outros módulos, inclusive o uso administrativo Basic.
            # Sem autorização geral, o catálogo omite somente o Zootécnico.
            if request.headers.get('x-portal-authorization'):
                try:
                    access = await run_in_threadpool(resolve_access, request)
                except HTTPException:
                    pass
        elif policy != 'other':
            access = await run_in_threadpool(resolve_access, request)
        if policy == "general" and access.mode != "todos":
            raise HTTPException(403, "Esta consulta exige acesso geral à Integração.")
        marker = CURRENT.set(access)
        try:
            response = await call_next(request)
        finally:
            CURRENT.reset(marker)
    except HTTPException as error:
        response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = ", ".join(filter(None, [response.headers.get("Vary"), "Authorization", "X-Portal-Authorization"]))
    return response


def _mask_literals(query):
    """Mantém offsets/identificadores; oculta literais e comentários do SQL gerado."""
    pattern = r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/|\$([A-Za-z_][A-Za-z0-9_]*|)\$[\s\S]*?\$\1\$"
    return re.sub(pattern, lambda match: " " * len(match[0]), query)


RELATION = re.compile(r'(?<![\w"])"?zootecnico"?\s*\.\s*(?:"([A-Za-z_][A-Za-z0-9_]*)"|([A-Za-z_][A-Za-z0-9_]*))', re.I)


def _identity(source, alias, mappings):
    """Alias só vem da CENTRAL. Literal faz escape; nenhum SQL vem do navegador."""
    cases = [sql.SQL("WHEN {} THEN {}").format(sql.Literal(value), sql.Literal(identifier))
             for src, value, identifier in mappings if src == source]
    if not cases:
        return sql.SQL("NULL::text")
    raw = sql.SQL("NULLIF(BTRIM(to_jsonb({})->>'tecnico'),'')").format(sql.Identifier(alias))
    return sql.SQL("(CASE {} {} ELSE NULL::text END)").format(raw, sql.SQL(" ").join(cases))


def _lot_keys(source, alias):
    # Não adivinha vínculo pelo galpão atual. Usa a chave histórica completa.
    from bi_generic.sql_utils import date_texto
    if source == "base_dinamica":
        keys, day = ("cod_prod", "galpao", "lote"), "data_de_alojamento"
    elif source in {"mortalidade_peso_abertos", "mortalidade_peso_fechados", "vw_historico_lotes_criacao_portal"}:
        keys = ("codigo_granja", "galp", "num_lote")
        day = "recepcao_dia_cache" if source.startswith("vw_") else "data_recepcao"
    else:
        # Também negar conflitos na view, sem presumir que um JOIN seja 1:1.
        return [sql.SQL("NULLIF(BTRIM({}.chave_lote::text),'')").format(sql.Identifier(alias))]
    result = [sql.SQL("NULLIF(BTRIM({}.{}::text),'')").format(sql.Identifier(alias), sql.Identifier(k)) for k in keys]
    # Mesma conversão tolerante a datas do BI; chave calculada uma vez por linha.
    result.append(sql.SQL("(SELECT {} FROM (SELECT {}.{} AS za_day) za_date)").format(
        date_texto("za_day"), sql.Identifier(alias), sql.Identifier(day)))
    return result


def _source_cte(source, access):
    table = sql.Identifier("zootecnico", source)
    if not any(src == source for src, _, _ in access.aliases):
        return sql.SQL('{} AS (SELECT s.* FROM {} s WHERE FALSE)').format(
            sql.Identifier('za_scope_' + source), table)
    owner = _identity(source, "s", access.aliases)
    guards = [sql.SQL("{} IS NOT NULL").format(owner)]
    if source == "vw_desempenho_acerto_portal":
        # A view do portal não possui candidatos_tecnico. JSON ->> retorna NULL
        # para a chave ausente; o COALESCE mantém a coluna realmente opcional.
        guards.append(sql.SQL("COALESCE(to_jsonb(s)->>'candidatos_tecnico','1') !~ '^(?:[2-9]|[1-9][0-9]+)$'"))
        display_cases = [sql.SQL("WHEN {} THEN {}").format(sql.Literal(value), sql.Literal(identifier))
                         for src, value, identifier in access.aliases if src == source]
        display = sql.SQL("(CASE BTRIM(to_jsonb(s)->>'tecnico_exibicao') {} ELSE NULL::text END)").format(sql.SQL(" ").join(display_cases)) if display_cases else sql.SQL("NULL::text")
        guards.append(sql.SQL("(NULLIF(BTRIM(to_jsonb(s)->>'tecnico_exibicao'),'') IS NULL OR {} = {})").format(owner, display))
    # Pré-agrupar as chaves conflitantes evita uma varredura por cada lote.
    # Não filtrar os snapshots antes desta conferência global da fonte.
    keys = [sql.Identifier('k' + str(i)) for i in range(len(_lot_keys(source, 'p')))]
    versions, conflicts = sql.Identifier('za_versions_' + source), sql.Identifier('za_conflicts_' + source)
    mapped = sql.SQL(', ').join(sql.SQL('{} AS {}').format(value,key)
                                for value,key in zip(_lot_keys(source,'p'),keys))
    version_cte = sql.SQL('{} AS MATERIALIZED (SELECT {}, {} AS za_owner FROM {} p)').format(
        versions, mapped, _identity(source,'p',access.aliases),table)
    conflict_cte = sql.SQL('{} AS (SELECT {} FROM {} GROUP BY {} '
                           'HAVING BOOL_OR(za_owner IS NULL) OR COUNT(DISTINCT za_owner)>1)').format(
        conflicts,sql.SQL(', ').join(keys),versions,sql.SQL(', ').join(keys))
    same_lot = sql.SQL(' AND ').join(sql.SQL('{} = p.{}').format(value,key)
                                    for value,key in zip(_lot_keys(source,'s'),keys))
    guards.append(sql.SQL('NOT EXISTS (SELECT 1 FROM {} p WHERE {})').format(conflicts,same_lot))
    scope_cte = sql.SQL("{} AS (SELECT s.* FROM {} s WHERE {})").format(
        sql.Identifier("za_scope_" + source), table, sql.SQL(" AND ").join(guards))
    return sql.SQL(', ').join([version_cte,conflict_cte,scope_cte])


def scope_query(query, access, connection=None, bound_params=False):
    raw = query if isinstance(query, str) else query.as_string(connection)
    masked = _mask_literals(raw)
    matches = list(RELATION.finditer(masked))
    if not matches:
        return query
    if access is None:
        # Inicialização administrativa original, fora de uma requisição HTTP.
        return query
    if access.mode == "none":
        raise HTTPException(403, "Fonte zootécnica exige autorização individual.")
    if access.mode == "todos":
        return query
    names = {m[1] or m[2] for m in matches}
    if names - SOURCES - REFERENCE_TABLES:
        raise HTTPException(403, "Fonte sem mapeamento de autorização.")
    if not re.match(r"\s*(SELECT\b|WITH\b)", masked, re.I):
        raise HTTPException(403, "Operação não autorizada.")
    scoped = sorted(names & SOURCES)
    if not scoped:
        return query
    for match in reversed(matches):
        name = match[1] or match[2]
        if name in SOURCES:
            raw = raw[:match.start()] + '"za_scope_' + name + '"' + raw[match.end():]
    ctes = sql.SQL(", ").join(_source_cte(name, access) for name in scoped).as_string(connection)
    if bound_params:
        ctes = ctes.replace('%', '%%')  # Não interpretar um % de um alias como placeholder.
    start = re.match(r"\s*WITH\s+(RECURSIVE\s+)?", raw, re.I)
    if start:
        return raw[:start.end()] + ctes + ", " + raw[start.end():]
    return "WITH " + ctes + " " + raw


class ScopedConnection:
    def __init__(self, connection, access):
        self.connection, self.access = connection, access

    def execute(self, query, params=None, **kwargs):
        return self.connection.execute(scope_query(query, self.access, self.connection, params is not None), params, **kwargs)

    def cursor(self, *args, **kwargs):
        # Evitar um caminho de execução que ignore o escopo obrigatório.
        raise HTTPException(403, "Use a conexão de consulta autorizada.")

    def __getattr__(self, name):
        return getattr(self.connection, name)


def scoped_connection(connection):
    access = CURRENT.get()
    return ScopedConnection(connection, access) if access is not None else connection


def catalog_general():
    access = CURRENT.get()
    return access is None or access.mode == 'todos'


def name_key(value):
    # Nome completo: só caixa/espaçamento. Sem iniciais, prefixos ou aproximação.
    return ' '.join(unicodedata.normalize('NFC',str(value or '')).split()).casefold()


def full_name(value):
    return len(str(value).split()) >= 2 and ' - ' not in str(value) and '.' not in str(value)


def build_technician_catalog(rows):
    """Agrupa valores exatos apenas com identidade completa ou chave inequívoca.

    Nunca exporta as chaves de lote. Um valor abreviado só recebe grupo automático
    se as provas observadas levarem a UM nome completo, sem conflito global.
    """
    labels={source:set() for source in SOURCES}
    graph=defaultdict(set);by_key=defaultdict(lambda:defaultdict(set))
    def node(source,value):
        value=str(value or '').strip()
        if not value or len(value)>500:return None
        result=(source,value);labels[source].add(value);graph[result]
        return result
    def edge(a,b):
        if a and b:graph[a].add(b);graph[b].add(a)
    for row in rows:
        source=row['fonte'];primary=node(source,row.get('tecnico'))
        display=node(source,row.get('exibicao')) if source=='vw_desempenho_acerto_portal' else None
        if row.get('ambiguo'):continue
        # Mesma linha oficial: não une dois nomes completos diferentes.
        if primary and display and (name_key(primary[1])==name_key(display[1]) or not(full_name(primary[1]) and full_name(display[1]))):
            edge(primary,display)
        for kind,key in (('lote',row.get('chaves')),('acerto',row.get('chave_lote'))):
            if key and (not isinstance(key,list) or all(v is not None and str(v).strip() for v in key)) and primary:
                by_key[(kind,json.dumps(key,ensure_ascii=False,sort_keys=True))][source].add(primary)
    exact=defaultdict(list)
    for entry in graph:
        if full_name(entry[1]):exact[name_key(entry[1])].append(entry)
    for entries in exact.values():
        for entry in entries[1:]:edge(entries[0],entry)
    for sources in by_key.values():
        # Nenhuma prova a partir de snapshots conflitantes na mesma fonte/chave.
        if any(len(values)!=1 for values in sources.values()):continue
        # Resultado real: a base dinâmica diverge do técnico histórico do lote.
        # Seus nomes completos entram por igualdade exata, nunca como prova de
        # equivalência de siglas com o responsável histórico de outra fonte.
        entries=[next(iter(values)) for source,values in sources.items() if source!='base_dinamica']
        for i,a in enumerate(entries):
            for b in entries[i+1:]:
                if name_key(a[1])==name_key(b[1]) or not(full_name(a[1]) and full_name(b[1])):edge(a,b)
    return finish_catalog(graph,labels)


def finish_catalog(graph,labels):
    exact=defaultdict(list)
    for entry in graph:
        if full_name(entry[1]):exact[name_key(entry[1])].append(entry)
    for entries in exact.values():
        for entry in entries[1:]:graph[entries[0]].add(entry);graph[entry].add(entries[0])
    seen=set();groups=[];pending=[]
    for start in graph:
        if start in seen:continue
        stack=[start];component=set()
        while stack:
            entry=stack.pop()
            if entry in component:continue
            component.add(entry);stack.extend(graph[entry]-component)
        seen.update(component)
        names={name_key(value) for source,value in component if full_name(value)}
        if len(names)!=1:
            # Uma sigla conflitante não invalida a igualdade exata dos nomes
            # completos. Preservar essas identidades; só a sigla fica pendente.
            pending.extend({'fonte':source,'valor':value,'candidates':sorted(names)}
                           for source,value in sorted(component) if not full_name(value))
        for key in sorted(names):
            selected=component if len(names)==1 else {(s,v) for s,v in component if full_name(v) and name_key(v)==key}
            grouped=defaultdict(list)
            for source,value in sorted(selected):grouped[source].append(value)
            canonical=sorted({v for s,v in selected if full_name(v)})[0]
            groups.append({'identifier':'tec_'+hashlib.sha256(key.encode('utf-8')).hexdigest()[:24],
                           'name':canonical,'nameKey':key,'labels':dict(grouped)})
    return {'ok':True,'sources':{source:sorted(values) for source,values in labels.items()},
            'groups':sorted(groups,key=lambda g:g['nameKey']),'pending':pending}


def catalog_from_evidence(values,evidences):
    """Mesmo critério do endpoint, aplicado ao levantamento completo retornado.

    Contagens/pares reais não são aprovação por maioria. Qualquer identidade
    conflitante nas fontes históricas impede a união automática do componente.
    """
    labels={source:set() for source in SOURCES};graph=defaultdict(set)
    for row in values:
        source,value=row['fonte'],row['valor']
        if source not in SOURCES or not isinstance(value,str) or not value or value!=value.strip():
            raise ValueError('Valor fora das seis fontes confirmadas.')
        labels[source].add(value);graph[source,value]
    for proof in evidences:
        a=(proof['fonte_a'],proof['valor_a']);b=(proof['fonte_b'],proof['valor_b'])
        if a not in graph or b not in graph:raise ValueError('Evidência sem valor de origem.')
        if proof['origem'] not in {'produtor_galpao_lote_alojamento','chave_lote','mesma_linha_tecnico_exibicao'}:
            raise ValueError('Origem de evidência desconhecida.')
        if 'base_dinamica' in {a[0],b[0]}:continue
        if name_key(a[1])==name_key(b[1]) or not(full_name(a[1]) and full_name(b[1])):
            graph[a].add(b);graph[b].add(a)
    return finish_catalog(graph,labels)


def create_access_router(banco):
    from fastapi import APIRouter
    router=APIRouter(prefix='/api/zootecnico/acesso',tags=['Acesso Integração'])
    @router.get('/opcoes')
    def options():
        # dispatch já exigiu Basic + admin verificado na CENTRAL.
        if CURRENT.get() is None or CURRENT.get().mode!='todos':raise HTTPException(403,'Admin obrigatório.')
        from bi_generic.sql_utils import texto,date_texto
        branches=[]
        for source in sorted(SOURCES):
            if source=='vw_desempenho_acerto_portal':
                keys=[texto(c) for c in ('codigo','gal','lote')]+[date_texto('dt_aloj')]
                key=sql.SQL('jsonb_build_array({})').format(sql.SQL(', ').join(keys))
            elif source=='acerto_lote_resultado_geral':key=sql.SQL('NULL::jsonb')
            else:
                fields=('cod_prod','galpao','lote','data_de_alojamento') if source=='base_dinamica' else ('codigo_granja','galp','num_lote','recepcao_dia_cache' if source.startswith('vw_') else 'data_recepcao')
                key=sql.SQL('jsonb_build_array({})').format(sql.SQL(', ').join([*[texto(c) for c in fields[:3]],date_texto(fields[3])]))
            branches.append(sql.SQL('SELECT {source} AS fonte, tecnico, {display} AS exibicao, '
                '{key} AS chaves, {lot} AS chave_lote, {ambiguous} AS ambiguo '
                'FROM {table} s LIMIT 50001').format(source=sql.Literal(source),key=key,
                display=sql.SQL("to_jsonb(s)->>'tecnico_exibicao'") if source.startswith('vw_desempenho') else sql.SQL('NULL::text'),
                lot=sql.Identifier('chave_lote') if source in {'vw_desempenho_acerto_portal','acerto_lote_resultado_geral'} else sql.SQL('NULL::text'),
                ambiguous=sql.SQL("COALESCE(to_jsonb(s)->>'candidatos_tecnico','1') ~ '^(?:[2-9]|[1-9][0-9]+)$'") if source.startswith('vw_desempenho') else sql.SQL('FALSE'),
                table=sql.Identifier('zootecnico',source)))
        with banco() as conn:
            rows=conn.execute(sql.SQL(' UNION ALL ').join(sql.SQL('({})').format(q) for q in branches)).fetchall()
        counts=defaultdict(int)
        for row in rows:counts[row['fonte']]+=1
        if any(value>50000 for value in counts.values()):
            # Amostra incompleta não prova identidade. Ainda oferecer os valores
            # reais no mesmo formulário, sem usar chaves truncadas como prova.
            with banco() as conn:
                rows=conn.execute(sql.SQL(' UNION ALL ').join(sql.SQL(
                    '(SELECT DISTINCT {} AS fonte, BTRIM(tecnico) AS tecnico FROM {} '
                    "WHERE NULLIF(BTRIM(tecnico),'') IS NOT NULL LIMIT 5001)").format(
                        sql.Literal(source),sql.Identifier('zootecnico',source)) for source in sorted(SOURCES))).fetchall()
                # O nome de exibição também é um alias real da view.
                rows+=conn.execute(sql.SQL("SELECT DISTINCT 'vw_desempenho_acerto_portal' AS fonte, "
                    "BTRIM(tecnico_exibicao) AS tecnico FROM zootecnico.vw_desempenho_acerto_portal "
                    "WHERE NULLIF(BTRIM(tecnico_exibicao),'') IS NOT NULL LIMIT 5001")).fetchall()
            counts=defaultdict(int)
            for row in rows:counts[row['fonte']]+=1
            if any(value>5000 for value in counts.values()):raise HTTPException(503,'Valores técnicos excedem o limite seguro; cadastro não validado.')
        return build_technician_catalog(rows)
    return router
