from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())

class Product(Base):
    __tablename__ = "shop_live_products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(100), default="")
    price: Mapped[float] = mapped_column(Float)
    approved_answers: Mapped[list] = mapped_column(JSON, default=list)
    prohibited_claims: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class LiveSession(Base):
    __tablename__ = "shop_live_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(160))
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="rascunho")
    seed: Mapped[int] = mapped_column(Integer, default=42)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

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
