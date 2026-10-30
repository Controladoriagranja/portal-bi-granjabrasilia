-- Executar manualmente ANTES de habilitar PORTAL_FORMS_IMPORT_ENABLED.
-- Sem dependencia nova no login/bootstrap. Nenhum chamado existente e alterado.
BEGIN;
CREATE TABLE IF NOT EXISTS public.chamados_forms_importacoes (
    origem text NOT NULL,
    resposta_key text NOT NULL,
    chamado_id bigint REFERENCES public.chamados(id) ON DELETE SET NULL,
    importado_em timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (origem, resposta_key)
);
-- Manter o recibo mesmo apos exclusao do chamado: reimportacao nao o recria.
COMMIT;
