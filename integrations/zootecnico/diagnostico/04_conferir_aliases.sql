-- MANUAL, BANCO INTERNO. Não executado pelo Codex. Sem escrita/ETL.
-- Preencher o CTE aliases com o cadastro REAL conferido no Neon.
-- Vazio por padrão: resultados de correspondência serão NULL, não falha de todos.
-- Não juntar bancos por FDW/dblink. Não copiar e-mails, senhas ou tokens.

-- acerto_lote_resultado_geral — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."acerto_lote_resultado_geral" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='acerto_lote_resultado_geral' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'acerto_lote_resultado_geral' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- acerto_lote_resultado_geral — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."acerto_lote_resultado_geral" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='acerto_lote_resultado_geral' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'acerto_lote_resultado_geral' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- base_dinamica — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."cod_prod"::text),'') AS k0, NULLIF(BTRIM("s"."galpao"::text),'') AS k1, NULLIF(BTRIM("s"."lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_de_alojamento" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."base_dinamica" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='base_dinamica' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'base_dinamica' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- base_dinamica — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."cod_prod"::text),'') AS k0, NULLIF(BTRIM("s"."galpao"::text),'') AS k1, NULLIF(BTRIM("s"."lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_de_alojamento" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."base_dinamica" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='base_dinamica' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'base_dinamica' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- mortalidade_peso_abertos — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."mortalidade_peso_abertos" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='mortalidade_peso_abertos' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_abertos' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- mortalidade_peso_abertos — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."mortalidade_peso_abertos" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='mortalidade_peso_abertos' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_abertos' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- mortalidade_peso_fechados — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."mortalidade_peso_fechados" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='mortalidade_peso_fechados' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_fechados' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- mortalidade_peso_fechados — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."mortalidade_peso_fechados" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='mortalidade_peso_fechados' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_fechados' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- vw_desempenho_acerto_portal — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."vw_desempenho_acerto_portal" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='vw_desempenho_acerto_portal' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'vw_desempenho_acerto_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- vw_desempenho_acerto_portal — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."vw_desempenho_acerto_portal" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='vw_desempenho_acerto_portal' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'vw_desempenho_acerto_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- vw_historico_lotes_criacao_portal — estimar antes (preencher aliases nas duas cópias)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."recepcao_dia_cache" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."vw_historico_lotes_criacao_portal" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='vw_historico_lotes_criacao_portal' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'vw_historico_lotes_criacao_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;

-- vw_historico_lotes_criacao_portal — correspondências (executar somente após estimativa)
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH aliases(fonte,valor,entidade_id) AS (
 SELECT NULL::text,NULL::text,NULL::text WHERE FALSE
 -- Substituir SELECT acima por VALUES ('fonte','valor EXATO','identificador confirmado'),...
), amostra AS MATERIALIZED (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."recepcao_dia_cache" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM "zootecnico"."vw_historico_lotes_criacao_portal" s LIMIT 500),
mapa AS (SELECT valor,COUNT(DISTINCT entidade_id) AS entidades,MIN(entidade_id) AS entidade_id FROM aliases
         WHERE fonte='vw_historico_lotes_criacao_portal' GROUP BY valor),
canon AS (SELECT a.*,m.valor AS alias_encontrado,m.entidades,
                CASE WHEN m.entidades=1 THEN m.entidade_id END AS identidade
         FROM amostra a LEFT JOIN mapa m ON m.valor=a.tecnico),
grupos AS (SELECT k0, k1, k2, k3,COUNT(DISTINCT identidade) AS identidades,BOOL_OR(identidade IS NULL) AS desconhecido
           FROM canon WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'vw_historico_lotes_criacao_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
       COUNT(*) AS linhas_amostra, COUNT(*) FILTER (WHERE a.tecnico IS NULL) AS sem_tecnico,
       (SELECT COUNT(*) FROM mapa) AS aliases_informados,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.tecnico IS NOT NULL AND a.alias_encontrado IS NULL) END AS linhas_sem_correspondencia,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN COUNT(*) FILTER (WHERE a.entidades>1) END AS linhas_com_alias_ambiguo,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1) END AS chaves_com_identidades_diferentes,
       CASE WHEN EXISTS(SELECT 1 FROM mapa) THEN (SELECT COUNT(*) FROM grupos WHERE identidades>1 OR desconhecido) END AS chaves_bloqueadas_na_amostra
FROM canon a;
ROLLBACK;
