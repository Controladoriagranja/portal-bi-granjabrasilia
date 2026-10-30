# Anexos simples: portal → Google Drive

Pasta: https://drive.google.com/drive/folders/1snZ6yjFvgoXidSdzXc5OnjCcIfmSK6mW

## Fluxo atual

1. Entrar no portal e abrir Dados & Power BI — Chamados.
2. Clicar em Anexar arquivos e escolher até 5 arquivos, de até 10 MB cada.
3. Clicar em Enviar anexos e aguardar a confirmação.
4. Abrir os links exibidos ou consultar os arquivos diretamente na pasta.

Não precisa selecionar chamado, aguardar importação do Forms ou ter recibo de
anexo no banco. Os arquivos recebem o nome oficial do cadastro, carimbo de data/hora
do servidor em Brasília, identificador único e nome original, por exemplo:
`Pessoa_2026-10-30_15-42-18_<identificador>_print.png`.

**Os arquivos não são vinculados automaticamente aos chamados nesse fluxo simples.**
A confirmação e os links ficam na tela até sair dela; os arquivos continuam no Drive.
O Forms continua independente, com nome/e-mail preenchidos e setor quando há apenas
um setor liberado. O botão Verificar envio do formulário mantém a importação manual.

## Neon e planilha

- O NOVO envio direto não grava arquivos, recibos ou metadados no Neon.
- A autenticação atual continua consultando o Neon para validar usuário ativo,
  bloqueios e permissões. Não foi criado cache de autenticação.
- Importar respostas do Forms para a lista continua gravando chamados/histórico no
  Neon, como antes. Isso é separado do envio dos arquivos.
- O portal não escreve na planilha nem altera o Google Forms.
- Não há SQL novo para executar nesta revisão. As tabelas que você já criou podem
  permanecer. A tabela de importação continua necessária para importar chamados.
- As rotas legadas de anexos vinculados e os arquivos já associados são preservados
  por compatibilidade. O frontend novo usa somente `/attachments/direct` para enviar.

## O que publicar agora

Você informou que já implantou o Apps Script e criou as variáveis. Para esta revisão:

1. Publicar juntos `api/app.py` e `api/drive_attachments.py` no backend, mantendo
   `api/forms_import.py` existente. Publicar o `index.html` no GitHub Pages.
2. O `integrations/drive_upload/Code.gs` não mudou; não precisa nova implantação no
   Google se a implantação atual já contém esse arquivo.
3. Manter no backend do Render:

| Variável | Valor |
| --- | --- |
| `PORTAL_DRIVE_UPLOAD_URL` | URL `/exec` abaixo |
| `PORTAL_DRIVE_UPLOAD_SECRET` | Mesmo segredo das propriedades do Apps Script, pelo menos 32 caracteres |

```text
https://script.google.com/macros/s/AKfycbyT5CsYzGP2NjaPJBBaCuTXVwlwkYJhcTGKXD3cP6dYbxrsI0iG1_FqWIGx1JlDVUSUCg/exec
```

Não coloque o segredo no HTML, GitHub, planilha ou conversa. O endereço da pasta
não substitui a autorização de escrita do Google. O Apps Script existente executa
com a conta autorizada e recebe solicitações assinadas do backend. Não exige chave
de API Google nem conta de serviço.

Para referência, a implantação original é Aplicativo da Web, Executar como: Eu,
Quem tem acesso: Qualquer pessoa; propriedade do script `PORTAL_DRIVE_UPLOAD_SECRET`
igual à variável do Render. A conta da implantação precisa poder editar a pasta.
[Documentação do Google](https://developers.google.com/apps-script/guides/web).

O código não altera os compartilhamentos da pasta. Abrir os links depende das
permissões que você já configurou no Drive.

## Se aparecer indisponível

- Agora há um botão Verificar conexão que pode ser usado novamente sem logout.
- A seleção local de arquivos continua habilitada mesmo se a primeira conexão falhar.
- Para admin, a tela identifica URL ausente/inválida, segredo ausente/curto ou backend
  que ainda não foi atualizado, sem exibir valor de segredo.
- O status autenticado é `GET /api/chamados/google-forms/attachments/status`.
  Retorna apenas motivo de configuração e contexto assinado; não consulta Drive ou
  tabelas de recibos. Não compartilhe o campo `context`.
- O botão Enviar anexos tenta preparar a conexão novamente; uma falha inicial não
  trava o componente até recarregar a página.

## Reenvios e limites

O nome vem do cadastro autenticado, não de um campo editável enviado pelo navegador.
O carimbo é assinado no servidor ao preparar o envio. A tentativa mantém contexto,
identificador e nome estáveis para recuperar um envio cuja resposta se perdeu.
Mudar usuário ou conteúdo produz identificadores diferentes. A seleção fica só na
memória da aba e é limpa ao sair da tela ou fazer logout; o portal não armazena os
arquivos no banco, localStorage ou cache offline. Depois de recarregar a página,
um novo envio é uma nova operação e pode criar outra cópia.

O cliente envia um arquivo por vez. O servidor e o Apps Script também limitam cada
arquivo a 10 MB. O limite de 5 arquivos é por seleção no navegador. Sem recibo no
banco, não há limite acumulado por chamado. Não há gatilhos, polling ocioso, serviços
novos ou alteração do modelo de autenticação. Armazenamento/cotas são os da conta Google.

## Verificação

Somente testes locais com mocks/AST e Chrome com tráfego externo bloqueado: contexto
assinado, identidade, limites, nome/carimbo estáveis, nenhuma transação ou escrita
no envio direto, recuperação após falha, logout, links e layout de celular/tablet/PC.
A integração da planilha e a visibilidade por perfil continuam cobertas por regressão.

Esta revisão não fez deploy, consultas reais ao Neon nem upload real ao Google.
Falta conferir o envio após publicar. Safari/iOS e PWA precisam de conferência nos
dispositivos; o teste local de responsividade foi em Chrome.
