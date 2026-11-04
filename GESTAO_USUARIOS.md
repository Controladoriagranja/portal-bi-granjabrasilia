# Gestão delegada de usuários

Implementação local; nenhuma migração, concessão ou publicação foi executada.

## Publicar na ordem

1. No SQL Editor do Neon, no banco do Portal, executar inteiro
   `api/migrations/20261104_gestao_usuarios.sql`. Se ocorrer erro, executar
   `ROLLBACK;` e resolver antes de publicar. A migração é transacional e reaplicável;
   não muda perfis, senhas, permissões ou bloqueios dos usuários existentes.
2. Render do Portal: publicar juntos `api/app.py`, `api/operation_permissions.py`
   e o novo `api/user_management.py`, preservando os demais arquivos do backend.
3. GitHub Pages: publicar `index.html` e `assets/js/user-management.js` juntos.
4. Como Admin, abrir Usuários → Editar a conta escolhida → Permissões de operações
   → marcar **Administrador TI** → salvar. É possível criar uma conta Setor sem
   setores/relatórios quando esta permissão estiver marcada. Não é necessário SQL
   individual para conceder a função.

Esta etapa não exige publicar Worker, API do Anderson ou frontend dos BIs.
Não há mudanças de `.env`, dependências novas ou autenticação separada.

## Comportamento

- Um Admin mantém todas as funções existentes e pode fazer as ações delegadas sem
  marcar a nova permissão.
- Para quem não é Admin, `usuarios.gerenciar` torna o acesso exclusivo à gestão
  de usuários, além de Trocar Senha/Sair. Setores/vínculos antigos não são apagados,
  mas não liberam os BIs enquanto esta função exclusiva estiver concedida.
- A conta é criada e configurada exclusivamente no cadastro normal do Admin,
  com a flag **Administrador TI**. Não existe formulário separado de criação
  nesta tela. O Administrador TI não cria contas, nem chamando a API diretamente,
  não edita cadastros, reseta senhas ou concede sua função a terceiros.
  A permissão interna `usuarios.gerenciar` foi reaproveitada: os vínculos existentes
  permanecem válidos, sem nova coluna, flag de banco ou migração para esta correção.
- O operador pode bloquear/desbloquear qualquer usuário, inclusive qualquer Admin.
  O bloqueio de Admin exige confirmação explícita no navegador e no corpo da API.
  **Não existe proteção do último Admin ativo**, conforme solicitado. O próprio
  Admin pode bloquear a si mesmo; a tela encerra sua sessão após a resposta.
- A exclusão de Admin está desabilitada por enquanto, para ambos os atores. O
  aviso explica que deve ser utilizado o bloqueio. Exclusão da própria conta
  também não é permitida.
- Excluir uma conta comum é uma exclusão lógica: registra `excluido_em`, bloqueia
  o acesso e retira a conta da lista principal. Não apaga chamados, arquivos do
  Drive, recibos de anexos, históricos ou permissões que precisem de conferência.
- Somente Admin pode usar **Mostrar excluídos** e **Restaurar**. A restauração
  mantém a conta bloqueada até reativação explícita. O e-mail de uma conta excluída
  continua reservado; restaure essa conta em vez de criar duplicata.
- A restrição também ocorre no backend, inclusive para URLs chamadas manualmente.
  Tokens continuam sendo os do Portal e as permissões são relidas a cada requisição.
  APIs externas recebem acesso comercial `none` e nenhum perfil privilegiado para
  uma conta de gestão exclusiva. Admin normal não perde suas funções existentes.

## Auditoria

Tabela: `public.auditoria_usuarios`. O botão de consulta e o painel de logs
foram retirados da tela. Os registros de auditoria e a consulta administrativa
existente na API foram preservados; nenhuma consulta é disparada pela interface.

Campos incluem ID/nome/e-mail do autor e do usuário afetado, ação, data/hora,
origem, usuário SQL e estado anterior/posterior dos campos permitidos. Não inclui
senhas, hashes, tokens, anexos ou o corpo da requisição.

O trigger no banco registra criação, bloqueio, desbloqueio, exclusão lógica,
restauração, alterações cadastrais e mudanças de senha. Ações dos Admins também são
registradas. Não há reconstrução dos eventos anteriores à migração. Uma exclusão
física realizada futuramente por SQL também gera log, que não possui FK para a conta.

As ações do Portal passam o contexto autenticado dentro da transação. SQL manual
sem esse contexto é identificado como origem `banco`, com `usuario_sql`; não é
atribuído indevidamente a uma pessoa do Portal. Se a inserção da auditoria falhar,
a alteração do usuário é cancelada na mesma transação.

Não há polling de auditoria ou listagem. O log é escrito nas ações e consultado
somente por solicitação. Os detalhes de erros SQL não são impressos com parâmetros
de senha nos logs dos endpoints de usuários.

## Recuperar um Admin sem outra conta de gestão ativa

Um gestor de usuários ativo também pode desbloquear Admin pelo Portal. Se não
restar nenhum Admin ou gestor ativo com essa autorização, usar o Neon:

No SQL Editor, conferir qual conta será recuperada:

```sql
SELECT id, nome, email, ativo
FROM public.usuarios
WHERE role = 'admin' OR perfil = 'admin'
ORDER BY id;
```

Substituir `ID_CONFIRMADO` pelo ID escolhido e executar:

```sql
UPDATE public.usuarios
SET ativo = TRUE, atualizado_em = NOW()
WHERE id = ID_CONFIRMADO AND excluido_em IS NULL
  AND (role = 'admin' OR perfil = 'admin')
RETURNING id, nome, email, ativo;
```

Essa recuperação também gera auditoria de origem `banco`. Não altera senha ou perfil.

## Verificação

Testes locais usam Flask/banco simulados e Chrome com HTTP bloqueado. Validam
negação de escalada de privilégios, bloqueio do último Admin, confirmação obrigatória,
exclusão protegida, preservação do histórico, restauração, leitura dos logs só por
Admin e rollback quando a auditoria falha. O navegador usa o HTML real com API
simulada, incluindo largura de celular, menus e avisos, sem endpoints reais.
Nesta entrega passaram 72 testes unitários/de regressão (33 de gestão/Comercial,
14 do cadastro canônico e 25 do formulário zootécnico), além de 34 verificações
desktop e verificações de navegação/largura mobile no Chrome offline.

Ainda requer validação após a implantação manual: executar o trigger no Neon real
com o papel utilizado pelo Render e testar uma ação do Portal conferindo o autor
na tabela. Não testar o bloqueio de todos os Admins sem ter o SQL Editor acessível.
Nenhum desses testes em produção foi executado pelo assistente.

## Nova modificação de 04/11/2026 — Administrador TI

Retirados o cadastro separado e a consulta de logs. A flag Administrador TI fica
no cadastro/edição normal de usuários, reaproveitando a permissão já existente.
Criação de contas é exclusiva do Admin no fluxo normal; a API também recusa
criação por Administrador TI. Nenhuma conta foi criada ou alterada neste trabalho.
Publicar `index.html`, `assets/js/user-management.js`, `api/app.py` e
`api/user_management.py`. Esta correção não exige nova migração, Worker ou Anderson.
Os pré-requisitos da implantação original permanecem aplicáveis, se ainda pendentes.
