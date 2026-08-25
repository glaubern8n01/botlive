from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from caption_ai import gerar_legenda
from clipper import validar_video_final
from transcriber import transcrever_fala
from vertical_meme import MemeTextConfig, credito_canal_para_nicho, renderizar_vertical_meme


# Orquestrador de publicacao, sempre POS-corte: recebe um corte horizontal ja
# pronto e validado e gera a versao vertical legendada + publish.json. Se
# qualquer etapa falhar, o horizontal ja esta salvo e nada se perde.

# Preco por 1M tokens (entrada, saida) dos modelos conhecidos, para registrar
# o custo real no publish.json. Modelo fora da tabela -> custo_usd = None.
PRECOS_USD_POR_MTOKEN = {
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass(frozen=True)
class PublishConfig:
    """Configuracao da publicacao vertical vinda do CLI (--publish-vertical).

    social carrega um SocialConfig (social_publisher) quando o auto-post nas
    redes esta ligado (--post-youtube); None = sem auto-post, como hoje.
    """

    enabled: bool = False
    nicho: Optional[str] = None
    credito_streamer: Optional[str] = None
    credito_canal: Optional[str] = None
    social: Optional[object] = None


def _custo_usd(model: Optional[str], tokens_in: int, tokens_out: int) -> Optional[float]:
    if not model or model not in PRECOS_USD_POR_MTOKEN:
        return None
    preco_in, preco_out = PRECOS_USD_POR_MTOKEN[model]
    return round(tokens_in / 1e6 * preco_in + tokens_out / 1e6 * preco_out, 6)


def _precisa_de_olho_humano(corte_path: Path) -> bool:
    """O corte esta na pasta needs_review: o filtro de nicho ficou em duvida.

    Antes, corte em duvida subia para o YouTube como unlisted e esperava
    aprovacao manual la. Parecia seguro - unlisted e rascunho -, mas em
    25/08/2026 quatro cortes de Counter-Strike foram parar no canal
    "GTA6 Brasil cortes oficial", que e so de GTA. O filtro mede movimento,
    audio e tela estatica; CS2 tem tiro e movimento igual, entao passa.

    Agora corte em duvida para no disco. O vertical e o publish.json continuam
    sendo gerados: aprovou, e so mover para ready.

    BOTLIVE_POSTAR_NEEDS_REVIEW=1 volta ao comportamento anterior.
    """
    if os.getenv("BOTLIVE_POSTAR_NEEDS_REVIEW", "").strip() == "1":
        return False
    return "needs_review" in {parte.lower() for parte in corte_path.resolve().parts}


def publicar_corte(
    corte_path: str | Path,
    nicho: Optional[str] = None,
    credito_streamer: Optional[str] = None,
    credito_canal: Optional[str] = None,
    saida_dir: Optional[str | Path] = None,
    social_config: Optional[object] = None,
) -> dict:
    """Gera vertical legendado + publish.json para um corte horizontal pronto.

    Nunca levanta excecao: erros de transcricao/IA caem em fallback e erro no
    render vertical fica registrado no json (o horizontal permanece intacto).
    Retorna o registro salvo no publish.json.
    """
    started = time.monotonic()
    corte_path = Path(corte_path)
    target_dir = Path(saida_dir) if saida_dir else corte_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    horizontal_path = corte_path
    if target_dir != corte_path.parent:
        horizontal_path = target_dir / corte_path.name
        shutil.copy2(corte_path, horizontal_path)

    # 1. Fala -> texto (local, gratis). Sem fala/erro -> texto vazio, segue.
    t0 = time.monotonic()
    transcricao = transcrever_fala(corte_path)
    tempo_transcricao = time.monotonic() - t0

    # 2. Texto -> legenda clickbait (unico custo). Sem chave/erro -> fallback.
    t0 = time.monotonic()
    legenda = gerar_legenda(transcricao.text, nicho=nicho, streamer=credito_streamer)
    tempo_ia = time.monotonic() - t0

    # 3. Corte + legenda -> vertical 9:16. Falha aqui NAO perde o corte.
    canal = credito_canal_para_nicho(nicho, credito_canal)
    vertical_path: Optional[Path] = target_dir / f"{corte_path.stem}_vertical.mp4"
    vertical_erro: Optional[str] = None
    t0 = time.monotonic()
    try:
        renderizar_vertical_meme(
            corte_path,
            vertical_path,
            # Nome do canal/streamer NÃO vai queimado no vídeo (afasta seguidor);
            # a atribuição fica na DESCRIÇÃO (montar_descricao já inclui "Creditos:").
            # O vídeo leva só o hook clickbait no topo.
            MemeTextConfig(
                legenda=legenda.legenda,
            ),
        )
        validation = validar_video_final(vertical_path, require_audio=False)
        if not validation.valid:
            raise RuntimeError(f"vertical invalido: {validation.reason}")
    except Exception as exc:
        vertical_erro = str(exc)
        if vertical_path is not None:
            vertical_path.unlink(missing_ok=True)
        vertical_path = None
    tempo_render = time.monotonic() - t0

    registro = {
        "corte": corte_path.name,
        "horizontal": str(horizontal_path),
        "vertical": str(vertical_path) if vertical_path else None,
        "vertical_erro": vertical_erro,
        "nicho": nicho,
        "credito_streamer": credito_streamer,
        "credito_canal": canal,
        "legenda": legenda.legenda,
        "hashtags": list(legenda.hashtags),
        "legenda_fonte": legenda.source,
        "legenda_fraca": legenda.weak,
        "legenda_modelo": legenda.model,
        "legenda_erro": legenda.error,
        "tokens": {"entrada": legenda.prompt_tokens, "saida": legenda.completion_tokens},
        "custo_usd": _custo_usd(legenda.model, legenda.prompt_tokens, legenda.completion_tokens),
        "transcricao": transcricao.text,
        "transcricao_erro": transcricao.error,
        "tempos_s": {
            "transcricao": round(tempo_transcricao, 1),
            "ia": round(tempo_ia, 1),
            "render_vertical": round(tempo_render, 1),
            "total": round(time.monotonic() - started, 1),
        },
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    json_path = target_dir / f"{corte_path.stem}_publish.json"
    json_path.write_text(json.dumps(registro, ensure_ascii=False, indent=4), encoding="utf-8")

    status = "ok" if vertical_erro is None else f"vertical_erro={vertical_erro}"
    print(
        f"[publisher] {corte_path.name} | legenda={legenda.legenda!r} "
        f"fonte={legenda.source} fraca={legenda.weak} | {status} | "
        f"tempos={registro['tempos_s']}"
    )

    # Auto-post nas redes: sempre depois do json salvo e opt-in (--post-youtube).
    # postar_redes nunca levanta excecao, mas o try garante que nem um bug do
    # modulo social derruba a publicacao (json e videos ja estao no disco).
    if social_config is not None and getattr(social_config, "enabled", False):
        if _precisa_de_olho_humano(corte_path):
            print(f"[social] {corte_path.name}: em needs_review, NAO vai para as redes. "
                  "O vertical e o publish.json ficam prontos aqui.")
        else:
            try:
                from social_publisher import postar_redes

                postar_redes(registro, social_config, json_path=json_path)
            except Exception as social_exc:
                print(f"[social][falha] {corte_path.name}: {social_exc}; pipeline segue.")
    return registro


def _listar_cortes(entrada: Path) -> list[Path]:
    if entrada.is_file():
        return [entrada]
    cortes = [
        path
        for path in sorted(entrada.glob("corte_*.mp4"))
        if not path.stem.endswith("_vertical")
    ]
    if not cortes:
        raise SystemExit(f"Nenhum corte_*.mp4 encontrado em {entrada}")
    return cortes


if __name__ == "__main__":
    import argparse

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Gera versao vertical legendada + publish.json para cortes ja prontos."
    )
    parser.add_argument("entrada", help="Arquivo de corte ou pasta com corte_*.mp4.")
    parser.add_argument("--nicho", choices=["football", "gta"], default=None)
    parser.add_argument("--credito", default=None, help="@ do streamer na tarja de baixo.")
    parser.add_argument(
        "--credito-canal",
        default=None,
        help="Canal proprio abaixo do credito. Sem esse valor, usa o default do --nicho.",
    )
    parser.add_argument("--saida", default=None, help="Pasta de saida. Padrao: mesma pasta do corte.")
    parser.add_argument(
        "--post-youtube",
        action="store_true",
        help="OPT-IN: apos gerar o publish.json, posta horizontal + vertical no YouTube.",
    )
    parser.add_argument(
        "--post-dry-run",
        action="store_true",
        help="Simula o auto-post: grava o bloco 'postagens' no json sem subir nada.",
    )
    parser.add_argument("--post-visibilidade", choices=["private", "unlisted", "public"], default="unlisted")
    parser.add_argument("--post-conta", default="principal", help="Conta autorizada (token em .tokens/).")
    args = parser.parse_args()

    social_config = None
    if args.post_youtube:
        from social_publisher import SocialConfig

        social_config = SocialConfig(
            redes=("youtube",),
            dry_run=args.post_dry_run,
            visibilidade=args.post_visibilidade,
            conta=args.post_conta,
        )

    for corte in _listar_cortes(Path(args.entrada)):
        publicar_corte(
            corte,
            nicho=args.nicho,
            credito_streamer=args.credito,
            credito_canal=args.credito_canal,
            saida_dir=args.saida,
            social_config=social_config,
        )
