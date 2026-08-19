# Importar / Adaptar / Publicar

Importa material **próprio, licenciado ou autorizado**, adapta ao padrão visual
do canal e entrega para a fila do VexPublish.

**Estado: IMPLEMENTADO + VALIDADO LOCALMENTE. Nenhuma publicação real.**
Módulo desligado por padrão — com `IMPORT_ADAPT_PUBLISH_ENABLED=false` a API
inteira responde 404.

## Fluxo

```
Fonte autorizada  →  Importação em lote  →  Biblioteca (dedup SHA-256)
        →  Plano de adaptação  →  Render + validação  →  Fila por canal
        →  PublishJob (draft, dry-run, aguardando aprovação)
```

## O que ele não faz

O documento do projeto é explícito: a finalidade **não** é apagar autoria nem
contornar direitos. Isso virou código, não comentário:

- Fonte sem `authorized`, sem quem autorizou e sem licença conhecida **não entra**.
- O plano de adaptação recusa qualquer chave de apropriação — `remove_watermark`,
  `remove_credits`, `strip_attribution`, `bypass_drm` e companhia — antes de
  qualquer render.
- `keep_credit=false` é recusado: o crédito da origem fica.
- Download automático precisa de **dois interruptores**: `IMPORT_ALLOW_DOWNLOAD=true`
  no ambiente **e** `allow_download` marcado naquela fonte.

## Estrutura

```
botlive-import/
├── local-agent/importer/
│   ├── store.py      banco isolado (import.db), 5 tabelas
│   ├── sources.py    fontes autorizadas e os dois interruptores de download
│   ├── library.py    biblioteca, dedup por SHA-256, metadados via ffprobe
│   ├── adapt.py      plano validado + render reaproveitando o motor do BotLive
│   ├── bridge.py     fila por canal → PublishJob no VexPublish
│   └── main.py       API local autenticada por papel
├── migrations/       upgrade/downgrade
└── tests/            44 testes
```

O pacote se chama `importer`, e não `app`, de propósito: `botlive-campaigns`
já usa `app`, e dois pacotes com o mesmo nome se sobrescrevem no mesmo
interpretador.

## Adaptação

Reaproveita o que o BotLive já tem, sem duplicar motor:

| Etapa | De onde vem |
|---|---|
| proporção, recorte, reenquadramento | `clipper.renderizar_layout` |
| tarjas, título, identidade, CTA | `overlay_editor.OverlayConfig` |
| validação da saída | `clipper.validar_video_final` |

Render que falha marca a adaptação como `failed` com o motivo — **o item
original nunca é alterado nem apagado**.

## Uso

```bash
python botlive-import/migrations/manage.py upgrade
python -m pytest botlive-import/tests -q
```

## Ainda não feito

- Download real por yt-dlp/gallery-dl (os dois interruptores existem; o executor não).
- Legendas automáticas e intro/outro estão no plano, mas não no executor.
- Worker de longa duração (hoje o render é síncrono pela API).
