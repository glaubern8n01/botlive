<#
    Campanhas de Cortes rodando no PC.

    Por que no PC: render de campanha e trabalho pesado e em lote. Na VPS ele
    briga com o vigia e com o produtor do Kwai - que sao o que ja da dinheiro -
    e em 23/08/2026 a Hostinger estrangulou a maquina (95% de steal time),
    matando um render depois de 37 minutos de gravacao e transcricao ja pagos.

    A VPS continua com o cadastro das campanhas e com o que ja funciona. O PC
    faz o peso: baixar a live, transcrever, escolher o corte pela fala,
    renderizar o vertical e queimar o selo.

    Uso:
        powershell -ExecutionPolicy Bypass -File ops\local\campanhas-pc.ps1
        powershell -ExecutionPolicy Bypass -File ops\local\campanhas-pc.ps1 -SoWorker
#>
param(
    [string]$Dados = "G:\botlive-campanhas",
    [int]$Porta = 8775,
    [int]$Atraso = 0,
    [switch]$SoWorker,
    [switch]$SoApi
)

$ErrorActionPreference = "Stop"

# Usado pelo atalho do startup. O boot desta maquina caiu de 5 min para 40s
# depois que o autostart foi limpo; nada nosso pode entrar competindo com o
# logon. Espera o desktop assentar e so entao comeca.
if ($Atraso -gt 0) {
    Write-Host "Esperando $Atraso s antes de subir (boot)."
    Start-Sleep -Seconds $Atraso
}
# Ja tem uma instancia de pe? Sai calado. O atalho do startup dispara a cada
# logon, e sem esta checagem um logoff/logon subiria um segundo worker que
# so ia brigar pela mesma fila e falhar ao abrir a porta.
try {
    $viva = Invoke-WebRequest -Uri "http://127.0.0.1:$Porta/campaigns/v1/health" `
        -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    if ($viva.StatusCode -eq 200) {
        Write-Host "Ja tem campanha rodando na porta $Porta. Nada a fazer."
        exit 0
    }
} catch { }

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$agente = Join-Path $repo "botlive-campaigns\local-agent"

foreach ($sub in @("", "midia", "saidas", "selos")) {
    $alvo = if ($sub) { Join-Path $Dados $sub } else { $Dados }
    if (-not (Test-Path $alvo)) { New-Item -ItemType Directory -Force $alvo | Out-Null }
}

$env:PYTHONPATH             = $agente
$env:CAMPAIGNS_ENABLED      = "true"
$env:CAMPAIGNS_DATABASE_PATH = Join-Path $Dados "campaigns.db"
$env:CAMPAIGNS_MEDIA_ROOT   = Join-Path $Dados "midia"
$env:CAMPAIGNS_OUTPUT_ROOT  = Join-Path $Dados "saidas"
$env:CAMPAIGNS_LAYOUT       = "vertical-crop"
$env:PYTHONUNBUFFERED       = "1"
$env:PYTHONUTF8             = "1"

# O AVG faz MITM de TLS e o Python 3.14 recusa a CA dele. Sem isto, yt-dlp e
# streamlink morrem em verificacao de certificado nesta maquina.
if (-not $env:BOTLIVE_TLS_NO_VERIFY) { $env:BOTLIVE_TLS_NO_VERIFY = "1" }

$cookies = Join-Path $Dados "cookies-youtube.txt"
if (Test-Path $cookies) { $env:CAMPAIGNS_COOKIES_FILE = $cookies }

# Token so para a API local. Fica num arquivo com o resto dos dados, nunca no
# repositorio.
$arquivoToken = Join-Path $Dados "token.txt"
if (-not (Test-Path $arquivoToken)) {
    $novo = -join ((1..24) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
    Set-Content -Path $arquivoToken -Value $novo -Encoding utf8 -NoNewline
}
$env:CAMPAIGNS_ADMIN_TOKEN = (Get-Content $arquivoToken -Raw).Trim()

Write-Host "Dados em: $Dados"
Write-Host "Banco:    $($env:CAMPAIGNS_DATABASE_PATH)"

python (Join-Path $repo "botlive-campaigns\migrations\manage.py") upgrade
if (-not $?) { throw "migracao falhou" }

$processos = @()
if (-not $SoWorker) {
    Write-Host "API em http://127.0.0.1:$Porta/campaigns/v1/health"
    $processos += Start-Process -PassThru -NoNewWindow python `
        -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$Porta","--no-access-log" `
        -WorkingDirectory $agente
}
if (-not $SoApi) {
    Write-Host "Worker ligado: varre as fontes a cada 10 min e corta sozinho."
    $processos += Start-Process -PassThru -NoNewWindow python `
        -ArgumentList "-m","app.worker" -WorkingDirectory $agente
}

Write-Host "Ctrl+C encerra. PIDs: $($processos.Id -join ', ')"
try {
    while ($true) {
        Start-Sleep -Seconds 5
        foreach ($p in $processos) {
            if ($p.HasExited) { throw "processo $($p.Id) caiu com codigo $($p.ExitCode)" }
        }
    }
} finally {
    foreach ($p in $processos) {
        if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
}
