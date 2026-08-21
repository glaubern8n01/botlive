"""Fila de postagem, com dois modos: API oficial ou navegador local.

MODO api (padrao e recomendado)
    Reaproveita instagram_publisher.py, que ja publica Reels em producao pela
    Graph API. E o caminho suportado pela Meta: nao arrisca a conta.

MODO local
    Navegador controlado por Playwright, com login manual feito pelo operador
    e sessao salva. Foi pedido no documento para nao depender da Graph API.

    AVISO QUE PRECISA FICAR ESCRITO: automatizar o app do Instagram por
    navegador vai contra os termos de uso da plataforma e pode custar a conta.
    O modo api nao tem esse risco. Use local sabendo disso.

Em qualquer modo:
  - dry-run ligado por padrao: monta tudo e para antes de confirmar;
  - intervalo minimo entre postagens;
  - desafio (captcha/2FA/checkpoint) NUNCA e contornado - o item vira
    manual_action_required e a fila para naquele item.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import projetos
from .store import MassaError, agora, atualizar, auditar, conectar, contar, inserir, listar, obter


REPO_ROOT = Path(__file__).resolve().parents[2]
MODOS = ("api", "local")
ESTADOS = ("queued", "running", "completed", "failed", "cancelled",
           "manual_action_required", "paused")


def flags() -> dict:
    def ligado(nome, padrao="false"):
        return os.getenv(nome, padrao).strip().lower() in {"1", "true", "yes", "sim"}

    modo = os.getenv("MASS_PUBLISHER_MODE", "api").strip().lower()
    if modo not in MODOS:
        modo = "api"
    return {
        "modo": modo,
        "dry_run": ligado("LOCAL_PUBLISHER_DRY_RUN", "true"),
        "intervalo_segundos": int(os.getenv("MASS_PUBLISH_INTERVALO", "300")),
        "habilitado": ligado("MASS_PUBLISH_ENABLED"),
    }


def enfileirar(projeto_id: str, arquivos: list, descricao: str = "",
               hashtags: list | None = None, conta: str = "principal",
               plataforma: str = "instagram") -> dict:
    """Coloca arquivos na fila de postagem. Mesmo arquivo nao entra duas vezes."""
    projeto = projetos.exigir(projeto_id)
    existentes = {
        x["arquivo"] for x in listar("mass_publicacoes", 2000, "projeto_id=?", (projeto_id,))
    }
    estado = flags()
    criados, repetidos = [], 0
    for arquivo in arquivos:
        caminho = Path(arquivo)
        if not caminho.is_file():
            continue
        if str(caminho) in existentes:
            repetidos += 1
            continue
        item = inserir("mass_publicacoes", {
            "projeto_id": projeto["id"],
            "plataforma": plataforma,
            "conta": conta,
            "arquivo": str(caminho),
            "descricao": descricao,
            "hashtags": json.dumps(hashtags or [], ensure_ascii=False),
            "status": "queued",
            "dry_run": 1 if estado["dry_run"] else 0,
            "created_at": agora(),
        })
        criados.append(item["id"])
    return {"enfileirados": len(criados), "repetidos": repetidos, "ids": criados}


def _legenda(item: dict) -> str:
    tags = json.loads(item["hashtags"] or "[]")
    partes = [item["descricao"].strip()] if item["descricao"].strip() else []
    if tags:
        partes.append(" ".join(t if t.startswith("#") else f"#{t}" for t in tags))
    return "\n\n".join(partes)


def ultima_publicacao(projeto_id: str) -> str | None:
    with conectar() as db:
        linha = db.execute(
            "SELECT publicado_em FROM mass_publicacoes WHERE projeto_id=? "
            "AND status='completed' AND dry_run=0 AND publicado_em IS NOT NULL "
            "ORDER BY publicado_em DESC LIMIT 1", (projeto_id,),
        ).fetchone()
    return linha["publicado_em"] if linha else None


def dentro_do_intervalo(projeto_id: str) -> tuple[bool, str]:
    """Respeita o intervalo entre postagens reais. Dry-run nao conta."""
    from datetime import datetime, timedelta, timezone

    estado = flags()
    if not estado["intervalo_segundos"]:
        return True, ""
    ultima = ultima_publicacao(projeto_id)
    if not ultima:
        return True, ""
    quando = datetime.fromisoformat(ultima)
    if datetime.now(timezone.utc) - quando < timedelta(seconds=estado["intervalo_segundos"]):
        return False, "intervalo_minimo"
    return True, ""


# --- modo API (oficial) ----------------------------------------------------


def _publicar_api(item: dict) -> dict:
    """Usa o instagram_publisher que ja esta em producao."""
    import importlib.util

    caminho = REPO_ROOT / "instagram_publisher.py"
    spec = importlib.util.spec_from_file_location("massa_ig", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)

    registro = {
        "vertical": item["arquivo"],
        "legenda": _legenda(item),
        "hashtags": json.loads(item["hashtags"] or "[]"),
    }

    class Config:
        dry_run = False
        conta = item["conta"] or "principal"
        visibilidade = "public"

    resultado = modulo.postar_corte_registro(registro, Config())
    if resultado.get("erro"):
        raise MassaError(f"Graph API: {resultado['erro']}")
    return {"url": resultado.get("permalink") or "", "detalhe": resultado}


# --- modo local (navegador) ------------------------------------------------


def sessao_dir(conta: str) -> Path:
    padrao = Path(__file__).resolve().parents[1] / "data" / "sessoes"
    destino = Path(os.getenv("MASS_SESSIONS_DIR", padrao)) / conta
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def sessao_salva(conta: str) -> bool:
    return (sessao_dir(conta) / "state.json").is_file()


def abrir_para_login(conta: str = "principal", timeout_minutos: int = 5) -> dict:
    """Abre o navegador para o operador logar A MAO e salva a sessao.

    Nao digita usuario nem senha, nao resolve captcha, nao toca no 2FA. O
    operador faz o login; o modulo so guarda o estado depois.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise MassaError(
            "Playwright nao instalado. Rode: python -m pip install playwright "
            "&& python -m playwright install chromium"
        )

    destino = sessao_dir(conta) / "state.json"
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=False)
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        pagina.goto("https://www.instagram.com/accounts/login/", timeout=60000)
        limite = time.time() + timeout_minutos * 60
        logado = False
        while time.time() < limite:
            if "/accounts/login" not in pagina.url:
                logado = True
                break
            time.sleep(2)
        if logado:
            contexto.storage_state(path=str(destino))
        navegador.close()

    if not logado:
        raise MassaError("login nao concluido dentro do tempo; nada foi salvo")
    auditar("sessao.salva", "conta", conta, {"arquivo": str(destino)})
    return {"conta": conta, "sessao": str(destino), "salva": True}


def _publicar_local(item: dict) -> dict:
    """Publicacao pelo navegador. So chega aqui fora do dry-run."""
    conta = item["conta"] or "principal"
    if not sessao_salva(conta):
        raise MassaError(
            f"sem sessao salva para {conta!r}. Rode o login manual antes "
            "(abrir_para_login)."
        )
    raise MassaError(
        "Publicacao local por navegador ainda nao habilitada nesta fase. "
        "A sessao ja e salva e o dry-run mostra o fluxo completo; o passo de "
        "confirmar o post no navegador fica para a proxima fase, junto com o "
        "tratamento de checkpoint. Use MASS_PUBLISHER_MODE=api para publicar."
    )


# --- fila ------------------------------------------------------------------


def publicar_item(publicacao_id: str) -> dict:
    item = obter("mass_publicacoes", publicacao_id)
    if not item:
        raise MassaError("Item de publicacao inexistente")
    if item["status"] in {"completed", "cancelled"}:
        return item

    estado = flags()
    if not estado["habilitado"]:
        return atualizar("mass_publicacoes", publicacao_id, {
            "status": "queued",
            "erro": "MASS_PUBLISH_ENABLED=false",
        })

    if not Path(item["arquivo"]).is_file():
        return atualizar("mass_publicacoes", publicacao_id,
                         {"status": "failed", "erro": "arquivo sumiu"})

    if estado["dry_run"]:
        auditar("publicacao.dry_run", "publicacao", publicacao_id,
                {"modo": estado["modo"], "arquivo": item["arquivo"]})
        return atualizar("mass_publicacoes", publicacao_id, {
            "status": "completed",
            "dry_run": 1,
            "erro": "dry-run: video preparado, legenda montada, publicacao NAO confirmada",
            "publicado_em": agora(),
        })

    permitido, motivo = dentro_do_intervalo(item["projeto_id"])
    if not permitido:
        return atualizar("mass_publicacoes", publicacao_id,
                         {"status": "queued", "erro": motivo})

    atualizar("mass_publicacoes", publicacao_id, {"status": "running", "erro": ""})
    try:
        envio = _publicar_api(item) if estado["modo"] == "api" else _publicar_local(item)
    except MassaError as erro:
        texto = str(erro).lower()
        # desafio da plataforma nao e retentado: exige humano
        travado = any(x in texto for x in ("checkpoint", "captcha", "2fa", "verificacao", "sessao"))
        estado_final = "manual_action_required" if travado else "failed"
        auditar("publicacao.falha", "publicacao", publicacao_id,
                {"erro": str(erro)[:200]}, resultado="erro")
        return atualizar("mass_publicacoes", publicacao_id,
                         {"status": estado_final, "erro": str(erro)[:400]})

    auditar("publicacao.enviada", "publicacao", publicacao_id, {"modo": estado["modo"]})
    return atualizar("mass_publicacoes", publicacao_id, {
        "status": "completed", "dry_run": 0,
        "url_publicada": envio.get("url", ""), "erro": "", "publicado_em": agora(),
    })


def rodar_fila(projeto_id: str, maximo: int = 1) -> dict:
    """Processa a fila de postagem. Padrao 1 por vez, por causa do intervalo."""
    projetos.exigir(projeto_id)
    with conectar() as db:
        linhas = db.execute(
            "SELECT * FROM mass_publicacoes WHERE projeto_id=? AND status='queued' "
            "ORDER BY rowid LIMIT ?", (projeto_id, max(1, maximo)),
        ).fetchall()
    processados = []
    for linha in linhas:
        resultado = publicar_item(linha["id"])
        processados.append({"id": linha["id"], "status": resultado["status"],
                            "erro": resultado.get("erro", "")})
    return {"processados": len(processados), "itens": processados,
            "fila": contar("mass_publicacoes", "projeto_id=?", (projeto_id,))}


def mudar_status(publicacao_id: str, status: str) -> dict:
    permitidos = {"queued", "paused", "cancelled"}
    if status not in permitidos:
        raise MassaError(f"Status invalido: {status}. Use {sorted(permitidos)}")
    if not obter("mass_publicacoes", publicacao_id):
        raise MassaError("Item inexistente")
    campos = {"status": status}
    if status == "queued":
        campos["erro"] = ""
    return atualizar("mass_publicacoes", publicacao_id, campos)


def fila(projeto_id: str, limite: int = 500) -> dict:
    return {
        "itens": listar("mass_publicacoes", limite, "projeto_id=?", (projeto_id,)),
        "resumo": contar("mass_publicacoes", "projeto_id=?", (projeto_id,)),
        "modo": flags(),
    }
