"""Gera SQL/patches locais para revisão. NÃO se conecta a bancos ou endpoints."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType

from psycopg import sql
from psycopg.adapt import Transformer
from psycopg._queries import PostgresQuery
from zootecnico_reference import Reference,DEFAULT_ARCHIVE,ROUTE_CASES,route_query,expected_columns,secondary_lookup_query

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'integrations/zootecnico/diagnostico'
WARNING='-- MANUAL, BANCO INTERNO. Não executado pelo Codex. Sem escrita/ETL.\n'


def quote(value):return sql.Literal(value).as_string()


def block(label,query,timeout='5s'):
    return ('\n-- '+label+'\nBEGIN READ ONLY;\nSET LOCAL statement_timeout='+quote(timeout)+';\n'
            "SET LOCAL lock_timeout='1s';\n"+query.rstrip(';')+';\nROLLBACK;\n')


def metadata(contract,sources):
    values=',\n'.join('  ('+','.join((quote(s),quote(c),quote(k),'TRUE' if required else 'FALSE'))+')'
                       for (s,c),(k,required) in sorted(contract.items()))
    wanted=','.join(quote(s) for s in sorted(sources))
    query=f"""SELECT current_database() AS banco, current_setting('transaction_read_only') AS somente_leitura;
-- Primeiro conferir os objetos; views não são consultadas nesta seção.
SELECT c.relname AS fonte,c.relkind,c.reltuples::bigint AS linhas_estimadas_estatistica
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='zootecnico' AND c.relname IN ({wanted}) ORDER BY c.relname;
WITH esperado(fonte,coluna,expectativa,obrigatoria) AS (VALUES
{values}
)
SELECT e.*,c.data_type,c.udt_name,c.is_nullable,
       CASE WHEN c.column_name IS NULL THEN CASE WHEN e.obrigatoria THEN 'FALTA_COLUNA' ELSE 'OPCIONAL_AUSENTE' END
            WHEN e.expectativa='numeric' AND c.udt_name NOT IN ('int2','int4','int8','numeric','float4','float8') THEN 'REVER_TIPO_NUMERICO'
            ELSE 'PRESENTE_TIPO_A_CONFERIR' END AS diagnostico
FROM esperado e LEFT JOIN information_schema.columns c
 ON c.table_schema='zootecnico' AND c.table_name=e.fonte AND c.column_name=e.coluna
ORDER BY e.fonte,e.coluna;
-- Constraints/índices reais. Ausência de FK não prova ausência de relação lógica.
SELECT c.relname AS fonte,k.conname,k.contype,pg_get_constraintdef(k.oid) AS definicao
FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='zootecnico' AND c.relname IN ({wanted}) ORDER BY c.relname,k.conname;
SELECT tablename,indexname,indexdef FROM pg_catalog.pg_indexes
WHERE schemaname='zootecnico' AND tablename IN ({wanted}) ORDER BY tablename,indexname;
SELECT c.relname AS fonte,pg_get_viewdef(c.oid,TRUE) AS definicao
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='zootecnico' AND c.relkind IN ('v','m') AND c.relname IN ({wanted}) ORDER BY c.relname;
-- Campo auxiliar de metas: inventário somente, sem ler registros.
SELECT table_name,column_name,data_type FROM information_schema.columns
WHERE table_schema='zootecnico' AND table_name='metas' ORDER BY ordinal_position"""
    return WARNING+'-- Executar antes das demais seções; parar se faltar fonte/coluna.\n'+block('01 METADADOS',query)


def samples(reference,acl):
    helper=reference.load('sql_utils')
    old={key:sys.modules.get(key) for key in ('bi_generic','bi_generic.sql_utils')}
    package=ModuleType('bi_generic');package.__path__=[]
    sys.modules.update({'bi_generic':package,'bi_generic.sql_utils':helper})
    parts=[WARNING,'-- Uma fonte por bloco. LIMIT 500 é amostra, não contagem total.\n'
           '-- EXPLAIN não executa o plano; só executar o bloco de amostra após revisar a estimativa.\n'
           '-- Views podem custar caro antes do LIMIT; timeout não substitui revisão do plano.\n']
    try:
        for source in sorted(acl.SOURCES):
            table=sql.Identifier('zootecnico',source).as_string()
            keys=acl._lot_keys(source,'s')
            normalized=', '.join(value.as_string()+' AS k'+str(i) for i,value in enumerate(keys))
            columns=', '.join('k'+str(i) for i in range(len(keys)))
            complete=' AND '.join('k'+str(i)+' IS NOT NULL' for i in range(len(keys)))
            query=f"""WITH amostra AS MATERIALIZED (SELECT * FROM {table} LIMIT 500),
normalizada AS (SELECT {normalized}, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT {columns},COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE {complete} GROUP BY {columns})
SELECT {quote(source)} AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT ({complete})) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos"""
            parts.append(block(source+' — primeiro estimar','EXPLAIN (FORMAT JSON, COSTS TRUE) '+query))
            parts.append(block(source+' — executar somente depois de revisar a estimativa',query))
    finally:
        for key,value in old.items():
            if value is None:sys.modules.pop(key,None)
            else:sys.modules[key]=value
    return ''.join(parts)


def literal_parameters(captured):
    query=PostgresQuery(Transformer());query.convert(captured.scoped,captured.params)
    raw=query.query.decode('utf-8')
    params=captured.params or []
    # Builders usam parâmetros posicionais; estes valores são APENAS os casos fixos
    # de diagnóstico abaixo, nunca entrada externa nem dados de usuários reais.
    return re.sub(r'\$(\d+)\b',lambda match:quote(params[int(match[1])-1]),raw)


def plans(reference,acl):
    access=acl.Access(1,'proprio',tuple((source,'__DIAGNOSTICO_FICTICIO__','diagnostico') for source in acl.SOURCES))
    parts=[WARNING,'-- Builders reais, credencial/técnico FICTÍCIO: não é concessão nem teste de resultado.\n'
           '-- EXPLAIN sem ANALYZE apenas planeja; não aprova isolamento/cardinalidade/desempenho real.\n'
           '-- Campos e tipos devem estar conferidos pelo arquivo 01 antes.\n']
    for bi,action,params in ROUTE_CASES:
        captured=route_query(reference,acl,bi,action,params,access)
        parts.append(block(bi+'/'+action+' '+json.dumps(params,ensure_ascii=False),
                           'EXPLAIN (FORMAT JSON, COSTS TRUE) '+literal_parameters(captured)))
    captured=secondary_lookup_query(reference,acl,access)
    parts.append(block('LOOKUP AUXILIAR base dinâmica — uma chave de entrada FICTÍCIA',
                       'EXPLAIN (FORMAT JSON, COSTS TRUE) '+literal_parameters(captured)))
    return ''.join(parts)


def aliases(reference,acl):
    parts=[WARNING,"-- Preencher o CTE aliases com o cadastro REAL conferido no Neon.\n"
           "-- Vazio por padrão: resultados de correspondência serão NULL, não falha de todos.\n"
           "-- Não juntar bancos por FDW/dblink. Não copiar e-mails, senhas ou tokens.\n"]
    old={key:sys.modules.get(key) for key in ('bi_generic','bi_generic.sql_utils')}
    package=ModuleType('bi_generic');package.__path__=[]
    sys.modules.update({'bi_generic':package,'bi_generic.sql_utils':reference.load('sql_utils')})
    for source in sorted(acl.SOURCES):
        table=sql.Identifier('zootecnico',source).as_string()
        expressions=acl._lot_keys(source,'s')
        keys=', '.join('k'+str(i) for i in range(len(expressions)))
        normalized=', '.join(value.as_string()+' AS k'+str(i) for i,value in enumerate(expressions))
        complete=' AND '.join('k'+str(i)+' IS NOT NULL' for i in range(len(expressions)))
        query=f"""WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT {normalized}, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM {table} s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte={quote(source)} GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT {keys},COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE {complete} GROUP BY {keys})
SELECT {quote(source)} AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a"""
        parts.append(block(source+' — estimar antes (preencher aliases nas duas cópias)','EXPLAIN (FORMAT JSON, COSTS TRUE) '+query))
        parts.append(block(source+' — correspondências (executar somente após estimativa)',query))
    for key,value in old.items():
        if value is None:sys.modules.pop(key,None)
        else:sys.modules[key]=value
    return ''.join(parts)


def prepare(reference,acl):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    contract=expected_columns(reference)
    files={'01_metadados.sql':metadata(contract,acl.SOURCES),
           '02_amostras_chaves.sql':samples(reference,acl),
           '03_explain_ctes.sql':plans(reference,acl),
           '04_conferir_aliases.sql':aliases(reference,acl)}
    for name,content in files.items():(OUTPUT/name).write_text(content,encoding='utf-8')
    changes=[];patches=[]
    for name in ('servico_zootecnico.py','portal_router.py','Dockerfile.zootecnico'):
        before=reference.source(name).replace('\r\n','\n')
        after=(ROOT/'integrations/zootecnico/api'/name).read_text(encoding='utf-8')
        patches.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                       fromfile='a/API/api_zootecnico/'+name,tofile='b/API/api_zootecnico/'+name))
        changes.append(dict(file=name,reference_sha256=hashlib.sha256(before.encode()).hexdigest(),
                            prepared_sha256=hashlib.sha256(after.encode()).hexdigest()))
    name='zootecnico_acesso.py';after=(ROOT/'integrations/zootecnico/api'/name).read_text(encoding='utf-8')
    patches.extend(difflib.unified_diff([],after.splitlines(True),fromfile='/dev/null',tofile='b/API/api_zootecnico/'+name))
    (OUTPUT/'api_contra_zip3.patch').write_text(''.join(patches),encoding='utf-8')
    manifest=dict(reference=str(reference.archive),reference_is_official=False,
                  reference_archive_sha256=hashlib.sha256(reference.archive.read_bytes()).hexdigest(),
                  file_hashes_normalized_lf=True,
                  sql_executed=False,production_accessed=False,expected_columns=len(contract),
                  route_cases=len(ROUTE_CASES),auxiliary_plan_cases=1,files=changes)
    (OUTPUT/'referencias.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    worker_source=Path.home()/'.codex/attachments/00fda2bc-11f0-475a-a2b6-4f8eb757546b/Pasted text.txt'
    if worker_source.is_file():
        original=worker_source.read_text(encoding='utf-8-sig')
        prepared=(ROOT/'integrations/zootecnico/worker/worker.js').read_text(encoding='utf-8')
        patch=''.join(difflib.unified_diff(original.splitlines(True),prepared.splitlines(True),fromfile='a/worker_historico_20261008.js',tofile='b/worker.js'))
        (ROOT/'integrations/zootecnico/worker/contra_fonte_historica.patch').write_text(patch,encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--api-zip',type=Path,default=DEFAULT_ARCHIVE)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('validation_acl',ROOT/'integrations/zootecnico/api/zootecnico_acesso.py')
    acl=importlib.util.module_from_spec(spec);sys.modules[spec.name]=acl;spec.loader.exec_module(acl)
    with Reference(args.api_zip) as reference:result=prepare(reference,acl)
    print(json.dumps({key:result[key] for key in ('expected_columns','route_cases','sql_executed','production_accessed')}))


if __name__=='__main__':main()
