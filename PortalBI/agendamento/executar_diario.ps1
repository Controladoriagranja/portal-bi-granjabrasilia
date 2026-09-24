param([switch]$Verificar)
$ErrorActionPreference = 'Stop'
$raizBI = '\\192.168.1.139\Controladoria\BI_Granja'
$pythonBI = 'C:\Users\asalvino\AppData\Local\Programs\Python\Python314\python.exe'
$logsBI = Join-Path $env:LOCALAPPDATA 'BI_Granja\logs'
New-Item -ItemType Directory -Path $logsBI -Force | Out-Null
$carimboBI = Get-Date -Format 'yyyyMMdd_HHmmss'
$logBI = Join-Path $logsBI "agenda_04h_$carimboBI.log"
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $agendaBI = Join-Path $raizBI 'PortalBI\api\agendar_atualizacoes.py'
    $agentBI = Join-Path $raizBI 'PortalBI\api\portal_bi_agent.py'
    if (-not (Test-Path -LiteralPath $agendaBI)) { throw 'Pasta de rede da automacao indisponivel.' }
    if ($Verificar) {
        & $pythonBI -B $agendaBI --verificar *> $logBI
        if ($LASTEXITCODE -ne 0) { throw 'Falha na verificacao. Consulte o log.' }
        exit 0
    }
    $agentesBI = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('python.exe', 'pythonw.exe') -and
        $_.CommandLine -match '[\\/]portal_bi_agent\.py(?:["\s]|$)'
    })
    if ($agentesBI.Count -eq 0) {
        $stdoutBI = Join-Path $logsBI "agent_$carimboBI.out.log"
        $stderrBI = Join-Path $logsBI "agent_$carimboBI.err.log"
        Start-Process -FilePath $pythonBI -ArgumentList @('-u', $agentBI) -WorkingDirectory $raizBI -WindowStyle Hidden -RedirectStandardOutput $stdoutBI -RedirectStandardError $stderrBI | Out-Null
    }
    & $pythonBI -B $agendaBI *> $logBI
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o lote. Consulte o log.' }
    exit 0
} catch {
    $_ | Out-String | Add-Content -LiteralPath $logBI
    exit 1
}
