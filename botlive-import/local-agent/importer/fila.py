"""Fila de trabalho da importacao: render fora do ciclo da requisicao.

Por que existe
--------------
Renderizar era sincrono: o POST /render segurava a conexao ate o FFmpeg
terminar. Num lote de material longo isso estoura o timeout do navegador e do
proxy, e o operador fica sem saber se o video saiu ou nao - quando saiu.
Agora a rota enfileira e responde na hora; quem trabalha e o worker.

A tabela `import_jobs` ja existia no schema desde a Fase 5 e nunca teve dono.
Este modulo e o dono.

Garantias
---------
- **Claim atomico**: dois workers nunca pegam o mesmo job. A reivindicacao e um
  UPDATE condicionado ao status, e quem nao mudou linha nenhuma nao ganhou o
  job.
- **Idempotencia**: a chave e do par (tipo, entidade). Apertar "renderizar"
  duas vezes nao cria duas filas para o mesmo video.
- **Backoff**: tentativa que falha volta para a fila com espera crescente, ate
  o teto de tentativas. Sem loop infinito.
- **Orfaos**: worker que morreu no meio deixa o job preso em `running`; a
  recuperacao devolve para a fila depois de um tempo, em vez de perder o
  trabalho.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone

from .store import ImportError_, agora, atualizar, conectar, inserir, listar, obter


TIPOS = ("render",)
MAX_TENTATIVAS = int(os.getenv("IMPORT_JOB_TENTATIVAS", "3"))
ORFAO_SEGUNDOS = int(os.getenv("IMPORT_JOB_ORFAO_SEGUNDOS", "1800"))


def identidade_do_worker() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _agora_dt() -> datetime:
    return datetime.now(timezone.utc)


def _espera(tentativas: int) -> str:
    """Backoff exponencial simples, em minutos: 1, 2, 4..."""
    minutos = min(2 ** max(0, tentativas - 1), 60)
    return (_agora_dt() + timedelta(minutes=minutos)).isoformat()


def enfileirar(kind: str, entity_id: str, payload: dict | None = None) -> dict:
    """Coloca um trabalho na fila. Repetido devolve o job que ja existia."""
    if kind not in TIPOS:
        raise ImportError_(f"Tipo de job invalido: {kind}. Use {list(TIPOS)}")
    chave = f"{kind}:{entity_id}"
    with conectar() as db:
        linha = db.execute("SELECT * FROM import_jobs WHERE idempotency_key=?", (chave,)).fetchone()
    if linha:
        atual = dict(linha)
        # Job encerrado com falha pode ser retentado; concluido nao volta.
        if atual["status"] == "failed":
            return atualizar("import_jobs", atual["id"], {
                "status": "queued", "attempts": 0, "error": "",
                "run_after": None, "worker_id": None, "claimed_at": None,
                "updated_at": agora(),
            })
        return atual

    stamp = agora()
    registro = inserir("import_jobs", {
        "kind": kind,
        "entity_id": entity_id,
        "payload": json.dumps(payload or {}, ensure_ascii=False),
        "status": "queued",
        "idempotency_key": chave,
        "created_at": stamp,
        "updated_at": stamp,
    })
    return obter("import_jobs", registro["id"])


def recuperar_orfaos(segundos: int = ORFAO_SEGUNDOS) -> int:
    """Job preso em running por worker que morreu volta para a fila."""
    limite = (_agora_dt() - timedelta(seconds=segundos)).isoformat()
    with conectar() as db:
        resultado = db.execute(
            "UPDATE import_jobs SET status='queued', worker_id=NULL, claimed_at=NULL, "
            "updated_at=? WHERE status='running' AND (claimed_at IS NULL OR claimed_at < ?)",
            (agora(), limite),
        )
        return resultado.rowcount or 0


def reivindicar(worker_id: str | None = None) -> dict | None:
    """Pega o proximo job disponivel, ou None.

    O UPDATE condicionado ao status e o que impede dois workers de pegarem o
    mesmo job: quem chega depois nao encontra mais a linha em 'queued' e o
    rowcount volta zero.
    """
    worker_id = worker_id or identidade_do_worker()
    agora_iso = agora()
    with conectar() as db:
        candidatos = db.execute(
            "SELECT id FROM import_jobs WHERE status='queued' AND attempts < max_attempts "
            "AND (run_after IS NULL OR run_after <= ?) ORDER BY created_at LIMIT 5",
            (agora_iso,),
        ).fetchall()
        for candidato in candidatos:
            resultado = db.execute(
                "UPDATE import_jobs SET status='running', worker_id=?, claimed_at=?, updated_at=? "
                "WHERE id=? AND status='queued'",
                (worker_id, agora_iso, agora_iso, candidato["id"]),
            )
            if resultado.rowcount:
                return obter("import_jobs", candidato["id"])
    return None


def _executar(job: dict) -> dict:
    from .adapt import executar as renderizar

    if job["kind"] == "render":
        return renderizar(job["entity_id"])
    raise ImportError_(f"Tipo de job sem executor: {job['kind']}")


def processar_um(worker_id: str | None = None) -> dict | None:
    """Executa um job da fila. Nunca levanta: falha vira status + motivo."""
    job = reivindicar(worker_id)
    if not job:
        return None

    tentativas = int(job["attempts"]) + 1
    try:
        _executar(job)
    except Exception as erro:
        esgotou = tentativas >= int(job["max_attempts"])
        return atualizar("import_jobs", job["id"], {
            "status": "failed" if esgotou else "queued",
            "attempts": tentativas,
            "error": str(erro)[:400],
            # Sem espera, um erro instantaneo viraria giro em vazio.
            "run_after": None if esgotou else _espera(tentativas),
            "worker_id": None,
            "claimed_at": None,
            "updated_at": agora(),
        })

    return atualizar("import_jobs", job["id"], {
        "status": "done", "attempts": tentativas, "error": "",
        "worker_id": None, "claimed_at": None, "updated_at": agora(),
    })


def rodar(maximo: int = 3, worker_id: str | None = None) -> dict:
    """Processa ate `maximo` jobs. Chamado pela interface ou por um laco."""
    recuperados = recuperar_orfaos()
    processados = []
    for _ in range(max(1, maximo)):
        resultado = processar_um(worker_id)
        if not resultado:
            break
        processados.append({
            "id": resultado["id"],
            "kind": resultado["kind"],
            "status": resultado["status"],
            "error": resultado.get("error", ""),
        })
    return {"processados": len(processados), "itens": processados, "orfaos_recuperados": recuperados}


def resumo() -> dict:
    with conectar() as db:
        linhas = db.execute("SELECT status, COUNT(*) AS total FROM import_jobs GROUP BY status")
        return {linha["status"]: int(linha["total"]) for linha in linhas}


def fila(limite: int = 200) -> dict:
    return {"items": listar("import_jobs", limite), "resumo": resumo()}
