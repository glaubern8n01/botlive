# Monitor leve para descobrir POR QUE o Claude Code fecha sozinho.
#
# Amostra a cada 30s: memoria livre, consumo do Chrome, consumo do Claude e
# quantos processos claude existem. Quando a contagem de processos zera ou o
# PID mais antigo muda, grava uma linha REINICIO com o estado do minuto
# anterior - que e exatamente o dado que falta hoje.
#
# Nao mexe em nada: so le e escreve o log. Encerrar com Ctrl+C.
#
#   powershell -ExecutionPolicy Bypass -File G:\botlive\ops\vigia-claude-code.ps1

$logPath = "G:\botlive\ops\claude-code-vigia.log"
$intervalo = 30
$anterior = $null
$pidAncora = $null

function Amostra {
    $os = Get-CimInstance Win32_OperatingSystem
    $livreGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $chrome = Get-Process chrome -ErrorAction SilentlyContinue
    $claude = Get-Process claude -ErrorAction SilentlyContinue
    $chromeGB = if ($chrome) { [math]::Round((($chrome | Measure-Object WorkingSet64 -Sum).Sum) / 1GB, 2) } else { 0 }
    $claudeGB = if ($claude) { [math]::Round((($claude | Measure-Object WorkingSet64 -Sum).Sum) / 1GB, 2) } else { 0 }
    $ancora = if ($claude) { ($claude | Sort-Object StartTime | Select-Object -First 1).Id } else { $null }

    [PSCustomObject]@{
        Quando     = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        LivreGB    = $livreGB
        TotalGB    = $totalGB
        UsoPct     = [math]::Round(100 - ($livreGB / $totalGB * 100), 1)
        ChromeGB   = $chromeGB
        ChromeQtd  = if ($chrome) { $chrome.Count } else { 0 }
        ClaudeGB   = $claudeGB
        ClaudeQtd  = if ($claude) { $claude.Count } else { 0 }
        PidAncora  = $ancora
    }
}

"# vigia iniciado em $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Add-Content -Path $logPath -Encoding utf8
Write-Output "Registrando em $logPath (Ctrl+C para parar)"

while ($true) {
    $atual = Amostra

    $linha = "{0} livre={1}GB uso={2}% chrome={3}GB/{4}p claude={5}GB/{6}p" -f `
        $atual.Quando, $atual.LivreGB, $atual.UsoPct, $atual.ChromeGB, $atual.ChromeQtd, $atual.ClaudeGB, $atual.ClaudeQtd

    # Reinicio detectado: sumiu tudo, ou o processo mais antigo trocou de PID.
    $reiniciou = $false
    if ($null -ne $anterior) {
        if ($anterior.ClaudeQtd -gt 0 -and $atual.ClaudeQtd -eq 0) { $reiniciou = $true }
        if ($null -ne $pidAncora -and $null -ne $atual.PidAncora -and $pidAncora -ne $atual.PidAncora) { $reiniciou = $true }
    }

    if ($reiniciou) {
        $alerta = "!!! REINICIO/FECHAMENTO detectado em {0}. Estado da amostra ANTERIOR: livre={1}GB uso={2}% chrome={3}GB/{4}p claude={5}GB/{6}p" -f `
            $atual.Quando, $anterior.LivreGB, $anterior.UsoPct, $anterior.ChromeGB, $anterior.ChromeQtd, $anterior.ClaudeGB, $anterior.ClaudeQtd
        $alerta | Add-Content -Path $logPath -Encoding utf8
        Write-Output $alerta
    }

    $linha | Add-Content -Path $logPath -Encoding utf8
    if ($null -ne $atual.PidAncora) { $pidAncora = $atual.PidAncora }
    $anterior = $atual
    Start-Sleep -Seconds $intervalo
}
