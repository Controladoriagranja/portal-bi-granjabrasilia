# API do Anderson — mesmo formato do arquivo recebido

Entrega: `entrega/api_zootecnico_atualizada.zip`.
Mantém a pasta raiz `api_zootecnico/` e TODOS os arquivos/pastas do ZIP
`api_zootecnico(3).zip`, confirmado pelo usuário como vigente.
Não há novo projeto, outro Docker ou mudança da forma de executar a API.

Somente estas alterações foram incorporadas:

- `api_zootecnico/servico_zootecnico.py`: autorização, conexão com escopo e registro
  do endpoint administrativo `/api/zootecnico/acesso/opcoes` para o cadastro único.
- `api_zootecnico/portal_router.py`: catálogo/cache e contexto das threads.
- `api_zootecnico/Dockerfile.zootecnico`: o MESMO arquivo original, com uma
  linha COPY adicional para incluir o módulo novo. Imagem, porta, CMD e demais
  linhas originais preservados.
- `api_zootecnico/zootecnico_acesso.py`: único arquivo novo; autorização e catálogo
  de nomes/provas por chave de lote, restrito a admin pela identidade do Comercial.

O `api_zootecnico/Dockerfile` principal permanece byte a byte igual ao original.
Todos os demais arquivos, inclusive configurações e backups, permanecem iguais.
O ZIP de entrada não foi modificado. O link da entrega anterior também foi
atualizado para fornecer este mesmo pacote completo.

Para implantar manualmente: extrair em uma pasta separada, guardar a versão atual
 e aplicar a atualização na estrutura existente, mantendo `.env` e configurações
locais do servidor. Usar o mesmo procedimento de build/reinício que já é utilizado
no Anderson. Nenhum desses comandos foi executado pelo Codex.

Pré-requisitos: estrutura Neon, SQL de compatibilidade dos acessos existentes,
backend do Portal atualizado e Worker encaminhando X-Portal-Authorization.
Ver `IMPLANTAR.md` para a ordem; não ativar a API antes da compatibilidade.
O cadastro do técnico de teste é pelo formulário de Usuários, sem seed/aliases SQL.
Se houver mudanças no servidor posteriores ao ZIP confirmado, usar o patch externo
`entrega/integracao_api.patch` para preservar essas mudanças.

O pacote completo é local e está no .gitignore, pois preserva as configurações
recebidas. As instruções e o patch ficam fora do ZIP, mantendo seu formato original.
