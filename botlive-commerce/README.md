# Commerce Studio

Fábrica de assets e criativos para **TikTok Shop** e **Shopee**. Alimenta o
Live Pilot com um pacote versionado e entrega publicação ao VexPublish.

**Estado: IMPLEMENTADO + VALIDADO LOCALMENTE. Nenhuma publicação real.**
Desligado por padrão (`COMMERCE_ENABLED=false`).

## O Live Pilot não foi tocado

`botlive-shop/` continua exatamente como estava — extensão, `shop-live.db`,
compliance de live, tudo. Este módulo tem banco próprio (`commerce.db`) e a
integração é por **arquivo/JSON**, nunca por tabela compartilhada.

```
Commerce Studio  ──LiveAssetPackage──▶  Live Pilot (só consome)
                 ──PublishJob draft──▶  VexPublish
```

## Proveniência: confiança não se digita

> "produto inserido manualmente não recebe automaticamente confidence=1"

Confiança é **derivada**, nunca informada. Todo produto nasce em `0.1` e sobe
conforme evidência anexada — respeitando um teto por origem:

| Origem | Teto de confiança |
|---|---|
| manual | 0.3 |
| importado | 0.5 |
| catálogo oficial | 0.9 |
| API de afiliado | 0.9 |

Produto cadastrado à mão **nunca** chega perto de 1, por mais evidência que
receba. Evidência sem origem declarada é recusada.

## Claims: nenhum sem suporte documentado

```
proposed  ──precisa de evidência do próprio produto──▶  supported
          ──com motivo obrigatório──▶  blocked (não volta)
```

`sustentar_claim(claim, [])` levanta erro com a frase do documento. Evidência
de outro produto é recusada.

## QA de criativo

12 tipos (`UGC_SELFIE` … `LIVE_SCENE`). O QA lê o **texto inteiro** do
roteiro, não só a lista de claims marcada, e reprova quando:

- o roteiro repete um claim bloqueado;
- o roteiro afirma um claim ainda sem evidência;
- um claim marcado não está `supported`;
- não há asset, ou não há CTA.

Aprovação humana só passa com QA limpo — e reprovar marca `qa_failed`.

## LiveAssetPackage

Contrato do documento: `product_id`, `images[]`, `videos[]`, `overlays[]`,
`talking_points[]`, `cta[]`, `metadata`, `version`.

**`talking_points` sai só de claim sustentado.** Um ponto de fala que a
evidência não aguenta não chega na boca de ninguém ao vivo. Exportar cria
versão nova (nunca sobrescreve) e o pacote carrega checksum — carregar um
pacote adulterado falha.

## Antes da fila

Seis conferências do documento: produto, claims, direitos dos assets, CTA,
link e plataforma. `COMMERCE_AUTO_PUBLISH=true` é **recusado** nesta fase.

## Uso

```bash
python botlive-commerce/migrations/manage.py upgrade
python -m pytest botlive-commerce/tests -q
```

## Entrega ao Live Pilot (Fase 8)

`handoff.py` traduz o pacote para as **rotas públicas que o Live Pilot já
expõe**. Não importa código dele, não abre `shop-live.db`, não pede mudança
na extensão — tem teste que lê o AST do módulo e confirma que só `urllib`
entra, nunca `sqlite3`, `sqlalchemy` ou o pacote `app`.

| Do pacote | Vira no Live Pilot |
|---|---|
| `talking_points` (só claims sustentados) | `ProductIn.approved_answers` |
| `metadata.claims_blocked` | `ProductIn.prohibited_claims` |
| `cta[]` | `ScriptBlockIn(kind="cta")` |
| `videos[]` | `MediaAssetIn(kind="video")` |

O encaixe de claims é literal: o Live Pilot já separa resposta aprovada de
alegação proibida, e o Commerce Studio já separa claim sustentado de
bloqueado. As duas listas se encontram sem adaptação.

**O que não cabe hoje** — reportado, nunca descartado em silêncio:

| Parte | Por quê | O que mudaria na extensão |
|---|---|---|
| `images[]` | `MediaAssetIn.kind` aceita só `video\|audio` | ampliar o `Literal` em `schemas.py` e o storage |
| `overlays[]` | o Live Pilot não tem entidade de overlay | modelo e rota novos |

Nenhuma dessas mudanças foi feita. `GET /commerce/v1/live-pilot/compatibility`
devolve esse relatório, e `entregar()` é **dry-run por padrão** — em dry-run
não sai requisição nenhuma.

## Ainda não feito

- Geração real de imagem/vídeo (o criativo guarda provider/seed/config; quem executa é a Fase 6).
- Achadinhos e automação de DM de link — o documento exige opt-in, limites e logs próprios; nada disso foi implementado.
- Aba de Shopee com regras fiscais/logísticas próprias (hoje só o campo de plataforma separa).
