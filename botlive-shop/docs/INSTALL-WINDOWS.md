# Instalação local no Windows

Requisitos: Windows 10/11, Python 3.12+, Node 20+, npm, Chrome/Chromium e FFmpeg com `ffprobe`. Execute PowerShell como usuário comum na raiz do repositório:

```powershell
.\botlive-shop\scripts\Install-ShopLive.ps1 -InstallFFmpeg
.\botlive-shop\scripts\Start-ShopLive.ps1 -Mode production
```

O instalador cria `.venv`, instala as dependências dentro dos intervalos declarados, compila o dashboard com Shop LIVE habilitado, prepara SQLite/Alembic, gera token criptograficamente aleatório e cria somente diretórios ignorados em `botlive-shop/data/`. O agente e dashboard escutam apenas `127.0.0.1`.

Carregue `botlive-shop/apps/extension` em `chrome://extensions` como extensão descompactada. Copie o ID para `SHOP_LIVE_ALLOWED_EXTENSION_IDS` em `.env.local`, separado por vírgulas caso existam instalações autorizadas adicionais. Reinicie o agente.

- Parar: `Stop-ShopLive.ps1`.
- Diagnosticar: `Diagnose-ShopLive.ps1`.
- Atualizar: `Update-ShopLive.ps1` faz dry-run; `-Apply` exige árvore limpa e usa apenas fast-forward.
- Desenvolvimento: `Start-ShopLive.ps1 -Mode development`.
