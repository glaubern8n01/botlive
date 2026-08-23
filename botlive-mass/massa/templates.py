"""Templates de edicao: configurar uma vez, aplicar em todo o lote.

Sem isso o operador reconfigura logo, CTA e formato a cada campanha - que e
exatamente o trabalho manual que o modulo existe para eliminar.

Os limites nao sao decorativos: velocidade fora de 0.5-2.0 destroi o audio,
escala de logo acima de 40% cobre o video, e formato fora da lista quebra o
render. Recusar aqui e melhor do que descobrir depois de 80 videos.
"""

from __future__ import annotations

from .store import MassaError, agora, atualizar, inserir, listar, obter


FORMATOS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

MODOS_HORIZONTAL = ("crop", "fit", "blur")
POSICOES = ("superior-esquerda", "superior-direita", "inferior-esquerda",
            "inferior-direita", "centro", "superior", "inferior")
AUDIOS = ("manter", "remover", "normalizar")

# Mockup aceita imagem ou video com canal alpha (webm/vp9, mov prores 4444).
# O editor detecta pela extensao e trata video em loop; ver editor.mockup_e_video.
LOGO_ACEITOS = (".png", ".webp", ".jpg", ".jpeg")
MOCKUP_ACEITOS = LOGO_ACEITOS + (".webm", ".mov", ".mp4", ".mkv")

PADRAO = {
    "formato": "9:16",
    "modo_horizontal": "blur",
    "logo_posicao": "inferior-direita",
    "logo_escala": 0.15,
    "logo_opacidade": 0.9,
    "mockup_posicao": "cobrir",
    "mockup_opacidade": 1.0,
    "cta_posicao": "inferior",
    "cta_tamanho": 0.055,
    "audio": "manter",
    "volume": 1.0,
    "cortar_inicio": 0.0,
    "cortar_fim": 0.0,
    "velocidade": 1.0,
}


def _validar(dados: dict) -> dict:
    from pathlib import Path

    if dados["formato"] not in FORMATOS:
        raise MassaError(f"Formato invalido: {dados['formato']}. Use {list(FORMATOS)}")
    if dados["modo_horizontal"] not in MODOS_HORIZONTAL:
        raise MassaError(f"Modo horizontal invalido. Use {list(MODOS_HORIZONTAL)}")
    if dados["audio"] not in AUDIOS:
        raise MassaError(f"Opcao de audio invalida. Use {list(AUDIOS)}")
    for campo in ("logo_posicao", "cta_posicao"):
        if dados[campo] and dados[campo] not in POSICOES:
            raise MassaError(f"{campo} invalida. Use {list(POSICOES)}")
    if not 0.02 <= dados["logo_escala"] <= 0.4:
        raise MassaError("logo_escala deve ficar entre 0.02 e 0.4 (acima disso cobre o video)")
    for campo in ("logo_opacidade", "mockup_opacidade"):
        if not 0 <= dados[campo] <= 1:
            raise MassaError(f"{campo} deve ficar entre 0 e 1")
    if not 0.5 <= dados["velocidade"] <= 2.0:
        raise MassaError("velocidade deve ficar entre 0.5 e 2.0 (fora disso o audio quebra)")
    if not 0 <= dados["volume"] <= 4:
        raise MassaError("volume deve ficar entre 0 e 4")
    for campo in ("cortar_inicio", "cortar_fim"):
        if dados[campo] < 0:
            raise MassaError(f"{campo} nao pode ser negativo")
    for campo in ("logo_path", "mockup_path"):
        caminho = dados.get(campo) or ""
        if caminho and not Path(caminho).is_file():
            raise MassaError(f"{campo} aponta para arquivo inexistente: {caminho}")
    mockup = dados.get("mockup_path") or ""
    if mockup and Path(mockup).suffix.lower() not in MOCKUP_ACEITOS:
        raise MassaError(
            f"mockup precisa ser imagem ou video com transparencia. "
            f"Aceito: {', '.join(MOCKUP_ACEITOS)}"
        )
    logo = dados.get("logo_path") or ""
    if logo and Path(logo).suffix.lower() not in LOGO_ACEITOS:
        raise MassaError(f"logo precisa ser imagem. Aceito: {', '.join(LOGO_ACEITOS)}")
    return dados


def criar(nome: str, **campos) -> dict:
    if not (nome or "").strip():
        raise MassaError("Template precisa de nome")
    dados = {**PADRAO, "logo_path": "", "mockup_path": "", "cta_texto": "", **campos}
    dados = _validar(dados)
    stamp = agora()
    return inserir("mass_templates", {
        "nome": nome.strip(), **dados, "created_at": stamp, "updated_at": stamp,
    })


def editar(template_id: str, **campos) -> dict:
    atual = obter("mass_templates", template_id)
    if not atual:
        raise MassaError("Template inexistente")
    fundido = {**atual, **campos}
    _validar({k: fundido[k] for k in {*PADRAO, "logo_path", "mockup_path"} if k in fundido})
    campos["updated_at"] = agora()
    return atualizar("mass_templates", template_id, campos)


def exigir(template_id: str) -> dict:
    template = obter("mass_templates", template_id)
    if not template:
        raise MassaError("Template inexistente")
    return template


def todos() -> list:
    return listar("mass_templates", 200)


def dimensoes(template: dict) -> tuple:
    return FORMATOS[template["formato"]]
