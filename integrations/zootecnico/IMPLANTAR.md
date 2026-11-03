# Implantação — cadastro único da Integração

Alterações locais, sem deploy e sem executar SQL ou consultar produção.
Usar a mesma sessão do Portal, o mesmo Worker e o serviço atual do Anderson.
Comercial, quatro telas, fórmulas, views, ETL e Docker original preservados.

## Preservar a publicação anterior

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
- Cloudflare: manter/publicar `integrations/zootecnico/worker/worker.js` se a ponte
  preparada anteriormente ainda não está publicada. Mesmo binding PRIVATE_API,
  secrets API_USER/API_PASSWORD e encaminhamento X-Portal-Authorization.
- Anderson: `entrega/api_zootecnico_atualizada.zip`, no formato completo original.
  Ajustados `servico_zootecnico.py`, `portal_router.py`, `Dockerfile.zootecnico`;
  adicionado `zootecnico_acesso.py`. Dockerfile principal intacto; no especializado
  somente um COPY adicional. Não trocar configurações locais nem a arquitetura.
- bi-zootecnico: manter/publicar a versão de `assets/js/api.js` já preparada no
  projeto e em `frontend/assets/js/api.js`, se ainda estiver pendente.

Ordem: SQL de compatibilidade → backend Portal → Worker com ponte → API Anderson
→ JavaScript do cadastro. Não ativar a API antes da compatibilidade dos existentes.
Nenhuma nova variável de ambiente, dependência, serviço ou login é necessária.

## Cadastro e edição

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

O catálogo só é consultado sob demanda administrativa. A busca é assíncrona para
não prender o worker do Render enquanto o Worker valida a sessão na CENTRAL.
O cache efêmero de 5 minutos contém só nomes/provas, sem tokens, chaves de lotes
ou permissões. Sem polling permanente. Se o limite de provas for excedido,
usa somente nomes reais e exige resolução manual de variantes não comprovadas.
Salvar refaz a validação no servidor dentro da mesma transação do usuário.
Falha desfaz usuário, senha, permissões e vínculos. Edição de outros campos
sem alterar o acesso zootécnico preserva a configuração anterior.

## Testar após publicação

1. Conta antiga geral: conferir RxP, quatro telas e relatórios comerciais.
2. Joelmir, janela separada: conferir filtros, indicadores, detalhes e galpões nas
   quatro telas. Alterar filtros para outro técnico não pode ampliar o acesso.
3. Gerente Setor/Equipe: ver somente a união dos usuários marcados; bloquear ou
   remover um membro deve retirar seus dados na próxima requisição.
4. Admin/Diretor: visão geral, inclusive RxP. Configurar um técnico não pode
   restringir esses perfis nem mudar o Comercial.
5. Abrir um usuário antigo e alterar outro campo: seu acesso deve continuar igual.

Testes locais: 40 de autorização, 25 de cadastro/compatibilidade, 10 dos builders
originais/middleware, 15 de regressão comercial e 3 do pacote; 27 verificações
Chrome com rede bloqueada e 94 do Worker em VM com transporte simulado.
Não são testes em PostgreSQL real, Cloudflare real ou produção. Nenhum acesso
real de Joelmir foi confirmado antes da publicação e validação no formulário.
