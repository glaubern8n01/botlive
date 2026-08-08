$ErrorActionPreference='Stop';$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path;$Run=Join-Path $Root 'data\run'
foreach($Name in @('agent','dashboard')){$File=Join-Path $Run "$Name.pid";if(Test-Path $File){$IdValue=[int](Get-Content -LiteralPath $File);$Process=Get-Process -Id $IdValue -ErrorAction SilentlyContinue;if($Process){Stop-Process -Id $IdValue};Remove-Item -LiteralPath $File -Force}}
Write-Host 'Processos locais do Shop LIVE encerrados.'
