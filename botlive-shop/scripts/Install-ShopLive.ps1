param([switch]$InstallFFmpeg)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Agent=Join-Path $Root 'apps\local-agent'
Write-Host 'Validando dependencias locais...'
foreach($Command in @('python','node','npm')){if(-not (Get-Command $Command -ErrorAction SilentlyContinue)){throw "Dependencia ausente: $Command"}}
if(-not (Get-Command ffprobe -ErrorAction SilentlyContinue)){
  if($InstallFFmpeg){if(-not (Get-Command winget -ErrorAction SilentlyContinue)){throw 'winget ausente; instale FFmpeg manualmente e confirme ffprobe no PATH'};winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements}
  else{throw 'ffprobe ausente. Execute novamente com -InstallFFmpeg ou instale FFmpeg por uma fonte confiavel.'}
}
if(-not (Test-Path (Join-Path $Agent '.venv\Scripts\python.exe'))){python -m venv (Join-Path $Agent '.venv')}
& (Join-Path $Agent '.venv\Scripts\python.exe') -m pip install -r (Join-Path $Agent 'requirements-dev.txt')
Push-Location (Join-Path $Root '..\dashboard');try{npm ci;npm run build}finally{Pop-Location}
Push-Location (Join-Path $Root 'apps\extension');try{npm ci}finally{Pop-Location}
$Data=Join-Path $Root 'data';New-Item -ItemType Directory -Force -Path (Join-Path $Data 'media'),(Join-Path $Data 'backups'),(Join-Path $Data 'run')|Out-Null
$EnvFile=Join-Path $Root '.env.local'
if(-not (Test-Path $EnvFile)){
  $Bytes=New-Object byte[] 32;[Security.Cryptography.RandomNumberGenerator]::Fill($Bytes);$Token=[Convert]::ToHexString($Bytes).ToLowerInvariant()
  @("SHOP_LIVE_LOCAL_TOKEN=$Token","SHOP_LIVE_AUTH_DISABLED=false","SHOP_LIVE_DATABASE_URL=sqlite:///./data/shop-live.db","SHOP_LIVE_MEDIA_ROOT=./data/media","SHOP_LIVE_BACKUP_ROOT=./data/backups","SHOP_LIVE_ALLOWED_ORIGINS=http://127.0.0.1:3017")|Set-Content -LiteralPath $EnvFile -Encoding UTF8
  Write-Host 'Configuracao local criada. Guarde o token exibido apenas no computador:';$Token
}
Push-Location $Agent;try{& '.\.venv\Scripts\python.exe' -m alembic upgrade head}finally{Pop-Location}
Write-Host 'Shop LIVE instalado. Carregue apps/extension como extensao descompactada e execute Start-ShopLive.ps1.'
