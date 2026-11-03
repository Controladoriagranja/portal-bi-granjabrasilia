# Acesso por técnico — Integração / BI Zootécnico

**Entrega para implantação:** ver [integrations/zootecnico/IMPLANTAR.md](integrations/zootecnico/IMPLANTAR.md).

**Estado atual — cadastro único e compatibilidade (03/11/2026):** técnicos e equipes
são configurados na mesma tela de Usuários; não usar o seed SQL de técnicos abaixo.
O backend resolve nomes exatos/provas por lote e administra as tabelas auxiliares.
Ambiguidades ficam no próprio formulário. A conta pode ser salva com vínculo
explicitamente pendente e autorização efetiva `none`; não há liberação automática.
Admin/Diretor continuam gerais mesmo sem a estrutura auxiliar nova. Para preservar
os usuários anteriores sem escopo configurado, foi preparado (não executado)
`api/migrations/20261103_zootecnico_preservar_existentes.sql`, uma única transição
que não sobrescreve restrições existentes e não libera usuários futuros.
Comercial e consultas gerais permanecem iguais. RxP continua geral, sem filtro
por técnico. Publicação coordenada e conferência real seguem pendentes.
Resultados reais fornecidos posteriormente: 65 contas, 35 identidades confirmadas,
177 aliases confirmados e 15 valores pendentes. A carga preparada preserva todos
os acessos gerais atuais, inclusive Leandro da Costa Elias (35) e Lucas (42).
Somente Lucas já tem conta entre as 14 pessoas do Word; nenhum usuário é criado
pelo SQL. Joelmir e Mariana têm aliases nas seis fontes, mas não têm conta.
O e-mail de Joelmir no Word termina em `.com`, sem `.br`; confirmar no cadastro.
Catálogo, conferência, carga única e rollback estão na pasta local
`integrations/zootecnico/carga-local/`, ignorada pelo Git. Nada foi executado.
Correção posterior da carga: fechada a aspa da chave JSON `nome` no teste da
conta; blocos DO finalizados explicitamente com `END;`. Gerador agora rejeita
aspas/parênteses incompletos antes de gravar arquivos. Carga e rollback regenerados
com o mesmo payload/identificador, sem execução no Neon.
Testes locais: 114 unitários/regressão/pacote e 27 verificações Chrome offline.
Os 94 testes anteriores do Worker permanecem no histórico; o Worker não mudou.
Detalhes e arquivos exatos em IMPLANTAR.md.

## Histórico das entregas anteriores (não são as instruções atuais de cadastro)
Em 03/11/2026, o usuário confirmou a execução de `01_metadados.sql` no PostgreSQL
real e a existência dos campos obrigatórios; `candidatos_tecnico` está ausente e
é opcional. Não foi solicitada nova auditoria. Módulo/Worker e pacote de integração
estavam preparados; naquela etapa o cadastro de teste aguardava aliases exatos.
Os registros de auditoria abaixo são o histórico das etapas anteriores.

Atualização após confirmação do usuário em 03/11/2026: `api_zootecnico(3).zip` é
a versão vigente informada do Anderson. O pacote final inclui os quatro arquivos
integrados nessa base e um patch para eventuais mudanças posteriores. Isso não é
inspeção do servidor. O cadastro do técnico de teste foi explicitamente adiado;
nome, e-mail e aliases permanecem sem preenchimento e nenhum SQL foi executado.

Formato final corrigido a pedido do usuário: `entrega/api_zootecnico_atualizada.zip`
conserva a pasta `api_zootecnico/` e todos os arquivos do ZIP recebido. Somente três
arquivos foram ajustados e um módulo foi adicionado. Dockerfile principal intacto;
Dockerfile.zootecnico original com um único COPY adicional. A entrega anterior
também foi regenerada nesse formato. Não há novo Docker nem mudança de arquitetura.

## Estado da entrega

Implementação LOCAL, sem deploy, sem migração executada, sem consulta a bancos ou
endpoints reais. Não foram criados usuários nem alteradas senhas. O cadastro da
lista `Usuarios Portal Resultados(1).docx` será uma etapa posterior: confirmar
e-mail, identidade canônica/aliases e forma de definir a senha inicial antes do INSERT.

Projetos inspecionados:

| Projeto | Base utilizada | Estado inicial |
|---|---|---|
| Portal | `Documents/GitHub/portal-bi-granjabrasilia`, branch `main` | Arquivos não rastreados de notificações do Forms preservados |
| Frontend Zootécnico | `Documents/GitHub/bi-zootecnico`, branch `main` | Alterações em `metrics.js`, `detalhes.html`, `formulas.html`, `index.html`, `lotes.html` preservadas |
| API especializada | `Downloads/api_zootecnico(3).zip`, raiz `api_zootecnico` | Pacote de trabalho, sem branch; não comprova a versão oficial publicada |

Na API, o ZIP original foi somente lido. A entrega dos quatro arquivos da API está
em `integrations/zootecnico/api/`. O `servico_zootecnico.py` é a cópia inspecionada
com SOMENTE três adaptações: import do módulo, chamada do middleware e wrapper
da conexão. Comparar essas três mudanças com a versão oficial antes de integrar;
não substituir uma versão oficial mais recente indiscriminadamente.

O Dockerfile especializado enumera os arquivos copiados: recebeu somente o COPY
do novo módulo. Porta, comando/entrypoint, base e dependências foram preservados.
O `portal_router.py` também foi ajustado: o resumo compartilhado omite somente o
Zootécnico para quem não tem acesso geral, separa as chaves de cache e transmite
o contexto de autorização para o executor de consultas em segundo plano.
O outro Dockerfile do pacote inicia `app:app` na porta 8000 e não é o serviço
especializado `servico_zootecnico:app` (8010); não foi alterado. Conferir no ambiente
oficial que nenhum acesso externo às fontes usa esse outro entrypoint.

O `assets/js/api.js` do repositório Zootécnico foi atualizado localmente. Há uma
cópia da entrega em `integrations/zootecnico/frontend/assets/js/api.js`.

## Auditoria: fluxo real e riscos

```text
Login do portal -> token assinado (itsdangerous), uid interno
   -> sessionStorage granjabi_auth_token, mesma origem GitHub Pages
   -> openReport/canOpenReportPage -> iframe, sem token na URL
   -> BI api.js -> Worker, Authorization: Bearer
   -> binding privado / autenticação Basic existente -> API especializada
   -> X-Portal-Authorization: Bearer (contrato já usado pelo Comercial)
   -> NOVO /api/auth/zootecnico-access no Render
   -> _usuario_autenticado/_usuario_por_token: valida token e usuário ativo no Neon
   -> verifica abertura do relatório 13 + escopo/vínculos/aliases atuais
   -> API restringe fontes antes dos filtros analíticos/agregações/paginação
   -> consultas ao PostgreSQL INTERNO, esquema zootecnico
```

Na Etapa 1 o código do Worker não estava disponível nos três projetos. Na Etapa 2
foi localizada uma fonte histórica em anexo e preparada sua correção local,
descrita ao final deste documento. O entrypoint/configuração publicados continuam
pendentes de conferência. Sem `X-Portal-Authorization`, a nova API nega o acesso:
não há fallback para Basic geral. Nenhuma credencial foi acrescentada ao frontend.

Antes, o Basic validava somente o acesso à infraestrutura. As quatro telas
consultavam a API genérica sem ACL individual. Havia também rotas de dados crus e
resumos com cache global. Filtrar apenas a tela deixaria caminhos alternativos.

O banco Neon de autenticação NÃO contém as tabelas zootécnicas. Nenhuma junção
entre os dois bancos é necessária: o Neon guarda apenas a configuração de acesso;
o filtro dos registros é executado no banco interno.

## Rotas e fontes

| Tela/recurso | Rotas GET | Fonte(s) |
|---|---|---|
| Desempenho Lotes Fechados e detalhes | `/api/bi/zootecnico/{filtros,resumo,detalhes,atualizacao}` | `vw_desempenho_acerto_portal`, auxiliares `base_dinamica` e `acerto_lote_resultado_geral` |
| GPD por Fase | `/api/bi/gpd-fases/{filtros,resumo,atualizacao}` | `base_dinamica`; deduplicação/cálculos originais preservados |
| Lotes em Criação | `/api/bi/lotes-abertos/{filtros,resumo,detalhes,atualizacao}` | `mortalidade_peso_abertos`; `metas` é configuração comum |
| Histórico de Lotes em Criação | `/api/bi/historico-abertos/{filtros,resumo,detalhes,atualizacao}` | `vw_historico_lotes_criacao_portal`; cargas de abertos/fechados |
| Histórico legado | `/api/bi/historico-fechados/*` | `mortalidade_peso_fechados`, mesma proteção |
| Dados crus das seis fontes mapeadas | `/api/zootecnico/dados/{tabela}` | Mesma restrição obrigatória, inclusive contagem/paginação |
| Administração zootécnica | `/api/zootecnico/*` administrativos, `/api/portal/zootecnico/*` | Exige sessão com acesso geral |
| Resumo compartilhado | `/api/portal/modulos` | Mantém outros módulos; omite Zootécnico sem autorização geral, antes das contagens, com cache separado |

O wrapper da conexão também recusa leituras qualificadas de `zootecnico` em outras
rotas sem autorização, impedindo usar outro nome de módulo como atalho. Fontes
desconhecidas são negadas para usuários restritos. `metas` é a única tabela de
configuração comum permitida, sem dados de lotes. O wrapper não é um firewall SQL
genérico: cobre o SQL gerado pelas rotas atuais inspecionadas. Novas rotas, outro
entrypoint ASGI ou uma segunda conexão precisam passar por revisão e testes.

**Diferença de Aves Abatidas (RxP):** não recebeu filtro por técnico nem mudança de
fórmulas. Como consulta `base_dinamica` pelo lookup compartilhado, nesta entrega
fica integral para acesso geral e é negada a usuários restritos. O mesmo vale para
o endpoint de atualização de Fórmulas que reúne fontes não mapeadas de RxP. Isso
evita usar essas consultas como contorno; ampliar acesso restrito a elas exige
uma regra específica em etapa futura. Conteúdo estático de fórmulas não foi alterado.

As quatro telas usam contratos GET da API. Não foi encontrada uma rota separada
de exportação no frontend dessas telas. Dados retornados por consultas detalhadas
e por dados crus mapeados são filtrados; não se adicionou exportação nova.
O catálogo esperado das tabelas de Matrizes não contém fonte zootécnica e conserva
o acesso anterior. A semente antiga do cache de módulos não é reutilizada nas novas
chaves, evitando servir um resumo geral na primeira consulta restrita.

## Política de acesso

Autorização de abertura do relatório permanece independente do alcance dos dados.

| Perfil/escopo | Regra |
|---|---|
| Admin e Diretor (`admin`/`director`, perfis administrativos equivalentes atuais) | Geral pela política explicitamente autorizada; vale para cadastros existentes e futuros |
| Setor com `proprio` | Exatamente um técnico ativo vinculado |
| Setor com `equipe` | Um ou mais técnicos ativos explicitamente vinculados |
| Setor com `todos` | Geral concedido explicitamente por administrador |
| Sem escopo ativo/vínculo válido | Nenhum dado restrito; sem fallback geral |

Nome do cargo, e-mail, setor, `commercial_access` e `supervisor_code` NÃO concedem
acesso zootécnico. Um gestor cadastrado como `sector` precisa de concessão `todos`;
somente mudar o nome de exibição para "Gestor" não concede nada. Rebaixar Admin/
Diretor no formulário não mantém a concessão implícita de visão geral.

Os administradores configuram os vínculos em **Usuários → Editar → Dados da
Integração — Zootécnico**. A criação de usuários tem a mesma opção. O Comercial
fica separado e conserva seu modelo atual. As gravações de escopo/vínculos
ocorrem na mesma transação do cadastro do usuário e somente após autorização de
administrador. Payload sem `zootecnicoAccess` preserva o cadastro existente.

## Modelo e correspondências

Migração UP: `api/migrations/20261103_zootecnico_access.sql`.
Migração DOWN: `api/migrations/20261103_zootecnico_access.down.sql`.

- `entidades_acesso_dados`: identificador canônico estável do técnico e nome.
- `usuario_escopos_acesso`: usuário interno (`public.usuarios.id`), recurso,
  escopo, ativo e auditoria de criação/última alteração.
- `usuario_vinculos_dados`: técnicos autorizados; revogação lógica individual.
- `entidade_aliases_dados`: valor EXATO de cada técnico em cada fonte. Chave única
  `(recurso,fonte,valor)` impede cadastrar uma mesma sigla da fonte para dois técnicos.

Os vínculos têm FKs, PKs/índices e auditoria por usuário interno. Não modificam
`neon_auth`, usuários, permissões existentes ou dados empresariais. A auditoria
guarda criador e última alteração; não é um histórico completo de todas as mudanças.

Exemplo conceitual (NÃO executado, não é cadastro real):

```text
entidade: tipo=tecnico, identificador=tecnico_001, nome=<nome confirmado>
alias: recurso=zootecnico, fonte=base_dinamica, valor=<nome EXATO>, entidade=tecnico_001
alias: recurso=zootecnico, fonte=mortalidade_peso_abertos, valor=<sigla EXATA>, entidade=tecnico_001
vínculo: usuario_id=<id interno>, recurso=zootecnico, entidade=tecnico_001
```

Cadastrar os valores efetivos nas SEIS fontes relacionadas, conforme existirem.
Para a view de desempenho, cadastrar tanto a identificação original (`tecnico`)
quanto a de exibição (`tecnico_exibicao`) para a mesma entidade, quando diferentes.
Não há aproximação por nomes, prefixos ou `ILIKE`: o identificador é comparado
exatamente após remover espaços nas pontas. Alias ausente produz conjunto vazio.

Não há preenchimento automático a partir da lista Word: logins, nomes e siglas
ainda precisam ser relacionados de forma inequívoca. Depois dessa conferência,
usuários e técnicos novos são dados de cadastro, sem nova alteração de HTML/JS.
O catálogo de entidades/aliases é administrado por SQL nesta etapa; o modal
administra os vínculos usuário → técnicos já cadastrados, não cria aliases.

## Responsabilidade histórica e versões

Não usa `galpoes` atual para transferir o histórico para outro técnico. Usa o
`tecnico` registrado em cada fonte. A chave de responsabilidade conferida é:

- desempenho/acerto: `chave_lote`;
- base dinâmica: `cod_prod + galpao + lote + data_de_alojamento`;
- abertos/fechados: `codigo_granja + galp + num_lote + data_recepcao`;
- histórico: `codigo_granja + galp + num_lote + recepcao_dia_cache`.

As conversões de datas reutilizam o helper SQL original. Antes de filtrar, uma
CTE materializada verifica as identidades por chave no conjunto original da fonte.
Uma chave com versões de técnicos diferentes, técnico desconhecido ou vazio não
entra no escopo restrito. Isso evita ressuscitar snapshot antigo ao filtrar antes
da deduplicação. É uma regra conservadora: lotes com trocas de responsável dentro
da MESMA chave podem ficar indisponíveis a técnicos, mas permanecem na visão geral.
Uma futura divisão por período exige regra de negócio confirmada.

A view de desempenho também rejeita registros com `candidatos_tecnico` maior que
um, quando esse campo existe, e divergência entre o técnico original e o de
exibição quando ambos estão preenchidos. Não altera as views nem as fórmulas.

## Sessão, cache e consumo

- Valida sessão, estado ativo, abertura do relatório e vínculos no servidor a
  cada consulta; nenhum cache de autorização permite manter um vínculo revogado.
- Nenhum token em URL, nenhum segredo no GitHub Pages, nenhum segundo login.
- Basic continua validado na API; não concede sozinho acesso a dados zootécnicos.
- Respostas da autorização/API: `Cache-Control: no-store`, Vary adequado. A
  autorização acrescenta `private`; o middleware Basic original mantém no-store.
- Frontend força `no-store`, omite cookies e rejeita resposta se a sessão mudar
  durante fetch ou leitura do JSON. Logout/perda de sessão descarta o iframe do
  portal; abertura pendente não reabre o relatório depois do logout.
- Não foi acrescentado cache offline, polling, job ou processo agendado.
- A validação acrescenta leituras de permissões no Neon durante consultas dos
  usuários. O Worker pode já validar a sessão também: conferir duplicidade na
  integração oficial antes de otimizar, sem sacrificar bloqueios imediatos.

CORS original da API privada foi preservado (localhost). O frontend continua
acessando o Worker, cuja política de origem não foi alterada nem verificada ao vivo.
Não habilitar CORS público amplo nem expor a API privada para contornar isso.

## Testes locais e limites

Executados sem bancos, uploads, endpoints reais ou importação de `api/app.py`:

Resultado da Etapa 1 (para resultados atuais, ver Etapa 2): **36 testes de autorização/SQL + 20 verificações no Chrome +
15 testes de regressão das permissões existentes aprovados**. Sintaxe dos cinco
arquivos Python de produção e `git diff --check` também aprovados.

```powershell
py -B tests/test_zootecnico_access.py
py -B tests/test_zootecnico_browser.py
py -B tests/test_operation_permissions.py
```

Autorização/SQL: usuário próprio/equipe/geral, ausência de vínculo, revogação,
negativa de relatório, sessão ausente/expirada, HTTP de autorização indisponível,
fontes mapeadas/desconhecidas, snapshots conflitantes, critérios de ambiguidade,
composição de CTEs/literais/placeholders e isolamento das outras rotas.
Também foram testados o resumo compartilhado sem acesso zootécnico, a separação
de caches e a preservação do contexto de autorização na thread do carregamento.

Navegador: catálogo/vínculo/equipe, gestor geral, rebaixamento de perfil, respostas
fora de ordem ao trocar de usuário, preservação em falha, larguras 390/768/1366,
transporte do Bearer, no-store e descarte de resposta após troca/logout. HTTP/HTTPS
foram bloqueados no Chrome e fetch foi simulado; nenhum download de driver.

Esses testes validam os contratos e a composição, NÃO executam o SQL em PostgreSQL.
Não comprovam a cardinalidade/qualidade atuais das views, o desempenho do plano
real, o encaminhamento do Worker, o isolamento em produção, nem equivalência
numérica após integração com uma versão oficial diferente da cópia local.

## Pendências antes da publicação

1. Confirmar a versão oficial/entrypoint em uso e integrar apenas os arquivos e
   três alterações descritos. Outro servidor/entrypoint não recebe esta proteção
   automaticamente.
2. No banco INTERNO, conferir somente por leitura as colunas/tipos/chaves das seis
   fontes e a definição das views (`pg_get_viewdef`). Conferir duplicações e
   técnicos por chave, sem executar ETL/refresh. O código pressupõe os campos
   identificados no projeto, que precisam ser comparados ao banco real.
3. Confirmar que o cadastro REAL continua sendo relatório `13`, setor `4`.
   O código fixa relatório 13 para evitar aceitar um recurso vindo do navegador.
4. Conferir os pares nome completo/sigla e cadastrar entidades/aliases. Não
   adivinhar correspondências a partir de iniciais semelhantes.
5. Definir e revisar a criação das contas da lista Word e as senhas iniciais,
   preservando senhas de contas existentes. Não há INSERT de usuários nesta entrega.

## Ordem segura de implantação (MANUAL)

1. Revisar o diff e guardar backup dos arquivos oficiais e da configuração de
   permissões. Não incluir `.env`/credenciais no Git.
2. Executar a migração UP uma única vez no Neon, após revisão. Ela é transacional;
   não usar IF NOT EXISTS para mascarar uma estrutura incompatível já existente.
3. Publicar backend do portal com `zootecnico_access.py` e `app.py`; publicar o
   frontend do portal com o novo JS. Login e Comercial não dependem da migração
   nova; uma migração ausente retorna indisponibilidade só da nova configuração.
4. Cadastrar e validar entidades/aliases e configurar os usuários no modal. Os
   atuais Admin/Diretor já têm visão geral por política; demais usuários começam
   sem acesso zootécnico até receber escopo. NÃO publicar a nova API supondo que
   os usuários já foram vinculados.
5. Conferir o Worker: encaminhamento do Bearer em `X-Portal-Authorization`, Basic
   privado e no-store. Não colocar Basic no navegador nem token no iframe.
6. Integrar `zootecnico_acesso.py`, seu COPY no `Dockerfile.zootecnico`, as adaptações
   de `portal_router.py` e as três mudanças de `servico_zootecnico.py`
   ao backend oficial. Publicar a API especializada de forma controlada.
7. Publicar a alteração de `bi-zootecnico/assets/js/api.js` no GitHub Pages,
   preservando as alterações locais dos demais arquivos. Não é necessário mudar
   URLs dos relatórios, views, ETL ou configuração de deploy nesta entrega.
8. Com contas de teste autorizadas, conferir as quatro telas, filtros, indicadores
   e detalhes; comparar geral com a referência e testar consultas diretas,
   revogação e troca de sessão. Validar um caso por técnico e equipe, nulos e
   ambiguidades. Somente então liberar os técnicos reais.

Variáveis novas: **nenhuma**. Mantêm-se as variáveis existentes de autenticação
do portal e PostgreSQL privado (`PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`).
Não modificar seus valores para esta implementação.

## Rollback

Sem alteração em views ou ETL, não há reconstrução de dados empresariais.

Se houver problema, retirar temporariamente o acesso ao BI Integração ou manter a
API com negação segura enquanto se reverte a integração. **Voltar à API anterior
reabre o acesso sem escopo**; não publicar esse rollback para técnicos restritos.
Os outros módulos podem continuar usando sua versão validada.

Reverter os arquivos dos três projetos para os backups revisados, preservando
trabalho local anterior. A migração pode permanecer instalada sem interferir no
código antigo. Se for necessário removê-la, exportar os quatro cadastros novos e
executar o DOWN manualmente, somente depois de retirar o código que os utiliza.
O DOWN elimina os metadados novos de autorização; não toca usuários nem seus dados.

---

## Etapa 2 — validação local em 03/11/2026

### 1. Worker localizado e compatibilidade

Endpoint público configurado: `https://api-bi-granja.controladoriagb05.workers.dev`.
Não foi encontrado o repositório/configuração implantável atual no workspace.
O preparador `BI-PCP/tools/preparar_worker_diagnostico.py` referencia uma fonte
histórica fornecida pelo usuário em anexo, de 08/10/2026. O anexo foi apenas lido;
o preparador não foi executado. A cópia completa corrigida e o diff estão em:

- `integrations/zootecnico/worker/worker.js`;
- `integrations/zootecnico/worker/contra_fonte_historica.patch`;
- `integrations/zootecnico/worker/README.md` (proveniência/hash e auditoria detalhada).

Incompatibilidade comprovada nessa fonte: o proxy troca `Authorization` por Basic
sem definir `X-Portal-Authorization`. O candidato local encaminha o MESMO Bearer
validado no Render, sobrescrevendo qualquer X-Portal-Authorization recebido do
cliente. Basic permanece exclusivamente entre Worker e API privada; nenhuma
credencial é enviada na URL ou devolvida em headers ao navegador.

CORS mantém exclusivamente a origem GitHub Pages atual e os métodos existentes.
O navegador envia só Authorization; não se liberou X-Portal-Authorization em CORS.
O candidato preserva método/corpo/filtros de outros módulos, exige usuário ativo,
trata JSON de autenticação inválido e 401/403/5xx, controla redirecionamentos,
mescla Vary e força no-store nas respostas/subrequests. Detalhes internos de 5xx
não são enviados ao cliente. Não adiciona logs com headers, tokens ou senhas.

Bindings/secrets mantidos por NOME, sem valores: `PRIVATE_API`, `API_USER`,
`API_PASSWORD`. O identificador/tipo do binding, destino vigente, wrangler,
compatibility_date e regras de cache externas NÃO foram encontrados. Não foram
inventados arquivos de deploy nem criado qualquer serviço/binding.

**Conclusão do Worker:** o candidato é compatível com o contrato local testado;
não há validação do Worker realmente publicado. Antes de integrar, obter o
entrypoint atual de `api-bi-granja` e seu wrangler/configuração equivalente sem
secrets. Comparar o patch; não substituir a versão atual pela cópia histórica.

### 2. PostgreSQL: o que foi e não foi validado

Não foi disponibilizada uma conexão de diagnóstico validada nesta sessão. Não
foram abertos arquivos `.env`/credenciais nem tentadas conexões a bancos. Nenhum
SQL foi executado em PostgreSQL, inclusive EXPLAIN. Não foram executados ETL,
refresh, migração, escrita ou cadastro no Neon.

Foi preparado o kit MANUAL em `integrations/zootecnico/diagnostico/`:

| Arquivo | Finalidade e limite |
|---|---|
| `01_metadados.sql` | Banco atual, seis fontes, 169 campos esperados, tipos reais, constraints, índices e definições das views; só catálogos |
| `02_amostras_chaves.sql` | EXPLAIN e blocos de amostra de até 500 linhas por fonte: chaves incompletas/repetidas, técnico vazio e valores de técnico diferentes |
| `03_explain_ctes.sql` | EXPLAIN sem ANALYZE de 19 caminhos de builders reais e um lookup auxiliar; usa técnico/chave fictícios, sem concessão |
| `04_conferir_aliases.sql` | Comparar aliases conferidos com amostras das seis fontes, contar desconhecidos e conflitos canônicos; não retorna nomes/e-mails/linhas empresariais |
| `referencias.json` | Base/hash do ZIP, hashes dos arquivos com finais de linha normalizados e limites explícitos da validação |
| `api_contra_zip3.patch` | Diferenças da API preparada contra a cópia local do ZIP; não é um diff contra o servidor oficial |

Os campos foram extraídos das configurações/builders originais e complementados
com os campos da autorização e do lookup auxiliar. Colunas numéricas usadas sem
conversão recebem conferência específica; campos que o builder converte de texto
continuam sujeitos à conferência dos valores/formato. `PRESENTE_TIPO_A_CONFERIR`
não significa aprovação automática de um tipo. `candidatos_tecnico` é opcional
no SQL atual; o significado/propagação desse campo precisa de confirmação na view.

Todos os blocos são transações READ ONLY com statement_timeout de 5s e lock_timeout
de 1s, terminando em ROLLBACK. **Executar um bloco por vez, não o arquivo inteiro.**
Primeiro conferir metadados; depois revisar o EXPLAIN da consulta e só então
decidir se executa a amostra. Em caso de erro, encerrar com ROLLBACK antes de
prosseguir. Um LIMIT em uma view não garante que sua origem custe pouco.

As amostras não são contagens globais. Zero duplicidades numa amostra não comprova
unicidade da fonte inteira. Valores distintos de técnico podem ser aliases da
mesma pessoa; não representam automaticamente responsáveis diferentes. No arquivo
04, o CTE de aliases está intencionalmente vazio: resultados de correspondência
ficam NULL enquanto o cadastro real não for preenchido. Não é prova de falha de
todos os técnicos. Não há junção entre Neon e banco interno, FDW ou dblink.

Não foi confirmado no banco real: existência/tipos atuais dos 169 campos,
cardinalidade das views, histórico de responsáveis, aliases efetivos, unicidade
das chaves ou índices/plano/custo/latência. As contagens antigas da investigação
não foram reutilizadas como resultado atual.

**Desempenho:** o acesso geral mantém o SQL original nos caminhos testados.
No restrito, as CTEs leem as fontes para conferir conflitos antes de filtrar,
com materialização e agrupamento por chave. Isso tem custo adicional, especialmente
quando a view é complexa. Sem plano real não se pode prometer a latência. Não
filtrar versões por técnico antes de conferir conflitos para tentar acelerar:
isso pode ressuscitar snapshot antigo. Nenhum índice, view, ETL ou timeout de
produção foi alterado.

### 3. Segurança e cobertura auditada

Foram invocados offline os builders originais de 19 caminhos: filtros/resumos/
detalhes/atualização das quatro telas, variantes de mortalidade (principal,
evolução e lotes paginados) e histórico legado. Cada execução foi interrompida
no primeiro SQL, sem executá-lo. O lookup secundário de `base_dinamica` foi também
construído com UMA linha de entrada fictícia para testar sua consulta auxiliar.
O parser de placeholders do psycopg confirmou a ordem/quantidade dos parâmetros;
isso não é análise sintática/plano executado em PostgreSQL.

Nos caminhos testados, a origem recebe escopo antes das agregações, filtros,
totais e paginação. Parâmetro tecnico é somente filtro adicional; role/usuario_id
forjados são rejeitados nos builders, e não mudam a identidade no endpoint central.
O teste do middleware original confirma que Basic sozinho não autoriza dados;
Basic válido e Bearer verificado mantêm o escopo até o handler. A validação de
Basic/PostgreSQL foi simulada, sem conexão real.

Rotas cruas mapeadas, consultas genéricas, metadados e cache de módulos conservam
as proteções da Etapa 1. RxP continua fora do filtro técnico, exigindo acesso
geral. Não foi encontrada exportação separada nas quatro telas; endpoints de
detalhes/dados continuam sujeitos ao mesmo escopo. Uma exportação ou entrypoint
adicionado na versão oficial precisa ser incluído na auditoria, não presumido
protegido por este resultado local.

O banco interno continua sendo a autoridade sobre o vínculo histórico de cada
registro; a lista de aliases e as permissões ficam no Neon. Não foi usado nome,
e-mail, setor ou parâmetro do navegador como prova de autorização.

### 4. Comparação para integração oficial

Referência disponível: `Downloads/api_zootecnico(3).zip`, SHA256 bruto
`3e8110d7b9855e9cb521b857f57ae6b195e26c73bfeba1f0a6ad4da91bbd9300`.
Ela NÃO foi confirmada como a versão em execução no Anderson. Não houve leitura
ou substituição automática de arquivos daquele computador.

| Arquivo oficial a comparar | Incorporação necessária |
|---|---|
| `API/api_zootecnico/servico_zootecnico.py` | Import, dispatch da autorização após Basic e wrapper da conexão (três adaptações) |
| `API/api_zootecnico/portal_router.py` | copy_context para thread, omissão zootécnica no catálogo restrito e caches separados, inclusive warmup |
| `API/api_zootecnico/Dockerfile.zootecnico` | COPY do novo módulo, preservando os demais COPY/CMD/porta atuais |
| `API/api_zootecnico/zootecnico_acesso.py` | Novo módulo de autorização; conferir contra eventual arquivo homônimo já existente |
| `API/api_zootecnico/bi_generic/` vigente | Comparar router, registry, sql_utils, analytics, gpd_config/gpd_fases_dinamica, mortalidade_*, filtros/principal_contexto e freshness para detectar rotas/colunas/conexões novas |

O patch não muda cálculos, fórmulas, views ou os módulos financeiros. No teste,
o escopo geral produz exatamente os mesmos SQLs capturados da referência.
Se os arquivos oficiais diferirem, integrar os trechos em revisão, sem substituir
os arquivos inteiros nem aplicar o patch cegamente. Outro entrypoint (`app:app`),
uma conexão própria ou um novo exportador pode constituir um caminho alternativo.

### 5. Problemas encontrados e correções desta etapa

- Fonte histórica do Worker sem encaminhamento do Bearer: corrigido no candidato
  local, sobrescrevendo X-Portal-Authorization forjado.
- 403 de autenticação transformado em 503, JSON inválido sem tratamento e cache
  de subrequests sem política explícita: corrigidos no mesmo candidato.
- Vary sobrescrito e retorno de headers/redirecionamento privado: candidato
  mescla Vary e remove headers de credenciais; recusa redirects privados e token
  explícito em URL, sem expor corpo diagnóstico de 5xx.
- Teste antigo do Worker dependia de arquivo ausente: não executado como se
  estivesse aprovado. Adicionado teste novo usando a fonte candidata disponível.
- Ausência de metadados/plano reais: gerado kit SQL; não foi "corrigida" por
  adivinhação nem tratada como aprovação do banco.

Não foi necessário alterar novamente a autorização da API, o frontend ou os
cálculos da Etapa 1. Alterações locais anteriores, inclusive as dos outros
arquivos do frontend Zootécnico e das notificações Forms, foram preservadas.

### 6. Resultados dos testes desta etapa

| Categoria | Executado/resultado | Limite |
|---|---|---|
| Unitários de autorização existentes + novo caso de identidade forjada | 37 aprovados | HTTP/banco simulados |
| Novos testes de builders/middleware/diagnósticos | 10 aprovados | 19 caminhos em restrito/geral + lookup fictício; nenhum SQL executado |
| Worker candidato em VM Node | 94 verificações aprovadas | fetch/Render/binding simulados; não é runtime Cloudflare nem Worker real |
| Navegador local | 20 verificações aprovadas | Chrome headless, HTTP/HTTPS bloqueados e fetch simulado |
| Regressão de permissões comerciais | 15 aprovados | Banco simulado; não valida BIs publicados |
| PostgreSQL real | NÃO EXECUTADO | Kit manual pendente |
| Worker/binding real | NÃO EXECUTADO | Código/configuração atual pendentes |
| Integração oficial/produção | NÃO EXECUTADA | Sem deploy, migração, usuários ou alteração de dados |

Comandos locais usados, sem importar `api/app.py` nem abrir banco:

```powershell
py -B tools/preparar_validacao_zootecnico.py
py -B tests/test_zootecnico_access.py
py -B tests/test_zootecnico_phase2.py
py -B tests/test_zootecnico_browser.py
py -B tests/test_operation_permissions.py
# Worker testado via VM Node das ferramentas; equivalente, se Node já instalado:
node tests/zootecnico_worker.js
```

O gerador só lê o ZIP, carrega os builders puros permitidos (sem serviço/app,
credenciais ou registro financeiro) e grava artefatos locais. Não usar sua
regeneração para sobrescrever um kit SQL em que já tenham sido preenchidos
aliases reais sem guardar essa edição antes.

### 7. Pendências reais antes de publicar

1. Obter o código/configuração ATUAL do Worker `api-bi-granja`, metadados do
   binding PRIVATE_API e conferir cache externo; sem valores de secrets.
2. Executar manualmente o 01 no PostgreSQL INTERNO e conferir campos/tipos/views.
   Enviar os resultados técnicos, não credenciais ou listagens pessoais.
3. Revisar EXPLAIN de cada consulta necessária antes de executar amostras;
   validar chaves, ambiguidades e aliases canônicos com os resultados reais.
4. Obter os arquivos oficiais do Anderson e revisar o diff por trechos; verificar
   entrypoints/rotas/exportações/conexões adicionais. Nenhum arquivo oficial foi
   sobrescrito e não se pode afirmar equivalência com a cópia local.
5. Somente depois: revisar migração/permissões/usuários e realizar implantação
   manual em ordem segura, com testes de contas próprias/equipe/geral/revogação.

**Aprovação desta etapa é local e parcial:** código/contratos testados; banco,
Worker vigente e integração oficial continuam pendentes. Não publicar supondo
que o isolamento por técnico já foi comprovado com dados de produção.
