"""Escolhe os cortes pelo que foi DITO, nao por movimento e volume.

Por que isto existe
-------------------
O `highlight_detector` do BotLive pontua movimento, audio e brilho. Funciona
para gameplay, onde a acao e visual. Nao funciona para podcast, entrevista e
reaction - que e a maior parte das campanhas de corte: ali o momento bom e uma
frase, e a tela nao muda nada.

Quem ganha dinheiro nesse mercado seleciona pela transcricao. O metodo que
circula e: puxar a transcricao do video e pedir a uma IA "me de 10 minutagens
de 15 a 60 segundos". Isto faz a mesma coisa, sem IA externa e sem custo: o
BotLive ja transcreve com faster-whisper na CPU.

Como pontua
-----------
Uma janela vale mais quando:
  - tem fala densa (palavra por segundo alta) - silencio e enrolacao nao viram
    corte;
  - comeca numa frase que prende (pergunta, numero, valor em dinheiro, marcador
    de historia) - e o que faz o dedo parar de rolar;
  - termina no fim de uma frase, e nao no meio de uma palavra.

Nao e IA adivinhando o que e engracado. E densidade de fala mais alguns
marcadores de abertura - explicavel, reproduzivel e de graca.
"""

from __future__ import annotations

import re
import sys

from .store import REPO_ROOT


ALGORITMO = "botlive-fala-v1"

JANELA_MIN = 15.0
JANELA_MAX = 60.0

# Aberturas que prendem: pergunta, numero, dinheiro e marcador de historia.
# Lista curta de proposito - marcador demais vira ruido e pontua tudo igual.
GANCHOS = re.compile(
    r"(\?|\bR\$|\d+\s*(mil|milh|reais|anos|vezes|%)|"
    r"\b(olha|olhe|presta aten|nunca|jamais|primeira vez|ninguem|ningu|"
    r"voce sabia|vc sabia|o segredo|a verdade|na real|acredita|imagina)\b)",
    re.IGNORECASE,
)


def _falas(caminho) -> list:
    """Transcreve o material com o whisper local que o BotLive ja usa."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from transcriber import transcrever_com_tempos

    return transcrever_com_tempos(caminho)


def _palavras(texto: str) -> int:
    return len([x for x in re.split(r"\s+", texto or "") if x])


def pontuar_janela(falas: list, inicio_indice: int, janela_min: float,
                   janela_max: float) -> dict | None:
    """Monta a janela que comeca numa fala e pontua o que cabe dentro dela."""
    abertura = falas[inicio_indice]
    limite = abertura.inicio + janela_max
    dentro = []
    for fala in falas[inicio_indice:]:
        if fala.inicio >= limite:
            break
        dentro.append(fala)
    if not dentro:
        return None

    # Termina na ultima fala que cabe inteira: cortar no meio da palavra e o
    # jeito mais rapido de perder o espectador.
    fim = dentro[-1].fim
    duracao = fim - abertura.inicio
    if duracao < janela_min:
        return None

    texto = " ".join(x.texto for x in dentro)
    palavras = _palavras(texto)
    densidade = palavras / max(duracao, 1.0)
    ganchos = len(GANCHOS.findall(" ".join(x.texto for x in dentro[:2])))

    # Densidade normalizada por 3 palavras/s, que e conversa normal. Gancho na
    # abertura vale ate meio ponto - ajuda, mas nao decide sozinho.
    score = min(densidade / 3.0, 1.0) * 0.8 + min(ganchos * 0.25, 0.5)
    return {
        "inicio": round(abertura.inicio, 2),
        "fim": round(fim, 2),
        "timestamp": round((abertura.inicio + fim) / 2, 2),
        "duracao": round(duracao, 2),
        "score": round(min(score, 1.0), 3),
        "palavras": palavras,
        "densidade": round(densidade, 2),
        "ganchos": ganchos,
        "texto": texto[:400],
        "reason": "fala densa" + (" com gancho na abertura" if ganchos else ""),
    }


def avaliar_com_llm(janelas: list, limite: int) -> list:
    """Reordena as janelas por potencial viral usando um modelo, quando houver.

    O metodo que da dinheiro no mercado e este: joga a transcricao num modelo e
    pergunta quais trechos viralizam. A heuristica acima aproxima por densidade
    de fala, mas nao entende contexto - modelo entende.

    Fica OPCIONAL e desligado por padrao, por causa da regra do projeto:
    LOCAL > GRATUITO > FREE TIER > PAGO. Configure CAMPAIGNS_LLM_URL apontando
    para um Ollama local (gratis) ou para qualquer API compativel com o formato
    da OpenAI. Sem configuracao, a heuristica decide sozinha e nada quebra.

    Falha de rede, modelo fora do ar ou resposta estranha caem de volta na
    ordem da heuristica - o lote nunca para por causa disto.
    """
    import json
    import os
    import urllib.request

    url = os.getenv("CAMPAIGNS_LLM_URL", "").strip()
    if not url or not janelas:
        return janelas

    modelo = os.getenv("CAMPAIGNS_LLM_MODEL", "llama3.1")
    chave = os.getenv("CAMPAIGNS_LLM_KEY", "").strip()
    trechos = [
        {"n": indice, "inicio": x["inicio"], "duracao": x["duracao"], "texto": x["texto"][:300]}
        for indice, x in enumerate(janelas[: limite * 3])
    ]
    pedido = {
        "model": modelo,
        "messages": [
            {"role": "system", "content":
             "Voce escolhe trechos de video com potencial viral para cortes. "
             "Responda APENAS um array JSON com os numeros dos melhores trechos, "
             "do melhor para o pior."},
            {"role": "user", "content":
             f"Escolha os {limite} melhores trechos:\n"
             + json.dumps(trechos, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }
    cabecalhos = {"Content-Type": "application/json"}
    if chave:
        cabecalhos["Authorization"] = f"Bearer {chave}"

    try:
        requisicao = urllib.request.Request(
            url, data=json.dumps(pedido).encode("utf-8"), headers=cabecalhos)
        with urllib.request.urlopen(requisicao, timeout=60) as resposta:
            corpo = json.loads(resposta.read().decode("utf-8"))
        texto = corpo["choices"][0]["message"]["content"]
        escolha = json.loads(re.search(r"\[.*\]", texto, re.S).group(0))
        ordenadas = [janelas[int(n)] for n in escolha if 0 <= int(n) < len(janelas)]
        # O que o modelo nao citou entra depois, na ordem da heuristica.
        restantes = [x for x in janelas if x not in ordenadas]
        for item in ordenadas:
            item["reason"] = item["reason"] + " (escolhido pelo modelo)"
        return ordenadas + restantes
    except Exception:
        return janelas


def detectar(caminho, max_candidates: int = 10, min_gap_seconds: float = 45,
             janela_min: float = JANELA_MIN, janela_max: float = JANELA_MAX,
             min_score: float = 0.0) -> list:
    """Devolve as melhores janelas faladas, sem sobreposicao.

    Lista vazia quando nao ha fala reconhecida - material sem voz (gameplay
    mudo, clipe musical) deve seguir pelo detector de movimento, nao por este.
    """
    falas = _falas(caminho)
    if not falas:
        return []

    janelas = []
    for indice in range(len(falas)):
        janela = pontuar_janela(falas, indice, janela_min, janela_max)
        if janela and janela["score"] >= min_score:
            janelas.append(janela)

    janelas.sort(key=lambda x: x["score"], reverse=True)
    janelas = avaliar_com_llm(janelas, max_candidates)
    escolhidas = []
    for janela in janelas:
        if len(escolhidas) >= max_candidates:
            break
        # Sobreposicao vira corte repetido, e repetido e o que as campanhas
        # recusam. O intervalo minimo e medido entre os centros.
        if any(abs(janela["timestamp"] - x["timestamp"]) < min_gap_seconds for x in escolhidas):
            continue
        escolhidas.append(janela)

    escolhidas.sort(key=lambda x: x["inicio"])
    return escolhidas
