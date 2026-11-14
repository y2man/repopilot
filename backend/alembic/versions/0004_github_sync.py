"""Track GitHub remotes and published patch commits."""
from alembic import op
import sqlalchemy as sa
revision = "0004_github_sync"
down_revision = "0003_github_oauth"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("repositories", sa.Column("remote_url", sa.String(500), nullable=True))
    op.add_column("repositories", sa.Column("remote_ref", sa.String(120), nullable=True))
    op.add_column("generated_patches", sa.Column("published_commit_url", sa.String(1000), nullable=True))

def downgrade():
    op.drop_column("generated_patches", "published_commit_url")
    op.drop_column("repositories", "remote_ref")
    op.drop_column("repositories", "remote_url")
