"""Relaciona sessões e produtos."""
from alembic import op
import sqlalchemy as sa
revision, down_revision = "20260808_0002", "20260808_0001"

def upgrade():
    op.create_table(
        "shop_live_session_products",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("shop_live_sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("shop_live_products.id", ondelete="CASCADE"), primary_key=True),
    )

def downgrade():
    op.drop_table("shop_live_session_products")
