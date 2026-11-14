"""Store encrypted per-user GitHub OAuth credentials."""
from alembic import op
import sqlalchemy as sa
revision = "0003_github_oauth"
down_revision = "0002_workflows"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("github_access_token_encrypted", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("users", "github_access_token_encrypted")
