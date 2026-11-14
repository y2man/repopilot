"""Track the last successful repository indexing timestamp."""
from alembic import op
import sqlalchemy as sa
revision = "0006_last_indexed"
down_revision = "0005_new_file_flag"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("repositories", sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("repositories", "last_indexed_at")
