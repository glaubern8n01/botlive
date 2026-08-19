"""Scheduler: decide se uma conta pode publicar agora e quando podera.

Todo limite vem da conta (max_posts_per_day, minimum_interval_minutes,
allowed_hours). Nenhum numero de posts por dia esta fixo no codigo.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..core import store


try:  # zoneinfo depende de tzdata no Windows; sem ele caimos para UTC.
    from zoneinfo import ZoneInfo

    def _zona(nome: str):
        try:
            return ZoneInfo(nome)
        except Exception:
            return timezone.utc

except ImportError:  # pragma: no cover - ambiente sem zoneinfo

    def _zona(nome: str):
        return timezone.utc


LIVRE = (True, "")


def _horas_permitidas(conta: dict) -> list:
    try:
        horas = json.loads(conta.get("allowed_hours") or "[]")
    except (TypeError, ValueError):
        return []
    return [hora for hora in horas if isinstance(hora, int) and 0 <= hora <= 23]


def _ultima_publicacao(account_id: str) -> datetime | None:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT posted_at FROM vexpublish_jobs "
            "WHERE account=? AND status='posted' AND posted_at IS NOT NULL "
            "ORDER BY posted_at DESC LIMIT 1",
            (account_id,),
        ).fetchone()
    if not linha or not linha["posted_at"]:
        return None
    return datetime.fromisoformat(linha["posted_at"])


def _publicados_no_dia(account_id: str, inicio: datetime) -> int:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT COUNT(*) AS total FROM vexpublish_jobs "
            "WHERE account=? AND status='posted' AND posted_at>=?",
            (account_id, inicio.isoformat()),
        ).fetchone()
    return int(linha["total"]) if linha else 0


def pode_publicar_agora(conta: dict, momento: datetime | None = None) -> tuple[bool, str]:
    """Devolve (permitido, motivo). Motivo vazio quando liberado."""
    momento = momento or datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)

    if conta.get("status") != "active":
        return False, "conta_inativa"

    local = momento.astimezone(_zona(conta.get("timezone") or "UTC"))
    horas = _horas_permitidas(conta)
    if horas and local.hour not in horas:
        return False, "fora_da_janela"

    intervalo = int(conta.get("minimum_interval_minutes") or 0)
    if intervalo:
        ultima = _ultima_publicacao(conta["id"])
        if ultima and momento - ultima < timedelta(minutes=intervalo):
            return False, "intervalo_minimo"

    teto = int(conta.get("max_posts_per_day") or 0)
    if teto:
        inicio_do_dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if _publicados_no_dia(conta["id"], inicio_do_dia.astimezone(timezone.utc)) >= teto:
            return False, "teto_diario"

    return LIVRE


def proximo_horario(conta: dict, momento: datetime | None = None) -> datetime:
    """Menor horario futuro que respeita janela e intervalo minimo.

    O teto diario nao e resolvido por espera curta: quando ele estoura, o
    proximo horario cai para o inicio do dia seguinte da conta.
    """
    momento = momento or datetime.now(timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    zona = _zona(conta.get("timezone") or "UTC")

    candidato = momento
    intervalo = int(conta.get("minimum_interval_minutes") or 0)
    if intervalo:
        ultima = _ultima_publicacao(conta["id"])
        if ultima:
            candidato = max(candidato, ultima + timedelta(minutes=intervalo))

    teto = int(conta.get("max_posts_per_day") or 0)
    if teto:
        local = candidato.astimezone(zona)
        inicio_do_dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if _publicados_no_dia(conta["id"], inicio_do_dia.astimezone(timezone.utc)) >= teto:
            candidato = (inicio_do_dia + timedelta(days=1)).astimezone(timezone.utc)

    horas = _horas_permitidas(conta)
    if horas:
        local = candidato.astimezone(zona)
        for adiantar in range(0, 48):
            tentativa = (local + timedelta(hours=adiantar)).replace(
                minute=0, second=0, microsecond=0
            )
            if tentativa.hour in horas and tentativa >= local.replace(
                minute=0, second=0, microsecond=0
            ):
                return tentativa.astimezone(timezone.utc)
    return candidato
