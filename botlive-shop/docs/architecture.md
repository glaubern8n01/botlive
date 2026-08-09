# Arquitetura e isolamento
Todos os arquivos mutáveis usam caminhos absolutos sob `botlive-shop/data/`: `shop-live.db`, `media/`, `backups/` e `run/`. Nenhum componente depende do diretório corrente.
O módulo vive em `botlive-shop/`; apenas a rota React condicionada pela feature flag toca o dashboard existente. Nenhum serviço ou módulo do BotLive legado é importado.

```text
Dashboard / extensão MV3
        │ HTTP + WebSocket com tickets temporários
        ▼
Agente FastAPI em 127.0.0.1
        ├── biblioteca local autorizada
        ├── runtime / fila / teleprompter / diagnósticos
        ├── auditoria e relatórios
        └── SQLite gerido exclusivamente por Alembic
```

O runtime persistido reúne sessão, fila, player, teleprompter, alertas e relatório. Dashboard e side panel recebem o mesmo estado. A câmera e o microfone permanecem no `MediaStream` do navegador e não são gravados nem enviados ao agente.

O TikTok LIVE Studio é preparado e operado manualmente. O adapter oficial permanece inerte até revisão, escopos, credenciais e autorização explícita. A extensão não possui host permission para TikTok. OBS é futuro opcional e não integra instalação ou operação.
