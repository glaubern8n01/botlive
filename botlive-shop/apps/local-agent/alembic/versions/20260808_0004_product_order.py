from alembic import op
import sqlalchemy as sa
revision="20260808_0004"
down_revision="20260808_0003"
branch_labels=None
depends_on=None
def upgrade(): op.add_column("shop_live_sessions",sa.Column("product_order",sa.JSON(),nullable=False,server_default="[]"))
def downgrade(): op.drop_column("shop_live_sessions","product_order")
