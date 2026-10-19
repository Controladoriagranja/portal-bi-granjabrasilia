# Atualizador — Logística e Suprimentos

As duas opções executam somente 16 extratores e dois tratamentos: nove extratores
de Logística e sete de Suprimentos, mais o tratamento de cada setor. Comercial,
PCP e Zootécnico não podem receber novos jobs nem ser reservados pelo Agent.
O histórico permanece disponível; jobs antigos desses setores não são apagados.

## BAT local / Agendador

Mantenha `Atualizador_BI_Granja.bat` em disco local. Execução normal por duplo clique;
para ocultar a janela do PowerShell, use:

```bat
Atualizador_BI_Granja.bat /silencioso
```

O CMD pode aparecer brevemente ao abrir pelo Explorer. No Agendador, use o caminho
local completo do BAT, argumento `/silencioso` e a opção “Não iniciar nova instância”.
Para execução sem sessão aberta, a conta configurada precisa acessar o
compartilhamento UNC com suas próprias permissões. Não depende da unidade W:.
Não marque encerramento forçado após determinado tempo: pode deixar um robô filho
ativo. O BAT verifica workers anteriores e mantém a trava local contra filas duplicadas.

O BAT continua sequencial, sem Render/Neon, sem repetição automática, com log ao
lado dele. Tratamento é ignorado se uma extração do mesmo setor falhar. Códigos
de saída: 0 sucesso, 1 falhas/ignorados, 2 erro fatal/pré-requisito.
O modo silencioso oculta o console; o comportamento do navegador dos robôs é mantido.

## Portal / Agent em segundo plano

1. Publicar `index.html` no GitHub Pages e `api/app.py` pelo fluxo existente do Render.
2. Se `PORTAL_BI_AGENT_ENABLED=false` estiver definido no Render, será necessário
   habilitá-lo explicitamente com `true`. Sem essa variável, o novo código habilita
   os dois setores. `false` continua sendo a pausa de emergência, sem consultar SQL
   nas rotas de criação/reserva/sinal/listagem. Credenciais não foram alteradas.
3. Na instalação existente, substituir **somente** `PortalBI/api/portal_bi_agent.py`
   pela versão deste repositório. Preservar `.env`, configurações, robôs e tratamentos.
   O Agent precisa ficar na árvore `BI_Granja/PortalBI/api`, junto à instalação que
   contém `Agrosys_Extractor/Core` e `Python`; o repositório isolado não contém esses robôs.
4. Aguardar trabalhos atuais terminarem e encerrar Agents antigos antes de iniciar
   o novo. Não deixar versões antigas consultando a fila a cada cinco segundos.
5. Usar o mesmo Python/ambiente da instalação. Para conferir a inicialização manual:

```powershell
py -u "\\192.168.1.139\Controladoria\BI_Granja\PortalBI\api\portal_bi_agent.py"
```

Para iniciar oculto, na conta com acesso à rede e Python configurado, uma alternativa
é este comando PowerShell (executar apenas uma instância):

```powershell
Start-Process -FilePath 'py.exe' -ArgumentList @('-u', '"\\192.168.1.139\Controladoria\BI_Granja\PortalBI\api\portal_bi_agent.py"') -WindowStyle Hidden -RedirectStandardOutput "$env:LOCALAPPDATA\BI_Granja_Agent.log" -RedirectStandardError "$env:LOCALAPPDATA\BI_Granja_Agent_erros.log"
```

O início do log deve mostrar versão **3.3.1**, **18 robôs autorizados** e até três
contas. Somente administradores usam a Central de Atualizações no portal. Ela
permite atualizar um item ou os dois setores, com dependências por setor preservadas.

O Agent consulta `/signal` a cada 5s **sem PostgreSQL**; recupera a fila no início,
por sinal e ao concluir um job. Fallback: 1h ocioso, 120s ativo, 60s se a rota de sinal
não existir. Heartbeat de 60s durante execuções e até três tentativas são preservados.
O monitor do portal permanece limitado à tela visível, com 15s ativo e 15min ocioso.
Criar jobs, consultar status e executar heartbeats ainda consome Neon.

A API mantém a reserva atômica e o limite global de três extrações entre Agents.
BAT e Agent dependem do `Core.agrosys_contas`/runtime compartilhado da instalação
para respeitar as mesmas três contas entre processos e computadores. Não alterar
esse Core nem usar cópias com diretórios de locks diferentes. A combinação das duas
formas exige essa versão cooperativa na instalação real; não foi iniciada aqui.

## Validação local

`py -B tests/test_update_scope.py`: oito testes com AST e mocks, sem importar app,
`.env`, Core ou robôs. Verifica catálogo comum, setores bloqueados, criação permitida,
permissões, pausa sem SQL, filtro de reserva, limite global e comandos/ambiente.
O payload PowerShell do BAT é analisado pelo parser, sem execução.

Não houve deploy, mudança de configuração real, agendamento, acesso a endpoint/banco
ou execução de robôs. Publicação, permissões da conta Windows, Core compartilhado e
funcionamento na instalação precisam de conferência pelo responsável.
