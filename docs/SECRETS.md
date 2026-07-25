# Secrets

`platform_accounts` guarda somente `secret_ref`. A view
`platform_accounts_safe` expõe apenas o booleano `secret_configured`.

Providers iniciais:

- `EnvironmentSecretProvider`: `env:NOME_DA_VARIAVEL`;
- `LocalTokenSecretProvider`: `local-token:youtube/principal.json`;
- `CompositeSecretProvider`: encaminha pela origem.

O provider local restringe caminhos à pasta `.tokens` e rejeita caminhos
absolutos ou `..`. Valores resolvidos não são logados nem retornados ao
dashboard.

Providers futuros (Vault, Supabase Vault, AWS Secrets Manager) podem implementar
`resolve(secret_ref)` sem alterar publishers.

## RLS

As migrations não ativam RLS porque o dashboard legado usa senha client-side e
anon key, sem Supabase Auth. Ativar políticas autenticadas agora quebraria o
frontend. O dashboard não deve ser exposto publicamente nesse estado.

Dívida registrada: migrar `AuthWrapper` para Supabase Auth, habilitar RLS em
todas as tabelas novas e legadas e conceder escrita apenas à organização correta.
