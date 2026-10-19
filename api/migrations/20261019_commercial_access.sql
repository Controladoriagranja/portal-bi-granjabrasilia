BEGIN;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS commercial_access jsonb NOT NULL DEFAULT '{"mode":"none"}'::jsonb;
-- Nenhum usuário recebe acesso geral por inferência de nome, setor ou perfil.
COMMIT;
