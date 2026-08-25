<#
    Desliga o BotLive deste PC.

    Existe porque o atalho do logon so sabia LIGAR. Depois de responder "sim",
    a unica saida era achar o processo no Gerenciador de Tarefas - e o nome
    dele e "python.exe", igual a qualquer outra coisa.

    Encerra o lancador, a API e o worker das campanhas. O que ja foi cortado
    fica onde esta; o que estava no meio de um render volta para a fila e e
    refeito na proxima vez que ligar.
#>
param([switch]$Silencioso)

$ErrorActionPreference = "Continue"
$meu = $PID
$parados = 0

# O filtro precisa excluir o proprio PID: o comando desta janela contem as
# mesmas palavras que estou procurando, e ela se mataria antes de terminar.
$alvos = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $meu -and (
        ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'app\.worker|uvicorn app\.main|vod_pc\.py') -or
        ($_.Name -eq 'powershell.exe' -and $_.CommandLine -match 'campanhas-pc\.ps1')
    )
}

foreach ($p in $alvos) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $parados++ } catch { }
}

Start-Sleep -Seconds 3
$sobrou = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $meu -and $_.Name -eq 'python.exe' -and
    $_.CommandLine -match 'app\.worker|uvicorn app\.main|vod_pc\.py'
}).Count

$recado = if ($sobrou -gt 0) {
    "Parei $parados processo(s), mas $sobrou ainda resiste. Tente de novo."
} elseif ($parados -eq 0) {
    "O BotLive nao estava rodando."
} else {
    "BotLive desligado ($parados processo(s))."
}

if ($Silencioso) {
    Write-Host $recado
} else {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($recado, "BotLive",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}
