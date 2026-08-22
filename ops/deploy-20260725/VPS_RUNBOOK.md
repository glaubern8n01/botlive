# Runbook VPS — rollout reversível do multi-profile (2026-07-25)

Princípio: **não substituir o BotLive atual**. O legado (Vigia + YouTube/Instagram)
continua rodando no caminho de sempre; o novo só liga por feature flag e o worker
começa em `--dry-run` (não publica nada).

Imagem: `Dockerfile` (python 3.12-slim, entrypoint traduz `BOTLIVE_*` → `main.py`).
O entrypoint tem escape hatch: `docker run <img> python publication_worker.py ...`.
Worker (`publication_worker.py`): `--once` | `--loop`, `--poll-seconds N`, `--dry-run`.

> ⚠️ A orquestração exata na VPS (docker run avulso / compose / systemd, nomes dos
> containers, caminho do `.env` de produção, volume `/data/botlive/output`) será
> **confirmada por inspeção read-only assim que o SSH estiver disponível**, antes
> de qualquer alteração. Os passos abaixo assumem containers Docker.

## 0. Backup ANTES de qualquer mudança

```bash
# no host da VPS
ts=$(date +%Y%m%d_%H%M%S)
mkdir -p ~/botlive-backups/$ts
cp /caminho/prod/.env            ~/botlive-backups/$ts/env.bak          # NÃO versionar
docker ps -a            > ~/botlive-backups/$ts/docker_ps.txt
docker images           > ~/botlive-backups/$ts/docker_images.txt
git -C /caminho/repo rev-parse HEAD > ~/botlive-backups/$ts/git_head.txt
# Supabase: backup é feito no lado do banco (dump/branch) — ver README do deploy.
```

Registrar o HEAD atual em produção e a imagem em uso (para rollback rápido).

## 1. Preparar a branch de forma reversível (sem trocar o que roda)

- Fazer `git fetch` e checar a branch `feat/multi-profile-kwai` num **diretório/worktree
  separado** ou taguear a imagem nova como `botlive:multiprofile` — **sem** parar nem
  recriar os containers legados.
- Build da imagem nova: `docker build -t botlive:multiprofile /caminho/repo`.
- O container legado continua na imagem/HEAD antigos até validarmos tudo.

## 2. Feature flags — ligar gradualmente (KWAI fica OFF)

Fase 1 (inerte para publicação), no `.env` de produção do serviço novo:

```
MULTI_PROFILE_ENABLED=1
PUBLICATION_QUEUE_ENABLED=1
CUT_ENABLED=1
NARRASTARS_ENABLED=1
NEW_PUBLISHER_CONTRACT_ENABLED=0   # só ligar quando formos de fato publicar
KWAI_ENABLED=0
KWAI_API_ENABLED=0                 # MANTER 0 — nada vai ao Kwai
```

Nada aqui publica em Kwai/YouTube/Instagram. O worker em `--dry-run` não envia mídia.

## 3. Worker em dry-run (não publica)

```bash
# um job, dry-run — inspecionar saída
docker run --rm --env-file /caminho/prod/.env botlive:multiprofile \
  python publication_worker.py --once --dry-run

# loop dry-run — validar poll/backoff/persistência
docker run --rm --env-file /caminho/prod/.env botlive:multiprofile \
  python publication_worker.py --loop --poll-seconds 5 --dry-run
```

Validar:
- **logs** legíveis, sem secret vazado;
- **restart**: SIGINT/SIGTERM encerram gracioso (docs/PUBLICATION_QUEUE.md);
- **retries**: backoff exponencial em erro temporário; auth/validação não repetem à toa;
- **persistência**: linhas em `publication_attempts` e transições de `publication_jobs`.

## 4. Dashboard conectado ao Supabase real

- `dashboard/` é Vite. Configurar `dashboard/.env.local` com a URL + anon key do
  Supabase REAL do BotLive (nunca service_role no frontend).
- Subir o dashboard (build/preview ou o serviço já existente) e validar `/perfis`:
  CRUD de `teste_cut`/`teste_narrastars`, associação de contas (só metadados), sem
  exibir `secret_ref` (view `platform_accounts_safe`).

## 5. Não publicar ainda

Enquanto `NEW_PUBLISHER_CONTRACT_ENABLED=0` / `KWAI_API_ENABLED=0` e worker em
`--dry-run`, nenhuma publicação real ocorre. Não fazer merge na `main`.

## Rollback

1. **Flags:** zerar `MULTI_PROFILE_ENABLED`, `PUBLICATION_QUEUE_ENABLED`, `CUT_ENABLED`,
   `NARRASTARS_ENABLED`, `NEW_PUBLISHER_CONTRACT_ENABLED`, `KWAI_ENABLED`,
   `KWAI_API_ENABLED` → o legado volta 100%.
2. **Container:** manter/retomar a imagem antiga; a nova (`botlive:multiprofile`) só é
   promovida após validação.
3. **Código:** `git revert` a partir de `d0fa43331141c347faf5280a27254e88a93d5380`,
   do commit mais recente ao mais antigo. Nunca `reset --hard` em worktree com edições.
4. **Banco:** migrations aditivas — não apagar tabelas; preservar para auditoria.

## O que falta para conectar a primeira conta CUT real

1. Migrations aplicadas + validadas no Supabase real (ver README do deploy).
2. Perfil CUT real (não o `teste_cut`) criado no `/perfis` com destino e conta.
3. `platform_accounts.secret_ref` apontando para a env/secret da conta (ex.:
   `env:KWAI_ACCOUNT_PRINCIPAL`), com o valor **só** no `.env` da VPS.
4. Ligar `NEW_PUBLISHER_CONTRACT_ENABLED=1` e, para Kwai, `KWAI_ENABLED=1` +
   `KWAI_API_ENABLED=1` **somente** com `official_api_authorized=true`, escopo
   `user_video_publish` e autorização regional confirmada (docs/KWAI.md).
5. Worker sem `--dry-run` — e aí, sim, com aprovação explícita, a primeira publicação.
