# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento PyInstaller do Producao em Massa.

O que entra: o launcher, o pacote `massa` e o painel ja compilado.
O que NAO entra, de proposito:
  - .env, tokens, cookies, banco ou sessoes (segredo nenhum vai no instalador);
  - FFmpeg e yt-dlp (pesados e com licenca propria - instalados a parte);
  - o resto do BotLive (cortes, live, shop): o modulo e isolado e assim segue.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


DESKTOP = Path(SPECPATH).resolve()
MODULO = DESKTOP.parent

# O painel so entra se tiver sido compilado antes (build-instalador.ps1 faz
# isso). Sem ele o app ainda sobe, servindo so a API.
painel = DESKTOP / "painel"
datas = [(str(painel), "painel")] if (painel / "index.html").is_file() else []
datas.append((str(DESKTOP / "LEIAME.txt"), "."))

# uvicorn e fastapi carregam parte das coisas por nome, em tempo de execucao:
# sem isso o exe sobe e quebra na primeira requisicao.
ocultos = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + ["massa.main", "massa.store", "massa.baixar", "massa.editor",
       "massa.exportar", "massa.fontes", "massa.postador", "massa.projetos",
       "massa.templates"]
)

analise = Analysis(
    [str(DESKTOP / "launcher.py")],
    pathex=[str(MODULO)],
    binaries=[],
    datas=datas,
    hiddenimports=ocultos,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)

pyz = PYZ(analise.pure)

exe = EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    [],
    name="BotLive-Massa",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # a janela mostra o token e o endereco do painel
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
