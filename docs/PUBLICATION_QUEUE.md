# Fila persistente de publicação

Aplicar, na ordem:

1. `20260725_multi_profile.sql`;
2. `20260725_publication_pipeline.sql`;
3. `20260725_destination_policies.sql`;
4. `20260725_publication_dashboard.sql`.

`publication_jobs` usa `publication_key` única para idempotência. A chave inclui
plataforma, conta, perfil, variante e fingerprint do ativo.

## Estados

`pending → validating → uploading → processing → published`

Estados laterais: `ready`, `retry_wait`, `rejected`, `cancelled` e `failed`.

`claim_publication_job()` usa `FOR UPDATE SKIP LOCKED`, grava `worker_id` e um
lock com expiração. Jobs abandonados voltam a ser elegíveis. Se um job recuperado
já tiver `external_id`, o worker consulta o remoto antes de qualquer novo envio.
Se o upload pode ter ocorrido mas não existe `external_id`, o job vai para
`failed` para reconciliação manual; o worker não arrisca uma duplicata.

## Worker

```powershell
$env:PUBLICATION_QUEUE_ENABLED="1"
python publication_worker.py --once
python publication_worker.py --loop --poll-seconds 5
python publication_worker.py --once --dry-run
```

O modo `--dry-run` faz claim e validação, mas não envia mídia. SIGINT/SIGTERM
encerram o loop de forma graciosa.

Retries temporários usam backoff exponencial. Autenticação e validação não são
repetidas indefinidamente. As tentativas ficam em `publication_attempts`.
