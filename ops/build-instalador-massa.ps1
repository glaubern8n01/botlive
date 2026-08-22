# Build do aplicativo Windows do Producao em Massa.
#
#   powershell -ExecutionPolicy Bypass -File ops\build-instalador-massa.ps1
#
# Faz, nesta ordem:
#   1. compila o painel (Vite) com a aba Producao em Massa ligada;
#   2. empacota launcher + modulo + painel num unico .exe (PyInstaller);
#   3. gera o instalador (Inno Setup), se o ISCC estiver na maquina.
#
# Nao empacota .env, token, cookie, banco nem sessao - ha uma checagem
# explicita para isso antes do passo 2. FFmpeg e yt-dlp ficam de fora de
# proposito: sao pesados e tem licenca propria (o LEIAME diz como instalar).

param(
    [switch]$PularPainel,   # reaproveita o painel ja compilado
    [switch]$SomenteExe     # nao tenta gerar o instalador
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$modulo = Join-Path $repo "botlive-mass"
$desktop = Join-Path $modulo "desktop"
$painel = Join-Path $desktop "painel"
$dist = Join-Path $modulo "dist"

function Passo($texto) { Write-Host "`n=== $texto" -ForegroundColor Cyan }

# --- 1. painel --------------------------------------------------------------
if (-not $PularPainel) {
    Passo "Compilando o painel (Vite)"
    $dash = Join-Path $repo "dashboard"
    if (-not (Test-Path (Join-Path $dash "node_modules"))) {
        Push-Location $dash; npm ci; Pop-Location
    }
    # So a aba nova entra ligada: o resto do painel continua atras das flags
    # de sempre, exatamente como no navegador.
    #
    # Vai por arquivo, e nao por $env:, porque no PowerShell atribuir "" APAGA a
    # variavel - o Vite recebia undefined, caia no endereco padrao 127.0.0.1:8825
    # e a pagina dava "Failed to fetch" quando o app subia em outra porta. No
    # arquivo, vazio e vazio mesmo: caminho relativo, a propria API serve tudo.
    $envLocal = Join-Path $dash ".env.production.local"
    $tinha = Test-Path $envLocal
    if ($tinha) { Copy-Item $envLocal "$envLocal.bak" -Force }
    Set-Content -Path $envLocal -Encoding utf8 -Value @(
        "VITE_MASS_ENABLED=true",
        "VITE_MASS_API_URL="
    )
    try {
        Push-Location $dash
        npm run build
        Pop-Location
    } finally {
        # O arquivo e so do build do app: deixar para tras mudaria o `npm run
        # dev` do Glauber depois.
        Remove-Item $envLocal -Force -ErrorAction SilentlyContinue
        if ($tinha) { Move-Item "$envLocal.bak" $envLocal -Force }
    }
    if (Test-Path $painel) { Remove-Item $painel -Recurse -Force }
    Copy-Item (Join-Path $dash "dist") $painel -Recurse
} else {
    Passo "Painel: reaproveitando $painel"
}

# --- checagem de segredos ---------------------------------------------------
Passo "Conferindo que nenhum segredo vai junto"
$proibidos = @("*.env", ".env*", "*token*.txt", "*cookies*", "*.db", "state.json")
$achados = @()
foreach ($padrao in $proibidos) {
    $achados += Get-ChildItem -Path $painel, $desktop -Recurse -Filter $padrao -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "LEIAME.txt" }
}
if ($achados.Count -gt 0) {
    $achados | ForEach-Object { Write-Host "  ! $($_.FullName)" -ForegroundColor Red }
    throw "Arquivo sensivel na pasta de empacotamento. Remova antes de continuar."
}
Write-Host "  ok - nada sensivel em desktop\ nem em painel\"

# --- 2. executavel ----------------------------------------------------------
Passo "Empacotando o executavel (PyInstaller)"
python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller nao instalado. Rode: python -m pip install pyinstaller"
}
Push-Location $desktop
python -m PyInstaller --noconfirm --clean `
    --distpath $dist --workpath (Join-Path $modulo "build") `
    "botlive-massa.spec"
Pop-Location

$exe = Join-Path $dist "BotLive-Massa.exe"
if (-not (Test-Path $exe)) { throw "Build terminou sem gerar $exe" }
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "  ok - $exe ($mb MB)"

# --- 3. instalador ----------------------------------------------------------
if ($SomenteExe) {
    Write-Host "`nPronto (so o exe, por opcao)." -ForegroundColor Green
    exit 0
}

Passo "Gerando o instalador (Inno Setup)"
# O winget instala o Inno Setup por usuario quando nao ha administrador,
# entao a pasta do perfil entra na busca junto com as duas do sistema.
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $noPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($noPath) { $iscc = $noPath.Source }
}

if (-not $iscc) {
    Write-Host "  Inno Setup nao encontrado - o .exe portatil acima ja funciona." -ForegroundColor Yellow
    Write-Host "  Para gerar o BotLive-Setup-Test.exe, instale e rode de novo:" -ForegroundColor Yellow
    Write-Host "      winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}

& $iscc (Join-Path $desktop "instalador.iss")
$setup = Join-Path $dist "BotLive-Setup-Test.exe"
if (Test-Path $setup) {
    $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host "`nInstalador pronto: $setup ($mb MB)" -ForegroundColor Green
} else {
    throw "ISCC rodou mas nao gerou $setup"
}
