# Visualizar o portal como usuário

Em Usuários, um Admin pode clicar em **Visualizar portal** na linha de uma conta ativa. Abre outra aba com o portal, relatórios e filtros da conta selecionada. O aviso identifica a pessoa; **Encerrar visualização** fecha somente essa aba. A sessão principal do Admin continua intacta.

O backend emite uma sessão assinada para o ID real do usuário selecionado, vinculada ao Admin que a solicitou, válida por 20 minutos. Cada consulta verifica novamente o usuário e o Admin no banco; bloqueio, exclusão ou retirada do perfil Admin invalida a visualização. Senhas e permissões existentes não são alteradas. Contas bloqueadas/excluídas não podem ser visualizadas como se tivessem acesso.

A transferência para a outra aba usa postMessage com origem, janela e identificador aleatório conferidos. O token não vai na URL. A aba usa sessionStorage próprio e descarta a referência à janela de origem após a transferência. Recarregar a aba mantém a visualização até expirar.

Consultas usam a mesma identidade que as APIs dos relatórios já validam em /api/auth/me, incluindo limites de área/responsável no Orçamento e vínculos nos demais módulos. O modo é somente leitura: o Portal e a API local bloqueiam alterações com essa sessão. A visão dos relatórios públicos externos mantém o comportamento que já é apresentado à conta selecionada.

Testes: test_user_preview.py; test_user_preview_browser.py; api_zootecnico/tests/test_preview_read_only.py. O navegador abre o portal completo, faz a transferência entre abas, abre o Orçamento e consulta os dados em transações somente leitura, conferindo o responsável e as áreas do Geovane. As rotas de autenticação nos testes usam tokens fictícios, sem credenciais de produção.
