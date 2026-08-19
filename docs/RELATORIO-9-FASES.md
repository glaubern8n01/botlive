# BOTLIVE — RELATÓRIO TÉCNICO DAS 9 FASES

Execução do documento `BotLive_TikTokShop_Arquitetura_e_Prompts_Completos.docx`
(consolidado em 18/08/2026), Prompt Mestre 1 e Prompt Mestre 2.

**Branch:** `feat/botlive-multichannel-vexpublish` (a partir de `feat/campanhas-cortes-completo`)

| Regra absoluta | Cumprida |
|---|---|
| Processos interrompidos | **NENHUM** |
| Deploy | **NÃO** |
| Push | **NÃO** |
| PR | **NÃO** |
| Publicação real | **NÃO** |
| Commit | **NÃO** (aguardando aprovação) |
| Alterações locais preservadas | sim |

## Números

**282 testes passando.** 8.371 linhas de Python novo, mais 302 linhas alteradas
em Campanhas de Cortes.

| Módulo | Linhas | Testes | Fase |
|---|---|---|---|
| `vexpublish/` | 3.836 | 106 | 1, 2, 4, 9 |
| `botlive-commerce/` | 2.084 | 51 | 7, 8 |
| `botlive-import/` | 1.545 | 44 | 5 |
| `botlive-media/` | 906 | 34 | 6 |
| `botlive-campaigns/` (evoluído) | +302 | 47 | 3 |

## Fase a fase

### Fase 0 — Auditoria
Mapeado o repositório (183 arquivos versionados, 3 sub-projetos, dashboard React
com 7 páginas). Achados que mudaram o plano: `Canais` já existia com outro
significado (canais Twitch de origem), VexPublish não existia, e Campanhas de
Cortes já tinha 12 tabelas e as 6 subabas.

### Fase 1 + 2 — Core e VexPublish
`Channel`, `Account`, `Session`, `MediaAsset`, `PublishJob`, máquina de estados
de 9 status, fila com lock atômico, scheduler, sessões isoladas, 4 adapters com
contrato completo.

Garantias com teste: job não roda duas vezes (chave de idempotência + claim
atômico), dry-run não chama `publish`, publicação real exige três condições
simultâneas, upload iniciado ≠ publicado, captcha/2FA trava a sessão, log não
vaza cookie/token/senha.

### Fase 3 — Campanhas de Cortes
Evoluído o módulo existente, sem paralelo. Fechados 4 buracos: as 7 validações
automáticas do documento (faltavam resolução, áudio, prazo e duplicidade),
medição (`campaign_metrics` existia sem endpoint), ponte para o VexPublish
(publicação era só exportação manual) e o diretório completo de 10 plataformas.

### Fase 4 — Multi-canais
Schema v2 com `MetricSnapshot`, comparação entre canais (publicações,
frequência, falhas por código, taxa de sucesso, views, retenção, receita) e API
local autenticada por papel.

Decisão registrada: métrica sem snapshot volta como **traço, não zero**. Canal
sem dado e canal com desempenho ruim não podem parecer a mesma coisa.

### Fase 5 — Importar / Adaptar / Publicar
Fontes com autorização obrigatória, biblioteca com dedup por SHA-256, plano de
adaptação validado e fila por canal. Download exige dois interruptores. O plano
recusa por código qualquer chave de apropriação (`remove_watermark`,
`strip_attribution`, `bypass_drm`…) e `keep_credit=false`.

### Fase 6 — Stack local de mídia
Catálogo das 15 ferramentas, matriz de decisão gerada por código
([STACK-MEDIA.md](STACK-MEDIA.md)), perfis de hardware e providers na ordem
`LOCAL > GRATUITO > FREE TIER > PAGO`.

**Nenhuma ferramenta foi auditada.** Licença, VRAM e RAM aparecem como
`não medido`. Concluir auditoria exige licença e commit informados. A stack
adotável hoje é **vazia**, e o código diz isso em vez de inventar.

### Fase 7 — Commerce Studio
Produtos com proveniência (confiança derivada da evidência, teto 0,3 para
cadastro manual), claims que só ficam `supported` com evidência do próprio
produto, 12 tipos de criativo com QA que lê o roteiro inteiro, e
`LiveAssetPackage` versionado com checksum.

### Fase 8 — Live Pilot por contrato
`git status botlive-shop/` → **0 arquivos**. A entrega usa as rotas HTTP que o
Live Pilot já expõe; teste de AST garante que só `urllib` entra no módulo.

O encaixe já existia: `talking_points` → `approved_answers`, `claims_blocked` →
`prohibited_claims`. `images[]` e `overlays[]` não cabem no contrato atual e são
**reportados**, com a mudança exata que seria necessária na extensão — mudança
que não foi feita.

### Fase 9 — Escala controlada
Quotas globais acima dos limites por conta (teto por hora, profundidade da fila,
publicações simultâneas e piso de disco livre) e `doctor` com 7 checagens
(dependências, banco, jobs travados, sessões, storage, filas, configuração).

O piso de disco é resposta direta ao incidente que derrubou a VPS: nenhum limite
por conta teria impedido aquilo.

## Repositórios

**Auditados: 0.** Nenhum instalado, nenhum código de terceiros copiado.
15 catalogados como candidatos, todos `NAO AUDITADO`.
Ver [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Plataformas de publicação

| Plataforma | Compatibilidade |
|---|---|
| TikTok | NÃO VALIDADO |
| Instagram | NÃO VALIDADO |
| YouTube | NÃO VALIDADO |
| Kwai | NÃO VALIDADO — ordem de investigação documentada, nada testado |

Os publishers legados (`yt_publisher.py`, `instagram_publisher.py`,
`tiktok_publisher.py`) seguem intocados e em operação.

## Feature flags

Todas nascem desligadas:

```
BOTLIVE_MULTICHANNEL_ENABLED=false     VEXPUBLISH_ENABLED=false
VEXPUBLISH_DRY_RUN=true                VEXPUBLISH_AUTO_PUBLISH=false
VEXPUBLISH_REQUIRE_APPROVAL=true       VEXPUBLISH_{TIKTOK,INSTAGRAM,YOUTUBE,KWAI}_ENABLED=false
IMPORT_ADAPT_PUBLISH_ENABLED=false     IMPORT_ALLOW_DOWNLOAD=false
COMMERCE_ENABLED=false                 COMMERCE_AUTO_PUBLISH=false
COMMERCE_REQUIRE_APPROVAL=true         COMMERCE_DRY_RUN=true
```

No dashboard: `VITE_MULTICHANNEL_ENABLED`, `VITE_IMPORT_ENABLED`,
`VITE_COMMERCE_ENABLED` — todas `false`.

## Definição de pronto

| Estado | Situação |
|---|---|
| IMPLEMENTADO | ✅ |
| VALIDADO LOCALMENTE | ✅ 282 testes |
| VALIDADO EM DRY-RUN | ✅ |
| VALIDADO COM LOGIN | ❌ |
| VALIDADO COM PUBLICAÇÃO REAL | ❌ (e permanece NÃO nesta fase) |

## Pendências que dependem do Glauber

1. **Aprovar o commit** — nada foi commitado.
2. **Decidir o nome de "Canais"** — a aba nova está como "Canais de publicação"
   (provisório) ao lado da aba `Canais` existente, que lista os canais Twitch
   vigiados. Ficou pendente junto com a questão do Instagram.
3. **Auditar as 15 ferramentas de mídia** — precisa de rede e bancada.
4. **Decidir sobre `images[]`/`overlays[]` no Live Pilot** — só então mexer na extensão.
5. **Validar Kwai** — a ordem de investigação está documentada, nada foi testado.

## O que não foi feito, de propósito

- Executor real de download (yt-dlp/gallery-dl) — os interruptores existem, o executor não.
- Geração real de imagem/vídeo — depende da auditoria da Fase 6.
- Achadinhos e automação de DM de link — o documento exige opt-in, limites e logs próprios.
- Legendas automáticas e intro/outro na adaptação — estão no plano validado, não no executor.
- Worker de longa duração — os renders hoje são síncronos pela API.
