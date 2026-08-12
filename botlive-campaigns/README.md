# BotLive Campanhas de Cortes

MVP local, isolado e desativado por padrão para organizar campanhas remuneradas de cortes. O módulo não publica conteúdo, não acessa contas externas, não faz scraping e não compartilha fila ou banco com o BotLive legado.

## Ativação segura

1. Copie `.env.example` para seu gerenciador local de ambiente.
2. Defina `CAMPAIGNS_ENABLED=true`, `CAMPAIGNS_DRY_RUN=true` e um `CAMPAIGNS_LOCAL_TOKEN` longo.
3. Inicie o agente em `127.0.0.1:8775` com `uvicorn app.main:app --app-dir botlive-campaigns/local-agent`.
4. No dashboard, defina `VITE_CAMPAIGNS_ENABLED=true` e, se necessário, `VITE_CAMPAIGNS_API_URL`.

Sem a flag, nenhuma rota operacional é liberada e a aba não aparece. Networking Club, ViewX e todas as demais plataformas usam entrada manual: nenhuma API pública oficial foi assumida.

## Limites do MVP

- Cadastro, materiais autorizados, candidatos, revisão, contas, publicações manuais, resultados e auditoria.
- Importação por upload local; URL externa é apenas referência até existir integração oficial revisada.
- O worker apenas prepara jobs em dry-run. Publicação real é bloqueada.
- O motor legado é referenciado por comando/arquivo de entrada, sem importá-lo no processo do agente.

## Rollback

Desative `VITE_CAMPAIGNS_ENABLED` e `CAMPAIGNS_ENABLED`. Para rollback de dados, pare somente o agente de campanhas e restaure `botlive-campaigns/data/backups/`; nunca mexa no banco/fila legados.

## Testes

`python -m unittest discover -s botlive-campaigns/tests -v`

