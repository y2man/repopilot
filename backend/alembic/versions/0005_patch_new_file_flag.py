"""Distinguish new-file patch proposals from empty existing files."""
from alembic import op
import sqlalchemy as sa
revision = "0005_new_file_flag"
down_revision = "0004_github_sync"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("generated_patches", sa.Column("is_new_file", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("generated_patches", "is_new_file")
