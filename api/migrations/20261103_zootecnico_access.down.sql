-- Rollback MANUAL: perde somente os novos vínculos/aliases. Exportar essas tabelas antes.
-- Retirar a nova API de serviço antes; reverter código para versão insegura reabre dados.
BEGIN;
DROP TABLE public.entidade_aliases_dados;
DROP TABLE public.usuario_vinculos_dados;
DROP TABLE public.usuario_escopos_acesso;
DROP TABLE public.entidades_acesso_dados;
COMMIT;
