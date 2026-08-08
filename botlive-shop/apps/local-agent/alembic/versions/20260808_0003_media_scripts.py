"""Biblioteca autorizada, roteiros e ordem de materiais."""
from alembic import op
import sqlalchemy as sa
revision, down_revision = "20260808_0003", "20260808_0002"

def upgrade():
    op.create_table("shop_live_media_assets", sa.Column("id",sa.String(36),primary_key=True), sa.Column("product_id",sa.String(36),sa.ForeignKey("shop_live_products.id"),nullable=True), sa.Column("kind",sa.String(16),nullable=False), sa.Column("name",sa.String(160),nullable=False), sa.Column("local_path",sa.Text,nullable=False), sa.Column("duration_seconds",sa.Integer,nullable=False), sa.Column("authorized",sa.Boolean,nullable=False), sa.Column("authorization_source",sa.String(200),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("shop_live_script_blocks", sa.Column("id",sa.String(36),primary_key=True), sa.Column("product_id",sa.String(36),sa.ForeignKey("shop_live_products.id",ondelete="CASCADE"),nullable=False), sa.Column("kind",sa.String(32),nullable=False), sa.Column("position",sa.Integer,nullable=False), sa.Column("duration_seconds",sa.Integer,nullable=False), sa.Column("text",sa.Text,nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("shop_live_session_materials", sa.Column("session_id",sa.String(36),sa.ForeignKey("shop_live_sessions.id",ondelete="CASCADE"),primary_key=True), sa.Column("media_id",sa.String(36),sa.ForeignKey("shop_live_media_assets.id",ondelete="CASCADE"),primary_key=True), sa.Column("position",sa.Integer,nullable=False), sa.Column("planned_duration_seconds",sa.Integer,nullable=False))

def downgrade():
    op.drop_table("shop_live_session_materials"); op.drop_table("shop_live_script_blocks"); op.drop_table("shop_live_media_assets")
