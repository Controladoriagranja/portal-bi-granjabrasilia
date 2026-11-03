-- UP: executar manualmente no Neon, antes de publicar a nova API especializada.
-- Não altera usuários, senhas, permissões comerciais, relatórios nem dados do BI.
BEGIN;
CREATE TABLE public.entidades_acesso_dados (
    tipo text NOT NULL,
    identificador text NOT NULL CHECK (identificador ~ '^[A-Za-z0-9_-]{1,80}$'),
    nome text NOT NULL CHECK (btrim(nome) <> ''),
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT NOW(),
    atualizado_em timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tipo,identificador)
);
CREATE TABLE public.usuario_escopos_acesso (
    usuario_id bigint NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    recurso text NOT NULL,
    escopo text NOT NULL CHECK (escopo IN ('none','proprio','equipe','todos')),
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT NOW(),
    atualizado_em timestamptz NOT NULL DEFAULT NOW(),
    criado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    atualizado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    PRIMARY KEY (usuario_id,recurso)
);
CREATE TABLE public.usuario_vinculos_dados (
    usuario_id bigint NOT NULL,
    recurso text NOT NULL,
    tipo_entidade text NOT NULL,
    entidade_id text NOT NULL,
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT NOW(),
    atualizado_em timestamptz NOT NULL DEFAULT NOW(),
    criado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    atualizado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    PRIMARY KEY (usuario_id,recurso,tipo_entidade,entidade_id),
    FOREIGN KEY (usuario_id,recurso) REFERENCES public.usuario_escopos_acesso(usuario_id,recurso) ON DELETE CASCADE,
    FOREIGN KEY (tipo_entidade,entidade_id) REFERENCES public.entidades_acesso_dados(tipo,identificador)
);
CREATE INDEX usuario_vinculos_dados_entidade_idx
    ON public.usuario_vinculos_dados(tipo_entidade,entidade_id) WHERE ativo;
CREATE TABLE public.entidade_aliases_dados (
    recurso text NOT NULL,
    fonte text NOT NULL,
    valor text NOT NULL CHECK (valor=btrim(valor) AND valor <> ''),
    tipo_entidade text NOT NULL,
    entidade_id text NOT NULL,
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT NOW(),
    atualizado_em timestamptz NOT NULL DEFAULT NOW(),
    criado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    atualizado_por bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    PRIMARY KEY (recurso,fonte,valor),
    FOREIGN KEY (tipo_entidade,entidade_id) REFERENCES public.entidades_acesso_dados(tipo,identificador),
    CHECK (recurso <> 'zootecnico' OR (tipo_entidade='tecnico' AND fonte IN (
      'vw_desempenho_acerto_portal','acerto_lote_resultado_geral','base_dinamica',
      'mortalidade_peso_abertos','mortalidade_peso_fechados','vw_historico_lotes_criacao_portal')))
);
CREATE INDEX entidade_aliases_dados_entidade_idx
    ON public.entidade_aliases_dados(tipo_entidade,entidade_id) WHERE ativo;
-- Nenhum vínculo de técnico é inferido de nome, e-mail ou sigla.
-- Admin/Diretor seguem política geral explícita no servidor, para existentes e novos.
COMMIT;
