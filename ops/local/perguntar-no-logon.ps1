<#
    Pergunta, ao ligar o PC, se o BotLive deve rodar agora.

    Antes o atalho do Startup subia o bot calado. O problema é que este PC
    também é onde o Glauber trabalha: render de vídeo é a coisa mais pesada que
    a máquina faz, e não dá para ela ficar lenta sem ele ter escolhido isso.

    Por isso aqui a decisão é dele, toda vez:
      Sim  -> sobe campanhas (e o VOD, se marcado) em prioridade baixa
      Não  -> não sobe nada; dá para ligar depois pelo atalho "Ligar BotLive"

    Prioridade BelowNormal não deixa o bot mais lento de forma relevante - ele
    passa o tempo esperando ffmpeg -, mas garante que o navegador, o editor e
    os jogos ganham a CPU sempre que precisarem.
#>
param(
    [int]$Atraso = 90,
    [switch]$SemPerguntar
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if ($Atraso -gt 0) { Start-Sleep -Seconds $Atraso }

# Já está de pé? Então não há o que perguntar.
try {
    $viva = Invoke-WebRequest -Uri "http://127.0.0.1:8775/campaigns/v1/health" `
        -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    if ($viva.StatusCode -eq 200) { exit 0 }
} catch { }

$rodar = $true
if (-not $SemPerguntar) {
    Add-Type -AssemblyName System.Windows.Forms
    $resposta = [System.Windows.Forms.MessageBox]::Show(
        "Ligar o BotLive agora?" + [Environment]::NewLine + [Environment]::NewLine +
        "Ele corta as campanhas sozinho e usa bastante CPU." + [Environment]::NewLine +
        "Se voce vai mexer no PC, escolha Nao - da para ligar depois pelo atalho.",
        "BotLive",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2)
    $rodar = ($resposta -eq [System.Windows.Forms.DialogResult]::Yes)
}

if (-not $rodar) { exit 0 }

& (Join-Path $PSScriptRoot "campanhas-pc.ps1")
