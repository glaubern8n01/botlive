param([string]$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path)
$ErrorActionPreference='Stop'
$Install=Join-Path $Root 'scripts\Install-ShopLive.ps1';$Start=Join-Path $Root 'scripts\Start-ShopLive.ps1';$Stop=Join-Path $Root 'scripts\Stop-ShopLive.ps1'
try {
  & $Install
  & $Start -Mode production
  $Token=((Get-Content (Join-Path $Root '.env.local')|Where-Object{$_ -like 'SHOP_LIVE_LOCAL_TOKEN=*'}) -split '=',2)[1];$Headers=@{'X-Shop-Live-Token'=$Token}
  for($Attempt=0;$Attempt -lt 30;$Attempt++){try{$Route=Invoke-WebRequest 'http://127.0.0.1:3017/shop-live' -UseBasicParsing;if($Route.StatusCode -eq 200 -and $Route.Content -match '<div id="root">'){break}}catch{};Start-Sleep -Milliseconds 500};if($Attempt -ge 30){throw 'Rota SPA /shop-live não respondeu'}
  if(-not (Invoke-RestMethod 'http://127.0.0.1:8765/shop-live/v1/health' -Headers $Headers).ok){throw 'Autenticação/health falhou'}
  $Wave=Join-Path $env:TEMP 'shop-live-clean-install.wav';$Samples=New-Object byte[] 16000;$Writer=New-Object IO.BinaryWriter([IO.File]::Create($Wave));$Writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF'));$Writer.Write([int](36+$Samples.Length));$Writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '));$Writer.Write([int]16);$Writer.Write([int16]1);$Writer.Write([int16]1);$Writer.Write([int]8000);$Writer.Write([int]16000);$Writer.Write([int16]2);$Writer.Write([int16]16);$Writer.Write([Text.Encoding]::ASCII.GetBytes('data'));$Writer.Write([int]$Samples.Length);$Writer.Write($Samples);$Writer.Dispose()
  $Uploaded=Invoke-RestMethod 'http://127.0.0.1:8765/shop-live/v1/media/upload' -Method Post -Headers $Headers -Form @{file=Get-Item $Wave;authorized='true';authorization_source='Teste limpo Windows'};$Library=Invoke-RestMethod 'http://127.0.0.1:8765/shop-live/v1/library' -Headers $Headers;if($Library.media.id -notcontains $Uploaded.id){throw 'Upload não apareceu na biblioteca'}
  $Storage=Invoke-RestMethod 'http://127.0.0.1:8765/shop-live/v1/storage' -Headers $Headers;$Backup=Invoke-RestMethod 'http://127.0.0.1:8765/shop-live/v1/backup' -Method Post -Headers $Headers;$Expected=[IO.Path]::GetFullPath((Join-Path $Root 'data'))
  foreach($Path in @((Join-Path $Root 'data\shop-live.db'),$Storage.root,$Backup.root,(Join-Path $Root 'data\run'))){if(-not ([IO.Path]::GetFullPath($Path)).StartsWith($Expected,[StringComparison]::OrdinalIgnoreCase)){throw "Caminho fora de data: $Path"}}
  Write-Host "CLEAN_INSTALL_OK data=$Expected media=$($Storage.root) backup=$($Backup.root)"
} finally { & $Stop;Remove-Item -LiteralPath (Join-Path $env:TEMP 'shop-live-clean-install.wav') -Force -ErrorAction SilentlyContinue }
