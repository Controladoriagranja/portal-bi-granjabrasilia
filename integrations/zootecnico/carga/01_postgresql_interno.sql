-- Executar no Adminer, banco bi_granja. SOMENTE LEITURA.
-- Usa as seis fontes e campos já confirmados; não repete o levantamento de metadados.
-- Resultado: uma célula JSON na coluna resultado. Copiar/exportar essa célula inteira.
-- A linha final ROLLBACK não é o resultado do levantamento.
-- Não há LIMIT/amostragem: as contagens e os valores são completos se a consulta terminar.
-- Se exceder 15 segundos, retornar o erro; não aumentar o timeout/repetir em loop.
-- As chaves de lote são usadas apenas dentro da consulta; não são exportadas.
-- Uma evidência candidata NÃO aprova uma identidade nem concede acesso.

BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '1s';

WITH
origem AS MATERIALIZED (
    SELECT 'vw_desempenho_acerto_portal'::text AS fonte,
           NULLIF(BTRIM(s.tecnico::text),'') AS tecnico,
           NULLIF(BTRIM(s.tecnico_exibicao::text),'') AS exibicao,
           NULLIF(BTRIM(s.codigo::text),'') AS produtor,
           NULLIF(BTRIM(s.gal::text),'') AS galpao,
           NULLIF(BTRIM(s.lote::text),'') AS lote,
           NULLIF(BTRIM(s.dt_aloj::text),'') AS dia_bruto,
           NULLIF(BTRIM(s.chave_lote::text),'') AS chave_lote,
           COALESCE(to_jsonb(s)->>'candidatos_tecnico','1') !~ '^[01]$' AS ambigua
    FROM zootecnico.vw_desempenho_acerto_portal s

    UNION ALL
    SELECT 'acerto_lote_resultado_geral',NULLIF(BTRIM(s.tecnico::text),''),
           NULL::text,NULL::text,NULL::text,NULL::text,NULL::text,
           NULLIF(BTRIM(s.chave_lote::text),''),FALSE
    FROM zootecnico.acerto_lote_resultado_geral s

    UNION ALL
    SELECT 'base_dinamica',NULLIF(BTRIM(s.tecnico::text),''),NULL::text,
           NULLIF(BTRIM(s.cod_prod::text),''),NULLIF(BTRIM(s.galpao::text),''),
           NULLIF(BTRIM(s.lote::text),''),NULLIF(BTRIM(s.data_de_alojamento::text),''),
           NULL::text,FALSE
    FROM zootecnico.base_dinamica s

    UNION ALL
    SELECT 'mortalidade_peso_abertos',NULLIF(BTRIM(s.tecnico::text),''),NULL::text,
           NULLIF(BTRIM(s.codigo_granja::text),''),NULLIF(BTRIM(s.galp::text),''),
           NULLIF(BTRIM(s.num_lote::text),''),NULLIF(BTRIM(s.data_recepcao::text),''),
           NULL::text,FALSE
    FROM zootecnico.mortalidade_peso_abertos s

    UNION ALL
    SELECT 'mortalidade_peso_fechados',NULLIF(BTRIM(s.tecnico::text),''),NULL::text,
           NULLIF(BTRIM(s.codigo_granja::text),''),NULLIF(BTRIM(s.galp::text),''),
           NULLIF(BTRIM(s.num_lote::text),''),NULLIF(BTRIM(s.data_recepcao::text),''),
           NULL::text,FALSE
    FROM zootecnico.mortalidade_peso_fechados s

    UNION ALL
    SELECT 'vw_historico_lotes_criacao_portal',NULLIF(BTRIM(s.tecnico::text),''),NULL::text,
           NULLIF(BTRIM(s.codigo_granja::text),''),NULLIF(BTRIM(s.galp::text),''),
           NULLIF(BTRIM(s.num_lote::text),''),NULLIF(BTRIM(s.recepcao_dia_cache::text),''),
           NULL::text,FALSE
    FROM zootecnico.vw_historico_lotes_criacao_portal s
),
-- Mesma interpretação ISO/DD/MM/AAAA usada pelos helpers atuais do BI.
-- Não converte códigos numéricos nem remove zeros/iniciais/acentos dos nomes.
partes AS (
    SELECT o.*,CASE
        WHEN dia_bruto ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T].*)?$'
            THEN ARRAY[substring(dia_bruto,1,4)::int,
                       substring(dia_bruto,6,2)::int,substring(dia_bruto,9,2)::int]
        WHEN dia_bruto ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
            THEN ARRAY[substring(dia_bruto,7,4)::int,
                       substring(dia_bruto,4,2)::int,substring(dia_bruto,1,2)::int]
        ELSE NULL::int[] END AS ymd
    FROM origem o
),
normalizada AS MATERIALIZED (
    SELECT p.*,CASE WHEN ymd[1] BETWEEN 1 AND 9999 AND ymd[2] BETWEEN 1 AND 12 THEN
        CASE WHEN ymd[3] BETWEEN 1 AND EXTRACT(day FROM
            make_date(ymd[1],ymd[2],1) + interval '1 month - 1 day')
        THEN make_date(ymd[1],ymd[2],ymd[3]) ELSE NULL::date END
        ELSE NULL::date END AS dia
    FROM partes p
),
fontes(fonte,campos_chave) AS (VALUES
    ('vw_desempenho_acerto_portal',ARRAY['codigo','gal','lote','dt_aloj','chave_lote']),
    ('acerto_lote_resultado_geral',ARRAY['chave_lote']),
    ('base_dinamica',ARRAY['cod_prod','galpao','lote','data_de_alojamento']),
    ('mortalidade_peso_abertos',ARRAY['codigo_granja','galp','num_lote','data_recepcao']),
    ('mortalidade_peso_fechados',ARRAY['codigo_granja','galp','num_lote','data_recepcao']),
    ('vw_historico_lotes_criacao_portal',ARRAY['codigo_granja','galp','num_lote','recepcao_dia_cache'])
),
resumo AS (
    SELECT f.fonte,f.campos_chave,COUNT(n.fonte) AS registros,
           COUNT(DISTINCT n.tecnico) AS valores_tecnico_distintos,
           COUNT(DISTINCT n.exibicao) AS valores_exibicao_distintos,
           COUNT(*) FILTER (WHERE n.fonte IS NOT NULL AND n.tecnico IS NULL) AS tecnico_vazio,
           COUNT(*) FILTER (WHERE n.ambigua) AS registros_ambiguos_na_view,
           COUNT(*) FILTER (WHERE n.fonte IS NOT NULL AND CASE
             WHEN n.fonte='acerto_lote_resultado_geral' THEN n.chave_lote IS NULL
             ELSE n.produtor IS NULL OR n.galpao IS NULL OR n.lote IS NULL OR n.dia IS NULL
           END) AS chave_ausente_ou_data_invalida
    FROM fontes f LEFT JOIN normalizada n ON n.fonte=f.fonte
    GROUP BY f.fonte,f.campos_chave
),
valores AS (
    SELECT n.fonte,v.campo,v.valor,COUNT(*) AS registros,
           COUNT(*) FILTER (WHERE n.ambigua) AS registros_ambiguos_na_view
    FROM normalizada n CROSS JOIN LATERAL (
        SELECT 'tecnico'::text AS campo,n.tecnico AS valor WHERE n.tecnico IS NOT NULL
        UNION ALL
        SELECT 'tecnico_exibicao',n.exibicao WHERE n.exibicao IS NOT NULL
    ) v
    GROUP BY n.fonte,v.campo,v.valor
),
-- Chave composta completa: nunca associa pessoas somente por galpão ou sigla.
indices AS (
    SELECT fonte,'produtor_galpao_lote_alojamento'::text AS tipo_chave,
           jsonb_build_array(produtor,galpao,lote,dia::text) AS chave,tecnico,ambigua
    FROM normalizada
    WHERE produtor IS NOT NULL AND galpao IS NOT NULL AND lote IS NOT NULL AND dia IS NOT NULL
    UNION ALL
    SELECT fonte,'chave_lote',to_jsonb(chave_lote),tecnico,ambigua
    FROM normalizada WHERE chave_lote IS NOT NULL
      AND fonte IN ('vw_desempenho_acerto_portal','acerto_lote_resultado_geral')
),
por_fonte_chave AS MATERIALIZED (
    SELECT fonte,tipo_chave,chave,COUNT(DISTINCT tecnico) AS quantidade_tecnicos,
           array_agg(DISTINCT tecnico ORDER BY tecnico) FILTER (WHERE tecnico IS NOT NULL) AS tecnicos,
           BOOL_OR(tecnico IS NULL OR ambigua) AS contem_ausencia_ou_ambiguidade
    FROM indices GROUP BY fonte,tipo_chave,chave
),
por_chave AS MATERIALIZED (
    SELECT tipo_chave,chave,
           BOOL_OR(quantidade_tecnicos<>1 OR contem_ausencia_ou_ambiguidade) AS conflitante,
           jsonb_agg(jsonb_build_object('fonte',fonte,'valor',tecnicos[1]) ORDER BY fonte) AS itens
    FROM por_fonte_chave GROUP BY tipo_chave,chave
),
evidencias AS (
    SELECT c.tipo_chave AS origem,a.item->>'fonte' AS fonte_a,a.item->>'valor' AS valor_a,
           b.item->>'fonte' AS fonte_b,b.item->>'valor' AS valor_b,COUNT(*) AS ocorrencias
    FROM por_chave c
    CROSS JOIN LATERAL jsonb_array_elements(c.itens) WITH ORDINALITY a(item,posicao)
    CROSS JOIN LATERAL jsonb_array_elements(c.itens) WITH ORDINALITY b(item,posicao)
    WHERE NOT c.conflitante AND a.posicao<b.posicao
    GROUP BY c.tipo_chave,a.item->>'fonte',a.item->>'valor',b.item->>'fonte',b.item->>'valor'
    UNION ALL
    SELECT 'mesma_linha_tecnico_exibicao',fonte,tecnico,fonte,exibicao,COUNT(*)
    FROM normalizada WHERE NOT ambigua AND tecnico IS NOT NULL AND exibicao IS NOT NULL AND tecnico<>exibicao
    GROUP BY fonte,tecnico,exibicao
),
conflitos AS (
    SELECT p.fonte,p.tipo_chave,p.tecnicos,p.quantidade_tecnicos,
           p.contem_ausencia_ou_ambiguidade,COUNT(*) AS quantidade_chaves
    FROM por_fonte_chave p JOIN por_chave c USING(tipo_chave,chave)
    WHERE c.conflitante
    GROUP BY p.fonte,p.tipo_chave,p.tecnicos,p.quantidade_tecnicos,p.contem_ausencia_ou_ambiguidade
)
SELECT jsonb_pretty(jsonb_build_object(
    'versao',1,
    'banco',current_database(),
    'somente_leitura',current_setting('transaction_read_only'),
    'alcance','completo_sem_amostragem',
    'fontes',COALESCE((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.fonte) FROM resumo r),'[]'::jsonb),
    'valores',COALESCE((SELECT jsonb_agg(to_jsonb(v) ORDER BY v.fonte,v.campo,v.valor) FROM valores v),'[]'::jsonb),
    'evidencias_candidatas',COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.origem,e.fonte_a,e.valor_a,e.fonte_b,e.valor_b) FROM evidencias e),'[]'::jsonb),
    'conflitos',COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.fonte,c.tipo_chave,c.tecnicos) FROM conflitos c),'[]'::jsonb)
)) AS resultado;

ROLLBACK;
