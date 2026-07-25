# Publishers

O contrato novo vive em `publisher_contract.py` e é aditivo. Os fluxos atuais
continuam chamando `social_publisher.py`, `yt_publisher.py` e
`instagram_publisher.py` sem alteração.

## Contrato

Cada publisher declara `PublisherCapabilities` e implementa:

- `validate(PublishJob)`;
- `publish(PublishJob, secrets)`;
- `get_status(external_id, account, secrets)`.

Os adapters `YouTubePublisher` e `InstagramPublisher` delegam às funções legadas
para preservar payloads e OAuth existentes. O `PublisherRegistry` seleciona o
adapter pela plataforma.

Erros são classificados em:

- `RetryablePublishError`;
- `PermanentPublishError`;
- `AuthenticationError`;
- `RateLimitError`;
- `AssetValidationError`.

Para adicionar uma plataforma, implemente o contrato, declare capacidades,
registre o publisher e escreva testes com HTTP mockado. Publishers não recebem
tokens pelo banco: recebem um mapa já resolvido por `SecretProvider`.
