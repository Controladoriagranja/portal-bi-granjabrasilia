# Atualizacao automatica diaria as 04h

Computador configurado: MDE-100137, sessao asalvino.
Tarefa: BI Granja - Todos os Robos 04h.
Horario: diariamente as 04:00, Brasilia (UTC-03).
Primeira execucao prevista: 25/09/2026 as 04:00.

A tela pode ficar bloqueada. E necessario manter a sessao do usuario aberta,
o computador ligado, conectado a tomada e com acesso a internet e a pasta de rede.
Desligamento e logoff nao sao equivalentes ao bloqueio da tela.
A suspensao automatica na tomada foi desativada neste computador; na bateria,
a configuracao anterior foi preservada.

O iniciador local fica em:
C:\Users\asalvino\AppData\Local\BI_Granja\executar_diario.ps1

Ele usa caminhos UNC para nao depender da unidade X:, inicia o Agent se nao
houver um rodando neste computador e cria o lote de todos os robos ativos.
O lote atual tem 31 extratores e 5 tratamentos, com as dependencias dos 31
extratores registradas em cada tratamento. As regras da fila mantem ate tres
execucoes simultaneas e exigem sucesso das dependencias.

A criacao e atomica, sem atribuir os trabalhos a um usuario humano, e idempotente
por data: repetir a tarefa no mesmo dia nao cria outro lote.
Se falhar, o Agendador tenta novamente ate tres vezes, a cada 15 minutos.
StartWhenAvailable e WakeToRun estao habilitados.

Logs do iniciador: %LOCALAPPDATA%\BI_Granja\logs\agenda_04h_*.log.
Logs dos robos: PortalBI\logs\jobs.

Validacao manual SEM criar trabalhos:
py -B PortalBI/api/agendar_atualizacoes.py --verificar

Testes:
py -B PortalBI/tests/test_agendamento.py

A validacao pelo proprio Agendador foi executada em 24/09/2026 e terminou com
LastTaskResult=0, validando acesso a 31 extratores e 5 tratamentos.
