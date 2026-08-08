# Análise da integração oficial TikTok Shop / LIVE Studio

Análise atualizada em 2026-08-08 usando somente documentação oficial.

## Oficialmente possível após aprovação

A TikTok Shop Open Platform oferece API V2 para catálogo, pedidos, fulfillment, finanças, promoções, autorização e webhooks. A integração exige aplicativo no Partner Center, mercados/categorias aprovados, escopos, autorização do seller, `access_token` e `shop_cipher`. O fluxo deve ser desenvolvido primeiro com Development Shop e submetido à revisão da plataforma.

Referências oficiais:

- [TikTok Shop Developer Guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide)
- [Open Platform overview](https://partner.tiktokshop.com/docv2/page/tts-api-concepts-overview)
- [App development and review](https://partner.tiktokshop.com/docv2/page/65b351a8c8448002e03949a9)
- [Product API overview](https://partner.tiktokshop.com/docv2/page/products-api-overview)

O `TikTokShopOfficialAdapter` permanece inerte. Ele documenta `app_key`, `access_token` e `shop_cipher` ausentes, mas não faz chamadas nem armazena segredos.

## Não comprovado como API pública

Não foi localizada API pública oficial para controlar TikTok LIVE Studio, iniciar/encerrar LIVE, trocar cenas, fixar produtos ao vivo ou escrever comentários. Essas ações permanecem instruções manuais. O Shop LIVE não usa seletores DOM, cookies, engenharia reversa ou automação oculta.

## Passos externos pendentes

1. Decisão comercial sobre mercado e categoria do aplicativo.
2. Conta de desenvolvedor e Development Shop.
3. Aprovação de escopos e revisão funcional/compliance.
4. Autorização explícita do seller e credenciais emitidas pela plataforma.
5. Nova aprovação do operador antes de qualquer teste externo.
