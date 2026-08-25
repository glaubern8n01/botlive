"""Painel que aparece ao ligar o PC: o que está pendente e o que fazer.

Por que existe
--------------
O atalho antigo só perguntava "ligar o BotLive?" - sem dizer o que havia para
fazer. E o Kwai CUT, que é o que está mais perto de virar dinheiro, ficou dias
descobrindo ZERO canais por causa de um cookie vencido, sem ninguém perceber.

Aqui a tela responde três coisas antes de qualquer botão:
  - o cookie do YouTube está bom? (se não, é só isso que trava o Kwai)
  - o Kwai CUT está produzindo?
  - tem VOD e campanha esperando corte?

E a decisão fica com o Glauber, porque este PC é dele: pode ligar tudo, ligar
só as campanhas, ou não ligar nada porque vai estudar/trabalhar na máquina.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ops" / "local"))

VPS = "root@69.62.96.161"
VOLUME = "/etc/easypanel/projects/botlive/botlive-app/volumes/botlive-output"
COOKIES_DE_SESSAO = {"SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID"}

VERDE, AMARELO, VERMELHO, CINZA = "#3fb950", "#d29922", "#f85149", "#8b949e"


def carregar_ambiente() -> None:
    """Credenciais da VPS vem do arquivo de dados, nunca da linha de comando."""
    try:
        import vod_pc

        vod_pc.carregar_ambiente()
    except Exception:
        pass


def na_vps(comando: str, segundos: int = 45) -> str:
    try:
        pronto = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", VPS, comando],
            capture_output=True, text=True, timeout=segundos,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return pronto.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def estado_do_cookie() -> tuple[str, str, str]:
    texto = na_vps(f"cat {VOLUME}/cookies-youtube.txt 2>/dev/null")
    if not texto:
        return VERMELHO, "Cookie do YouTube", "Nao ha cookie na VPS - o Kwai CUT nao descobre nada"
    vencimentos = []
    for linha in texto.splitlines():
        campos = linha.split("\t")
        if len(campos) >= 7 and "youtube.com" in campos[0] \
                and campos[5] in COOKIES_DE_SESSAO and campos[4].isdigit() and int(campos[4]) > 0:
            vencimentos.append(int(campos[4]))
    if not vencimentos:
        return VERMELHO, "Cookie do YouTube", "Sem cookie de login (SID) - gere um novo"
    dias = int((min(vencimentos) - datetime.now(timezone.utc).timestamp()) / 86400)
    if dias < 0:
        return VERMELHO, "Cookie do YouTube", f"VENCIDO ha {abs(dias)} dia(s) - gere um novo"
    if dias <= 7:
        return AMARELO, "Cookie do YouTube", f"Vence em {dias} dia(s) - troque esta semana"
    return VERDE, "Cookie do YouTube", f"Valido por mais {dias} dias"


def estado_do_kwai() -> tuple[str, str, str]:
    vivo = na_vps('docker ps --format "{{.Names}}" | grep -c kwai-cut')
    prontos = na_vps(f'find {VOLUME}/kwai_cut/ready -name "*.mp4" 2>/dev/null | wc -l')
    if vivo != "1":
        return VERMELHO, "Kwai CUT", "Produtor parado na VPS"
    trabalhou = na_vps('docker service logs botlive_kwai-cut-producer --since 6h 2>&1 '
                       '| grep -ci "real pipeline"')
    if trabalhou.isdigit() and int(trabalhou) > 0:
        return VERDE, "Kwai CUT", f"Produzindo - {prontos or '?'} video(s) prontos para o celular"
    return AMARELO, "Kwai CUT", f"Rodando, mas sem producao nas ultimas 6h ({prontos or '?'} prontos)"


def estado_do_vod() -> tuple[str, str, str]:
    try:
        import vod_pc
        cliente = vod_pc.cliente()
        config = vod_pc.ler_config(cliente)
        fila = vod_pc.pendentes(cliente, config)
    except Exception as erro:
        return CINZA, "VOD (cortes da Twitch)", f"nao consegui checar: {str(erro)[:50]}"
    if not fila:
        return VERDE, "VOD (cortes da Twitch)", "Nada esperando"
    return AMARELO, "VOD (cortes da Twitch)", f"{len(fila)} VOD(s) esperando corte neste PC"


def estado_das_campanhas() -> tuple[str, str, str]:
    banco = Path(os.getenv("CAMPAIGNS_DATABASE_PATH", r"G:\botlive-campanhas\campaigns.db"))
    if not banco.is_file():
        return CINZA, "Campanhas de corte", "banco ainda nao criado"
    import sqlite3
    try:
        with sqlite3.connect(f"file:{banco}?mode=ro", uri=True) as db:
            prontos = db.execute("SELECT COUNT(*) FROM campaign_candidates "
                                 "WHERE output_path!=''").fetchone()[0]
            fila = db.execute("SELECT COUNT(*) FROM campaign_jobs "
                              "WHERE status IN ('queued','retry_wait')").fetchone()[0]
    except sqlite3.Error as erro:
        return CINZA, "Campanhas de corte", str(erro)[:50]
    return VERDE, "Campanhas de corte", f"{prontos} corte(s) prontos, {fila} na fila"


class Painel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BotLive")
        self.configure(bg="#0d1117")
        self.resizable(False, False)
        self.escolha = None

        tk.Label(self, text="BotLive", bg="#0d1117", fg="#e6edf3",
                 font=("Segoe UI", 20, "bold")).pack(pady=(18, 2))
        tk.Label(self, text="Conferindo como estao as coisas...", bg="#0d1117",
                 fg=CINZA, font=("Segoe UI", 9), name="sub").pack(pady=(0, 12))

        self.linhas = tk.Frame(self, bg="#0d1117")
        self.linhas.pack(padx=22, fill="x")

        self.botoes = tk.Frame(self, bg="#0d1117")
        self.botoes.pack(pady=18, padx=22, fill="x")
        self._botao("Ligar tudo (campanhas + VOD)", "tudo", "#238636")
        self._botao("So as campanhas", "campanhas", "#1f6feb")
        self._botao("Nao rodar nada - vou usar o PC", "nada", "#30363d")

        threading.Thread(target=self._checar, daemon=True).start()

    def _botao(self, texto, valor, cor):
        tk.Button(self.botoes, text=texto, bg=cor, fg="white", relief="flat",
                  font=("Segoe UI", 10), cursor="hand2", pady=8,
                  command=lambda: self._decidir(valor)).pack(fill="x", pady=3)

    def _decidir(self, valor):
        self.escolha = valor
        self.destroy()

    def _linha(self, cor, titulo, detalhe):
        quadro = tk.Frame(self.linhas, bg="#161b22")
        quadro.pack(fill="x", pady=3)
        tk.Frame(quadro, bg=cor, width=4).pack(side="left", fill="y")
        interno = tk.Frame(quadro, bg="#161b22")
        interno.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        tk.Label(interno, text=titulo, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(interno, text=detalhe, bg="#161b22", fg=CINZA,
                 font=("Segoe UI", 9), anchor="w", wraplength=380,
                 justify="left").pack(fill="x")

    def _checar(self):
        precisa_cookie = False
        for funcao in (estado_do_cookie, estado_do_kwai, estado_do_vod, estado_das_campanhas):
            try:
                cor, titulo, detalhe = funcao()
            except Exception as erro:
                cor, titulo, detalhe = CINZA, funcao.__name__, str(erro)[:60]
            if cor == VERMELHO and "ookie" in titulo:
                precisa_cookie = True
            self.after(0, self._linha, cor, titulo, detalhe)
        recado = ("Precisa de cookie novo: gere no Chrome e cole no painel, aba Kwai CUT"
                  if precisa_cookie else "Escolha o que rodar agora")
        self.after(0, lambda: self.nametowidget("sub").config(text=recado))


def main() -> int:
    carregar_ambiente()
    painel = Painel()
    painel.eval("tk::PlaceWindow . center")
    painel.mainloop()

    escolha = painel.escolha
    if escolha in (None, "nada"):
        return 0

    lancador = Path(__file__).parent / "campanhas-pc.ps1"
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                      "-WindowStyle", "Hidden", "-File", str(lancador)],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if escolha == "tudo":
        subprocess.Popen([sys.executable, str(Path(__file__).parent / "vod_pc.py"), "--laco"],
                         cwd=str(REPO),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    messagebox.showinfo("BotLive", "Ligado em prioridade baixa.\n\n"
                        "Para desligar: atalho 'Desligar BotLive' na area de trabalho.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
