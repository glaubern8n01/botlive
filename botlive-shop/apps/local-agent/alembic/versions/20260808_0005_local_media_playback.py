from alembic import op
import sqlalchemy as sa
revision="20260808_0005"
down_revision="20260808_0004"
branch_labels=None
depends_on=None
def upgrade():
    with op.batch_alter_table("shop_live_media_assets") as batch:
        batch.add_column(sa.Column("stored_name",sa.String(80),nullable=True))
        batch.add_column(sa.Column("duration_milliseconds",sa.Integer(),nullable=False,server_default="0"))
        batch.add_column(sa.Column("mime_type",sa.String(100),nullable=False,server_default=""))
        batch.add_column(sa.Column("size_bytes",sa.Integer(),nullable=False,server_default="0"))
        batch.add_column(sa.Column("format_name",sa.String(80),nullable=False,server_default=""))
        batch.add_column(sa.Column("width",sa.Integer(),nullable=True))
        batch.add_column(sa.Column("height",sa.Integer(),nullable=True))
        batch.create_unique_constraint("uq_shop_live_media_stored_name",["stored_name"])
    op.create_table("shop_live_media_playback",sa.Column("session_id",sa.String(36),sa.ForeignKey("shop_live_sessions.id",ondelete="CASCADE"),primary_key=True),sa.Column("media_id",sa.String(36),sa.ForeignKey("shop_live_media_assets.id",ondelete="SET NULL"),nullable=True),sa.Column("status",sa.String(24),nullable=False,server_default="stopped"),sa.Column("queue_index",sa.Integer(),nullable=False,server_default="0"),sa.Column("position_seconds",sa.Float(),nullable=False,server_default="0"),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")))
def downgrade():
    op.drop_table("shop_live_media_playback")
    with op.batch_alter_table("shop_live_media_assets") as batch:
        batch.drop_constraint("uq_shop_live_media_stored_name",type_="unique")
        for name in ["height","width","format_name","size_bytes","mime_type","duration_milliseconds","stored_name"]: batch.drop_column(name)
