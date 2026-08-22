"""Ponto de entrada do BotLive Producao em Massa como aplicativo Windows.

E o MESMO codigo do modulo, so que empacotado: sobe a API local, serve o
painel ja compilado e abre o navegador na aba Producao em Massa. Nao existe
um segundo produto - se o modulo mudar, o instalador muda junto.

O que este arquivo garante, e que o instalador NAO pode carregar:
  - nenhum segredo empacotado: o token de acesso e sorteado na primeira
    execucao, na maquina do usuario, e guardado no perfil dele;
  - dados fora do Program Files: banco, projetos e sessoes vao para
    %LOCALAPPDATA%\\BotLive\\massa, que e gravavel sem administrador;
  - postagem desligada e dry-run ligado: instalacao nova nao publica nada.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


PORTA_PADRAO = int(os.getenv("MASS_DESKTOP_PORT", "8825"))


def raiz_recursos() -> Path:
    """Onde estao os arquivos: descompactados pelo PyInstaller ou no repo."""
    empacotado = getattr(sys, "_MEIPASS", "")
    return Path(empacotado) if empacotado else Path(__file__).resolve().parents[1]


def pasta_de_dados() -> Path:
    """Perfil do usuario - Program Files nao e gravavel sem administrador."""
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    destino = Path(base) / "BotLive" / "massa"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def token_local(dados: Path) -> str:
    """Token sorteado na primeira execucao. Nunca vem dentro do instalador."""
    arquivo = dados / "token.txt"
    if arquivo.is_file():
        atual = arquivo.read_text(encoding="utf-8").strip()
        if atual:
            return atual
    novo = secrets.token_urlsafe(24)
    arquivo.write_text(novo, encoding="utf-8")
    return novo


def porta_livre(preferida: int) -> int:
    """Se a porta estiver ocupada, sobe na proxima em vez de morrer."""
    for porta in range(preferida, preferida + 20):
        with socket.socket() as teste:
            if teste.connect_ex(("127.0.0.1", porta)) != 0:
                return porta
    return preferida


def ferramentas_faltando() -> list:
    """FFmpeg e yt-dlp nao sao empacotados: sao pesados e tem licenca propria."""
    faltando = []
    for nome in ("ffmpeg", "ffprobe"):
        if not shutil.which(nome):
            faltando.append(nome)
    if not shutil.which("yt-dlp"):
        try:
            import importlib.util

            if not importlib.util.find_spec("yt_dlp"):
                faltando.append("yt-dlp")
        except Exception:
            faltando.append("yt-dlp")
    return faltando


def preparar_ambiente() -> tuple:
    dados = pasta_de_dados()
    # setdefault em tudo: um .env ou uma variavel do sistema continua mandando.
    os.environ.setdefault("MASS_CONTENT_STUDIO_ENABLED", "true")
    os.environ.setdefault("MASS_DATABASE_PATH", str(dados / "massa.db"))
    os.environ.setdefault("MASS_PROJECTS_DIR", str(dados / "projetos"))
    os.environ.setdefault("MASS_SESSIONS_DIR", str(dados / "sessoes"))
    # instalacao nova nao publica: dry-run ligado e postagem desligada.
    os.environ.setdefault("LOCAL_PUBLISHER_DRY_RUN", "true")
    os.environ.setdefault("MASS_PUBLISH_ENABLED", "false")
    os.environ.setdefault("MASS_PUBLISHER_MODE", "api")
    token = token_local(dados)
    os.environ["MASS_ADMIN_TOKEN"] = token
    return dados, token


def montar_painel(app, raiz: Path) -> bool:
    """Serve o painel compilado na mesma porta da API.

    O mount vai para o fim da lista de rotas, entao as rotas /mass/v1/* que
    ja estao registradas continuam ganhando - o painel so pega o que sobra.
    """
    painel = raiz / "painel"
    if not (painel / "index.html").is_file():
        return False
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as ErroHTTP

    class PainelSPA(StaticFiles):
        """Rota do painel que nao existe no disco devolve o index.

        O painel e uma SPA: /producao-em-massa nao e arquivo nenhum, quem
        resolve o caminho e o React. E o mesmo `try_files $uri /index.html`
        que o nginx faz na VPS.

        O StaticFiles LEVANTA 404 em vez de devolver uma resposta 404, por
        isso o tratamento e no except - conferir o status nunca pegaria nada.
        """

        async def get_response(self, path, scope):
            try:
                return await super().get_response(path, scope)
            except ErroHTTP as erro:
                if erro.status_code != 404:
                    raise
                return await super().get_response("index.html", scope)

    app.mount("/", PainelSPA(directory=str(painel), html=True), name="painel")
    return True


def main() -> int:
    dados, token = preparar_ambiente()
    raiz = raiz_recursos()
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    from massa.main import app
    from massa.store import migrar

    migrar()
    tem_painel = montar_painel(app, raiz)
    porta = porta_livre(PORTA_PADRAO)
    endereco = f"http://127.0.0.1:{porta}"

    print("=" * 62)
    print(" BotLive - Producao em Massa")
    print("=" * 62)
    print(f" Painel:  {endereco}/producao-em-massa" if tem_painel else
          f" API:     {endereco}/mass/v1/health")
    print(f" Token:   {token}")
    print(f"          (tambem em {dados / 'token.txt'})")
    print(f" Dados:   {dados}")
    print(" Postagem: DESLIGADA e em dry-run. Ligue so quando quiser publicar.")
    faltando = ferramentas_faltando()
    if faltando:
        print(f" ATENCAO: falta instalar {', '.join(faltando)} - sem isso o")
        print("          download e a edicao nao rodam. Veja o LEIAME.txt.")
    print("=" * 62)
    print(" Feche esta janela para encerrar.")

    destino = f"{endereco}/producao-em-massa" if tem_painel else endereco
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(destino)),
                     daemon=True).start()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
