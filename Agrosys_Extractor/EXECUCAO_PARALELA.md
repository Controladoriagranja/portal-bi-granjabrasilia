# Execucao com tres contas Agrosys

Os robos ativos usam as contas completas de config.py, na raiz do Agrosys_Extractor.
Sao consideradas a principal e as alternativas 2, 3 e 4, com limite de tres
usuarios distintos. Contas incompletas e os exemplos COLOQUE_ sao ignorados.
Variaveis AGROSYS_USUARIO / AGROSYS_SENHA e as alternativas com sufixos
_2, _3 e _4 tem prioridade. Senhas nao sao exibidas pelo controle de contas.

O portal_bi_agent.py inicia ate tres extracoes em paralelo. Reinicie o Agent
apos terminar os jobs atuais para carregar o novo codigo. Ele informa o numero
de contas completas no inicio. Tratamentos tratar_* aguardam as extracoes do proprio modulo.
A API impede extracao e tratamento simultaneos do mesmo modulo entre os Agents.
Modulos independentes podem executar seus tratamentos em paralelo.

Robos executados diretamente tambem reservam uma conta livre automaticamente.
Inicie arquivos diferentes em processos separados para aproveitar o paralelismo.
Se as tres contas estiverem ocupadas, o proximo robo aguarda.
A mesma conta e mantida no login, consultas e URLs de download do relatorio.

A pasta .locks e compartilhada por todos os processos que usam esta instalacao.
Nao apague os arquivos de lock: o bloqueio e mantido pelo sistema operacional,
e liberado quando o processo termina, inclusive apos encerramento inesperado.
Nao execute copias antigas dos robos em paralelo com os atualizados: elas nao
participam desse controle. Sessoes abertas manualmente no Agrosys tambem nao
participam dele; as contas dos robos devem ficar disponiveis.

HTML fica em html/execucoes. Downloads temporarios ficam no disco local em
%TEMP%/BI_Granja/downloads, separados por robo. Os destinos finais e os filtros dos relatorios sao mantidos.
Duas execucoes do mesmo arquivo aguardam uma a outra.

O portal local antigo continua com a fila sequencial. As contas e pastas
isoladas funcionam nos robos chamados por ele, mas o paralelismo automatico
desta alteracao esta no portal_bi_agent.py.

Os nove robos PCP estao nos caminhos ativos e usam o mesmo controle de contas.

Validacao offline (sem acessar Agrosys ou banco):
    py -B Agrosys_Extractor/tests/test_contas_paralelas.py

O ganho real depende do tempo de processamento e dos limites do Agrosys.


## Falhas e novas tentativas
O Agent 3.2 repete cada trabalho que falha ate tres vezes, com esperas de 10 e
20 segundos. O heartbeat continua ativo durante as tentativas. Parametros
invalidos e scripts ausentes sao erros de configuracao e nao sao repetidos.
O mesmo periodo e usado nas tentativas. Filtros automaticos continuam seguindo
as regras do robo. A repeticao pode atualizar novamente arquivos ja gerados.
Os logs completos ficam em PortalBI/logs/jobs, um arquivo por tentativa.
O portal permite expandir o erro completo. O backend limita a fila a tres
extracoes e impede tratamentos simultaneos com extracoes do mesmo modulo entre todos os Agents.

Para ativar, aguarde os trabalhos atuais terminarem, encerre os Agents antigos
nos computadores e inicie uma instancia do PortalBI/api/portal_bi_agent.py.
A inicializacao deve mostrar a versao 3.2.


Tratamentos aguardam SUCESSO das extracoes do proprio modulo no lote, inclusive as que
falharam antes. A API aplica a regra globalmente. Apos esgotar as tentativas,
o tratamento permanece aguardando; uma nova extracao com o mesmo periodo e
parametros pode reparar a dependencia. Trabalhos de recuperacao passam a frente
de tratamentos bloqueados. A regra vale para todos os modulos.
