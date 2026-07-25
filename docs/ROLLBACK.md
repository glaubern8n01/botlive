# Rollback

## Desligar somente funcionalidades novas

Defina todas as flags como `0`:

```text
MULTI_PROFILE_ENABLED=0
PUBLICATION_QUEUE_ENABLED=0
NEW_PUBLISHER_CONTRACT_ENABLED=0
KWAI_ENABLED=0
KWAI_API_ENABLED=0
CUT_ENABLED=0
NARRASTARS_ENABLED=0
```

O CLI, Vigia, YouTube e Instagram continuam no caminho legado.

## Voltar ao início desta sessão

HEAD de referência: `d0fa43331141c347faf5280a27254e88a93d5380`.

Use `git revert` nos commits posteriores, do mais recente para o mais antigo.
Não é necessário apagar tabelas: todas as migrations são aditivas e o legado não
depende delas. Não use `reset --hard` em worktree com alterações do usuário.

## Banco

Não há rollback destrutivo automático. Desabilite workers/flags e preserve os
dados para auditoria. Qualquer remoção futura de tabelas deve ser uma operação
manual, separada e aprovada.
