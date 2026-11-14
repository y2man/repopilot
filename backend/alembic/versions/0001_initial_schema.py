"""Initial user, repository and retrieval schema."""
from alembic import op
import sqlalchemy as sa
try:
    from pgvector.sqlalchemy import Vector
    EMBEDDING_COLUMN = Vector(384).with_variant(sa.JSON(), "sqlite")
except ImportError:
    EMBEDDING_COLUMN = sa.JSON()
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("users", sa.Column("id",sa.Integer(),primary_key=True),sa.Column("email",sa.String(320),nullable=False),sa.Column("password_hash",sa.String(256),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_users_email","users",["email"],unique=True)
    op.create_table("repositories",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("owner_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("name",sa.String(255),nullable=False),sa.Column("source",sa.String(32),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("file_count",sa.Integer(),nullable=False),sa.Column("chunk_count",sa.Integer(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_repositories_owner_id","repositories",["owner_id"])
    op.create_table("repository_files",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("repository_id",sa.Integer(),sa.ForeignKey("repositories.id",ondelete="CASCADE"),nullable=False),sa.Column("path",sa.String(1024),nullable=False),sa.Column("language",sa.String(64),nullable=False),sa.Column("content",sa.Text(),nullable=False),sa.Column("line_count",sa.Integer(),nullable=False),sa.UniqueConstraint("repository_id","path",name="uq_repository_file_path"))
    op.create_index("ix_repository_files_repository_id","repository_files",["repository_id"])
    op.create_table("code_chunks",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("repository_id",sa.Integer(),sa.ForeignKey("repositories.id",ondelete="CASCADE"),nullable=False),sa.Column("file_path",sa.String(1024),nullable=False),sa.Column("language",sa.String(64),nullable=False),sa.Column("start_line",sa.Integer(),nullable=False),sa.Column("end_line",sa.Integer(),nullable=False),sa.Column("content",sa.Text(),nullable=False),sa.Column("embedding",EMBEDDING_COLUMN,nullable=True))
    op.create_index("ix_code_chunks_repository_id","code_chunks",["repository_id"])
    op.create_index("ix_code_chunks_file_path","code_chunks",["file_path"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_code_chunks_embedding_hnsw ON code_chunks USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL")
def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw")
    op.drop_index("ix_code_chunks_file_path",table_name="code_chunks");op.drop_index("ix_code_chunks_repository_id",table_name="code_chunks");op.drop_table("code_chunks")
    op.drop_index("ix_repository_files_repository_id",table_name="repository_files");op.drop_table("repository_files")
    op.drop_index("ix_repositories_owner_id",table_name="repositories");op.drop_table("repositories")
    op.drop_index("ix_users_email",table_name="users");op.drop_table("users")
