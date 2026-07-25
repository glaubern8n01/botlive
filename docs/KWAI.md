# Kwai Publisher

`KwaiPublisher` possui três modos:

- `dry_run`: valida e monta o pacote, sem rede;
- `prepare_only`: gera/valida vídeo, capa e caption, sem envio;
- `api`: usa somente o Open Platform oficial, quando a conta estiver aprovada.

Documentação oficial consultada:

- criação/upload/publicação:
  https://open.kuaishou.com/platformDocs/openAbility/contentManagement/createAVideo.html
- SDK e consulta de vídeo:
  https://open.kuaishou.com/platformDocs/develop/serverSDK

O modo API exige simultaneamente:

- `KWAI_ENABLED=1`;
- `KWAI_API_ENABLED=1`;
- `official_api_authorized=true` na conta;
- escopo `user_video_publish`;
- `secret_ref` resolvendo `app_id` e `access_token`.

Isso não presume que uma autorização Kuaishou seja válida no Kwai Brasil. A
confirmação regional/contratual precisa vir do portal ou suporte oficial.

O fluxo implementado segue os endpoints documentados
`/openapi/photo/start_upload`, upload direto/fragmentado no endpoint devolvido e
`/openapi/photo/publish`. A consulta de status só usa `video_info_url` fornecida
explicitamente pela configuração aprovada; sem ela o status fica `unknown`.

Não existe automação de login, CAPTCHA, identidade, idade, região ou antiabuso.
