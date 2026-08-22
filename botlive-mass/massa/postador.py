"""Fila de postagem, com dois modos: API oficial ou navegador local.

MODO api (padrao e recomendado)
    Reaproveita instagram_publisher.py, que ja publica Reels em producao pela
    Graph API. E o caminho suportado pela Meta: nao arrisca a conta.

MODO local
    Navegador controlado por Playwright, com login manual feito pelo operador
    e sessao salva. Foi pedido no documento para nao depender da Graph API.
    O fluxo completo esta implementado: abre o Instagram com a sessao salva,
    cria a publicacao, carrega o video, preenche a legenda e - so fora do
    dry-run - confirma. Com MASS_DRY_RUN_NAVEGADOR=true o ensaio percorre a
    tela inteira e PARA antes de Compartilhar.

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
from contextlib import contextmanager
from pathlib import Path

from . import projetos
from .store import MassaError, agora, atualizar, auditar, conectar, contar, inserir, listar, obter


REPO_ROOT = Path(__file__).resolve().parents[2]
MODOS = ("api", "local")
ESTADOS = ("queued", "running", "completed", "failed", "cancelled",
           "manual_action_required", "paused")

# Fluxo do navegador local. Os seletores sao listas porque o Instagram muda o
# layout e a lingua da conta muda o rotulo do botao: tenta na ordem e para no
# primeiro que existir. Se nenhum existir, o item falha com motivo legivel em
# vez de clicar no lugar errado.
TIMEOUT_LOCAL_MS = int(os.getenv("MASS_LOCAL_TIMEOUT", "45")) * 1000

SINAIS_DESAFIO = ("/challenge", "/accounts/login", "two_factor",
                  "checkpoint", "/accounts/suspended")

BOTAO_CRIAR = (
    'svg[aria-label="Nova publicação"]', 'svg[aria-label="New post"]',
    '[aria-label="Nova publicação"]', '[aria-label="New post"]',
    'a[href="/create/select/"]',
)
BOTAO_SELECIONAR = (
    'button:has-text("Selecionar do computador")',
    'button:has-text("Select from computer")',
)
ENTRADA_ARQUIVO = 'input[type="file"]'
BOTAO_AVANCAR = (
    'div[role="button"]:has-text("Avançar")', 'button:has-text("Avançar")',
    'div[role="button"]:has-text("Next")', 'button:has-text("Next")',
)
CAMPO_LEGENDA = (
    'textarea[aria-label*="legenda" i]', 'textarea[aria-label*="caption" i]',
    'div[contenteditable="true"][aria-label*="legenda" i]',
    'div[contenteditable="true"][aria-label*="caption" i]',
    'div[role="textbox"][contenteditable="true"]',
)
BOTAO_COMPARTILHAR = (
    'div[role="button"]:has-text("Compartilhar")', 'button:has-text("Compartilhar")',
    'div[role="button"]:has-text("Share")', 'button:has-text("Share")',
)
CONFIRMACAO = 'text=/publicad|compartilhad|shared|your post/i'


def ligado(nome: str, padrao: str = "false") -> bool:
    return os.getenv(nome, padrao).strip().lower() in {"1", "true", "yes", "sim"}


def flags() -> dict:
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


def _checar_desafio(url: str, etapa: str = "") -> None:
    """Desafio da plataforma para o fluxo - nunca tenta contornar.

    Captcha, 2FA e checkpoint sao barreiras de seguranca do Instagram. O item
    vira manual_action_required (o chamador reconhece a palavra "checkpoint")
    e quem resolve e o operador, no navegador, com as proprias maos.
    """
    alvo = (url or "").lower()
    if any(sinal in alvo for sinal in SINAIS_DESAFIO):
        onde = f" em {etapa}" if etapa else ""
        raise MassaError(
            f"checkpoint do Instagram{onde}: ACAO MANUAL NECESSARIA. "
            f"Abra a conta no navegador, resolva o desafio e rode o login "
            f"manual de novo. A fila parou neste item de proposito."
        )


def _clicar_primeiro(pagina, seletores, timeout_ms: int, rotulo: str = "",
                     obrigatorio: bool = True) -> str:
    """Clica no primeiro seletor que existir. Layout mudou = erro legivel."""
    for seletor in seletores:
        try:
            pagina.click(seletor, timeout=timeout_ms)
            return seletor
        except Exception:
            continue
    if obrigatorio:
        raise MassaError(
            f"nao encontrei {rotulo or 'o elemento'} na tela do Instagram. "
            f"O layout pode ter mudado - confira no navegador antes de repetir."
        )
    return ""


def _preencher_primeiro(pagina, seletores, texto: str, timeout_ms: int) -> str:
    for seletor in seletores:
        try:
            pagina.fill(seletor, texto, timeout=timeout_ms)
            return seletor
        except Exception:
            continue
    raise MassaError("nao encontrei o campo de legenda na tela do Instagram")


def fluxo_publicacao(pagina, arquivo: str, legenda: str,
                     timeout_ms: int = TIMEOUT_LOCAL_MS,
                     confirmar: bool = True) -> dict:
    """Passos do post no site do Instagram, um por um.

    Recebe a pagina pronta em vez de abrir o navegador aqui: assim o fluxo e
    testavel sem Playwright instalado e sem tocar em conta nenhuma.

    Com confirmar=False faz tudo - carrega o video, preenche a legenda - e
    PARA antes de Compartilhar. E o dry-run do documento, mas de verdade:
    exercitando a tela, nao so o banco.
    """
    passos = []
    pagina.goto("https://www.instagram.com/", timeout=timeout_ms)
    _checar_desafio(pagina.url, "abertura")

    _clicar_primeiro(pagina, BOTAO_CRIAR, timeout_ms, "o botao de nova publicacao")
    passos.append("criar")
    _clicar_primeiro(pagina, BOTAO_SELECIONAR, timeout_ms,
                     "o botao de selecionar do computador", obrigatorio=False)

    pagina.set_input_files(ENTRADA_ARQUIVO, arquivo, timeout=timeout_ms)
    passos.append("video carregado")

    # corte -> filtros -> legenda: dois "Avancar" ate a tela da descricao.
    for _ in range(2):
        _clicar_primeiro(pagina, BOTAO_AVANCAR, timeout_ms, "o botao Avancar")
    passos.append("avancou ate a legenda")

    if legenda:
        _preencher_primeiro(pagina, CAMPO_LEGENDA, legenda, timeout_ms)
        passos.append("legenda preenchida")

    _checar_desafio(pagina.url, "antes de publicar")

    if not confirmar:
        passos.append("PAROU antes de confirmar (dry-run)")
        return {"confirmado": False, "passos": passos, "url": ""}

    _clicar_primeiro(pagina, BOTAO_COMPARTILHAR, timeout_ms, "o botao Compartilhar")
    # publicar demora mais que clicar: o video ainda sobe depois do clique.
    pagina.wait_for_selector(CONFIRMACAO, timeout=timeout_ms * 4)
    _checar_desafio(pagina.url, "depois de publicar")
    passos.append("publicado")
    return {"confirmado": True, "passos": passos, "url": pagina.url}


@contextmanager
def _navegador(conta: str):
    """Abre o Chromium com a sessao salva. Nao faz login, nao digita senha."""
    # Sessao primeiro: falta de sessao e coisa que o operador resolve (login
    # manual), e Playwright ausente e problema de instalacao. Trocar a ordem
    # esconderia o motivo real atras do outro.
    if not sessao_salva(conta):
        raise MassaError(
            f"sem sessao salva para {conta!r}. Rode o login manual antes "
            "(abrir_para_login)."
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise MassaError(
            "Playwright nao instalado. Rode: python -m pip install playwright "
            "&& python -m playwright install chromium"
        )

    estado = sessao_dir(conta) / "state.json"
    headless = os.getenv("MASS_LOCAL_HEADLESS", "false").strip().lower() in {
        "1", "true", "yes", "sim"
    }
    with sync_playwright() as p:
        # visivel por padrao: se o Instagram pedir alguma coisa, o operador ve
        # a tela e resolve na hora em vez de descobrir por um erro seco.
        navegador = p.chromium.launch(headless=headless)
        contexto = navegador.new_context(storage_state=str(estado))
        pagina = contexto.new_page()
        try:
            yield pagina
            contexto.storage_state(path=str(estado))  # renova o que expirou
        finally:
            navegador.close()


def _publicar_local(item: dict, confirmar: bool = True) -> dict:
    """Publicacao pelo navegador, com a sessao que o operador salvou.

    AVISO: automatizar o site do Instagram vai contra os termos de uso e pode
    custar a conta. O modo api nao tem esse risco.
    """
    conta = item["conta"] or "principal"
    legenda = _legenda(item)
    with _navegador(conta) as pagina:
        resultado = fluxo_publicacao(pagina, item["arquivo"], legenda,
                                     TIMEOUT_LOCAL_MS, confirmar)
    return {"url": resultado.get("url", ""), "detalhe": resultado}


# --- fila ------------------------------------------------------------------


def _registrar_falha(publicacao_id: str, erro: Exception) -> dict:
    """Desafio da plataforma nao e retentado: exige humano."""
    texto = str(erro).lower()
    travado = any(x in texto for x in
                  ("checkpoint", "captcha", "2fa", "verificacao", "sessao",
                   "acao manual"))
    auditar("publicacao.falha", "publicacao", publicacao_id,
            {"erro": str(erro)[:200]}, resultado="erro")
    return atualizar("mass_publicacoes", publicacao_id, {
        "status": "manual_action_required" if travado else "failed",
        "erro": str(erro)[:400],
    })


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
        nota = "dry-run: video preparado, legenda montada, publicacao NAO confirmada"
        # No modo local da para ensaiar na tela de verdade: carrega o video,
        # preenche a legenda e para antes de Compartilhar. Fica atras de flag
        # porque abre navegador - o dry-run padrao continua so no banco.
        if estado["modo"] == "local" and ligado("MASS_DRY_RUN_NAVEGADOR"):
            try:
                ensaio = _publicar_local(item, confirmar=False)
            except MassaError as erro:
                return _registrar_falha(publicacao_id, erro)
            nota = "dry-run no navegador: " + " · ".join(ensaio["detalhe"]["passos"])
        auditar("publicacao.dry_run", "publicacao", publicacao_id,
                {"modo": estado["modo"], "arquivo": item["arquivo"]})
        return atualizar("mass_publicacoes", publicacao_id, {
            "status": "completed",
            "dry_run": 1,
            "erro": nota,
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
        return _registrar_falha(publicacao_id, erro)

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
