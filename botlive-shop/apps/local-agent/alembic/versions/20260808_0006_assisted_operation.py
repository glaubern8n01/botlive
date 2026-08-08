from alembic import op
import sqlalchemy as sa

revision = "20260808_0006"
down_revision = "20260808_0005"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("shop_live_products") as batch:
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table("shop_live_sessions") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    with op.batch_alter_table("shop_live_media_assets") as batch:
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
    with op.batch_alter_table("shop_live_script_blocks") as batch:
        batch.add_column(sa.Column("title", sa.String(160), nullable=False, server_default=""))
    with op.batch_alter_table("shop_live_session_materials") as batch:
        batch.add_column(sa.Column("product_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("script_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_material_product", "shop_live_products", ["product_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_material_script", "shop_live_script_blocks", ["script_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("shop_live_media_playback") as batch:
        batch.add_column(sa.Column("volume", sa.Float(), nullable=False, server_default="1"))
    op.create_table("shop_live_session_runtime",
        sa.Column("session_id",sa.String(36),sa.ForeignKey("shop_live_sessions.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("mode",sa.String(24),nullable=False,server_default="prepared"),sa.Column("status",sa.String(24),nullable=False,server_default="ready"),
        sa.Column("current_index",sa.Integer(),nullable=False,server_default="0"),sa.Column("script_index",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("elapsed_seconds",sa.Integer(),nullable=False,server_default="0"),sa.Column("teleprompter_speed",sa.Float(),nullable=False,server_default="1"),
        sa.Column("teleprompter_font_size",sa.Integer(),nullable=False,server_default="32"),sa.Column("teleprompter_paused",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("connection_state",sa.String(24),nullable=False,server_default="local"),sa.Column("started_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("ended_at",sa.DateTime(timezone=True),nullable=True),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("shop_live_local_settings",sa.Column("key",sa.String(80),primary_key=True),sa.Column("value",sa.JSON(),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")))

def downgrade():
    op.drop_table("shop_live_local_settings"); op.drop_table("shop_live_session_runtime")
    with op.batch_alter_table("shop_live_media_playback") as batch: batch.drop_column("volume")
    with op.batch_alter_table("shop_live_session_materials") as batch:
        batch.drop_constraint("fk_material_script",type_="foreignkey");batch.drop_constraint("fk_material_product",type_="foreignkey");batch.drop_column("script_id");batch.drop_column("product_id")
    with op.batch_alter_table("shop_live_script_blocks") as batch: batch.drop_column("title")
    with op.batch_alter_table("shop_live_media_assets") as batch: batch.drop_column("notes");batch.drop_column("tags")
    with op.batch_alter_table("shop_live_sessions") as batch: batch.drop_column("updated_at")
    with op.batch_alter_table("shop_live_products") as batch: batch.drop_column("active");batch.drop_column("notes");batch.drop_column("tags")
