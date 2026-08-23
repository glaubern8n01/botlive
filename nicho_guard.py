"""Guarda de nicho: a fala do corte confere com o nicho do canal?

Por que existe
-------------
O filtro de conteudo (gta_content_filter) mede movimento e audio. Ele nao tem
como saber SE o que esta na tela e um videogame: um reality show em tela cheia
tem movimento alto e audio animado, entao passa como "action" e vai para o ar.
Foi assim que dois cortes do bahiaqz — um jogo de futebol e um trecho com audio
do Rio Shore — subiram e levaram bloqueio global por Content ID (Paramount).

Tentei separar por pixel antes de escrever isto. Medido nos arquivos reais:
  - taxa de corte de camera: TV 0,15-0,20/s | gameplay 0,00-1,15/s -> nao separa
  - HUD fixo (minimapa/barras): TV 0,000-0,006 | gameplay 0,000-0,061 -> nao separa
Os dois sinais se sobrepoem. O que separa e a FALA, e o pipeline ja transcreve
todo corte — entao o sinal ja esta pago.

O que este modulo faz
---------------------
Le a transcricao e responde uma pergunta so: aparece vocabulario de OUTRO
dominio (futebol, reality, TV) sem nenhum vocabulario do nicho? Nao tenta
adivinhar o que o corte e; so levanta a mao quando ha sinal de que NAO e.

O veredito nunca REJEITA sozinho — manda para revisao humana. Um corte errado
que sobe custa um bloqueio de Content ID; um corte certo que espera revisao
custa alguns minutos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Literal


Veredito = Literal["ok", "fora_do_nicho", "sem_sinal"]

# Vocabulario de GTA RP. Palavras que aparecem na cena de roleplay e quase
# nunca numa transmissao esportiva ou de TV.
MARCADORES_GTA = (
    "policia", "policial", "viatura", "delegacia", "cadeia", "prisao", "preso",
    "assalto", "assaltar", "roubo", "roubar", "bandido", "ladrao", "refem",
    "faccao", "mafia", "trafico", "droga", "arma", "pistola", "fuzil", "colete",
    "hospital", "medico", "paramedico", "advogado", "juiz de paz", "tribunal",
    "mecanico", "oficina", "concessionaria", "rp", "roleplay", "personagem",
    "servidor", "cidade", "prefeitura", "banco", "assaltando", "algemado",
    "revistar", "abordagem", "codigo penal", "multa", "carteira", "documento",
    "spawn", "respawn", "loot", "missao", "npc", "gta", "helicoptero",
)

# Futebol: o caso do corte "DEMITE O TECNICO! ... QUE BOLAO!".
# Separados em FORTES e AMBIGUOS por causa de um falso-positivo real: um corte
# do @dantas dizia "estou construindo um estadio aqui" num jogo de construcao e
# foi levantado por "estadio" + "placar". Palavra ambigua sozinha nao acusa.
MARCADORES_FUTEBOL_FORTES = (
    "escanteio", "penalti", "penalty", "tecnico", "campeonato", "escalacao",
    "zagueiro", "goleiro", "atacante", "var", "primeiro tempo", "segundo tempo",
    "bolao", "cartao amarelo", "cartao vermelho", "impedimento", "brasileirao",
    "libertadores", "artilheiro", "contra-ataque", "rebaixamento", "camisa 10",
    "golaco", "craque", "drible",
)
MARCADORES_FUTEBOL_AMBIGUOS = (
    "gol", "meia", "lateral", "juiz", "torcida", "estadio", "falta", "copa",
    "selecao", "empate", "placar", "tabela", "titulo",
)

# Reality / TV aberta: a origem do bloqueio da Paramount.
MARCADORES_TV_FORTES = (
    "paredao", "eliminacao", "participante", "confinamento", "prova do lider",
    "sincerao", "big brother", "bbb", "reality", "apresentador", "programa de tv",
    "novela", "capitulo", "camera escondida", "plateia",
)
MARCADORES_TV_AMBIGUOS = (
    "eliminado", "votacao", "episodio", "temporada", "elenco", "gravacao",
)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", str(texto).lower())
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9\s]+", " ", sem_acento)


def _contar(texto_normalizado: str, marcadores: Iterable[str]) -> list[str]:
    """Conta marcadores presentes, com fronteira de palavra.

    Fronteira importa: sem ela "gol" casa dentro de "golpe" e "var" dentro de
    "varanda", e ai qualquer conversa vira futebol.
    """
    achados = []
    for marcador in marcadores:
        padrao = r"\b" + r"\s+".join(re.escape(p) for p in marcador.split()) + r"\b"
        if re.search(padrao, texto_normalizado):
            achados.append(marcador)
    return achados


@dataclass(frozen=True)
class ResultadoNicho:
    veredito: Veredito
    motivo: str
    marcadores_nicho: tuple[str, ...]
    marcadores_fora: tuple[str, ...]

    @property
    def precisa_revisao(self) -> bool:
        return self.veredito != "ok"


def avaliar_transcricao(
    transcricao: str,
    *,
    nicho: str = "gta",
    minimo_fora: int = 2,
    exigir_sinal_do_nicho: bool = False,
) -> ResultadoNicho:
    """Compara a fala do corte com o vocabulario do nicho.

    minimo_fora: quantos marcadores de outro dominio bastam para levantar a mao.
        2 e o piso proposital — uma palavra solta ("copa", "juiz") aparece em
        conversa de RP sem que o corte seja de futebol.

    exigir_sinal_do_nicho: se True, corte SEM nenhum marcador do nicho tambem
        vai para revisao. Pega o caso da narracao generica (o trecho do Rio
        Shore nao tem palavra de futebol nem de RP), mas o custo em revisao
        manual e alto — por isso fica desligado por padrao e medido antes.
    """
    texto = _normalizar(transcricao)
    if not texto.strip():
        return ResultadoNicho("sem_sinal", "transcricao vazia", (), ())

    if nicho != "gta":
        # Sem lexico calibrado para outro nicho, nao opina.
        return ResultadoNicho("ok", f"nicho {nicho} sem lexico; guarda nao opina", (), ())

    do_nicho = tuple(_contar(texto, MARCADORES_GTA))
    fortes = tuple(_contar(texto, MARCADORES_FUTEBOL_FORTES) + _contar(texto, MARCADORES_TV_FORTES))
    ambiguos = tuple(_contar(texto, MARCADORES_FUTEBOL_AMBIGUOS) + _contar(texto, MARCADORES_TV_AMBIGUOS))
    fora = fortes + ambiguos

    # Exige ao menos um marcador FORTE: so palavra ambigua nao acusa ninguem.
    if fortes and len(fora) >= minimo_fora and not do_nicho:
        return ResultadoNicho(
            "fora_do_nicho",
            f"fala de outro dominio ({', '.join(fora[:6])}) e nenhum termo do nicho",
            do_nicho, fora,
        )

    if exigir_sinal_do_nicho and not do_nicho:
        return ResultadoNicho(
            "sem_sinal",
            "nenhum termo do nicho na fala; confianca baixa",
            do_nicho, fora,
        )

    return ResultadoNicho("ok", "fala compativel com o nicho", do_nicho, fora)
