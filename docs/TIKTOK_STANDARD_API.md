# TikTok Standard — GTA6 Brasil Cortes

Estado inicial: `prepare_only`. Esta integração é um destino aditivo do perfil
editorial GTA e não substitui YouTube Shorts ou Instagram Reels. TikTok Shop é
um projeto futuro separado e permanece sem conta, credenciais, jobs ou API.

## Fontes oficiais consultadas em 30/07/2026

- Login Kit for Web e OAuth v2:
  `https://developers.tiktok.com/doc/login-kit-web`
- Gerenciamento de tokens:
  `https://developers.tiktok.com/doc/login-kit-manage-user-access-tokens`
- Upload de vídeo:
  `https://developers.tiktok.com/doc/content-posting-api-reference-upload-video`
- Direct Post:
  `https://developers.tiktok.com/doc/content-posting-api-reference-direct-post`
- Creator info:
  `https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info`
- Status:
  `https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status`
- Transferência de mídia:
  `https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide`
- Sandbox:
  `https://developers.tiktok.com/doc/sandbox`
- URL verification:
  `https://developers.tiktok.com/doc/content-posting-api-get-started`
- App Review e Content Sharing Guidelines:
  `https://developers.tiktok.com/doc/app-review-guidelines`
  e `https://developers.tiktok.com/doc/content-sharing-guidelines`

## OAuth

Autorização web:

`GET https://www.tiktok.com/v2/auth/authorize/`

Parâmetros: `client_key`, `response_type=code`, `scope`, `redirect_uri` e
`state`. O callback valida um `state` aleatório, curto e de uso único. A troca e
o refresh ocorrem exclusivamente no backend:

`POST https://open.tiktokapis.com/v2/oauth/token/`

Revogação:

`POST https://open.tiktokapis.com/v2/oauth/revoke/`

O Client Secret fica somente em variável protegida do EasyPanel. Access e
refresh tokens ficam criptografados no volume do serviço público. Supabase
recebe somente `secret_ref` e metadados não secretos.

Escopos iniciais: `user.info.basic` e `video.upload`. `video.publish` só será
solicitado/demonstrado quando a interface e a auditoria estiverem prontas.
Usuários podem conceder apenas um subconjunto; o dashboard mostra o conjunto
real recebido.

## Content Posting API

| Operação | Endpoint | Escopo | Limite documentado |
|---|---|---|---|
| Inicializar rascunho | `/v2/post/publish/inbox/video/init/` | `video.upload` | 6/min/token |
| Creator info | `/v2/post/publish/creator_info/query/` | `video.publish` | 20/min/token |
| Inicializar Direct Post | `/v2/post/publish/video/init/` | `video.publish` | 6/min/token |
| Consultar status | `/v2/post/publish/status/fetch/` | upload ou publish | 30/min/token |
| Cancelar transferência | `/v2/post/publish/cancel/` | upload ou publish | resposta da API |

`upload_draft` entrega o conteúdo à caixa de entrada do TikTok para o criador
concluir no aplicativo; não equivale a vídeo publicado.

Direct Post sempre consulta `creator_info` imediatamente antes da tentativa,
usa apenas opções de privacidade retornadas, inicia comentários/Duet/Stitch
desmarcados e exige consentimento explícito. Cliente não auditado fica sujeito
à visibilidade privada. O modo permanece desligado.

## FILE_UPLOAD

O backend inicializa com `source=FILE_UPLOAD` e envia o MP4 ao `upload_url` por
`PUT`, com `Content-Type`, `Content-Length` e `Content-Range`.

- chunk: mínimo 5 MB e máximo 64 MB;
- exceção: arquivo inteiro abaixo de 5 MB;
- último chunk pode chegar a 128 MB;
- máximo 1.000 chunks;
- upload sequencial;
- `upload_url` válido por uma hora;
- MP4/H.264 recomendado, 23–60 fps, dimensões 360–4096 px;
- até 4 GB e até 10 minutos na inicialização do upload.

Capacidade diária e excesso de rascunhos pendentes são respostas dinâmicas da
API e não devem ser substituídos por uma meta fixa.

## Modos e flags

```text
TIKTOK_STANDARD_ENABLED=1
TIKTOK_STANDARD_API_ENABLED=0
TIKTOK_STANDARD_UPLOAD_DRAFT_ENABLED=0
TIKTOK_STANDARD_DIRECT_POST_ENABLED=0
TIKTOK_SHOP_ENABLED=0
TIKTOK_SHOP_API_ENABLED=0
```

`prepare_only` valida e organiza o material sem qualquer chamada ao TikTok.
`upload_draft` exige API, escopo e flag de rascunho. `direct_post` exige API,
escopo aprovado, revisão compatível, flag própria, creator info e consentimento.

## Sandbox, revisão e limites honestos

O Sandbox pode validar Login Kit e autorização com target users, mas não deve
ser apresentado como prova de publicação pública pelo Content Posting API.
Aplicativos destinados apenas ao desenvolvedor ou às suas contas administradas
podem não cumprir as Content Sharing Guidelines. Nenhuma alegação de audiência
ampla, representação empresarial ou aprovação será feita sem comprovação.

O primeiro pedido de revisão recomendado abrange Login Kit,
`user.info.basic` e `video.upload`. `video.publish` fica para uma revisão
posterior se ainda não houver demonstração completa e elegível.

## Operação e rollback

1. manter a branch isolada;
2. fazer backup antes da migration;
3. aplicar `20260730_tiktok_standard_gta.sql`;
4. implantar o serviço público separado e validar `/health`, `/privacy`,
   `/terms`, `/tiktok/connect`, `/tiktok/disconnect`,
   `/tiktok/data-deletion` e `/auth/tiktok/callback`;
5. cadastrar exatamente a mesma redirect URI no portal;
6. manter as três flags de API em zero até autorização real;
7. para rollback, desabilitar o destino/serviço. Não remover tabelas nem dados
   dos demais destinos.
