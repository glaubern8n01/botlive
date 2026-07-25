# Configuração multi-perfil — Fase 2

Esta fase adiciona o domínio e a persistência de perfis sem trocar o caminho
operacional do BotLive. O `Vigia` continua lendo `vigia_config` e os publishers
YouTube/Instagram continuam usando as flags e a conta do fluxo legado.

## Compatibilidade

- `vigia_config`, `vigia_channels`, `vigia_streams` e `vigia_clip_index` não são
  alteradas nem removidas.
- A linha `vigia_config.id = 1` é espelhada como o perfil `default`.
- A migração não sobrescreve o perfil `default` caso ele já exista.
- Com as tabelas novas ausentes, os fluxos CLI/Vigia atuais continuam iguais; só
  a página **Perfis** informa que a migração precisa ser aplicada.
- O fluxo legado continua independente. Fila, Kwai, CUT e Narrastars são
  módulos posteriores opt-in e permanecem inertes com as feature flags desligadas.

## Modelos Python

`profile_config.py` define:

- `ProfileConfig`
- `EditorialPolicy`
- `RenderPolicy`
- `SourceConfig`
- `DestinationConfig`

`default_profile_from_legacy()` é a fronteira explícita que converte uma linha
de `vigia_config` para o novo modelo, sempre com `profile_id="default"`.

## Banco

Aplicar no SQL Editor do Supabase:

```text
supabase/migrations/20260725_multi_profile.sql
```

A migração cria:

- `profiles`
- `profile_sources`
- `profile_destinations`
- `profile_render_settings`
- `platform_accounts`

`platform_accounts.secret_ref` aceita somente uma referência opaca para uma
variável de ambiente ou secret manager. Tokens, refresh tokens, senhas e client
secrets não devem ser gravados nessas tabelas.

RLS não é ativado automaticamente nesta migração porque o dashboard legado usa
a anon key sem uma sessão Supabase Auth. Ativar políticas apenas para usuários
autenticados nesta etapa quebraria o dashboard atual. Antes de expor o dashboard
publicamente, a autenticação local deve ser migrada para Supabase Auth e as
políticas devem ser habilitadas por usuário/organização.

## Dashboard

A rota `/perfis` lê exclusivamente as tabelas novas e permite:

- listar perfis, fontes, destinos, contas e política de renderização;
- criar e editar um perfil;
- ativar ou desativar um perfil;
- associar contas previamente cadastradas em `platform_accounts`;
- configurar formato, layout, duração, marca, CTA e modo de publicação.

O frontend seleciona apenas metadados públicos das contas. `secret_ref` não é
consultado nem exibido.

`PublicationPlanner` transforma uma variante/asset em um job por destino ativo.
Limite diário, intervalo mínimo, horários, timezone, máximo de pendentes e
tentativas pertencem ao destino, não a uma conta global.

## Rollback

O rollback operacional é simplesmente não usar a rota `/perfis`: o Vigia e os
fluxos legados não dependem das tabelas novas. Não é necessário apagar tabelas
ou dados. Se o código precisar ser revertido, reverta o commit desta fase; as
tabelas adicionais podem permanecer sem afetar o BotLive atual.
