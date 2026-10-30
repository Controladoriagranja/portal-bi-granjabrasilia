# Google Forms → Chamados por CSV público

A integração usa diretamente o CSV da planilha compartilhada:
https://docs.google.com/spreadsheets/d/1mCLD88B_986zsZ16aDEFMK2RNhXKafMfuB99wWebe9k/export?format=csv

**Não exige Apps Script, chave da API Google, segredo adicional ou novo serviço.**
O endpoint público foi conferido uma vez e retornou CSV com os 16 cabeçalhos informados.
Apenas cabeçalhos e formato de data foram exibidos na verificação.

## Mão única: planilha → portal

A API faz somente HTTP GET no endereço fixo, sem cookies, Bearer ou corpo de escrita.
Editar status, prioridade, responsável ou excluir chamados no portal não altera
células, respostas ou abas. O envio do próprio Google Forms continua registrando
respostas pelo Google, como antes. A URL pública pode ser lida por quem possui o
link, conforme autorizado pelo usuário; isso não publica credenciais do Portal/Neon.

## Regras mantidas

- Cada importação exige a sessão original do próprio solicitante e usuário ativo.
  Admin também importa apenas respostas do próprio e-mail; a lista admin continua global.
- O primeiro E-mail (coluna C) deve corresponder ao e-mail da sessão. O segundo
  E-mail (coluna N) é somente dado de um pedido de acesso; não autentica ninguém.
- O carimbo deve ser posterior ao início assinado daquele login. Respostas anteriores
  ou de outro e-mail são ignoradas. Não é uma importação em lote do histórico.
- A API valida novamente ID/e-mail/usuário ativo antes da gravação, sem aceitar
  identidade ou linhas enviadas pelo navegador. O contexto usa salt separado,
  hash do login e expiração; não pode ser usado como token de acesso ao Portal.
- Os chamados chegam em `awaiting_manager`, prioridade Média, sem criar usuários,
  conceder acessos, aprovar solicitações ou atribuir responsável/datas automaticamente.
- Os detalhes de ajuste, melhoria e pedido de usuário são copiados como texto com
  seus rótulos. As referências de anexos são texto; o importador não baixa arquivos do Drive.
- Os perfis comuns continuam somente com Forms e sem leitura da lista de chamados.

O CSV preserva as duas colunas E-mail por posição. Os 16 cabeçalhos são conferidos.
O formato verificado foi `29/10/2026 17:46:39`, interpretado no fuso de Brasília
(`America/Sao_Paulo`; fallback UTC-03 em Windows sem base IANA). Não altera o fuso
nem a formatação da planilha. A aba padrão exportada atualmente tem os cabeçalhos
corretos; se a estrutura ou a aba mudar, conferir a leitura antes de continuar.

## Preenchimento no Forms

Na tela autenticada de Chamados, a URL incorporada preenche o Nome e o primeiro
E-mail com o cadastro do usuário logado. Os identificadores foram conferidos no
formulário público: `entry.431207813` (Nome), `entry.1258827024` (E-mail do solicitante)
e `entry.1132196072` (Setor). O E-mail do usuário solicitado, `entry.455859597`, fica
sem preenchimento automático. Nenhum token ou senha é colocado na URL do Google.

Quando existe um único setor liberado no cadastro, seu rótulo preenche o Setor.
Quando existem vários, o campo fica em branco, conforme definido pelo usuário:
os setores cadastrados são permissões de relatórios, não um departamento pessoal.
Outro usuário/login recarrega o iframe, evitando dados da sessão
anterior. No botão público da tela de login não há identidade autenticada para preencher.

O pré-preenchimento não envia respostas nem modifica a planilha. Os campos do
Google continuam editáveis; a API mantém a validação da identidade na importação.
O formulário público conferido não contém pergunta de upload. Ativar upload no
Google exige alterar o próprio formulário; o HTML do portal não cria perguntas no
iframe. O código legado de anexos do portal guarda nome/tamanho, não o arquivo.
Destino definido: upload pelo portal para pasta no Google Drive, com nome da
pessoa e data/hora. O fluxo simples é independente da importação, não exige selecionar
chamado e não grava recibos/metadados de anexos no Neon. Os arquivos ficam na pasta,
sem vínculo automático com a lista. Instruções em [ANEXOS_DRIVE.md](ANEXOS_DRIVE.md).
Não houve envio real de arquivos pelo Codex.

"Logado" segue o modelo de autenticação já existente: token válido, não expirado e
usuário ativo, verificados na requisição. O logout é stateless. O e-mail no Forms
é autodeclarado; cruzá-lo com o login não prova quem digitou a resposta no Google.
Uma prova do ato de envio exigiria alterar o Forms/formulário; isso não foi feito.

## Atualização e duplicações

A checagem é automática ao abrir/retornar ao Forms. Novos carregamentos do iframe
fazem até três tentativas limitadas para tolerar o atraso de gravação no Google.
Não há polling ocioso, agendador ou consultas globais em segundo plano. Ocultar
aba, sair da tela ou fazer logout cancela pedidos/timers. Se o Google demorar mais
que as tentativas, voltar à tela/aba provoca outra checagem. O iframe, por ser de
outra origem, não oferece confirmação direta de envio ao código do Portal.

A API não mantém transação SQL aberta durante o GET do CSV. O download é limitado
a 1 MB e 100 respostas do solicitante dentro da sessão. O recibo é gravado na mesma
transação do chamado/histórico, sem sobrescrever registros existentes. Permanece
após excluir o chamado, evitando que uma nova leitura o recrie. A numeração de novos
chamados é serializada entre importação e criação normal.

A origem não fornece ID de resposta. A chave usa planilha, aba lógica padrão,
carimbo e primeiro e-mail. Duas respostas do mesmo e-mail com o mesmo carimbo exibido
(no CSV verificado, precisão de segundos) são consideradas a mesma origem.
Não apagar os recibos para "limpar fila". Outros admins usam o Atualizar já existente
para ver novidades; ao voltar do Forms, a lista do admin é recuperada normalmente.

## Para ativar — somente dois passos

1. Executar manualmente `api/migrations/20261030_forms_import.sql` no banco CENTRAL.
   Cria apenas a tabela de recibos; não muda usuários nem chamados existentes.
2. Publicar `api/app.py` e `api/forms_import.py` juntos no Render e o `index.html`
   no GitHub Pages. Recarregar o Portal.

Nenhuma chave/configuração Google é necessária. A leitura vem habilitada no código
novo. A variável opcional `PORTAL_FORMS_IMPORT_ENABLED=false` serve apenas para
pausar; se ela já tiver sido definida como false, alterar para true para ativar.
As variáveis `PORTAL_FORMS_READER_URL` e `PORTAL_FORMS_READER_SECRET` não são usadas.
A autenticação normal continua usando a configuração de segurança que o Portal já tem.

**Migração antes da publicação.** A tabela nova é usada apenas na importação;
login, bootstrap e relatórios não passam a depender dela. Sem a tabela, a gravação
do Forms falha sem confirmar lote parcial, mas o login continua independente.
Não foi executada migração, publicação ou escrita real no Neon/planilha.

## Verificações locais

- `py -B tests/test_forms_import.py`: CSV por GET sem credenciais, formato brasileiro,
  dois E-mails, sessão, datas, duplicações, exclusão, bloqueio e rollback, com mocks.
- `node tests/forms_import_client.js`: cliente real do HTML com DOM/API/relógio falsos.
- `py -B tests/test_tickets_forms_browser.py`: perfis e responsividade no Chrome local,
  com toda a rede externa bloqueada e formulário simulado.
- `git diff --check` e compilação do JavaScript completo.

A leitura pública foi confirmada. A escrita no Neon, permissões da tabela de recibos,
a publicação do backend e o fluxo completo com nova resposta real continuam pendentes.
