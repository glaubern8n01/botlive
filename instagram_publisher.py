from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# Plugin Instagram/Reels do auto-post (Instagram API with Instagram Login).
# Sub-etapa B: autorizacao (token do painel Meta -> long-lived salvo em
# .tokens/instagram/<conta>.json, com refresh automatico) + testar-auth +
# montagem/dry-run do post. O upload real (resumable p/ rupload.facebook.com)
# entra na sub-etapa D; ate la, postar sem dry-run registra erro claro no
# publish.json e o pipeline segue — mesmo caminho de maturacao do yt_publisher.
#
# Suporta os DOIS tipos de token da Meta:
#   - Instagram Login (token IGAA/IGQ): graph.instagram.com direto, sem Pagina.
#   - Facebook Login / System User (token EAA): graph.facebook.com, conta IG
#     resolvida pela Pagina vinculada (/me/accounts -> instagram_business_account).
#     Token de System User NAO expira — ideal para automacao (sem refresh).
# Para postar na PROPRIA conta, Standard Access dispensa o Meta App Review.
#
# Tudo em urllib stdlib de proposito: zero dependencia nova. Atencao no PC do
# Glauber: o MITM do AVG quebra TLS para *.facebook.com (rodar auth na VPS ou
# definir BOTLIVE_TLS_NO_VERIFY=1 localmente).

GRAPH_IG = "https://graph.instagram.com"
GRAPH_FB = "https://graph.facebook.com"
GRAPH_VERSION = "v23.0"

# Reels aceita 3-90s; nosso corte padrao e 45s. Legenda max oficial 2200.
CAPTION_MAX_CHARS = 2000  # folga sobre o limite oficial

TOKENS_DIR = Path(__file__).resolve().parent / ".tokens" / "instagram"

# Renova o long-lived (60 dias) quando faltar menos que isto para expirar.
_REFRESH_ANTES_DE_EXPIRAR = timedelta(days=10)


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass


def _token_path(conta: str) -> Path:
    return TOKENS_DIR / f"{conta}.json"


def _ssl_context():
    """BOTLIVE_TLS_NO_VERIFY=1 so para dev local atras do MITM do AVG."""
    import ssl

    if os.environ.get("BOTLIVE_TLS_NO_VERIFY") == "1":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return None


def _get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph API HTTP {exc.code}: {corpo}") from exc


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _salvar_token(conta: str, dados: dict) -> Path:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    token_path = _token_path(conta)
    token_path.write_text(json.dumps(dados, ensure_ascii=False, indent=4), encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    expira_em = dados.get("expira_em")
    print(
        f"[ig-auth] conta {conta!r} autorizada como @{dados.get('username')} "
        f"(via {dados.get('api_host')}); token salvo em {token_path}"
        + (f" — expira em {expira_em}" if expira_em else " — token SEM expiracao/renovado por refresh")
    )
    return token_path


def listar_paginas(token: str) -> list[dict]:
    """Paginas do token FB e a conta IG vinculada a cada uma (se houver)."""
    resposta = _get(
        f"{GRAPH_FB}/{GRAPH_VERSION}/me/accounts",
        {"fields": "id,name,instagram_business_account{id,username}", "access_token": token},
    )
    return list(resposta.get("data") or [])


def autorizar(conta: str, token: Optional[str], pagina: Optional[str] = None) -> Path:
    """Valida o token da Meta, resolve a conta IG e salva em .tokens/instagram/.

    Aceita token de Instagram Login (IGAA/IGQ, graph.instagram.com) ou de
    Facebook Login/System User (EAA, graph.facebook.com — conta IG resolvida
    pela Pagina vinculada; --pagina escolhe quando houver mais de uma).
    Token de System User nao expira: zero manutencao.
    Cole o token no prompt (sem --token) para nao vazar em historico/chat.
    """
    if not token:
        token = input("[ig-auth] cole o access token gerado no painel Meta: ").strip()
    if not token:
        raise RuntimeError("token vazio.")

    # 1) Tenta como token do Instagram Login.
    try:
        me = _get(
            f"{GRAPH_IG}/{GRAPH_VERSION}/me",
            {"fields": "user_id,username,account_type", "access_token": token},
        )
        return _salvar_token(
            conta,
            {
                "access_token": token,
                "api_host": "graph.instagram.com",
                "ig_user_id": str(me.get("user_id") or me.get("id") or ""),
                "username": me.get("username"),
                "obtido_em": _agora().isoformat(timespec="seconds"),
                "expira_em": None,
            },
        )
    except RuntimeError:
        pass  # nao e token do Instagram Login; tenta a plataforma Facebook

    # 2) Plataforma Facebook: valida e resolve Pagina -> conta IG vinculada.
    quem = _get(f"{GRAPH_FB}/{GRAPH_VERSION}/me", {"fields": "id,name", "access_token": token})
    print(f"[ig-auth] token da plataforma Facebook valido (usuario/sistema: {quem.get('name')}).")
    paginas = listar_paginas(token)
    if not paginas:
        raise RuntimeError("token nao enxerga nenhuma Pagina (falta escopo pages_show_list?).")

    com_ig = [p for p in paginas if p.get("instagram_business_account")]
    alvo: Optional[dict] = None
    if pagina:
        candidatas = [p for p in paginas if pagina in (p.get("id"), p.get("name"))]
        if not candidatas:
            nomes = ", ".join(f"{p['name']} (id {p['id']})" for p in paginas)
            raise RuntimeError(f"pagina {pagina!r} nao encontrada; disponiveis: {nomes}")
        alvo = candidatas[0]
    elif len(com_ig) == 1:
        alvo = com_ig[0]
        print(f"[ig-auth] unica pagina com IG vinculado: {alvo['name']!r}; usando-a (mude com --pagina).")
    else:
        detalhe = "; ".join(
            f"{p['name']}: "
            + (f"@{p['instagram_business_account']['username']}" if p.get("instagram_business_account") else "SEM IG vinculado")
            for p in paginas
        )
        raise RuntimeError(f"escolha a pagina com --pagina <nome|id>. Encontradas: {detalhe}")

    ig = alvo.get("instagram_business_account")
    if not ig:
        raise RuntimeError(
            f"a pagina {alvo['name']!r} (id {alvo['id']}) NAO tem conta Instagram vinculada. "
            "Vincule a conta IG profissional a esta Pagina (Business Suite > Configuracoes > "
            "Contas vinculadas) e rode autorizar de novo."
        )
    return _salvar_token(
        conta,
        {
            "access_token": token,
            "api_host": "graph.facebook.com",
            "ig_user_id": str(ig["id"]),
            "username": ig.get("username"),
            "page_id": alvo.get("id"),
            "page_name": alvo.get("name"),
            "obtido_em": _agora().isoformat(timespec="seconds"),
            "expira_em": None,
        },
    )


def _base(dados: dict) -> str:
    host = dados.get("api_host") or "graph.instagram.com"
    return f"https://{host}/{GRAPH_VERSION}"


def _refresh(conta: str, dados: dict) -> dict:
    """refresh_access_token (SO Instagram Login): renova long-lived por +60 dias."""
    novo = _get(
        f"{GRAPH_IG}/refresh_access_token",
        {"grant_type": "ig_refresh_token", "access_token": dados["access_token"]},
    )
    expira_em = (_agora() + timedelta(seconds=int(novo.get("expires_in") or 0))).isoformat(
        timespec="seconds"
    )
    dados = {**dados, "access_token": novo["access_token"], "expira_em": expira_em,
             "obtido_em": _agora().isoformat(timespec="seconds")}
    _token_path(conta).write_text(json.dumps(dados, ensure_ascii=False, indent=4), encoding="utf-8")
    print(f"[ig-auth] token renovado; nova expiracao {expira_em}.")
    return dados


def _credenciais(conta: str) -> dict:
    """Token salvo, renovado automaticamente quando perto de expirar."""
    token_path = _token_path(conta)
    ajuda = f"rode: python instagram_publisher.py autorizar --conta {conta}"
    if not token_path.is_file():
        raise RuntimeError(f"conta {conta!r} nao autorizada ({token_path} inexistente); {ajuda}")
    dados = json.loads(token_path.read_text(encoding="utf-8"))
    expira_raw = dados.get("expira_em")
    if expira_raw:
        expira = datetime.fromisoformat(expira_raw)
        if expira <= _agora():
            raise RuntimeError(f"token da conta {conta!r} expirou em {expira_raw}; {ajuda}")
        if expira - _agora() < _REFRESH_ANTES_DE_EXPIRAR and dados.get("api_host") == "graph.instagram.com":
            try:
                dados = _refresh(conta, dados)
            except Exception as exc:
                print(f"[ig-auth] refresh falhou ({exc}); usando o token atual ate expirar.")
    return dados


def testar_auth(conta: str) -> None:
    """Prova a conexao: perfil + uso do limite de publicacao (100 posts/24h)."""
    dados = _credenciais(conta)
    base = _base(dados)
    ig_user_id = dados.get("ig_user_id")
    perfil = _get(
        f"{base}/{ig_user_id}",
        {"fields": "username,media_count", "access_token": dados["access_token"]},
    )
    print(
        f"[ig-auth] conectado como @{perfil.get('username')} | midias publicadas: {perfil.get('media_count')}"
        + (f" | via pagina {dados['page_name']!r}" if dados.get("page_name") else "")
    )
    try:
        limite = _get(
            f"{base}/{ig_user_id}/content_publishing_limit",
            {"fields": "quota_usage,config", "access_token": dados["access_token"]},
        )
        uso = (limite.get("data") or [{}])[0]
        quota = ((uso.get("config") or {}).get("quota_total")) or 100
        print(f"[ig-auth] publicacoes via API nas ultimas 24h: {uso.get('quota_usage', '?')}/{quota}")
    except Exception as exc:
        print(f"[ig-auth] content_publishing_limit indisponivel ({exc}); conexao ok mesmo assim.")
    if dados.get("expira_em"):
        print(f"[ig-auth] token expira em {dados['expira_em']}.")
    else:
        print("[ig-auth] token sem expiracao (System User) — nada a renovar.")


def montar_legenda(registro: dict) -> str:
    """Legenda do Reel: frase da IA + creditos + hashtags, dentro do limite."""
    partes: list[str] = []
    legenda = (registro.get("legenda") or "").strip()
    if legenda:
        partes.append(legenda)
    creditos: list[str] = []
    streamer = (registro.get("credito_streamer") or "").strip()
    if streamer:
        creditos.append(f"Creditos: {streamer}")
    canal = (registro.get("credito_canal") or "").strip()
    if canal:
        creditos.append(f"Siga {canal}")
    if creditos:
        partes.append(" | ".join(creditos))
    hashtags = " ".join(
        tag if tag.startswith("#") else f"#{tag}" for tag in (registro.get("hashtags") or [])
    )
    if hashtags:
        partes.append(hashtags)
    texto = "\n\n".join(partes)
    return texto[:CAPTION_MAX_CHARS]


def montar_post(registro: dict) -> dict:
    """Payload do container REELS (o que a sub-etapa D enviara de verdade)."""
    return {
        "media_type": "REELS",
        "upload_type": "resumable",  # binario local -> rupload.facebook.com (sem URL publica)
        "caption": montar_legenda(registro),
        "share_to_feed": True,
    }


def _video_vertical(registro: dict) -> Optional[Path]:
    raw = registro.get("vertical")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


# ------------------------------------------------------ upload real (sub-etapa D)

RUPLOAD_BASE = "https://rupload.facebook.com/ig-api-upload"
_PUBLISH_POLL_SECONDS = 10
_PUBLISH_POLL_MAX = 60  # ate 10min de processamento do Reel

# Retry do upload dentro do proprio job. Antes disso, uma falha do rupload
# custava um ciclo inteiro do vigia; producao gastava ~5 ciclos por Reel.
_UPLOAD_TENTATIVAS = int(os.getenv("BOTLIVE_IG_UPLOAD_TENTATIVAS", "5"))
_UPLOAD_ESPERA_BASE = int(os.getenv("BOTLIVE_IG_UPLOAD_ESPERA", "15"))
_UPLOAD_ESPERA_MAX = int(os.getenv("BOTLIVE_IG_UPLOAD_ESPERA_MAX", "120"))


def _post_form(url: str, params: dict) -> dict:
    corpo = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=corpo, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph API HTTP {exc.code}: {corpo_erro}") from exc


def _upload_binario(container_id: str, video_path: Path, token: str) -> None:
    dados = video_path.read_bytes()
    request = urllib.request.Request(
        f"{RUPLOAD_BASE}/{GRAPH_VERSION}/{container_id}", data=dados, method="POST"
    )
    request.add_header("Authorization", f"OAuth {token}")
    request.add_header("offset", "0")
    request.add_header("file_size", str(len(dados)))
    request.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(request, timeout=600, context=_ssl_context()) as response:
            corpo = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo_erro = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"rupload HTTP {exc.code}: {corpo_erro}") from exc
    if not corpo.get("success", True):
        raise RuntimeError(f"rupload sem sucesso: {corpo}")
    print(f"[ig-upload] {video_path.name}: {len(dados) / 1e6:.1f}MB enviados.")


def _publicar_reel(registro: dict, video_path: Path, conta: str) -> dict:
    """Container resumable -> upload binario -> poll -> media_publish."""
    dados = _credenciais(conta)
    base = _base(dados)
    token = dados["access_token"]
    ig_user_id = dados["ig_user_id"]

    payload = montar_post(registro)

    # O rupload do Meta devolve ProcessingFailedError com retriable=false, mas
    # a mesma midia sobe numa tentativa seguinte - o log de producao mostrou 3
    # cortes precisando de 16 tentativas, e os 3 publicaram. Sem retry aqui,
    # cada falha queimava um ciclo inteiro do vigia.
    #
    # Cada tentativa cria um container NOVO de proposito: e o caminho que a
    # producao ja comprovava entre ciclos. Reaproveitar container que falhou
    # nao esta validado.
    container_id = None
    for tentativa in range(1, _UPLOAD_TENTATIVAS + 1):
        container = _post_form(
            f"{base}/{ig_user_id}/media", {**payload, "access_token": token}
        )
        container_id = str(container["id"])
        print(
            f"[ig-upload] container {container_id} criado; subindo binario "
            f"(tentativa {tentativa}/{_UPLOAD_TENTATIVAS})..."
        )
        try:
            _upload_binario(container_id, video_path, token)
            break
        except RuntimeError as exc:
            if tentativa >= _UPLOAD_TENTATIVAS:
                raise
            espera = min(_UPLOAD_ESPERA_BASE * 2 ** (tentativa - 1), _UPLOAD_ESPERA_MAX)
            print(f"[ig-upload] falha na tentativa {tentativa}: {exc}")
            print(f"[ig-upload] novo container em {espera}s")
            time.sleep(espera)

    for tentativa in range(_PUBLISH_POLL_MAX):
        status = _get(
            f"{base}/{container_id}", {"fields": "status_code,status", "access_token": token}
        )
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"processamento do Reel falhou: {status}")
        if tentativa % 6 == 0:
            print(f"[ig-upload] processando ({code})...")
        time.sleep(_PUBLISH_POLL_SECONDS)
    else:
        raise RuntimeError(f"Reel nao ficou pronto em {_PUBLISH_POLL_MAX * _PUBLISH_POLL_SECONDS}s")

    publicado = _post_form(
        f"{base}/{ig_user_id}/media_publish",
        {"creation_id": container_id, "access_token": token},
    )
    media_id = str(publicado["id"])
    permalink = None
    try:
        permalink = _get(
            f"{base}/{media_id}", {"fields": "permalink", "access_token": token}
        ).get("permalink")
    except RuntimeError:
        pass  # permalink e cosmetico; o post ja esta publicado
    print(f"[ig-upload] Reel publicado: {permalink or media_id}")
    return {"media_id": media_id, "permalink": permalink}


def postar_corte_registro(registro: dict, config) -> dict:
    """Contrato do plugin (ver social_publisher): publica o VERTICAL como Reel.

    Instagram nao tem visibilidade tipo unlisted/private: todo Reel publicado
    e publico. config.visibilidade e ignorada de proposito (fica registrado no
    resultado para auditoria). Sem vertical no registro, o post e pulado.
    """
    resultado: dict = {"erro": None, "rede": "instagram", "observacao": "Reel e sempre publico; visibilidade do CLI ignorada"}
    video_path = _video_vertical(registro)
    if video_path is None:
        resultado["reel"] = {"pulado": registro.get("vertical_erro") or "arquivo vertical inexistente"}
        return resultado

    payload = montar_post(registro)
    if config.dry_run:
        resultado["reel"] = {
            "simulado": True,
            "media_id": None,
            "permalink": None,
            "arquivo": str(video_path),
            "payload": payload,
        }
        return resultado

    try:
        publicado = _publicar_reel(registro, video_path, config.conta)
        resultado["reel"] = {
            "simulado": False,
            "media_id": publicado["media_id"],
            "permalink": publicado["permalink"],
            "arquivo": str(video_path),
            "payload": payload,
        }
    except Exception as exc:
        resultado["reel"] = {"erro": str(exc), "arquivo": str(video_path)}
        resultado["erro"] = str(exc)
    return resultado


if __name__ == "__main__":
    import argparse

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Plugin Instagram/Reels do auto-post: autorizacao e utilidades.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_auth = sub.add_parser("autorizar", help="Salva o access token da conta (gerado no painel Meta).")
    p_auth.add_argument("--conta", default="principal", help="Nome do token em .tokens/instagram/<conta>.json.")
    p_auth.add_argument("--token", default=None, help="Access token; sem a flag, pede no prompt (mais seguro).")
    p_auth.add_argument("--token-file", default=None, help="Arquivo contendo o access token (alternativa ao prompt).")
    p_auth.add_argument("--pagina", default=None, help="Nome ou id da Pagina (token EAA com mais de uma Pagina).")

    p_teste = sub.add_parser("testar-auth", help="Prova a conexao: perfil + limite de publicacao (100/24h).")
    p_teste.add_argument("--conta", default="principal")

    p_post = sub.add_parser("montar-post", help="Mostra o payload do Reel que um publish.json geraria (sem postar).")
    p_post.add_argument("publish_json", help="Caminho de um *_publish.json.")

    args = parser.parse_args()

    if args.comando == "autorizar":
        try:
            token = args.token
            if not token and args.token_file:
                token = Path(args.token_file).read_text(encoding="utf-8").strip()
            autorizar(args.conta, token, pagina=args.pagina)
        except Exception as exc:
            raise SystemExit(f"[ig-auth][falha] {exc}")
    elif args.comando == "testar-auth":
        try:
            testar_auth(args.conta)
        except Exception as exc:
            raise SystemExit(f"[ig-auth][falha] {exc}")
    else:
        registro = json.loads(Path(args.publish_json).read_text(encoding="utf-8"))
        print(json.dumps(montar_post(registro), ensure_ascii=False, indent=4))
