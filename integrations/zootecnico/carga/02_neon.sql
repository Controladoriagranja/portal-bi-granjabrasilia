-- Executar no SQL Editor do Neon, banco portal-bi-granjabrasilia. SOMENTE LEITURA.
-- Usa as quatro tabelas auxiliares existentes; não cria nem modifica nada.
-- Resultado: uma célula JSON na coluna resultado. Copiar/exportar essa célula inteira.
-- A linha final ROLLBACK não é o resultado do levantamento.
-- Não lê senha_hash, tokens, segredos, dados comerciais ou dados de lotes.
-- Inclui vínculos inativos para detectar colisões sem reaproveitá-los indevidamente.

BEGIN READ ONLY;
SET LOCAL statement_timeout = '8s';
SET LOCAL lock_timeout = '1s';

WITH usuarios AS (
    SELECT u.id,u.nome,u.email,u.ativo,u.role,u.perfil,u.report_access_mode,
           (LOWER(BTRIM(COALESCE(u.role,''))) IN ('admin','director')
            OR LOWER(BTRIM(COALESCE(u.perfil,''))) IN ('admin','diretor','director')) AS perfil_geral,
           EXISTS (
               SELECT 1 FROM public.relatorios r
               JOIN public.setores s ON s.id=r.setor_id AND s.ativo
               WHERE r.id=13 AND (
                   (u.report_access_mode='specific' AND EXISTS (
                       SELECT 1 FROM public.usuario_relatorios ur
                       WHERE ur.usuario_id=u.id AND ur.relatorio_id=r.id))
                   OR (COALESCE(u.report_access_mode,'sector')<>'specific' AND EXISTS (
                       SELECT 1 FROM public.usuario_setores us
                       WHERE us.usuario_id=u.id AND us.setor_id=r.setor_id)))) AS integracao_liberada_por_relatorio_ou_setor
    FROM public.usuarios u
),
entidades AS (
    SELECT tipo,identificador,nome,ativo,criado_em,atualizado_em
    FROM public.entidades_acesso_dados WHERE tipo IN ('tecnico','usuario_portal')
),
aliases AS (
    SELECT recurso,fonte,valor,tipo_entidade,entidade_id,ativo,criado_em,atualizado_em
    FROM public.entidade_aliases_dados WHERE recurso LIKE 'zootecnico%'
),
escopos AS (
    SELECT usuario_id,recurso,escopo,ativo,criado_em,atualizado_em
    FROM public.usuario_escopos_acesso WHERE recurso LIKE 'zootecnico%'
),
vinculos AS (
    SELECT usuario_id,recurso,tipo_entidade,entidade_id,ativo,criado_em,atualizado_em
    FROM public.usuario_vinculos_dados WHERE recurso LIKE 'zootecnico%'
)
SELECT jsonb_pretty(jsonb_build_object(
    'versao',1,
    'banco',current_database(),
    'somente_leitura',current_setting('transaction_read_only'),
    'usuarios',COALESCE((SELECT jsonb_agg(to_jsonb(u) ORDER BY u.id) FROM usuarios u),'[]'::jsonb),
    'entidades',COALESCE((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.tipo,e.identificador) FROM entidades e),'[]'::jsonb),
    'aliases',COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.recurso,a.fonte,a.valor) FROM aliases a),'[]'::jsonb),
    'escopos',COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.usuario_id,s.recurso) FROM escopos s),'[]'::jsonb),
    'vinculos',COALESCE((SELECT jsonb_agg(to_jsonb(v) ORDER BY v.usuario_id,v.recurso,v.tipo_entidade,v.entidade_id) FROM vinculos v),'[]'::jsonb)
)) AS resultado;

ROLLBACK;
