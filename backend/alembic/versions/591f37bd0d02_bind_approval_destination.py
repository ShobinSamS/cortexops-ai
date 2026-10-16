"""Bind approval to its destination; legacy requests require a fresh approval.

Revision ID: 591f37bd0d02
Revises: ae2739a5aa6e
"""
from alembic import op
import sqlalchemy as sa

revision = "591f37bd0d02"
down_revision = "ae2739a5aa6e"
branch_labels = depends_on = None


def upgrade():
    op.add_column("approvals", sa.Column("target", sa.JSON(), nullable=False, server_default="{}"))
    op.execute("UPDATE approvals SET status='expired' WHERE status IN ('pending','approved')")
    op.alter_column("approvals", "target", server_default=None)


def downgrade():
    op.drop_column("approvals", "target")
