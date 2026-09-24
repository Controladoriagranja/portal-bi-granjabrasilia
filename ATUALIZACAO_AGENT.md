# Agent 3.1 e fila de atualizacoes

O portal cria todos os trabalhos de extracao e registra os IDs como
dependencias dos tratamentos. A API libera ate tres trabalhos ao mesmo tempo,
considerando todos os Agents. Tratamentos so iniciam quando todas as extracoes
necessarias concluem com sucesso. Erros nao liberam tratamentos.
Uma nova extracao bem-sucedida com os mesmos parametros pode reparar uma
dependencia anterior; trabalhos de recuperacao nao ficam presos atras dela.

O Agent repete falhas de execucao ate tres vezes, com esperas de 10 e 20 segundos,
mantendo heartbeat. Cada tentativa tem log completo em PortalBI/logs/jobs.
As pausas de ENTER foram retiradas dos robos e tratamentos ativos.
O Chrome baixa os temporarios no disco local antes de transferir o arquivo
pronto para a rede. O portal permite expandir a mensagem completa de erro.

## Aplicacao na instalacao existente
- Preserve Agrosys_Extractor/config.py, PortalBI/api/.env e config_banco.py.
  Eles nao sao publicados no repositorio.
- Copie PortalBI/api/portal_bi_agent.py, Agrosys_Extractor e Python para os
  mesmos caminhos na instalacao existente, preservando seus arquivos locais.
- Aguarde as execucoes atuais terminarem e encerre os Agents antigos.
- Inicie uma instancia com:
  py -u X:\BI_Granja\PortalBI\api\portal_bi_agent.py
- Confira Versao 3.1 e Extracoes paralelas: 3.
- A publicacao do site usa index.html; a API do Render usa api/app.py.
  A versao esperada de /api/health e 2026.09.24-fila-dependencias-v1.

Os robos de banco preservam os modulos banco_*.py e configuracoes da instalacao.
As novas tentativas nao alteram os filtros; podem atualizar arquivos ja gerados.

## Validacao
- py -B Agrosys_Extractor/tests/test_contas_paralelas.py
- py -B PortalBI/tests/test_agent_retries.py
- py -B PortalBI/tests/test_portal_browser.py
- py -B PortalBI/tests/validar_fila_sql.py

O ultimo teste usa conexao PostgreSQL configurada localmente, com dados
ficticios em SELECT; nao altera tabelas. O teste de navegador usa Chrome oculto
e nao cria trabalhos reais.


Atualizacao 3.2: a API e o Agent liberam tratamentos por modulo. Cada tratamento
aguarda apenas suas extracoes, incluindo recuperacoes; outros modulos continuam.
A regra tambem filtra dependencias globais dos lotes criados anteriormente.
