-- Aplicar manualmente após 20261030_forms_import.sql. Não altera login/permissões.
-- Guarda apenas recibos; nunca conteúdo/base64 dos arquivos.
CREATE TABLE IF NOT EXISTS public.chamados_forms_anexos (
    upload_key varchar(32) PRIMARY KEY,
    chamado_id bigint REFERENCES public.chamados(id) ON DELETE SET NULL,
    usuario_id bigint NOT NULL REFERENCES public.usuarios(id),
    original_name text NOT NULL,
    stored_name text NOT NULL,
    bytes_size integer NOT NULL CHECK (bytes_size > 0 AND bytes_size <= 10485760),
    mime_type text NOT NULL,
    sha256 varchar(64) NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done')),
    drive_file_id text,
    criado_em timestamptz NOT NULL DEFAULT NOW(),
    atualizado_em timestamptz NOT NULL DEFAULT NOW(),
    UNIQUE (chamado_id, usuario_id, sha256, original_name)
);
