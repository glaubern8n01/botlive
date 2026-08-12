# BotLive Campanhas de Cortes

Módulo local isolado para campanhas remuneradas. Ele reutiliza o detector e o renderizador do BotLive por adaptador, mas mantém banco, mídia, fila, worker, rotas, limites e pausa próprios. A feature flag nasce desligada e não existe publicação automática.

## Capacidades

- campanhas e regras estruturadas;
- upload autorizado em quarentena com extensão/MIME/assinatura, SHA-256, deduplicação e `ffprobe` com timeout;
- fila SQLite com claim atômico, heartbeat, retries, backoff, cancelamento e recuperação de órfãos;
- detecção pelo `highlight_detector.py` e render 1080×1920 pelo `clipper.py` legado;
- texto/gancho/marca autorizada queimados no vídeo e arquivo SRT acompanhante;
- checklist crítico, revisão humana e comparação original/corte;
- canais, exportação manual para celular por link temporário, métricas, pagamentos, CSV e auditoria;
- papéis `admin`, `operator` e `reviewer`, autorização backend e rate limit de endpoints sensíveis.

## Execução local segura

Use Python 3.12+ com FFmpeg e FFprobe no PATH. Instale `local-agent/requirements.txt`. Configure os valores de `.env.example` em seu gerenciador de ambiente e mantenha:

```env
CAMPAIGNS_ENABLED=true
CAMPAIGNS_DRY_RUN=true
CAMPAIGNS_PAUSED=false
```

Migre e inicie apenas os componentes novos:

```powershell
python botlive-campaigns/migrations/manage.py upgrade
uvicorn app.main:app --app-dir botlive-campaigns/local-agent --host 127.0.0.1 --port 8775
python -m app.worker  # executar a partir de botlive-campaigns/local-agent
```

No dashboard:

```env
VITE_CAMPAIGNS_ENABLED=true
VITE_CAMPAIGNS_API_URL=http://127.0.0.1:8775
```

Os tokens ficam somente em `sessionStorage`. O backend não usa cookie/sessão, portanto CSRF baseado em cookie não se aplica; CORS é limitado às origens configuradas. Nenhuma senha social é armazenada.

## Fluxo dry-run

1. Cadastre campanha e regras.
2. Faça upload apenas de arquivo autorizado.
3. Enfileire detecção e execute o worker.
4. Renderize o candidato e confira os dois players/checklist.
5. Aprove manualmente.
6. Gere pacote ZIP com vídeo, texto e manifesto. O link móvel expira em 15 minutos.
7. Publique manualmente fora do BotLive e registre depois a URL/métricas.

TikTok não é descrito como “rascunho automático”: o MVP fornece `ready_for_manual_publication`. APIs das plataformas externas não são chamadas.

## Testes

```powershell
python -m unittest discover -s botlive-campaigns/tests -v
npm run lint --prefix dashboard
npm run build --prefix dashboard
```

O smoke real usa um vídeo sintético local, produz saída 1080×1920 H.264/AAC e a valida novamente com o motor legado. Artefatos ficam em `botlive-campaigns/rendered-tests/`, ignorados pelo Git.

## Migração e rollback

`manage.py upgrade` é idempotente. Para testar rollback em um banco temporário, use `downgrade --confirm`. Em operação, prefira backup/restauração do `campaigns.db`; nunca aponte `CAMPAIGNS_DATABASE_PATH` para banco legado.

Rollback de aplicação: desligue `VITE_CAMPAIGNS_ENABLED` e `CAMPAIGNS_ENABLED`. Isso remove a aba e bloqueia as rotas sem tocar no dashboard, filas ou serviços do BotLive original.

## Limitações honestas

- transcrição automática do motor legado ainda é um stub; o módulo gera SRT/texto a partir dos metadados aprovados, sem alegar transcrição por IA;
- integrações externas permanecem manuais até API, escopos e termos oficiais serem aprovados;
- controle rígido de CPU/memória deve ser aplicado pelo serviço/container; internamente a concorrência padrão é um worker;
- HTTPS para link móvel depende do proxy local/VPS e não é ativado por este módulo.
