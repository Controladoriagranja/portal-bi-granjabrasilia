# Ativar anexos do portal no Google Drive

Pasta já configurada no código:
https://drive.google.com/drive/folders/1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW

Preparado localmente. Nenhum envio real, migração ou deploy foi executado.

## 1. Autorizar o envio no Google

1. Abra https://script.google.com/ com uma conta que possa **editar** essa pasta.
2. Clique em **Novo projeto** e dê o nome `Anexos Portal BI Granja`.
3. Substitua o conteúdo do arquivo `Código.gs` pelo conteúdo de
   [integrations/drive_upload/Code.gs](integrations/drive_upload/Code.gs). Salve.
   A pasta já está preenchida. Não crie gatilhos/agendamentos.
4. Gere um segredo privado no PowerShell do seu computador:

   ```powershell
   [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
   ```

   Guarde o resultado para os dois locais abaixo. Não o coloque no HTML, GitHub,
   planilha, código do Apps Script nem nesta conversa.
5. Na engrenagem **Configurações do projeto → Propriedades do script**, adicione
   `PORTAL_DRIVE_UPLOAD_SECRET`, com esse segredo no valor.
6. Clique em **Implantar → Nova implantação → Aplicativo da Web**.
   Selecione **Executar como: Eu** e **Quem tem acesso: Qualquer pessoa**.
   O servidor precisa chamar esse endereço; sem assinatura válida, o script
   rejeita o envio antes de acessar a pasta.
7. Clique em **Implantar**, autorize o acesso do seu projeto ao Drive e copie a
   URL que termina em `/exec`. A conta precisa autorizar a criação de arquivos.
   Se a organização não oferecer a opção “Qualquer pessoa”, informe isso.

Não precisa de chave de API Google nem de conta de serviço. Esse segredo protege
apenas a comunicação **servidor → Apps Script**. [Documentação do Google](https://developers.google.com/apps-script/guides/web).

## 2. Preparar e publicar o portal

Passos manuais, ainda não executados:

1. No SQL Editor do Neon da CENTRAL, executar uma vez, nesta ordem:
   - [api/migrations/20261030_forms_import.sql](api/migrations/20261030_forms_import.sql),
     caso ainda não tenha sido aplicada;
   - [api/migrations/20261030_drive_attachments.sql](api/migrations/20261030_drive_attachments.sql).
   São tabelas de recibos; login/bootstrap não dependem delas. Use o banco correto.
2. No serviço do backend em **Render → Environment**, adicionar:

   | Variável | Valor |
   | --- | --- |
   | `PORTAL_DRIVE_UPLOAD_URL` | URL `/exec` abaixo, fornecida pelo proprietário |
   | `PORTAL_DRIVE_UPLOAD_SECRET` | Mesmo segredo das propriedades do script |

   Valor de `PORTAL_DRIVE_UPLOAD_URL`:

   ```text
   https://script.google.com/macros/s/AKfycbyT5CsYzGP2NjaPJBBaCuTXVwlwkYJhcTGKXD3cP6dYbxrsI0iG1_FqWIGx1JlDVUSUCg/exec
   ```

   Endereço recebido em 30/10/2026; autorização e envio real ainda não foram
   conferidos. O segredo deve ser cadastrado diretamente no Render, não no arquivo.

   Não substitua as configurações/credenciais existentes.
3. Publicar juntos `api/app.py`, `api/forms_import.py` e `api/drive_attachments.py`
   no backend. Publicar o `index.html` no GitHub Pages. O `.gs` deve estar
   implantado no Google conforme a etapa 1.
4. Para futuras alterações no `.gs`: **Gerenciar implantações → Editar → Nova versão**,
   mantendo a URL `/exec` original.

Sem configuração válida, somente os anexos ficam indisponíveis. O Forms e a
importação continuam no fluxo existente.

## 3. Como usar

1. Entrar no portal e abrir **Dados & Power BI — Chamados**.
2. Preencher e **enviar** o Forms. Nome/e-mail vêm preenchidos; setor só quando há
   um único setor liberado. Os campos do Google continuam editáveis.
3. Clicar em **Anexar arquivos**. A solicitação importada aparece no seletor.
   Se necessário, usar **Verificar envio do formulário** e aguardar o Google.
4. Conferir número/título, selecionar até 5 arquivos (10 MB cada) e clicar em
   **Enviar anexos**. Aguardar a confirmação.
5. Os links aparecem na confirmação e nos anexos do chamado para a equipe que já
   acessa a listagem. Usuários comuns continuam sem carregar essa lista.

Nome dos arquivos: nome oficial do cadastro, data/hora de início do envio em
Brasília, identificador único e nome original, por exemplo:
`Pessoa_2026-10-30_15-42-18_<identificador>_print.png`.

O login do portal autoriza o **envio**. Para **abrir** arquivos privados, a conta
Google do leitor precisa ter permissão na pasta. Para evitar anexos públicos,
deixe **Acesso geral: Restrito** e conceda leitura à equipe necessária. O código
não altera compartilhamentos ou permissões da pasta.

## Garantias e limites

- Nenhuma escrita na planilha ou alteração do Forms. Upload separado, posterior
  à importação e vinculado ao pedido escolhido.
- Somente usuário autenticado, ativo e solicitante do pedido pode anexar. O pedido
  deve ter sido importado do Forms na janela do login atual. Sem upload anônimo
  na tela de login ou envio para pedidos de outros usuários.
- Conta e titularidade revalidadas antes e depois da chamada ao Drive.
- Neon guarda recibos/metadados/links. Bytes/base64 não vão ao banco, localStorage
  ou cache offline. Nenhuma transação SQL fica aberta durante o upload HTTP.
- Envio sequencial por navegador e limites também no servidor e no Google.
  Nenhum polling ocioso, gatilho ou serviço adicional.
- Repetir mesmo arquivo/nome no mesmo chamado reaproveita o recibo. Se uma resposta
  HTTP se perder, repetir recupera o arquivo pelo nome estável. Reservas incompletas
  deixam de ocupar vagas após dois minutos, sem temporizador ou consultas de rotina.
- Drive e PostgreSQL não têm transação conjunta. Se a confirmação no banco falhar,
  tente novamente com o mesmo arquivo. Exclusão do chamado, bloqueio do usuário ou
  perda de permissão durante o envio podem deixar arquivo sem vínculo concluído.
  Não há exclusão automática; a equipe pode conferir a pasta pelo nome/horário.
- Anexos do Drive são preservados ao salvar cópias antigas de chamados e abrem em
  nova aba. Excluir esses arquivos pelo portal não faz parte desta etapa. Anexos
  legados, que guardavam somente metadados, mantêm o comportamento anterior.
- Armazenamento/cotas são os da conta Google. Nenhum serviço pago foi contratado.

## Testes e conferência real

Somente testes locais, com mocks/AST e Chrome com rede externa bloqueada:

- `py -B tests/test_drive_attachments.py`: autenticação, titularidade, identidade,
  tamanho, assinatura, repetição, falhas e transações fechadas durante o HTTP.
- `node tests/drive_upload_script.js`: Apps Script com Drive simulado, assinatura
  inválida/expirada, hash/tamanho/pasta e repetição sem duplicar.
- `py -B tests/test_forms_import.py` e `node tests/forms_import_client.js`:
  regressão da importação e autenticação sem acesso externo.
- `py -B tests/test_tickets_forms_browser.py`: perfis, ausência da lista para comum,
  multipart simulado, logout e celular/tablet/PC.
- Regressão curta de permissões/escopo, sintaxe JavaScript e `git diff --check`.

Pendentes: autorização do Google, implantação `/exec`, migrações, variáveis no
Render, publicação e um envio real acompanhado. Safari/iOS e PWA precisam de
conferência nos dispositivos após publicar; responsividade local testada no Chrome.
