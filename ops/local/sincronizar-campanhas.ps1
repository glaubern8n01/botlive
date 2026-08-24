<#
    Traz o cadastro de campanhas da VPS para o banco do PC.

    A VPS manda no cadastro (campanha, regra, hashtag, selo, fonte, prazo); o PC
    faz o peso. Os ids sao preservados, entao os dois lados falam da mesma
    campanha. Material, corte e publicacao ficam de cada lado - ver
    app/sincronizar.py.

    Rode sempre que mexer nas campanhas pelo painel.
#>
param(
    [string]$Dados = "G:\botlive-campanhas",
    [string]$Vps = "root@69.62.96.161"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$agente = Join-Path $repo "botlive-campaigns\local-agent"
$foto = Join-Path $env:TEMP "campanhas-vps.json"

Write-Host "Puxando o cadastro da VPS..."
# O script remoto vai em base64: mandar varias linhas direto pelo ssh fazia o
# shell de la quebrar cada linha num argumento e o python recebia "-c" sem nada.
$remoto = @'
C=$(docker ps -q --filter name=botlive_agents | head -1)
docker exec "$C" python -c "
import json,os,sqlite3,sys
# sqlite3 puro de proposito: assim a exportacao nao depende de a VPS estar com
# a imagem mais nova. Sincronizar cadastro nao pode ficar refem de deploy.
db=sqlite3.connect(os.environ['CAMPAIGNS_DATABASE_PATH'])
db.row_factory=sqlite3.Row
foto={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in ('campaign_campaigns','campaign_sources')}
print(json.dumps(foto, ensure_ascii=False))
"
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoto))
ssh -o BatchMode=yes $Vps "echo $b64 | base64 -d | bash" | Out-File -FilePath $foto -Encoding utf8

if (-not (Test-Path $foto)) { throw "nao consegui puxar o cadastro" }

$env:PYTHONPATH = $agente
$env:CAMPAIGNS_DATABASE_PATH = Join-Path $Dados "campaigns.db"
$env:PYTHONUTF8 = "1"

python -c @"
import json,sys
sys.path.insert(0, r'$agente')
from app import store, sincronizar
store.migrate()
with open(r'$foto', encoding='utf-8-sig') as f:
    dados = json.load(f)
print(sincronizar.importar(dados))
for c in store.rows('campaign_campaigns', 200, 0):
    if c['status'] == 'active':
        fontes = store.rows('campaign_sources', 50, 0, 'campaign_id=? AND enabled=1', (c['id'],))
        print(f\"  {c['name']}: {len(fontes)} fonte(s) ligada(s)\")
"@
