"""은행별 가상 고객 식별자와 표시 이름."""
from alembic import op
import sqlalchemy as sa

revision = "001_customer"
down_revision = None


def upgrade():
    op.create_table(
        "demo_customer",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("display_name", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("demo_customer")
