param([switch]$Apply)
$ErrorActionPreference='Stop';$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location (Join-Path $Root '..');try{git fetch origin;git status --short;if(-not $Apply){Write-Host 'Dry-run concluido. Use -Apply somente apos revisar o diff.';exit 0};if(git status --porcelain){throw 'Ha alteracoes locais; atualizacao cancelada'};git pull --ff-only}finally{Pop-Location}
& (Join-Path $PSScriptRoot 'Install-ShopLive.ps1')
