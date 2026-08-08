"""Tabelas isoladas do Shop LIVE."""
from alembic import op
import sqlalchemy as sa
revision, down_revision = "20260808_0001", None

def upgrade():
    op.create_table("shop_live_products", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(160), nullable=False), sa.Column("category", sa.String(100), nullable=False), sa.Column("price", sa.Float, nullable=False), sa.Column("approved_answers", sa.JSON, nullable=False), sa.Column("prohibited_claims", sa.JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("shop_live_sessions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(160), nullable=False), sa.Column("estimated_minutes", sa.Integer, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("seed", sa.Integer, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("shop_live_audit_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("shop_live_sessions.id")), sa.Column("type", sa.String(80), nullable=False), sa.Column("source", sa.String(40), nullable=False), sa.Column("result", sa.String(20), nullable=False), sa.Column("payload", sa.JSON, nullable=False), sa.Column("correlation_id", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table("shop_live_audit_events"); op.drop_table("shop_live_sessions"); op.drop_table("shop_live_products")
