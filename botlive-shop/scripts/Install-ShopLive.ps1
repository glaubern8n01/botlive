param([switch]$InstallFFmpeg)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Agent=Join-Path $Root 'apps\local-agent'
$Data=Join-Path $Root 'data';New-Item -ItemType Directory -Force -Path $Data,(Join-Path $Data 'media'),(Join-Path $Data 'backups'),(Join-Path $Data 'run')|Out-Null
$EnvFile=Join-Path $Root '.env.local'
if(-not (Test-Path $EnvFile)){
  $Bytes=New-Object byte[] 32;$Rng=[Security.Cryptography.RandomNumberGenerator]::Create();$Rng.GetBytes($Bytes);$Rng.Dispose();$Token=($Bytes|ForEach-Object{$_.ToString('x2')}) -join ''
  @("SHOP_LIVE_LOCAL_TOKEN=$Token","SHOP_LIVE_AUTH_DISABLED=false","SHOP_LIVE_ALLOWED_ORIGINS=http://127.0.0.1:3017")|Set-Content -LiteralPath $EnvFile -Encoding UTF8
  Write-Host 'Configuracao local criada em .env.local; o token nao sera exibido em logs.'
}
Get-Content -LiteralPath $EnvFile|ForEach-Object{if($_ -match '^([^#=]+)=(.*)$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}}
Write-Host 'Validando dependencias locais...'
foreach($Command in @('python','node','npm')){if(-not (Get-Command $Command -ErrorAction SilentlyContinue)){throw "Dependencia ausente: $Command"}}
$NodeMajor=[int]((node --version).TrimStart('v').Split('.')[0]);if($NodeMajor -lt 22){throw 'Node.js 22 ou superior e obrigatorio pelas dependencias atuais do dashboard.'}
if(-not (Get-Command ffprobe -ErrorAction SilentlyContinue)){
  if($InstallFFmpeg){if(-not (Get-Command winget -ErrorAction SilentlyContinue)){throw 'winget ausente; instale FFmpeg manualmente e confirme ffprobe no PATH'};winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements}
  else{throw 'ffprobe ausente. Execute novamente com -InstallFFmpeg ou instale FFmpeg por uma fonte confiavel.'}
}
if(-not (Test-Path (Join-Path $Agent '.venv\Scripts\python.exe'))){python -m venv (Join-Path $Agent '.venv')}
& (Join-Path $Agent '.venv\Scripts\python.exe') -m pip install -r (Join-Path $Agent 'requirements-dev.txt');if($LASTEXITCODE -ne 0){throw 'Falha ao instalar dependencias Python'}
Push-Location (Join-Path $Root '..\dashboard');try{npm ci;if($LASTEXITCODE -ne 0){throw 'Falha ao instalar dependencias do dashboard'};$env:VITE_SHOP_LIVE_ENABLED='true';npm run build;if($LASTEXITCODE -ne 0){throw 'Falha ao compilar dashboard'}}finally{Pop-Location}
& (Join-Path $Agent '.venv\Scripts\python.exe') -m alembic -c (Join-Path $Agent 'alembic.ini') upgrade head;if($LASTEXITCODE -ne 0){throw 'Falha na migracao Alembic'}
Write-Host 'Shop LIVE instalado. Carregue apps/extension como extensao descompactada e execute Start-ShopLive.ps1.'
