"""Entidades core compartilhadas: Channel, Account, Session, MediaAsset, PublishJob.

As entidades nascem aqui para que Campanhas de Cortes, Importar/Adaptar/Publicar
e Commerce Studio produzam PublishJob em vez de falar direto com navegador/API.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from . import store
from .errors import CodigoErro, VexPublishError, exigir_transicao
from .flags import PLATAFORMAS, carregar


SLUG_INVALIDO = re.compile(r"[^a-z0-9-]+")


def _slug(texto: str) -> str:
    base = SLUG_INVALIDO.sub("-", texto.strip().lower()).strip("-")
    if not base:
        raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Nome de canal invalido")
    return base


def _exigir_plataforma(plataforma: str) -> str:
    normal = (plataforma or "").strip().lower()
    if normal not in PLATAFORMAS:
        raise VexPublishError(
            CodigoErro.VALIDATION_ERROR,
            f"Plataforma nao suportada: {plataforma}",
            {"suportadas": list(PLATAFORMAS)},
        )
    return normal


def _json(valor) -> str:
    return json.dumps(valor if valor is not None else [], ensure_ascii=False)


# --- Channel ---------------------------------------------------------------


@dataclass
class Channel:
    """Canal de publicacao (marca/nicho). Nome interno provisorio.

    Nao confundir com vigia_channels, que sao os canais Twitch de origem.
    """

    name: str
    niche: str = ""
    platforms: list = field(default_factory=list)
    identity: dict = field(default_factory=dict)
    voice: str = ""
    calendar: dict = field(default_factory=dict)
    content_rules: dict = field(default_factory=dict)
    preferred_providers: list = field(default_factory=list)
    status: str = "paused"
    notes: str = ""

    def salvar(self) -> dict:
        for plataforma in self.platforms:
            _exigir_plataforma(plataforma)
        stamp = store.agora()
        return store.inserir(
            "vexpublish_channels",
            {
                "name": self.name,
                "slug": _slug(self.name),
                "niche": self.niche,
                "identity": _json(self.identity),
                "voice": self.voice,
                "platforms": _json(self.platforms),
                "calendar": _json(self.calendar),
                "content_rules": _json(self.content_rules),
                "preferred_providers": _json(self.preferred_providers),
                "status": self.status,
                "notes": self.notes,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )


# --- Account ---------------------------------------------------------------


@dataclass
class Account:
    """Conta de uma plataforma vinculada a um canal.

    Limites sao por conta e configuraveis: nada de 10 a 100 posts/dia fixo no codigo.
    """

    channel_id: str
    platform: str
    handle: str
    label: str = ""
    status: str = "inactive"
    max_posts_per_day: int = 0
    minimum_interval_minutes: int = 0
    allowed_hours: list = field(default_factory=list)
    timezone: str = "UTC"

    def salvar(self) -> dict:
        plataforma = _exigir_plataforma(self.platform)
        for hora in self.allowed_hours:
            if not isinstance(hora, int) or not 0 <= hora <= 23:
                raise VexPublishError(
                    CodigoErro.VALIDATION_ERROR, "allowed_hours aceita apenas horas 0-23"
                )
        if self.max_posts_per_day < 0 or self.minimum_interval_minutes < 0:
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Limite negativo")
        stamp = store.agora()
        return store.inserir(
            "vexpublish_accounts",
            {
                "channel_id": self.channel_id,
                "platform": plataforma,
                "handle": self.handle,
                "label": self.label,
                "status": self.status,
                "max_posts_per_day": self.max_posts_per_day,
                "minimum_interval_minutes": self.minimum_interval_minutes,
                "allowed_hours": _json(sorted(self.allowed_hours)),
                "timezone": self.timezone,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )


# --- MediaAsset ------------------------------------------------------------


@dataclass
class MediaAsset:
    path: str
    channel_id: str | None = None
    sha256: str = ""
    mime: str = ""
    width: int = 0
    height: int = 0
    duration_seconds: float = 0.0
    size_bytes: int = 0
    source: str = ""
    rights: str = ""
    authorized: bool = False

    def salvar(self) -> dict:
        return store.inserir(
            "vexpublish_media_assets",
            {
                "channel_id": self.channel_id,
                "path": self.path,
                "sha256": self.sha256,
                "mime": self.mime,
                "width": self.width,
                "height": self.height,
                "duration_seconds": self.duration_seconds,
                "size_bytes": self.size_bytes,
                "source": self.source,
                "rights": self.rights,
                "authorized": 1 if self.authorized else 0,
                "created_at": store.agora(),
            },
        )


# --- PublishJob ------------------------------------------------------------


def chave_idempotencia(
    channel_id: str,
    platform: str,
    account: str,
    media_path: str,
    scheduled_at: str | None = None,
) -> str:
    """Mesma midia, mesma conta e mesmo horario nunca geram dois jobs."""
    bruto = "|".join([channel_id, platform, account, media_path, scheduled_at or ""])
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


@dataclass
class PublishJob:
    channel_id: str
    platform: str
    account: str
    media_path: str
    title: str = ""
    caption: str = ""
    hashtags: list = field(default_factory=list)
    scheduled_at: str | None = None
    requires_approval: bool | None = None
    idempotency_key: str | None = None
    max_attempts: int | None = None

    def criar(self) -> dict:
        flags = carregar()
        plataforma = _exigir_plataforma(self.platform)
        if not self.media_path:
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "media_path obrigatorio")
        conta = store.obter("vexpublish_accounts", self.account)
        if not conta:
            raise VexPublishError(CodigoErro.VALIDATION_ERROR, "Conta inexistente")
        if conta["platform"] != plataforma:
            raise VexPublishError(
                CodigoErro.VALIDATION_ERROR, "Conta nao pertence a plataforma informada"
            )
        if conta["channel_id"] != self.channel_id:
            raise VexPublishError(
                CodigoErro.VALIDATION_ERROR, "Conta nao pertence ao canal informado"
            )

        chave = self.idempotency_key or chave_idempotencia(
            self.channel_id, plataforma, self.account, self.media_path, self.scheduled_at
        )
        existente = buscar_por_chave(chave)
        if existente:
            return existente

        if self.requires_approval is None:
            aprovacao = flags.require_approval
        else:
            aprovacao = self.requires_approval
        stamp = store.agora()
        job = store.inserir(
            "vexpublish_jobs",
            {
                "channel_id": self.channel_id,
                "platform": plataforma,
                "account": self.account,
                "media_path": self.media_path,
                "title": self.title,
                "caption": self.caption,
                "hashtags": _json(self.hashtags),
                "scheduled_at": self.scheduled_at,
                "requires_approval": 1 if aprovacao else 0,
                "status": "draft",
                "idempotency_key": chave,
                "attempts": 0,
                "max_attempts": self.max_attempts or flags.max_attempts,
                "dry_run": 1 if flags.dry_run else 0,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        store.registrar_evento(job["id"], "job.created", "ok", to_status="draft")
        return store.obter("vexpublish_jobs", job["id"])


def buscar_por_chave(chave: str) -> dict | None:
    with store.conectar() as db:
        linha = db.execute(
            "SELECT * FROM vexpublish_jobs WHERE idempotency_key=?", (chave,)
        ).fetchone()
    return dict(linha) if linha else None


def mudar_status(job_id: str, destino: str, **campos) -> dict:
    """Transicao validada e atomica: nunca pula estado nem revive job terminal."""
    with store.conectar() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            linha = db.execute("SELECT * FROM vexpublish_jobs WHERE id=?", (job_id,)).fetchone()
            if not linha:
                raise KeyError(job_id)
            origem = linha["status"]
            exigir_transicao(origem, destino)
            payload = {"status": destino, "updated_at": store.agora(), **campos}
            setters = ",".join(f"{chave}=?" for chave in payload)
            db.execute(
                f"UPDATE vexpublish_jobs SET {setters} WHERE id=? AND status=?",
                (*payload.values(), job_id, origem),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    store.registrar_evento(job_id, f"job.{destino}", "ok", from_status=origem, to_status=destino)
    return store.obter("vexpublish_jobs", job_id)


def aprovar(job_id: str) -> dict:
    """Aprovacao humana. Sem isto o job nunca sai de draft."""
    return mudar_status(job_id, "approved")


def liberar_para_fila(job_id: str) -> dict:
    job = store.obter("vexpublish_jobs", job_id)
    if not job:
        raise KeyError(job_id)
    if job["status"] == "draft":
        if job["requires_approval"]:
            raise VexPublishError(
                CodigoErro.VALIDATION_ERROR, "Job exige aprovacao humana antes da fila"
            )
        # requires_approval=False significa aprovacao automatica, nao ausencia
        # de aprovacao: o job passa por approved do mesmo jeito, para o
        # historico registrar quem liberou e quando.
        job = mudar_status(job_id, "approved")
    destino = "scheduled" if job["scheduled_at"] else "pending"
    return mudar_status(job_id, destino)


def cancelar(job_id: str, motivo: str = "") -> dict:
    return mudar_status(job_id, "cancelled", last_error=motivo)
