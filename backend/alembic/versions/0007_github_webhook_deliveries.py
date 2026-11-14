"""Persist GitHub webhook delivery IDs and synchronization status."""
from alembic import op
import sqlalchemy as sa

revision = "0007_github_webhooks"
down_revision = "0006_last_indexed"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "github_webhook_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False, server_default="push"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("detail", sa.Text(), nullable=False, server_default="Queued for synchronization"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_github_webhook_deliveries_delivery_id", "github_webhook_deliveries", ["delivery_id"], unique=True)
    op.create_index("ix_github_webhook_deliveries_repository_id", "github_webhook_deliveries", ["repository_id"])


def downgrade():
    op.drop_index("ix_github_webhook_deliveries_repository_id", table_name="github_webhook_deliveries")
    op.drop_index("ix_github_webhook_deliveries_delivery_id", table_name="github_webhook_deliveries")
    op.drop_table("github_webhook_deliveries")
