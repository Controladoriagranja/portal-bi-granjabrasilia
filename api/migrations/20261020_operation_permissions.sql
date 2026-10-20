-- Executar manualmente ANTES de publicar o backend que usa usuario_operacoes.
-- Nao concede permissoes nem altera cadastros/alcances existentes.
BEGIN;

CREATE TABLE IF NOT EXISTS public.usuario_operacoes (
    usuario_id bigint NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    permissao text NOT NULL,
    concedido_em timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (usuario_id, permissao),
    CONSTRAINT usuario_operacoes_codigo_valido CHECK (
        permissao ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'
    )
);

COMMENT ON TABLE public.usuario_operacoes IS
    'Concessoes explicitas por ID permanente CENTRAL; ausencia nega escrita, inclusive Admin/Diretor.';

COMMIT;
