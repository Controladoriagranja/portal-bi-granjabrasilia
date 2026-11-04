-- Executar manualmente ANTES de publicar. Não concede permissões a ninguém.
BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS excluido_em timestamptz;
DO $restricao$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.usuarios'::regclass
                   AND conname='usuarios_excluido_inativo') THEN
        ALTER TABLE public.usuarios ADD CONSTRAINT usuarios_excluido_inativo
            CHECK (excluido_em IS NULL OR ativo IS FALSE);
    END IF;
END;
$restricao$;

CREATE TABLE IF NOT EXISTS public.auditoria_usuarios (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocorrido_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    acao text NOT NULL,
    autor_id bigint,
    autor_nome text,
    autor_email text,
    usuario_id bigint NOT NULL,
    usuario_nome text,
    usuario_email text,
    origem text NOT NULL,
    usuario_sql text NOT NULL DEFAULT current_user,
    antes jsonb,
    depois jsonb
);
-- Sem FK: o log sobrevive à exclusão física do autor/alvo por manutenção futura.
CREATE INDEX IF NOT EXISTS auditoria_usuarios_alvo_idx ON public.auditoria_usuarios(usuario_id, id DESC);

CREATE OR REPLACE FUNCTION public.registrar_auditoria_usuarios()
RETURNS trigger LANGUAGE plpgsql AS $auditoria$
DECLARE
    contexto jsonb := coalesce(nullif(current_setting('portal.audit_actor', true), ''), '{}')::jsonb;
    antigo jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) ELSE NULL END;
    novo jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) ELSE NULL END;
    anterior jsonb;
    posterior jsonb;
    alvo jsonb := coalesce(novo, antigo);
    evento text;
BEGIN
    -- Lista explícita: NUNCA armazenar senha_hash, senhas, tokens ou corpo HTTP.
    SELECT jsonb_object_agg(chave, antigo->chave), jsonb_object_agg(chave, novo->chave)
    INTO anterior, posterior
    FROM unnest(ARRAY['nome','email','role','perfil','ativo','excluido_em',
                     'report_access_mode','ticket_panel_access','commercial_access']) AS campos(chave);
    IF TG_OP='INSERT' THEN evento := 'criacao'; anterior := NULL;
    ELSIF TG_OP='DELETE' THEN evento := 'exclusao_fisica'; posterior := NULL;
    ELSIF antigo->>'excluido_em' IS NULL AND novo->>'excluido_em' IS NOT NULL THEN evento := 'exclusao';
    ELSIF antigo->>'excluido_em' IS NOT NULL AND novo->>'excluido_em' IS NULL THEN evento := 'restauracao';
    ELSIF antigo->>'ativo' IS DISTINCT FROM novo->>'ativo' THEN
        evento := CASE WHEN (novo->>'ativo')::boolean THEN 'desbloqueio' ELSE 'bloqueio' END;
    ELSIF anterior IS DISTINCT FROM posterior THEN evento := 'alteracao';
    ELSIF antigo->>'senha_hash' IS DISTINCT FROM novo->>'senha_hash' THEN evento := 'troca_senha';
    ELSE RETURN NULL;
    END IF;
    INSERT INTO public.auditoria_usuarios
        (acao,autor_id,autor_nome,autor_email,usuario_id,usuario_nome,usuario_email,origem,antes,depois)
    VALUES
        (evento,(contexto->>'id')::bigint,contexto->>'nome',contexto->>'email',
         (alvo->>'id')::bigint,alvo->>'nome',alvo->>'email',
         CASE WHEN contexto->>'id' IS NULL THEN 'banco' ELSE 'portal' END,anterior,posterior);
    RETURN NULL;
END;
$auditoria$;

DROP TRIGGER IF EXISTS usuarios_auditoria_trg ON public.usuarios;
CREATE TRIGGER usuarios_auditoria_trg AFTER INSERT OR UPDATE OR DELETE ON public.usuarios
FOR EACH ROW EXECUTE FUNCTION public.registrar_auditoria_usuarios();
COMMENT ON TABLE public.auditoria_usuarios IS
 'Auditoria transacional, sem credenciais. Ações via SQL sem contexto ficam com origem banco e usuario_sql; não inventa autor do portal.';
COMMIT;

-- Recuperação manual se não houver Admin OU gestor de usuários ativo autorizado:
-- UPDATE public.usuarios SET ativo=TRUE WHERE id=ID_CONFIRMADO_DO_ADMIN;
-- A própria ação de recuperação também será registrada com origem banco.
