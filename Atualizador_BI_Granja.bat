@echo off
setlocal
rem ATUALIZADOR LOCAL. Nao chama Portal, Render, Neon ou BI Agent.
rem Agendador: executar somente esta fila; regra "Nao iniciar nova instancia".
rem Opcional: definir BI_GRANJA_PYTHON com o caminho completo do python.exe
rem do ambiente de producao. Sem override, usa py -3 e depois python.exe do PATH.
rem Log UTF-8 criado apenas ao executar, ao lado deste BAT em disco LOCAL.
rem Codigos: 0=sucesso; 1=falhas/ignorados; 2=pre-requisito ou erro fatal.
set "BI_GRANJA_BAT=%~f0"
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$text=[IO.File]::ReadAllText($env:BI_GRANJA_BAT); $marker=':__BI_POWERSHELL__'; & ([scriptblock]::Create($text.Substring($text.LastIndexOf($marker)+$marker.Length)))"
exit /b %errorlevel%
:__BI_POWERSHELL__
$ErrorActionPreference = 'Stop'
$root = '\\192.168.1.139\Controladoria\BI_Granja'
$homeLocal = [IO.Path]::GetDirectoryName($env:BI_GRANJA_BAT)
$script:writer = $null
$script:logFailed = $false
$queueMutex = $null
$ownsQueue = $false
$results = New-Object 'System.Collections.Generic.List[object]'
$failedModules = @{Comercial=$false; Logistica=$false; Suprimentos=$false}
$startedAt = Get-Date
$clock = [Diagnostics.Stopwatch]::StartNew()
$fatalFailure = $false
$exitCode = 2

function Log([AllowEmptyString()][string]$Message = '') {
    Write-Host $Message
    if ($null -ne $script:writer) {
        try { $script:writer.WriteLine($Message); $script:writer.Flush() }
        catch {
            $script:logFailed = $true
            try { $script:writer.Dispose() } catch {}
            $script:writer = $null
            Write-Host 'AVISO: falha no log local; a saida permanece no terminal.'
        }
    }
}
function Duration([TimeSpan]$Elapsed) {
    return '{0:00}:{1:00}:{2:00}' -f [math]::Floor($Elapsed.TotalHours), $Elapsed.Minutes, $Elapsed.Seconds
}
function Job([string]$Module,[string]$Name,[string]$Relative,[string[]]$ArgsList = @()) {
    [pscustomobject]@{Module=$Module; Name=$Name; Path=(Join-Path $root $Relative); ArgsList=$ArgsList}
}
function Quote-Native([string]$Value) {
    # Windows argv escaping: quotes and backslashes, including a trailing slash.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Resolve-Python {
    $override = $env:BI_GRANJA_PYTHON
    $launcherArgs = @()
    if ($override) {
        if (-not [IO.Path]::IsPathRooted($override) -or -not (Test-Path -LiteralPath $override -PathType Leaf)) {
            throw 'BI_GRANJA_PYTHON deve indicar um python.exe existente com caminho absoluto.'
        }
        $candidate = $override
    } else {
        $command = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidate=$command.Source; $launcherArgs=@('-3') }
        else {
            $command = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $command -or $command.Source -match '\\WindowsApps\\') {
                throw 'Python nao encontrado. Defina BI_GRANJA_PYTHON com o executavel usado em producao.'
            }
            $candidate=$command.Source
        }
    }
    $probe = @(& $candidate @launcherArgs -B -c 'import sys; print(sys.executable)' 2>&1)
    if ($LASTEXITCODE -ne 0 -or -not $probe.Count) { throw 'Nao foi possivel resolver o interpretador Python.' }
    $resolved = ([string]$probe[-1]).Trim()
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw 'Interpretador Python resolvido nao existe.' }
    return $resolved
}
function Child-Line([string]$Line,$State) {
    Log ('    | ' + $Line)
    # Scripts legados podem informar falhas parciais e encerrar com exit code zero.
    if ($Line -match '^\s*Erros(?:/avisos)?\s*:\s*(\d+)\b') {
        if ([long]$Matches[1] -gt 0) { $State.ReportedFailure=$true }
    }
    if ($Line -cmatch '^\s*ERRO:\s+\S') { $State.ReportedFailure=$true }
}
function Run-Job($Item,[int]$Index,[int]$Total) {
    $label = '{0} - {1}' -f $Item.Module,$Item.Name
    Log ''
    Log ('[{0:00}/{1:00}] {2}' -f $Index,$Total,$label)
    Log ('         Inicio: {0:dd/MM/yyyy HH:mm:ss}' -f (Get-Date))
    $watch=[Diagnostics.Stopwatch]::StartNew()
    $nativeExit=$null
    $state=@{ReportedFailure=$false}
    $status='ERRO'
    $reason=''
    if (-not (Test-Path -LiteralPath $Item.Path -PathType Leaf)) {
        $reason='Script nao encontrado: ' + $Item.Path
    } else {
        Log '         Status: EXECUTANDO...'
        Log ('         Script: ' + $Item.Path)
        if ($Item.ArgsList.Count) { Log ('         Argumentos: ' + ($Item.ArgsList -join ' ')) }
        $process=New-Object Diagnostics.Process
        try {
            $info=New-Object Diagnostics.ProcessStartInfo
            $info.FileName=$script:python
            # CMD permanece local. O proprio Python entra no diretorio UNC do script,
            # preservando __file__, sys.argv, imports e caminhos relativos originais.
            $wrapper="import os, runpy, sys; p=os.path.abspath(sys.argv[1]); sys.argv=sys.argv[1:]; os.chdir(os.path.dirname(p)); sys.path.insert(0, os.path.dirname(p)); runpy.run_path(p, run_name='__main__')"
            $arguments=@('-u','-B','-X','utf8','-c',$wrapper,$Item.Path) + @($Item.ArgsList)
            $info.Arguments=($arguments | ForEach-Object { Quote-Native ([string]$_) }) -join ' '
            $info.WorkingDirectory=$homeLocal
            $info.UseShellExecute=$false
            $info.CreateNoWindow=$true
            $info.RedirectStandardInput=$true
            $info.RedirectStandardOutput=$true
            $info.RedirectStandardError=$true
            $info.StandardOutputEncoding=[Text.Encoding]::UTF8
            $info.StandardErrorEncoding=[Text.Encoding]::UTF8
            $info.EnvironmentVariables['PYTHONUNBUFFERED']='1'
            $info.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
            $info.EnvironmentVariables['PYTHONDONTWRITEBYTECODE']='1'
            $info.EnvironmentVariables['AGROSYS_PERIODO']='auto'
            # Nao herdar um periodo manual/particao de uma execucao anterior.
            foreach ($key in @('AGROSYS_DATA_INICIO','AGROSYS_DATA_FIM','AGROSYS_SOLICITACOES_PARTICAO')) {
                $info.EnvironmentVariables.Remove($key)
            }
            $process.StartInfo=$info
            [void]$process.Start()
            $process.StandardInput.Close()
            $out=$process.StandardOutput.ReadLineAsync()
            $err=$process.StandardError.ReadLineAsync()
            $lastProgress=[datetime]::UtcNow
            # Drena ambos os canais simultaneamente para nao bloquear pipes cheios.
            while ($null -ne $out -or $null -ne $err) {
                if ($null -ne $out -and $out.IsCompleted) {
                    $line=$out.GetAwaiter().GetResult()
                    if ($null -eq $line) { $out=$null }
                    else { Child-Line $line $state; $out=$process.StandardOutput.ReadLineAsync() }
                }
                if ($null -ne $err -and $err.IsCompleted) {
                    $line=$err.GetAwaiter().GetResult()
                    if ($null -eq $line) { $err=$null }
                    else { Child-Line $line $state; $err=$process.StandardError.ReadLineAsync() }
                }
                if (([datetime]::UtcNow - $lastProgress).TotalSeconds -ge 30) {
                    Log ('         Em andamento: {0} | {1:HH:mm:ss}' -f (Duration $watch.Elapsed),(Get-Date))
                    $lastProgress=[datetime]::UtcNow
                }
                if (($null -ne $out -and -not $out.IsCompleted) -or ($null -ne $err -and -not $err.IsCompleted)) {
                    Start-Sleep -Milliseconds 50
                }
            }
            $process.WaitForExit()
            $nativeExit=$process.ExitCode
            if ($nativeExit -eq 0 -and -not $state.ReportedFailure) { $status='CONCLUIDO' }
            elseif ($nativeExit -ne 0) { $reason='Codigo de retorno Python: ' + $nativeExit }
            else { $reason='Script retornou zero, mas informou erro parcial. Conferir saida acima.' }
        } catch {
            $reason='Falha ao iniciar/acompanhar o processo: ' + $_.Exception.Message
        } finally {
            # Se a leitura dos canais falhar, nao iniciar outro robo em paralelo.
            try { if (-not $process.HasExited) { $process.WaitForExit() } } catch {}
            $process.Dispose()
        }
    }
    $watch.Stop()
    Log ('         Status: ' + $status)
    if ($reason) { Log ('         Motivo: ' + $reason) }
    Log ('         Fim: {0:dd/MM/yyyy HH:mm:ss} | Tempo: {1}' -f (Get-Date),(Duration $watch.Elapsed))
    [void]$results.Add([pscustomobject]@{Name=$label; Status=$status; NativeExit=$nativeExit; Reason=$reason; Time=(Duration $watch.Elapsed)})
    if ($status -ne 'CONCLUIDO') { $failedModules[$Item.Module]=$true }
}

try {
    [Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
    # Nunca escrever o log de controle em compartilhamento ou unidade mapeada.
    if ($homeLocal.StartsWith('\\') -or ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($homeLocal))).DriveType -eq [IO.DriveType]::Network) {
        throw 'Copie o BAT para disco local antes de executar. Logs de controle nao podem ficar na rede.'
    }
    # Protege esta fila no mesmo PC, inclusive em sessoes diferentes do Windows.
    # A reserva GLOBAL de contas entre PCs continua pertencendo ao Core na rede.
    $queueMutex=[Threading.Mutex]::new($false,'Global\GranjaBrasilia_AtualizadorBI')
    try { $ownsQueue=$queueMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $ownsQueue=$true }
    if (-not $ownsQueue) { throw 'Outra fila deste atualizador ja esta em execucao neste computador.' }
    # Encerrar PowerShell/CMD nem sempre encerra o filho Python. Nunca iniciar
    # uma fila nova sobre um worker anterior, inclusive da versao antiga do BAT.
    # Consulta somente processos LOCAIS; nao acessa endpoints nem altera processos.
    $pythonProcesses=@(Get-CimInstance -ClassName Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name LIKE 'python3%.exe'" -ErrorAction Stop)
    $unknown=@($pythonProcesses | Where-Object { [string]::IsNullOrWhiteSpace($_.CommandLine) })
    if ($unknown.Count -gt 0) {
        throw 'Nao foi possivel verificar a linha de comando de processos Python locais. Revisar permissoes da conta do Agendador antes de iniciar.'
    }
    $orphans=@($pythonProcesses | Where-Object {
        $_.CommandLine.IndexOf($root,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $_.CommandLine.Contains('runpy.run_path')
    })
    if ($orphans.Count -gt 0) {
        throw ('Worker de uma fila anterior ainda ativo. Aguardar/revisar antes de tentar novamente. PID(s): ' + (($orphans | ForEach-Object {$_.ProcessId}) -join ', '))
    }
    $logPath=Join-Path $homeLocal ('Atualizador_BI_Granja_{0:yyyyMMdd_HHmmss}_{1}.log' -f $startedAt,$PID)
    $script:writer=[IO.StreamWriter]::new($logPath,$false,[Text.UTF8Encoding]::new($false))
    Log '============================================================'
    Log '              ATUALIZADOR BI - GRANJA BRASILIA'
    Log '============================================================'
    Log ('INICIO: {0:dd/MM/yyyy HH:mm:ss}' -f $startedAt)
    Log ('LOG LOCAL: ' + $logPath)
    Log 'Fila sequencial. Sem reexecucao automatica. Sem Render/Neon.'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Compartilhamento UNC indisponivel para esta conta do Windows.' }
    $script:python=Resolve-Python
    Log ('PYTHON: ' + $script:python)
    # Apenas pre-requisitos, sem instalar pacotes ou importar configuracoes de rede.
    $check="import sys, importlib.util as u; names=['requests','pandas','selenium','openpyxl','xlrd','lxml']; missing=[n for n in names if u.find_spec(n) is None]; missing += [] if (u.find_spec('pyarrow') or u.find_spec('fastparquet')) else ['pyarrow ou fastparquet']; print('Python '+sys.version.split()[0]); print('Dependencias: OK' if not missing else 'Dependencias ausentes: '+', '.join(missing)); sys.exit(0 if sys.version_info >= (3,10) and not missing else 2)"
    $preflight=@(& $script:python -B -c $check 2>&1)
    $preflightExit=$LASTEXITCODE
    foreach ($line in $preflight) { Log ([string]$line) }
    if ($preflightExit -ne 0) { throw 'Requer Python 3.10+ com dependencias no mesmo ambiente usado em producao. Nada foi instalado.' }

    $extractors=@(
        (Job 'Comercial' 'Faturamento CFOP' 'Agrosys_Extractor\Comercial\comercial_faturamento_cfop.py' @('--modo','auto','--sem-pausa'))
        (Job 'Comercial' 'Cadastro de Vendedores' 'Agrosys_Extractor\Comercial\cadastro_de_vendedores.py')
        (Job 'Comercial' 'Clientes Cadastrados' 'Agrosys_Extractor\Comercial\clientes_cadastrados.py' @('--sem-pausa'))
        (Job 'Logistica' 'Cadastro de Vendedores' 'Agrosys_Extractor\Logistica\logistica_cadastro_vendedores.py')
        (Job 'Logistica' 'Contas a Pagar' 'Agrosys_Extractor\Logistica\logistica_contas_a_pagar.py')
        (Job 'Logistica' 'Controle de Frete' 'Agrosys_Extractor\Logistica\logistica_controle_frete.py' @('--modo','auto'))
        (Job 'Logistica' 'Controle de Pallets' 'Agrosys_Extractor\Logistica\logistica_controle_pallets.py')
        (Job 'Logistica' 'Devolucoes' 'Agrosys_Extractor\Logistica\logistica_devolucoes.py' @('--modo','auto'))
        (Job 'Logistica' 'Faturamento CFOP' 'Agrosys_Extractor\Logistica\logistica_faturamento_cfop.py' @('--modo','auto'))
        (Job 'Logistica' 'Frete' 'Agrosys_Extractor\Logistica\logistica_frete.py' @('--modo','auto'))
        (Job 'Logistica' 'Ocorrencias de Viagens/Custo' 'Agrosys_Extractor\Logistica\logistica_ocorrencia_viagens_custo.py' @('--modo','auto'))
        (Job 'Logistica' 'Relatorio de Veiculos' 'Agrosys_Extractor\Logistica\logistica_relatorio_veiculos.py')
        (Job 'Suprimentos' 'Contas Pagas' 'Agrosys_Extractor\Suprimentos\suprimentos_contas_pagas.py' @('--modo','auto'))
        (Job 'Suprimentos' 'Notas Fiscais do Item' 'Agrosys_Extractor\Suprimentos\suprimentos_notas_fiscais_item.py' @('--modo','auto'))
        (Job 'Suprimentos' 'Ordens de Compras Emitidas' 'Agrosys_Extractor\Suprimentos\suprimentos_ordens_compras_emitidas.py' @('--modo','auto'))
        (Job 'Suprimentos' 'Relacao OC/NF' 'Agrosys_Extractor\Suprimentos\suprimentos_relacao_oc_nf.py')
        (Job 'Suprimentos' 'Relatorio de Usuarios' 'Agrosys_Extractor\Suprimentos\suprimentos_relatorio_usuarios.py')
        (Job 'Suprimentos' 'Solicitacoes por Requisitante' 'Agrosys_Extractor\Suprimentos\suprimentos_solicitacoes_requisitante.py' @('--modo','automatico'))
        (Job 'Suprimentos' 'Titulos Agrupados' 'Agrosys_Extractor\Suprimentos\suprimentos_titulos_agrupados.py' @('--modo','auto'))
    )
    $treatments=@(
        (Job 'Comercial' 'Tratamento' 'Python\Comercial\Tratar_Comercial.py' @('--sem-pausa'))
        (Job 'Logistica' 'Tratamento' 'Python\Logistica\Tratar_Logistica.py' @('--sem-pausa'))
        (Job 'Suprimentos' 'Tratamento' 'Python\Suprimentos\Tratar_Suprimentos.py' @('--sem-pausa'))
    )
    Log ''
    Log ('ETAPA 1/2 - EXTRACOES ({0})' -f $extractors.Count)
    for ($i=0;$i -lt $extractors.Count;$i++) { Run-Job $extractors[$i] ($i+1) $extractors.Count }
    Log ''
    Log 'ETAPA 2/2 - TRATAMENTOS (3)'
    Log 'Modos originais: Comercial/Logistica incrementais; Suprimentos consolida a base.'
    for ($i=0;$i -lt $treatments.Count;$i++) {
        $item=$treatments[$i]
        if ($failedModules[$item.Module]) {
            $label=$item.Module + ' - Tratamento'
            Log ('[{0:00}/03] {1} | IGNORADO: houve falha nas extracoes deste setor.' -f ($i+1),$label)
            [void]$results.Add([pscustomobject]@{Name=$label;Status='IGNORADO';NativeExit=$null;Reason='Falha de extracao no mesmo setor';Time='00:00:00'})
        } else { Run-Job $item ($i+1) $treatments.Count }
    }
    $exitCode=0
    if (@($results | Where-Object {$_.Status -ne 'CONCLUIDO'}).Count -gt 0) { $exitCode=1 }
} catch {
    $fatalFailure=$true
    Log ('ERRO FATAL: ' + $_.Exception.Message)
    $exitCode=2
} finally {
    $clock.Stop()
    Log ''
    Log '============================================================'
    Log 'RESUMO FINAL'
    Log '============================================================'
    foreach ($result in $results) { Log ('{0,-10} | {1} | {2}' -f $result.Status,$result.Name,$result.Time) }
    Log ('Concluidos: {0}' -f @($results | Where-Object {$_.Status -eq 'CONCLUIDO'}).Count)
    Log ('Erros:      {0}' -f (@($results | Where-Object {$_.Status -eq 'ERRO'}).Count + [int]$fatalFailure))
    Log ('Ignorados:  {0}' -f @($results | Where-Object {$_.Status -eq 'IGNORADO'}).Count)
    Log ('FIM: {0:dd/MM/yyyy HH:mm:ss} | Duracao total: {1}' -f (Get-Date),(Duration $clock.Elapsed))
    if ($script:logFailed) { $exitCode=2 }
    Log ('Codigo final: ' + $exitCode)
    try { if ($script:writer) { $script:writer.Dispose() } }
    finally {
        if ($ownsQueue -and $null -ne $queueMutex) { $queueMutex.ReleaseMutex() }
        if ($null -ne $queueMutex) { $queueMutex.Dispose() }
    }
}
exit $exitCode