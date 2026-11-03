-- COMPATIBILIDADE: executar manualmente UMA VEZ após a migração de estrutura,
-- antes de ativar a autorização por técnico na API. Não é cadastro de técnicos.
-- Preserva a visão geral que os usuários já tinham por relatório/setor.
-- Escopos já configurados (inclusive none/inativos/próprio/equipe) não mudam.
-- Não altera permissões do Comercial, usuários, senhas ou acesso ao relatório.
BEGIN;
SELECT pg_advisory_xact_lock(71811203);
DO $$
BEGIN
    -- Marcador nas estruturas existentes: repetir o arquivo não libera novos
    -- usuários cadastrados depois desta transição.
    INSERT INTO public.entidades_acesso_dados(tipo,identificador,nome,ativo)
    VALUES ('migracao','zootecnico_preservar_existentes_v1',
            'Compatibilidade dos acessos anteriores à restrição por técnico',FALSE)
    ON CONFLICT (tipo,identificador) DO NOTHING;
    IF NOT FOUND THEN
        RAISE NOTICE 'Compatibilidade já aplicada; nenhuma permissão alterada.';
        RETURN;
    END IF;

    INSERT INTO public.usuario_escopos_acesso(usuario_id,recurso,escopo,ativo)
    SELECT u.id,'zootecnico','todos',TRUE
    FROM public.usuarios u
    WHERE EXISTS (
        SELECT 1 FROM public.relatorios r
        JOIN public.setores s ON s.id=r.setor_id AND s.ativo
        WHERE r.id=13 AND (
            (u.report_access_mode='specific' AND EXISTS (
                SELECT 1 FROM public.usuario_relatorios ur
                WHERE ur.usuario_id=u.id AND ur.relatorio_id=r.id))
            OR (COALESCE(u.report_access_mode,'sector')<>'specific' AND EXISTS (
                SELECT 1 FROM public.usuario_setores us
                WHERE us.usuario_id=u.id AND us.setor_id=r.setor_id))))
    ON CONFLICT (usuario_id,recurso) DO NOTHING;
    -- Inclui usuários bloqueados com a mesma liberação anterior, sem ativá-los:
    -- autenticação e bloqueios continuam sendo verificados em cada requisição.
END $$;
COMMIT;
