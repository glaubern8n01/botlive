from __future__ import annotations

import importlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Nucleo generico de auto-post nas redes sociais. Roda sempre DEPOIS da
# publicacao (publish.json ja gravado) e e opt-in por flag (--post-youtube).
# YouTube e Instagram usam plugins locais. TikTok permanece isolado no worker
# tiktok-public: depois do sucesso do Reel, apenas criamos um job Supabase em
# tiktok_standard/upload_draft; nenhuma credencial TikTok entra neste container.
REDES_DISPONIVEIS = {
    "youtube": "yt_publisher",
    # Normaliza H.264/AAC/yuv420p/faststart antes do rupload para evitar
    # ProcessingFailedError da Meta em MP4 gerado por fontes variadas.
    "instagram": "instagram_safe_publisher",
}

VISIBILIDADES = ("private", "unlisted", "public")


@dataclass(frozen=True)
class SocialConfig:
    """Config do auto-post vinda do CLI. redes vazio = auto-post desligado."""

    redes: tuple[str, ...] = ()
    dry_run: bool = False
    visibilidade: str = "unlisted"
    conta: str = "principal"

    @property
    def enabled(self) -> bool:
        return bool(self.redes)


def _carregar_plugin(rede: str):
    module_name = REDES_DISPONIVEIS.get(rede)
    if not module_name:
        raise ValueError(f"rede desconhecida: {rede!r} (disponiveis: {sorted(REDES_DISPONIVEIS)})")
    return importlib.import_module(module_name)


def _enfileirar_tiktok_apos_instagram(registro: dict, config: SocialConfig) -> dict:
    """Restaura o fluxo antigo: Reel aceito -> fila do servico tiktok-public."""
    if config.dry_run:
        return {"tipo": "fila_tiktok_public", "dry_run": True, "erro": None}
    try:
        from legacy_tiktok_bridge import enfileirar_rascunho_tiktok

        resultado = enfileirar_rascunho_tiktok(registro)
        print(
            "[social] Instagram concluido; job tiktok_standard/upload_draft "
            f"enfileirado para tiktok-public: {resultado.get('job_id')}"
        )
        return resultado
    except Exception as exc:
        print(f"[social][tiktok][falha] Reel publicado, mas fila TikTok falhou: {exc}")
        return {"tipo": "fila_tiktok_public", "erro": str(exc), "dry_run": False}


def postar_redes(
    registro: dict,
    config: SocialConfig,
    json_path: Optional[str | Path] = None,
) -> dict:
    """Posta o corte nas redes configuradas e grava o resultado no publish.json.

    Nunca levanta excecao: qualquer falha vira {"erro": ...} no bloco da rede
    e o pipeline segue. Depois de um Instagram real bem-sucedido, cria de forma
    idempotente o job que o container tiktok-public transforma em notificacao
    editavel no aplicativo TikTok.
    """
    postagens = registro.get("postagens") or {}
    for rede in config.redes:
        anterior = postagens.get(rede)
        if anterior and not anterior.get("erro") and not anterior.get("dry_run"):
            print(f"[social] {rede}: ja postado antes, pulando (idempotente).")
            # Um Reel antigo pode ter sido publicado antes da ponte ser restaurada.
            # Nesse caso ainda tentamos criar o job TikTok ausente.
            if rede == "instagram":
                tiktok = postagens.get("tiktok") or {}
                if not tiktok or tiktok.get("erro"):
                    postagens["tiktok"] = _enfileirar_tiktok_apos_instagram(registro, config)
            continue

        t0 = time.monotonic()
        try:
            plugin = _carregar_plugin(rede)
            resultado = plugin.postar_corte_registro(registro, config)
        except Exception as exc:
            resultado = {"erro": str(exc), "dry_run": config.dry_run}
            print(f"[social][falha] rede={rede} motivo={exc}; pipeline segue.")
        resultado.setdefault("erro", None)
        resultado["conta"] = config.conta
        resultado["dry_run"] = config.dry_run
        resultado["tempo_s"] = round(time.monotonic() - t0, 1)
        resultado["registrado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        postagens[rede] = resultado
        registro["postagens"] = postagens
        modo = "dry-run" if config.dry_run else "real"
        status = "ok" if resultado.get("erro") is None else f"erro={resultado['erro']}"
        print(f"[social] rede={rede} modo={modo} conta={config.conta} | {status}")

        if rede == "instagram" and resultado.get("erro") is None:
            postagens["tiktok"] = _enfileirar_tiktok_apos_instagram(registro, config)
            registro["postagens"] = postagens

        # Persiste apos cada destino, para o erro da ponte ficar visivel e poder
        # ser retentado no ciclo seguinte sem repetir um Reel ja publicado.
        if json_path is not None:
            try:
                Path(json_path).write_text(
                    json.dumps(registro, ensure_ascii=False, indent=4), encoding="utf-8"
                )
            except Exception as exc:
                print(f"[social][falha] nao gravou postagens em {json_path}: {exc}")

    registro["postagens"] = postagens
    if json_path is not None:
        try:
            Path(json_path).write_text(
                json.dumps(registro, ensure_ascii=False, indent=4), encoding="utf-8"
            )
        except Exception as exc:
            print(f"[social][falha] nao gravou postagens em {json_path}: {exc}")
    return postagens


def postar_de_publish_json(json_path: str | Path, config: SocialConfig) -> dict:
    """Auto-post a partir de um publish.json ja existente (uso standalone)."""
    json_path = Path(json_path)
    registro = json.loads(json_path.read_text(encoding="utf-8"))
    return postar_redes(registro, config, json_path=json_path)


def _listar_publish_jsons(entrada: Path) -> list[Path]:
    if entrada.is_file():
        return [entrada]
    arquivos = sorted(entrada.glob("*_publish.json"))
    if not arquivos:
        raise SystemExit(f"Nenhum *_publish.json encontrado em {entrada}")
    return arquivos


if __name__ == "__main__":
    import argparse

    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Auto-post nas redes a partir de publish.json ja gerados."
    )
    parser.add_argument("entrada", help="Um *_publish.json ou pasta com varios.")
    parser.add_argument(
        "--rede",
        action="append",
        choices=sorted(REDES_DISPONIVEIS),
        required=True,
        help="Rede de destino; repita a flag para mais de uma.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula: monta o post e grava no json, sem subir nada.")
    parser.add_argument("--visibilidade", choices=VISIBILIDADES, default="unlisted")
    parser.add_argument("--conta", default="principal", help="Nome da conta autorizada (token em .tokens/).")
    args = parser.parse_args()

    config = SocialConfig(
        redes=tuple(dict.fromkeys(args.rede)),
        dry_run=args.dry_run,
        visibilidade=args.visibilidade,
        conta=args.conta,
    )
    for json_file in _listar_publish_jsons(Path(args.entrada)):
        print(f"[social] processando {json_file.name}")
        postar_de_publish_json(json_file, config)
