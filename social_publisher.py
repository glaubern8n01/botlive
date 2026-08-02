from __future__ import annotations

import importlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Núcleo genérico de auto-post. Cada rede é um plugin importado sob demanda.
# O TikTok usa Upload to TikTok: envia para a caixa de entrada como rascunho,
# nunca publica diretamente no perfil.
REDES_DISPONIVEIS = {
    "youtube": "yt_publisher",
    "instagram": "instagram_publisher",
    "tiktok": "tiktok_publisher",
}

VISIBILIDADES = ("private", "unlisted", "public")


@dataclass(frozen=True)
class SocialConfig:
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
        raise ValueError(
            f"rede desconhecida: {rede!r} (disponíveis: {sorted(REDES_DISPONIVEIS)})"
        )
    return importlib.import_module(module_name)


def _tiktok_depois_do_instagram() -> bool:
    """Liga o encadeamento Reels -> rascunho TikTok.

    Padrão ligado para restaurar o fluxo pedido. Pode ser desligado com
    BOTLIVE_TIKTOK_AFTER_INSTAGRAM=0. Sem token, a falha fica registrada no
    publish.json e não derruba o Reel nem o restante do pipeline.
    """
    return os.environ.get("BOTLIVE_TIKTOK_AFTER_INSTAGRAM", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def postar_redes(
    registro: dict,
    config: SocialConfig,
    json_path: Optional[str | Path] = None,
) -> dict:
    """Posta nas redes e persiste cada resultado no publish.json.

    Quando Instagram termina com sucesso, adiciona TikTok à fila e envia o
    mesmo MP4 vertical para a caixa de entrada como rascunho. O encadeamento é
    idempotente e não baixa o Reel: reutiliza o arquivo original sem marca-d'água.
    """
    postagens = registro.get("postagens") or {}
    fila = list(dict.fromkeys(config.redes))
    indice = 0

    while indice < len(fila):
        rede = fila[indice]
        indice += 1
        anterior = postagens.get(rede)
        # Idempotente apenas para ação real bem-sucedida. Dry-run e erro podem
        # ser substituídos numa tentativa futura.
        if anterior and not anterior.get("erro") and not anterior.get("dry_run"):
            print(f"[social] {rede}: já concluído antes, pulando (idempotente).")
            if (
                rede == "instagram"
                and _tiktok_depois_do_instagram()
                and "tiktok" not in fila
            ):
                fila.append("tiktok")
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
        resultado["registrado_em"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        postagens[rede] = resultado

        modo = "dry-run" if config.dry_run else "real"
        status = "ok" if resultado.get("erro") is None else f"erro={resultado['erro']}"
        print(f"[social] rede={rede} modo={modo} conta={config.conta} | {status}")

        # Só encadeia após Reel realmente aceito. Erro no TikTok nunca desfaz o
        # Instagram e fica visível no publish.json para nova tentativa.
        if (
            rede == "instagram"
            and resultado.get("erro") is None
            and _tiktok_depois_do_instagram()
            and "tiktok" not in fila
        ):
            fila.append("tiktok")
            print("[social] Instagram concluído; enviando o mesmo vertical ao TikTok como rascunho.")

        if json_path is not None:
            try:
                registro["postagens"] = postagens
                Path(json_path).write_text(
                    json.dumps(registro, ensure_ascii=False, indent=4),
                    encoding="utf-8",
                )
            except Exception as exc:
                print(f"[social][falha] não gravou postagens em {json_path}: {exc}")

    registro["postagens"] = postagens
    return postagens


def postar_de_publish_json(json_path: str | Path, config: SocialConfig) -> dict:
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
        description="Publica a partir de publish.json; TikTok é enviado como rascunho."
    )
    parser.add_argument("entrada", help="Um *_publish.json ou pasta com vários.")
    parser.add_argument(
        "--rede",
        action="append",
        choices=sorted(REDES_DISPONIVEIS),
        required=True,
        help="Rede de destino; repita para mais de uma.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula e grava o resultado sem subir nada.",
    )
    parser.add_argument("--visibilidade", choices=VISIBILIDADES, default="unlisted")
    parser.add_argument("--conta", default="principal")
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
