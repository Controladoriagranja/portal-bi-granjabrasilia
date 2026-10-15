# Consumo Neon — auditoria e correção de 15/10/2026

## Escopo

O diagnóstico de 84,09 das 100 CU-h foi informado pelo usuário; não foi consultado
nem modificado o ambiente real. Não houve deploy, leitura de credenciais, conexão
com Render/Neon, execução de robôs, extrações, tratamentos ou agendamentos.

A única alteração no código de produção é index.html. Backend Flask, Agent,
scripts agendados, catálogo de robôs, PCP/Zootécnico, regras de negócio, rotas
analíticas, SQL, pool, fórmulas, visual e configuração de deploy ficaram intactos.

## Correções implementadas

- Chamados: polling somente com usuário/token presentes, tela autenticada ativa,
  aba visível e tickets ou ticketadmin selecionada. O painel mantém a exigência de
  admin ou permissão individual de chamados.
- Entrada e retorno à aba/tela fazem leitura imediata, incluindo cadastro de usuários
  necessário aos responsáveis. Falhas temporárias nesse cadastro são recuperadas
  no próximo ciclo. O intervalo de 10s continua enquanto o módulo está em uso.
- Um setTimeout é armado após terminar o ciclo anterior. Geração do monitor,
  cancelamento de leitura e trava impedem ciclos duplicados e respostas de telas antigas.
- Troca de tela, aba oculta, pagehide, logout e invalidação da autenticação interrompem
  o polling. O logout local ocorre antes de aguardar a rede.
- Respostas e gravações enfileiradas de uma sessão encerrada não podem usar as
  credenciais de um novo login. O servidor valida permissões em cada pedido.
- Leituras anteriores a edições/exclusões não sobrescrevem mudanças locais. O polling
  não lê a base enquanto existem salvamentos ou exclusões pendentes.
- A fila serial mantém os deltas explicitamente alterados na chamada. Uma resposta
  anterior da fila não faz itens inalterados de um snapshot antigo serem enviados
  como novos, inclusive após exclusão em outro navegador. Histórico, anexos e gestores
  continuam seguindo os mesmos endpoints e formatos.
- Não há upload automático de cache ou chamada automática a /api/chamados/merge.
  O snapshot em cache serve apenas de baseline de deltas e fallback visual.
- Central de Atualizações: monitor suspenso com aba oculta e retomado ao voltar.
  Mantidos 15s para jobs ativos/aquecimento e 15min quando ociosos. Requisição anterior
  pendente é aguardada com timer local de 1s, sem nova consulta SQL, antes da atualização;
  evita esperar 15min sobre dados antigos ao retornar.

## Consumo evitado

Antes, cada aba autenticada disparava /api/chamados a cada 10s mesmo em Relatórios:
360 requisições por hora, além das chamadas iniciais. Cada uma consulta autenticação
em public.usuarios e lê/normaliza a base de chamados. Agora esse polling é zero
fora do módulo, no login e com a aba oculta. Ao entrar há leitura sob demanda.

O status de jobs podia consultar até 240 vezes/h com jobs ativos ou 4 vezes/h ocioso
mesmo com aba oculta. Agora o monitor não consulta nesse estado.

Essas são contagens de requisições evitadas, não previsão de CU-h. A economia real
depende de todas as fontes de atividade. Neon Free suspende o compute após 5 minutos
de inatividade: https://neon.com/docs/introduction/scale-to-zero
Um cliente com polling frequente pode impedir esse período de inatividade.

## Agent v3.3 e backend — auditados e preservados

- /api/agent/jobs/signal valida chave privada e lê arquivo efêmero; não usa SQLAlchemy
  nem PostgreSQL. Cache-Control: no-store evita sinal antigo.
- Criação e finalização de job notificam o arquivo após commit. Workers na mesma
  instância compartilham o arquivo via substituição atômica.
- Agent v3.3 consulta o sinal HTTP a cada 5s; isso não é polling SQL da fila.
- Claim imediato no startup recupera backlog; sinal novo e conclusão de execução
  provocam novo claim. Reserva atômica e recuperação por heartbeat não foram alteradas.
- Fallback preservado: 3600s ocioso, 120s com execução ativa, 60s se /signal retornar 404.
  Heartbeat de 60s durante execução, inclusive entre tentativas, permanece.
- Não existe novo scheduler/serviço. Não foi restaurado polling SQL de 5s.
- agendar_atualizacoes.py escreve diretamente no banco e não notifica o arquivo do
  Render. Esse caminho existente depende de startup/fallback do Agent; não foi mudado
  nem executado. Confirmar se é usado na instalação antes de planejar qualquer mudança.

## SQLAlchemy e outras fontes auditadas

- Todos os checkouts engine.connect()/engine.begin() encontrados em api/app.py são
  gerenciados por with. Não foi encontrado SessionLocal instanciado nessa API ou
  conexão global aberta mantida pelo módulo.
- pool_pre_ping=True testa no checkout; pool_recycle=300 recicla na próxima retirada
  do pool, não cria timer ou consulta periódica de cinco minutos. Documentação:
  https://docs.sqlalchemy.org/en/20/core/pooling.html
  Não há motivo comprovado para substituir o pool nesta etapa.
- /api/health não acessa o banco. /api/chamados/health consulta PostgreSQL: conferir
  monitores externos dessa rota; nenhum timer do frontend atual a utiliza.
- Não foi encontrado loop SQL automático no processo Flask. Threads de execução
  existentes não foram alteradas.
- public.usuarios continua sendo lida em cada requisição autenticada. Não foi criado
  cache de permissões: bloqueios e mudanças de perfil valem na próxima chamada.
- Não foi executado validar_fila_sql.py, pois acessa banco real.

## Testes locais realizados

- py -B PortalBI/tests/test_neon_sync_browser.py
- py -B PortalBI/tests/test_neon_audit.py
- py -B PortalBI/tests/test_portal_controls.py
- git diff --check

O teste de navegador usa o HTML real, relógio e fetch falsos, rede HTTP externa
bloqueada e dados fictícios. Cobre tela/visibilidade, entrada/retorno, concorrência,
401, token ausente, logout/relogin, requisições atrasadas, exclusão remota, anexos,
histórico, gestores, delta em fila, falha temporária, gravação pendente e intervalos
de jobs. A regressão de controles verifica as nove telas e navegação mobile.

Os testes Python carregam funções isoladas via AST, sem importar app, banco, .env
ou configuração do Agent. SQL, HTTP, relógio, executor e futures são falsos; nenhum
job/robô é executado. Nove testes verificam sinal sem DB, autenticação por pedido,
encerramento do contexto SQL, notificações após commit, backlog, fallback ocioso,
ativo/404, conclusão simulada e heartbeat.

## Conferências pendentes no ambiente real

- Publicar o frontend pelo fluxo existente, sem necessidade de alteração de backend.
  Abas antigas precisam recarregar para receber a correção.
- Conferir caminho/versão de cada Agent em execução. O repositório contém v3.3, mas
  isso não comprova que a instalação usa esse arquivo. A cópia v3.2 informada pode
  continuar consultando /claim a cada 5s e anular boa parte do ganho. Não houve inspeção
  ou encerramento de processos, nem troca de arquivos da instalação.
- Confirmar se /signal publicado corresponde ao código auditado; backend antigo sem
  a rota usa fallback de 60s e pode manter o banco continuamente ativo.
- Conferir monitores, agendamentos, outros BIs, SQL Editors e consumidores do mesmo
  compute. Não foram consultados ou alterados.
- Observar períodos de compute suspenso e variação de CU-h no painel existente após
  atualização. Não medir com loops de consultas que acordem o próprio banco.
- Conexões/transações efetivamente abertas em produção não podem ser descartadas só
  pela leitura de código; esta auditoria não consultou pg_stat_activity.
- Uma consulta recebida pelo servidor pode terminar mesmo após abort no navegador.
  Respostas antigas são descartadas; gravações já recebidas continuam sujeitas à
  transação e à validação de permissões existentes.
- A sincronização entre usuários continua periódica, a cada 10s mais a duração da
  resposta, enquanto a tela estiver visível. Após inatividade pode haver cold start.
  Não se alterou a política de conflitos entre edições do mesmo chamado.
