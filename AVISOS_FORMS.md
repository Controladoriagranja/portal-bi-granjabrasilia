# Avisos de novas respostas do Forms por e-mail

Remetente: **controladoriagb05@gmail.com**. Essa conta deve criar e autorizar o gatilho.
Destinatários: asalvino@granjabrasilia.com.br, bantunes@granjabrasilia.com.br e
vchaves@granjabrasilia.com.br, todos no campo Para.

Somente respostas novas do Forms. Sem polling, Render, Neon, alteração de células,
reenvio do histórico ou mudança no aplicativo de upload do Drive.

## Campos por seção

Os índices são validados pelos cabeçalhos, inclusive as duas colunas E-mail.

| Parte | Colunas | Dados |
| --- | --- | --- |
| Sempre | A–F | Data/hora, autor, e-mail do solicitante, telefone, setor e tipo |
| Ajuste | G–J | BI/tela, tipo de ajuste, descrição e referência de anexos informada |
| Melhoria | K–L | BI/tela e descrição |
| Novo usuário | M–O | Nome e e-mail do novo usuário e relatórios solicitados |

**A coluna P não é usada.** Campos de outras seções ficam fora do e-mail, mesmo
quando contêm valores. O solicitante é B/C; os dados do novo usuário são M/N.
Anexos de J são apenas texto/referências existentes na resposta, sem baixar arquivos.
Os arquivos enviados pelo portal diretamente ao Drive não são vinculados ao Forms
automaticamente e não são anexados a esses e-mails.

O layout inicial tem título e tabela simples em HTML, com alternativa em texto.
Texto digitado no Forms é escapado; não vira HTML ou destinatário de e-mail.
Prévia com dados fictícios: [exemplo-email.html](integrations/forms_notifications/exemplo-email.html).

## Ativar quando o layout estiver aprovado

1. Entre no Google com **controladoriagb05@gmail.com** e abra a planilha de respostas:
   https://docs.google.com/spreadsheets/d/1mCLD88B_986zsZ16aDEFMK2RNhXKafMfuB99wWebe9k/edit
2. Na planilha, abra **Extensões → Apps Script**. Use o projeto vinculado à planilha,
   separado do aplicativo de upload do Drive. Se já houver código, preserve-o e
   crie um novo arquivo chamado `NotificacoesForms`.
3. Cole [NotificacoesForms.gs](integrations/forms_notifications/NotificacoesForms.gs)
   e salve. Não precisa criar implantação, URL `/exec`, segredo ou variável no Render.
4. No seletor de funções, escolha **configurarAvisosForms** e clique em **Executar**.
   Autorize os serviços solicitados usando o Gmail remetente. Isso cria o gatilho
   **Da planilha → Ao enviar formulário**. Não envia e-mail nem percorre respostas antigas.
5. A partir daí, uma nova resposta pelo Forms gera um aviso para os três endereços.
   Não execute `avisarNovaSolicitacaoForms` manualmente; ela exige o evento do Forms.

Se a configuração for executada novamente, reaproveita o gatilho existente criado
por essa conta no mesmo projeto. Não crie outro gatilho manual ou em outro projeto.
O script não altera nem exclui gatilhos de outras funções.

## Controle e limites

- A função valida conta remetente, planilha, aba de respostas e cabeçalhos antes de enviar.
- Gatilhos são executados como a conta que os criou; não é preciso senha no código.
- Os últimos 100 envios ficam registrados nas propriedades do Apps Script para
  impedir duplicações normais. Nada é escrito na planilha ou no Neon.
- Não há transação única entre envio de e-mail e registro nas propriedades: uma
  interrupção exatamente entre essas operações pode exigir conferir duplicação.
- O Gmail pessoal tem cota do Apps Script de 100 destinatários/dia. Três por aviso
  permitem até 33 avisos, descontados outros envios da conta. O código verifica o
  saldo antes de enviar. Sem saldo ou em caso de erro, consultar **Execuções** no
  Apps Script; não há fila ou reenvio automático nesta versão.
- A notificação considera todas as respostas novas do Forms; não consulta cadastro
  ou login do portal. A importação para chamados continua com suas regras próprias.

Referências: [gatilhos instaláveis](https://developers.google.com/apps-script/guides/triggers/installable),
[cotas](https://developers.google.com/apps-script/guides/services/quotas).

## Estado da entrega

Código local e layout provisório para revisão. Nenhum gatilho foi instalado pelo
Codex e nenhum e-mail real foi enviado. Os testes usam serviços Google simulados:
`node tests/forms_notifications_script.js`, com 53 verificações de remetente,
destinatários, três seções, exclusão de P, duplicações, cota e escape de HTML.
