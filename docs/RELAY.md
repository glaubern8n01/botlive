# Relay de download residencial — Kwai CUT

## Por que existe
O YouTube bloqueia downloads do IP da VPS (datacenter): `Sign in to confirm
you're not a bot`, mesmo com yt-dlp nightly, todos os player_client e PO Token.
Confirmado empiricamente. Cloud gratuito também é datacenter (bloqueado).

Uma máquina em **conexão residencial NÃO é bloqueada**. O relay roda nela: baixa
o vídeo, valida, envia o MP4 para o volume da VPS e registra a fonte como
`local_file`. O produtor na VPS corta/edita **sem baixar nada** (via
`resolver_fonte_video`, que aceita arquivo local).

Cadeia validada ponta a ponta: 1 corte real 1080×1920 H.264/AAC, `valid`, com
legenda/hashtags/créditos, `GET 200` e `Range 206` no player/download.

## Requisitos
- Python + `yt-dlp` + `ffmpeg/ffprobe` na máquina residencial.
- `.env` local com `ROBO_SUPABASE_URL` e `ROBO_SUPABASE_KEY` (NÃO versionar).
- Chave SSH para a VPS em `~/.ssh/id_ed25519` (NÃO versionar).

## Variáveis (todas com default; nenhuma é segredo)
| Var | Default | Uso |
|-----|---------|-----|
| `VPS_HOST` | `root@69.62.96.161` | host SSH da VPS |
| `VPS_SSH_KEY` | `~/.ssh/id_ed25519` | chave SSH (arquivo, fora do Git) |
| `VPS_OUTPUT_VOLUME` | `/etc/easypanel/projects/botlive/botlive-app/volumes/botlive-output` | caminho do volume no host que o container vê como `/data/botlive/output` |
| `RELAY_WORK` | `~/.botlive-relay` | pasta temporária local (apagada após envio) |

## Uso
```bash
# processa 3 candidatos de review_required
python relay_run.py --limit 3

# mantém o estoque em 30, repondo quando cair (o PC precisa estar ligado)
python relay_run.py --limit 30 --loop --target 30
```

## Estoque em vez de 24/7
O relay mantém um buffer de vídeos prontos. Não é preciso o PC ligado o tempo
todo — só o suficiente para repor o estoque; postar consome do estoque. Para
24/7 real sem o PC principal, rode o mesmo `relay_run.py` num aparelho barato
sempre-ligado em casa (Raspberry Pi, ou celular via Termux).

## Auto-start no Windows (roda quando o PC liga)
```powershell
$action  = New-ScheduledTaskAction -Execute "python" -Argument "G:\botlive\relay_run.py --limit 30 --loop" -WorkingDirectory "G:\botlive"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "BotLiveRelay" -Action $action -Trigger $trigger -Description "Relay Kwai CUT (download residencial)"
```

## Fallbacks de download (`robust_downloader.py`)
Ordem: 1) MP4/HLS direto (ffmpeg) · 2) yt-dlp multi-client · 3) yt-dlp
cookies+PO token (`BOTLIVE_COOKIES_FILE`) · 4) relay (`DOWNLOAD_RELAY_URL`).
Detecta o bot-block e encaminha automaticamente.

## Segurança
`.env`, cookies e a chave SSH ficam **fora do Git**. O relay não imprime nem
versiona segredos; usa apenas variáveis de ambiente.
