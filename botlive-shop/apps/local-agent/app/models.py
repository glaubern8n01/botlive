from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())

session_products = Table(
    "shop_live_session_products", Base.metadata,
    Column("session_id", String(36), ForeignKey("shop_live_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", String(36), ForeignKey("shop_live_products.id", ondelete="CASCADE"), primary_key=True),
)

class Product(Base):
    __tablename__ = "shop_live_products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(100), default="")
    price: Mapped[float] = mapped_column(Float)
    approved_answers: Mapped[list] = mapped_column(JSON, default=list)
    prohibited_claims: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sessions: Mapped[list["LiveSession"]] = relationship(secondary=session_products, back_populates="products")

class LiveSession(Base):
    __tablename__ = "shop_live_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(160))
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="rascunho")
    seed: Mapped[int] = mapped_column(Integer, default=42)
    product_order: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    products: Mapped[list[Product]] = relationship(secondary=session_products, back_populates="sessions")

class AuditEvent(Base):
    __tablename__ = "shop_live_audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("shop_live_sessions.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(40), default="local-agent")
    result: Mapped[str] = mapped_column(String(20), default="ok")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(36), default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class MediaAsset(Base):
    __tablename__ = "shop_live_media_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("shop_live_products.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(160))
    local_path: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    duration_milliseconds: Mapped[int] = mapped_column(Integer, default=0)
    authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    authorization_source: Mapped[str] = mapped_column(String(200), default="")
    stored_name: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    format_name: Mapped[str] = mapped_column(String(80), default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ScriptBlock(Base):
    __tablename__ = "shop_live_script_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str] = mapped_column(ForeignKey("shop_live_products.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=60)
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SessionMaterial(Base):
    __tablename__ = "shop_live_session_materials"
    session_id: Mapped[str] = mapped_column(ForeignKey("shop_live_sessions.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("shop_live_media_assets.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    planned_duration_seconds: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("shop_live_products.id", ondelete="SET NULL"), nullable=True)
    script_id: Mapped[str | None] = mapped_column(ForeignKey("shop_live_script_blocks.id", ondelete="SET NULL"), nullable=True)

class MediaPlayback(Base):
    __tablename__ = "shop_live_media_playback"
    session_id: Mapped[str] = mapped_column(ForeignKey("shop_live_sessions.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[str | None] = mapped_column(ForeignKey("shop_live_media_assets.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="stopped")
    queue_index: Mapped[int] = mapped_column(Integer, default=0)
    position_seconds: Mapped[float] = mapped_column(Float, default=0)
    volume: Mapped[float] = mapped_column(Float, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class SessionRuntime(Base):
    __tablename__ = "shop_live_session_runtime"
    session_id: Mapped[str] = mapped_column(ForeignKey("shop_live_sessions.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(24), default="prepared")
    status: Mapped[str] = mapped_column(String(24), default="ready")
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    script_index: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    teleprompter_speed: Mapped[float] = mapped_column(Float, default=1)
    teleprompter_font_size: Mapped[int] = mapped_column(Integer, default=32)
    teleprompter_paused: Mapped[bool] = mapped_column(Boolean, default=True)
    connection_state: Mapped[str] = mapped_column(String(24), default="local")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class LocalSetting(Base):
    __tablename__ = "shop_live_local_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
