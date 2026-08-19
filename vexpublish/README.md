# VexPublish

Camada compartilhada de publicação do BotLive. Recebe `PublishJob` de qualquer
produtor (Campanhas de Cortes, Importar/Adaptar/Publicar, Commerce Studio) e
cuida de fila, agendamento, limites, sessões, tentativas e histórico.

**Estado atual: IMPLEMENTADO + VALIDADO LOCALMENTE. Nenhuma publicação real.**
Os quatro adapters existem com contrato completo, mas o passo `publish` de todos
levanta `MANUAL_ACTION_REQUIRED` — nada foi ligado a plataforma nenhuma.

## Por que ele existe

Hoje a publicação do BotLive é direta: `social_publisher.py` chama o plugin de
cada rede. Não há job, nem chave de idempotência, nem lock, nem multi-conta.
O VexPublish existe para que o produtor de conteúdo pare de falar com
navegador/API e passe a produzir jobs auditáveis.

Ele **não substitui** `yt_publisher.py`, `instagram_publisher.py` nem
`tiktok_publisher.py` nesta fase. Roda ao lado, desligado.

## Estrutura

```
vexpublish/
├── core/        flags, errors (códigos + máquina de estados), obs (log), store, models
├── queue/       lock, execução, retry com backoff, recuperação de órfãos
├── scheduler/   janela de horário, intervalo mínimo, teto diário por conta
├── accounts/    registro, ativação e limites
├── sessions/    cofre por conta+plataforma, fora do repositório
├── adapters/    contrato + TikTok, Instagram, YouTube, Kwai, mock de teste
├── core/analytics.py  comparação entre canais e snapshots de métrica
├── api.py       API local que serve a aba de canais do dashboard
├── migrations/  upgrade/downgrade do banco isolado
└── tests/       86 testes
```

## Multi-canais

Cada canal é uma marca própria: nicho, identidade, voz, plataformas, calendário
e contas. As contas carregam os limites (`max_posts_per_day`,
`minimum_interval_minutes`, `allowed_hours`) — nenhum número fica fixo no código.

A comparação entre canais mostra publicações, frequência, falhas por código,
taxa de sucesso, views, retenção e receita. **Métrica sem snapshot registrado
volta como traço, não como zero** (`sem_metricas: true`): dado ausente e
desempenho ruim não são a mesma coisa.

A API sobe com multi-canais ligado e é autenticada por papel
(`admin`/`operator`/`reviewer`). Gerenciar canal e conta não publica nada;
aprovar e enfileirar apenas movem o job na fila, que segue presa às flags.

## Ciclo do PublishJob

```
draft ──aprovar──▶ approved ──▶ pending ─┐
                                scheduled ┴─▶ publishing ─┬─▶ posted
                                                          ├─▶ retry ──▶ publishing
                                                          └─▶ failed
```

`cancelled` sai de draft/approved/pending/scheduled/retry/failed.
`posted` e `cancelled` são terminais e não revivem.

## Garantias que os testes cobrem

| Garantia | Como |
|---|---|
| Job não roda duas vezes | `idempotency_key` única + claim atômico com `BEGIN IMMEDIATE` e guarda de status |
| Dry-run não publica | `adapters.base.executar` para depois de `prepare`; `publish` nunca é chamado |
| Publicação real exige 3 condições | `VEXPUBLISH_ENABLED` + plataforma habilitada + `DRY_RUN=false` |
| Upload iniciado não é publicação | adapter precisa devolver `url` ou `external_id`, senão vira `UPLOAD_FAILED` |
| Captcha/2FA não é contornado | sessão vai para `manual_required` e trava a execução |
| Limite não é fixo no código | `max_posts_per_day`, `minimum_interval_minutes` e `allowed_hours` são por conta |
| Log não vaza segredo | `core/obs.py` mascara cookie, token, senha, authorization, session_id, api_key |
| Retry não vira loop | backoff exponencial com teto e `max_attempts` |

## Uso

```bash
python vexpublish/migrations/manage.py upgrade
python -m pytest vexpublish/tests -q
```

Flags e caminhos: veja `.env.example`. Todas nascem `false`, com `DRY_RUN=true`.

## Ainda não feito

- Nenhum adapter validado com login real (`compatibilidade = NAO VALIDADO` nos quatro).
- Kwai sem rota confirmada — ordem de investigação documentada em `adapters/kwai.py`.
- Worker de longa duração e dashboard próprio.
- Migração dos publishers legados para os adapters.
