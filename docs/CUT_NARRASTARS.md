# Estratégias CUT e Narrastars

Ambas são opt-in (`CUT_ENABLED` e `NARRASTARS_ENABLED`) e não substituem
detecção, `smart_window`, `clipper`, `vertical_meme`, captions ou overlays.

## CUT

`CutPolicy` configura duração, pre/post-evento, gancho, captions, headline,
branding, CTA, layout e áudio. `CutStrategy` gera uma `EditorialVariant` com
janela material. Regras comerciais não são hardcoded.

## Narrastars

Pipeline de domínio:

`ContentEvent → contexto → ScriptGenerator → NarrationProvider → variante`

`ScriptGenerator` e `NarrationProvider` são protocolos independentes de
fornecedor. O fallback produz roteiro simples e nenhuma narração. Quando o perfil
exige narração mas não existe provider, pode retornar `prepare_only`.

Uma variante precisa alterar janela, gancho, cenas, crop, narração, contexto,
áudio ou texto queimado. Fonte, cor ou título isolados não geram assinatura.
