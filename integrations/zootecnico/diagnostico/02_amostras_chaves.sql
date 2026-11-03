-- MANUAL, BANCO INTERNO. Não executado pelo Codex. Sem escrita/ETL.
-- Uma fonte por bloco. LIMIT 500 é amostra, não contagem total.
-- EXPLAIN não executa o plano; só executar o bloco de amostra após revisar a estimativa.
-- Views podem custar caro antes do LIMIT; timeout não substitui revisão do plano.

-- acerto_lote_resultado_geral — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."acerto_lote_resultado_geral" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'acerto_lote_resultado_geral' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- acerto_lote_resultado_geral — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."acerto_lote_resultado_geral" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'acerto_lote_resultado_geral' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- base_dinamica — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."base_dinamica" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."cod_prod"::text),'') AS k0, NULLIF(BTRIM("s"."galpao"::text),'') AS k1, NULLIF(BTRIM("s"."lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_de_alojamento" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'base_dinamica' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- base_dinamica — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."base_dinamica" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."cod_prod"::text),'') AS k0, NULLIF(BTRIM("s"."galpao"::text),'') AS k1, NULLIF(BTRIM("s"."lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_de_alojamento" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'base_dinamica' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- mortalidade_peso_abertos — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."mortalidade_peso_abertos" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_abertos' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- mortalidade_peso_abertos — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."mortalidade_peso_abertos" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_abertos' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- mortalidade_peso_fechados — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."mortalidade_peso_fechados" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_fechados' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- mortalidade_peso_fechados — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."mortalidade_peso_fechados" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."data_recepcao" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'mortalidade_peso_fechados' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- vw_desempenho_acerto_portal — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."vw_desempenho_acerto_portal" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'vw_desempenho_acerto_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- vw_desempenho_acerto_portal — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."vw_desempenho_acerto_portal" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s".chave_lote::text),'') AS k0, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL GROUP BY k0)
SELECT 'vw_desempenho_acerto_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- vw_historico_lotes_criacao_portal — primeiro estimar
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
EXPLAIN (FORMAT JSON, COSTS TRUE) WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."vw_historico_lotes_criacao_portal" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."recepcao_dia_cache" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'vw_historico_lotes_criacao_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;

-- vw_historico_lotes_criacao_portal — executar somente depois de revisar a estimativa
BEGIN READ ONLY;
SET LOCAL statement_timeout='5s';
SET LOCAL lock_timeout='1s';
WITH amostra AS MATERIALIZED (SELECT * FROM "zootecnico"."vw_historico_lotes_criacao_portal" LIMIT 500),
normalizada AS (SELECT NULLIF(BTRIM("s"."codigo_granja"::text),'') AS k0, NULLIF(BTRIM("s"."galp"::text),'') AS k1, NULLIF(BTRIM("s"."num_lote"::text),'') AS k2, (SELECT CASE WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 6 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 9 for 2)::integer) ELSE NULL END ELSE NULL END WHEN NULLIF(BTRIM("za_day"::text), '') ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer BETWEEN 1 AND 9999 AND substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer BETWEEN 1 AND 12 THEN CASE WHEN substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer BETWEEN 1 AND EXTRACT(day FROM (make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,1) + interval '1 month - 1 day')) THEN make_date(substring(NULLIF(BTRIM("za_day"::text), '') from 7 for 4)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 4 for 2)::integer,substring(NULLIF(BTRIM("za_day"::text), '') from 1 for 2)::integer) ELSE NULL END ELSE NULL END ELSE NULL END FROM (SELECT "s"."recepcao_dia_cache" AS za_day) za_date) AS k3, NULLIF(BTRIM(s.tecnico::text),'') AS tecnico FROM amostra s),
grupos AS (SELECT k0, k1, k2, k3,COUNT(*) AS versoes,COUNT(DISTINCT tecnico) AS tecnicos,
                  BOOL_OR(tecnico IS NULL) AS tecnico_ausente
           FROM normalizada WHERE k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL GROUP BY k0, k1, k2, k3)
SELECT 'vw_historico_lotes_criacao_portal' AS fonte, 'AMOSTRA_MAX_500_NAO_E_TOTAL' AS alcance,
 (SELECT COUNT(*) FROM normalizada) AS linhas_amostra,
 (SELECT COUNT(*) FROM normalizada WHERE NOT (k0 IS NOT NULL AND k1 IS NOT NULL AND k2 IS NOT NULL AND k3 IS NOT NULL)) AS chaves_incompletas,
 (SELECT COUNT(*) FROM normalizada WHERE tecnico IS NULL) AS tecnico_vazio,
 COUNT(*) AS chaves_completas_distintas,
 COUNT(*) FILTER (WHERE versoes>1) AS chaves_repetidas_na_amostra,
 COUNT(*) FILTER (WHERE tecnicos>1) AS chaves_com_valores_tecnico_distintos,
 COUNT(*) FILTER (WHERE tecnico_ausente) AS chaves_com_tecnico_ausente
FROM grupos;
ROLLBACK;
