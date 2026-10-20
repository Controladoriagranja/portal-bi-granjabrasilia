# Permissões de operações da CENTRAL

Primeira operação: `comercial.frete.editar`. A concessão apenas habilita a verificação
futura da escrita; esta entrega não implementa gravação de frete, Worker, FastAPI,
writer, nem modifica tabelas do Anderson.

## Arquivos e estrutura

- `api/operation_permissions.py`: catálogo, validação, substituição transacional e
  verificador reutilizável `has_operation_permission(usuario_autenticado, codigo)`.
- `api/migrations/20261020_operation_permissions.sql`: migração manual independente
  de `20261019_commercial_access.sql`. Não foi executada.
- `api/app.py`: leitura no login/autenticação/snapshot e gravação pelos CRUDs atuais.
- `index.html`: seção Permissões de operações nos dois formulários administrativos.
- `tests/test_operation_permissions.py` e `tests/operation_permissions_frontend.js`:
  testes offline com AST, transações, DOM e API simulados.

`public.usuario_operacoes` usa PK `(usuario_id, permissao)`, FK para
`public.usuarios.id`, exclusão em cascata e data da concessão. Não referencia
legacy_id, nome ou e-mail. A PK também atende às leituras por usuário. Sem linha,
não existe autorização. Novas operações exigem adicionar o código ao catálogo e
a opção administrativa, sem criar coluna ou alterar a tabela.

Usuários bloqueados/inativos não autenticam; concessões são conservadas para a
administração, mas ficam ineficazes enquanto `ativo=false`. Admin/Diretor não
recebem escrita por perfil, setor, `allow_updates`, acesso geral ou relatório.

## Concessão e revogação

Como **administrador autenticado**, abrir Gerenciar Usuários → criar/editar →
Permissões de operações → Comercial → marcar/desmarcar **Editar fretes** e salvar.
Diretor e usuários comuns não administram concessões, inclusive por HTTP manual.

Os contratos atuais permanecem. Campos adicionais em POST `/api/admin/usuarios`,
PATCH `/api/admin/usuarios/<id permanente>` e nos itens `users` do PUT `/api/portal-data`:

```json
{"operationPermissions": ["comercial.frete.editar"]}
```

Lista vazia `[]` revoga todas as operações. Campo ausente preserva concessões de
usuários existentes; usuário novo começa sem elas. `null`, tipo incorreto, duplicatas
ou códigos desconhecidos produzem 400. Os exemplos mostram apenas o campo novo:
os demais campos obrigatórios do cadastro continuam necessários. O PATCH existente
continua exigindo o cadastro, não é um endpoint novo de atualização parcial arbitrária.

Cadastro, relações e concessões usam a mesma transação; falha nas concessões desfaz
também o cadastro. A linha do usuário é bloqueada durante substituições de operações
para serializá-las. Em edições simultâneas explícitas, prevalece a última gravação;
não há controle de versão do formulário nesta etapa.

O frontend envia operações explicitamente ao criar/salvar o modal. Aprovação, bloqueio
e outros PATCHs as omitem. O PUT genérico de outras telas remove esse campo do snapshot
enviado, evitando reenviar cache de concessões. Clientes antigos que o omitem também
preservam as permissões. Clientes que enviem uma lista antiga explicitamente ainda
podem substituí-las; devem respeitar esse contrato.

## Identidade e contrato para Worker/FastAPI

GET `/api/auth/me`, com `Authorization: Bearer <token CENTRAL>`, retorna todos os
campos atuais e acrescenta `user.operationPermissions`. Exemplo **ilustrativo**, sem
criar usuário (o ID real é inteiro e vem de `public.usuarios.id`):

```json
{
  "ok": true,
  "user": {
    "id": 123,
    "name": "<nome cadastrado>",
    "nome": "<nome cadastrado>",
    "email": "<email cadastrado>",
    "perfil": "setor",
    "role": "sector",
    "ativo": true,
    "isAdmin": false,
    "dataAccess": {"mode": "none"},
    "commercialAccess": {"mode": "none"},
    "operationPermissions": ["comercial.frete.editar"]
  }
}
```

A autenticação mantém assinatura/expiração e busca o usuário ativo no banco. As
concessões são lidas junto com a consulta existente, sem nova consulta HTTP, timer
ou cache de permissões. A revogação vale na próxima autenticação da requisição.
`/me` retorna `Cache-Control: no-store`; falha de banco nunca vira concessão.

Na etapa futura, a API que efetivamente grava deve, para **cada operação**:

1. Receber o token CENTRAL e consultar `/api/auth/me` na URL confiável da CENTRAL.
   Não basta o Worker dizer que autorizou; a API de gravação também precisa validar.
2. Exigir HTTP 200, `ok=true`, `ativo=true`, ID permanente válido e presença exata
   de `comercial.frete.editar`. Ausência, 401/403, erro ou timeout negam a escrita.
3. Obter a identidade e permissões dessa resposta, nunca de JSON, e-mail, ID,
   cabeçalho de permissões enviado pelo navegador ou conteúdo não verificado do token.
4. Validar separadamente a unidade e o registro alvo; só então gravar com parâmetros
   SQL e demais regras do negócio. Não usar `isAdmin`, `general` ou setor como bypass.

Dentro da CENTRAL, `has_operation_permission` recebe somente o usuário carregado
pela autenticação existente. Fora dela, usa-se `/me`; não há segunda identidade,
nova chave compartilhada, endpoint de escrita de frete ou cache de autorização.

## Lacuna de alcance por unidade

O mecanismo real em `api/commercial_access.py` descreve alcance de dados:
`none`, `general`, `supervisor` e `seller`, com código do vínculo nos dois últimos.
`commercialAccess` e `dataAccess` são aliases preservados. Admin/Diretor continuam
com visão geral dos relatórios. Setores, páginas e relatórios também são mantidos.

Nenhum desses campos define uma lista confiável de unidades autorizadas para escrita.
Não foi encontrada ACL de unidades na CENTRAL inspecionada. A API do Anderson deverá
obter o vínculo por unidade de uma fonte confiável, relacionado ao ID CENTRAL, e
conferir no servidor a unidade do registro alvo. Vendedor/supervisor não equivalem
a autorização por unidade. Até definir essa regra, a futura gravação deve negar
pedidos sem autorização de unidade, inclusive para quem possui a operação.

## Implantação e riscos

1. Conferir e executar manualmente a migração nova no Neon existente. Preservar a
   migração comercial anterior. Confirmar que o papel já usado pela aplicação tem
   SELECT/INSERT/DELETE na tabela nova; não ampliar privilégios indiscriminadamente.
2. Publicar backend com `operation_permissions.py` e `app.py` juntos.
3. Publicar `index.html` e recarregar as abas administrativas.
4. O administrador concede somente aos usuários autorizados. Sem concessão, a lista
   é vazia para todos, inclusive Admin/Diretor.

**Não publicar backend antes da migração**: autenticação e snapshot passam a consultar
a tabela nova; sem ela falham. Frontend novo com backend antigo pode aparentar salvar
sem persistir o campo. A migração é aditiva, compatível com o backend anterior; em
rollback, manter a tabela e as concessões. Não executar DROP para desfazer publicação.

Não foi acessado o Neon, Render, APIs ou compartilhamentos, nem executados robôs,
migrações, commit ou deploy. Os testes não validam o SQL em PostgreSQL real, privilégios
do papel de produção ou integração entre serviços futuros. A alteração acrescenta uma
busca indexada à consulta já existente; não cria consumidores periódicos do Neon.

Verificações locais realizadas: 15 testes em `py -B tests/test_operation_permissions.py`,
oito testes de regressão em `py -B tests/test_update_scope.py`, 27 verificações em
`tests/operation_permissions_frontend.js` executadas em Node com DOM/API simulados,
compilação do script inline completo do HTML sem executá-lo e `git diff --check`.
