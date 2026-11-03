# Implantação — cadastro único da Integração

Alterações locais, sem deploy e sem executar SQL ou consultar produção.
Usar a mesma sessão do Portal, o mesmo Worker e o serviço atual do Anderson.
Comercial, quatro telas, fórmulas, views, ETL e Docker original preservados.

## Preservar a publicação anterior

**Estado após os resultados reais:** a estrutura já existe e há 16 escopos gerais.
Não repetir as migrações abaixo nessa base. A carga inicial atual é somente
`carga-local/03_carga_inicial_neon.sql`, depois da conferência. Ela preserva os
escopos gerais existentes e o perfil Diretor de Lucas. Leandro da Costa Elias
(id 35) já está em `todos`, e continua assim. Não há promoção de perfil nem
restrição automática de quem já tem acesso hoje.

Antes de ativar a nova autorização na API, executar manualmente no Neon:

1. `api/migrations/20261103_zootecnico_access.sql` SOMENTE se a estrutura ainda
   não foi instalada. Não repetir a criação das tabelas existentes.
2. `api/migrations/20261103_zootecnico_preservar_existentes.sql`.

O segundo arquivo mantém visão geral para quem já tinha o relatório Integração
liberado por setor/relatório e ainda não tem escopo zootécnico configurado.
Não altera escopos existentes (nem `none`, bloqueios, próprio ou equipe).
Um marcador impede que repetir o arquivo libere usuários cadastrados depois.
Admin/Diretor têm visão geral pelo perfil, mesmo sem as tabelas auxiliares novas.
Não há fallback que dê todos os dados quando ocorrer erro ou faltar um técnico.

Se uma conta antiga já tem `none` ou restrição explícita e deve continuar geral,
o admin deve escolher **Todos os dados** na edição dessa conta. Não é necessário
SQL por usuário. Retirar o relatório ou bloquear a conta continua impedindo acesso.
RxP mantém o funcionamento anterior para acesso geral; não foi ampliado para
usuários restritos por técnico, pois isso exporia registros de outros técnicos.

## Arquivos para publicar

- Render (Portal): `api/app.py`, `api/zootecnico_access.py` e o novo
  `api/zootecnico_catalog.py`, junto do restante do backend atual.
- GitHub Pages (Portal): `assets/js/zootecnico-access.js` (index.html já o inclui).
- Republicar também `index.html`, que agora informa quando o usuário foi salvo
  com vínculo pendente, sem declarar a identificação como concluída.
- Cloudflare: manter/publicar `integrations/zootecnico/worker/worker.js` se a ponte
  preparada anteriormente ainda não está publicada. Mesmo binding PRIVATE_API,
  secrets API_USER/API_PASSWORD e encaminhamento X-Portal-Authorization.
- Anderson: `entrega/api_zootecnico_atualizada.zip`, no formato completo original.
  Ajustados `servico_zootecnico.py`, `portal_router.py`, `Dockerfile.zootecnico`;
  adicionado `zootecnico_acesso.py`. Dockerfile principal intacto; no especializado
  somente um COPY adicional. Não trocar configurações locais nem a arquitetura.
- bi-zootecnico: manter/publicar a versão de `assets/js/api.js` já preparada no
  projeto e em `frontend/assets/js/api.js`, se ainda estiver pendente.

Ordem para a base já levantada: conferir/executar `03_carga_inicial_neon.sql` →
backend Portal → conferir a ponte do Worker → API Anderson → index.html e
JavaScript do cadastro. As migrações antigas já aplicadas não precisam ser repetidas.
Nenhuma nova variável de ambiente, dependência, serviço ou login é necessária.

## Cadastro e edição

Entrega da carga, somente local e ignorada pelo Git:

- `carga-local/catalogo_tecnicos.json`: valores, contagens, fontes, evidências,
  35 identidades e os 15 valores pendentes; 177 aliases prontos para carga.
- `carga-local/conferencia_carga.md`: cruzamento dos 14 registros do Word com
  as 65 contas existentes; só Lucas já tem conta por e-mail exato.
- `carga-local/03_carga_inicial_neon.sql`: único SQL da carga inicial,
  idempotente e transacional, com diário das linhas realmente inseridas nas
  próprias estruturas auxiliares. Não cria tabelas nem contas.
- `carga-local/04_rollback_carga_neon.sql`: usar somente se precisar reverter;
  verifica alterações posteriores e referências novas antes de remover linhas.
  Não executar o rollback junto da implantação.

Se a primeira tentativa retornou `mismatched parentheses`, clicar no botão
ROLLBACK do SQL Editor para encerrar a transação abortada, substituir todo o SQL
pelo arquivo 03 atualizado e executá-lo novamente. O arquivo 04 não é usado para
limpar esse erro. Foi corrigida a aspa da chave JSON `nome` no teste da conta;
carga e rollback foram regenerados, sem alterar as identidades/permissões.

Nenhum alias pendente é carregado. Os nomes completos confirmados permanecem
separados mesmo quando uma sigla pode indicar mais de uma pessoa. As divergências
da base dinâmica não são usadas para juntar nomes: a responsabilidade histórica
é conferida nas fontes de mortalidade/histórico e na chave de acerto. Não há
regra de maioria, iniciais ou aproximação para conceder dados.

**Não usar `20261103_zootecnico_tecnico_teste.sql` no fluxo novo.**
Técnicos, identidades e aliases são gerenciados internamente pelo formulário.

- Joelmir: Usuários → cadastrar/editar → perfil Setor → Integração → Dados da
  Integração: Somente seus dados. O nome do cadastro identifica a pessoa.
- Gerente com equipe específica: perfil Setor → Integração → Equipe → marcar
  usuários do Portal. Não selecionar IDs de técnicos nem repetir cadastros.
- Admin/Diretor: visão geral automática; demais perfis recebem geral somente
  com autorização explícita do administrador.
- Se a correspondência não for inequívoca, Resolver aqui apresenta valores reais
  por fonte. O admin confere e confirma ali. Pode marcar uma fonte sem registros
  para mantê-la SEM acesso. Não se deduz vínculo por iniciais ou nome parcial.
- Um nome completo exato, único no cadastro, pode ser associado às variantes
  comprovadas por chave completa de lote. Siglas com mais de um dono não são
  associadas automaticamente. Catálogo legado sem dono pode ser reaproveitado;
  uma identidade que já pertence a outro usuário não é transferida.

O backend usa primeiro os aliases confirmados no Neon: um usuário identificado
não depende da disponibilidade da API especializada a cada cadastro/salvamento.
Quando falta uma correspondência, o catálogo da API só é consultado sob demanda
administrativa. A busca é assíncrona para
não prender o worker do Render enquanto o Worker valida a sessão na CENTRAL.
O cache efêmero de 5 minutos contém só nomes/provas, sem tokens, chaves de lotes
ou permissões. Sem polling permanente. Se o limite de provas for excedido,
usa somente nomes reais e exige resolução manual de variantes não comprovadas.
Salvar refaz a validação no servidor dentro da mesma transação do usuário.
API indisponível ou correspondência não resolvida permite salvar o usuário com
vínculo explicitamente pendente. O recurso `zootecnico_pendente` guarda a intenção
e a equipe selecionada; a autorização efetiva fica `none`, sem aliases novos.
O formulário e o aviso de salvamento mostram que não foram liberados registros.
Não há ativação automática posterior: o admin confere e salva novamente quando
a correspondência puder ser validada. Falha SQL ou conflito durante uma gravação
validada desfaz toda a transação. Edição de outros campos sem alterar o acesso
zootécnico preserva a configuração anterior.

O erro genérico do catálogo ganhou motivos específicos para 401/403/404/5xx e
falha de conexão. Não foram consultados logs/endpoints reais nesta etapa; não
afirmar qual status o servidor publicado retornou. O pacote da API precisa conter
o endpoint de opções e o Worker precisa manter a ponte já preparada.

## Testar após publicação

1. Conta antiga geral: conferir RxP, quatro telas e relatórios comerciais.
2. Joelmir, janela separada: conferir filtros, indicadores, detalhes e galpões nas
   quatro telas. Alterar filtros para outro técnico não pode ampliar o acesso.
   Antes, criar a conta comum pelo portal, com senha inicial pelo fluxo atual,
   perfil Setor, Integração e Somente seus dados. Confirmar o e-mail: o Word traz
   domínio `.com`, sem `.br`; a carga não corrige esse valor por suposição.
   Repetir com Mariana; ela também não tem conta no resultado recebido.
3. Gerente Setor/Equipe: ver somente a união dos usuários marcados; bloquear ou
   remover um membro deve retirar seus dados na próxima requisição.
4. Admin/Diretor: visão geral, inclusive RxP. Configurar um técnico não pode
   restringir esses perfis nem mudar o Comercial.
5. Abrir um usuário antigo e alterar outro campo: seu acesso deve continuar igual.
6. Simular catálogo indisponível em ambiente de teste: salvar uma correspondência
   pendente e conferir que a conta existe, mas não consulta registros. Reabrir a
   edição deve mostrar o modo solicitado e a equipe, com estado pendente.

Testes locais: 40 de autorização, 25 de cadastro/compatibilidade, 21 da carga,
pendências e aliases reais fornecidos, 10 dos builders originais/middleware,
15 de regressão comercial e 3 do pacote; 27 verificações Chrome com rede bloqueada.
Os 94 testes do Worker são da etapa anterior, cujo código foi preservado.
Não são testes em PostgreSQL real, Cloudflare real ou produção. Nenhum acesso
real de Joelmir foi confirmado antes da publicação e validação no formulário.
