-- NEON: executar MANUALMENTE, DEPOIS de 20261103_zootecnico_access.sql.
-- Preencher SOMENTE o JSON de configuração. Não preencher com suposições.
-- Vincula uma conta comum JÁ CRIADA pelo portal; não cria/redefine senha.
-- Não altera perfil, permissões comerciais, outros vínculos ou regras dos BIs.
-- Se qualquer validação falhar, a transação inteira deve ser encerrada com ROLLBACK.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '10s';

DO $cadastro$
DECLARE
    cfg jsonb := $config${
      "nome": null,
      "email_portal": null,
      "tecnico_id": "tecnico_teste_01",
      "aliases": {
        "vw_desempenho_acerto_portal": [],
        "base_dinamica": [],
        "mortalidade_peso_abertos": [],
        "vw_historico_lotes_criacao_portal": [],
        "acerto_lote_resultado_geral": [],
        "mortalidade_peso_fechados": []
      }
    }$config$::jsonb;
    -- Na view de Desempenho, incluir tecnico E tecnico_exibicao no mesmo array
    -- quando forem diferentes. As últimas duas fontes são auxiliares de carga/histórico.
    fontes text[] := ARRAY['vw_desempenho_acerto_portal','base_dinamica',
      'mortalidade_peso_abertos','vw_historico_lotes_criacao_portal',
      'acerto_lote_resultado_geral','mortalidade_peso_fechados'];
    v_fonte text;
    item jsonb;
    valor_alias text;
    nome_tecnico text := BTRIM(cfg->>'nome');
    email_usuario text := LOWER(BTRIM(cfg->>'email_portal'));
    v_tecnico_id text := cfg->>'tecnico_id';
    conta record;
    entidade record;
    vinculo_existente record;
    dono_alias text;
BEGIN
    IF current_database() <> 'portal-bi-granjabrasilia' THEN
        RAISE EXCEPTION 'Execute no Neon do Portal, banco portal-bi-granjabrasilia, não no banco interno.';
    END IF;
    IF COALESCE(nome_tecnico,'')='' OR COALESCE(email_usuario,'')='' THEN
        RAISE EXCEPTION 'Preencha nome e email_portal REAIS no JSON. Nenhum cadastro foi realizado.';
    END IF;
    IF v_tecnico_id IS NULL OR v_tecnico_id !~ '^[A-Za-z0-9_-]{1,80}$' THEN
        RAISE EXCEPTION 'tecnico_id inválido.';
    END IF;
    IF jsonb_typeof(cfg->'aliases') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Informe o objeto aliases.';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(cfg->'aliases') AS f(nome)
               WHERE NOT (f.nome=ANY(fontes))) THEN
        RAISE EXCEPTION 'Fonte desconhecida no JSON de aliases.';
    END IF;
    FOREACH v_fonte IN ARRAY fontes LOOP
        IF jsonb_typeof(cfg->'aliases'->v_fonte) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'Informe um array de aliases exatos para %.',v_fonte;
        END IF;
        IF jsonb_array_length(cfg->'aliases'->v_fonte)=0 THEN
            RAISE EXCEPTION 'Falta confirmar alias exato da fonte %. Nenhum cadastro foi realizado.',v_fonte;
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(cfg->'aliases'->v_fonte) LOOP
            valor_alias := item #>> '{}';
            IF jsonb_typeof(item)<>'string' OR COALESCE(valor_alias,'')=''
               OR valor_alias<>BTRIM(valor_alias) OR LENGTH(valor_alias)>500 THEN
                RAISE EXCEPTION 'Alias inválido para %. Use o valor exato, sem espaços nas pontas.',v_fonte;
            END IF;
        END LOOP;
    END LOOP;

    IF (SELECT COUNT(*) FROM public.usuarios WHERE LOWER(email)=email_usuario)<>1 THEN
        RAISE EXCEPTION 'Crie primeiro uma única conta para % em Usuários no Portal. Não será inventada uma senha.',email_usuario;
    END IF;
    SELECT id,ativo,role,perfil,report_access_mode INTO STRICT conta
      FROM public.usuarios WHERE LOWER(email)=email_usuario FOR UPDATE;
    IF conta.ativo IS DISTINCT FROM TRUE
       OR LOWER(COALESCE(conta.role,'')) IN ('admin','director')
       OR LOWER(COALESCE(conta.perfil,'')) IN ('admin','diretor','director') THEN
        RAISE EXCEPTION 'A conta de teste deve estar ativa e ser comum/Setor; Admin/Diretor continuam com acesso geral.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.relatorios r JOIN public.setores s ON s.id=r.setor_id
                   WHERE r.id=13 AND r.setor_id=4 AND s.ativo=TRUE) THEN
        RAISE EXCEPTION 'O relatório 13 / setor 4 não corresponde ao cadastro esperado da Integração.';
    END IF;

    SELECT escopo,ativo INTO vinculo_existente FROM public.usuario_escopos_acesso
      WHERE usuario_id=conta.id AND recurso='zootecnico' FOR UPDATE;
    IF FOUND AND vinculo_existente.ativo AND vinculo_existente.escopo NOT IN ('none','proprio') THEN
        RAISE EXCEPTION 'Conta já possui acesso de equipe/geral. Escolha outra conta de teste; nada será rebaixado.';
    END IF;
    IF EXISTS (SELECT 1 FROM public.usuario_vinculos_dados
               WHERE usuario_id=conta.id AND recurso='zootecnico' AND ativo
                 AND (tipo_entidade<>'tecnico' OR entidade_id<>v_tecnico_id)) THEN
        RAISE EXCEPTION 'Conta já vinculada a outro técnico. Nenhum vínculo existente será removido.';
    END IF;

    -- Bloqueia alterações concorrentes do catálogo durante a validação/inclusão.
    LOCK TABLE public.entidade_aliases_dados IN SHARE ROW EXCLUSIVE MODE;
    SELECT nome,ativo INTO entidade FROM public.entidades_acesso_dados
      WHERE tipo='tecnico' AND entidades_acesso_dados.identificador=v_tecnico_id;
    IF FOUND AND (entidade.nome<>nome_tecnico OR entidade.ativo IS DISTINCT FROM TRUE) THEN
        RAISE EXCEPTION 'tecnico_id já existe com outro nome/estado. Use o identificador canônico correto.';
    END IF;
    FOREACH v_fonte IN ARRAY fontes LOOP
        FOR item IN SELECT value FROM jsonb_array_elements(cfg->'aliases'->v_fonte) LOOP
            valor_alias := item #>> '{}';
            SELECT entidade_id INTO dono_alias FROM public.entidade_aliases_dados a
              WHERE a.recurso='zootecnico' AND a.fonte=v_fonte AND a.valor=valor_alias;
            IF FOUND AND dono_alias<>v_tecnico_id THEN
                RAISE EXCEPTION 'Alias da fonte % já pertence a outro técnico; não será reassociado.',v_fonte;
            END IF;
        END LOOP;
    END LOOP;

    INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome)
      VALUES ('tecnico',v_tecnico_id,nome_tecnico) ON CONFLICT DO NOTHING;
    INSERT INTO public.usuario_escopos_acesso(usuario_id,recurso,escopo,ativo)
      VALUES (conta.id,'zootecnico','proprio',TRUE)
      ON CONFLICT (usuario_id,recurso) DO UPDATE SET escopo='proprio',ativo=TRUE,atualizado_em=NOW();
    INSERT INTO public.usuario_vinculos_dados(usuario_id,recurso,tipo_entidade,entidade_id,ativo)
      VALUES (conta.id,'zootecnico','tecnico',v_tecnico_id,TRUE)
      ON CONFLICT (usuario_id,recurso,tipo_entidade,entidade_id) DO UPDATE SET ativo=TRUE,atualizado_em=NOW();
    FOREACH v_fonte IN ARRAY fontes LOOP
        FOR item IN SELECT value FROM jsonb_array_elements(cfg->'aliases'->v_fonte) LOOP
            INSERT INTO public.entidade_aliases_dados(recurso,fonte,valor,tipo_entidade,entidade_id,ativo)
              VALUES ('zootecnico',v_fonte,item #>> '{}','tecnico',v_tecnico_id,TRUE)
              ON CONFLICT (recurso,fonte,valor) DO UPDATE SET ativo=TRUE,atualizado_em=NOW();
        END LOOP;
    END LOOP;
    IF conta.report_access_mode='specific' THEN
        INSERT INTO public.usuario_relatorios(usuario_id,relatorio_id)
          SELECT conta.id,13 WHERE NOT EXISTS (
            SELECT 1 FROM public.usuario_relatorios ur WHERE ur.usuario_id=conta.id AND ur.relatorio_id=13)
          ON CONFLICT DO NOTHING;
    ELSE
        INSERT INTO public.usuario_setores(usuario_id,setor_id)
          SELECT conta.id,4 WHERE NOT EXISTS (
            SELECT 1 FROM public.usuario_setores us WHERE us.usuario_id=conta.id AND us.setor_id=4)
          ON CONFLICT DO NOTHING;
    END IF;
    RAISE NOTICE 'Conta % vinculada ao técnico %. Acesso próprio na Integração; senha/perfil/Comercial preservados.',email_usuario,v_tecnico_id;
END
$cadastro$;
COMMIT;
