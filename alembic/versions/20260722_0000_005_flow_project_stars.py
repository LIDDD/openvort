"""Add flow_project_stars table for per-member project favorites.

Revision ID: 005
Revises: 004
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "005"
down_revision: Union[str, Sequence[str], None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等：engine.py 启动期的 Base.metadata.create_all 会先于本迁移创建所有 ORM 新表，
    # 因此这里若表/索引已存在则跳过，避免与「create_all 兜底」冲突导致启动失败。
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("flow_project_stars"):
        return

    op.create_table(
        "flow_project_stars",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("member_id", sa.String(length=32), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("project_id", sa.String(length=32), sa.ForeignKey("flow_projects.id"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("member_id", "project_id", name="uq_flow_project_star"),
    )
    op.create_index("ix_flow_project_stars_member_id", "flow_project_stars", ["member_id"])
    op.create_index("ix_flow_project_stars_project_id", "flow_project_stars", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("flow_project_stars"):
        return
    existing_indexes = {ix["name"] for ix in insp.get_indexes("flow_project_stars")}
    if "ix_flow_project_stars_project_id" in existing_indexes:
        op.drop_index("ix_flow_project_stars_project_id", table_name="flow_project_stars")
    if "ix_flow_project_stars_member_id" in existing_indexes:
        op.drop_index("ix_flow_project_stars_member_id", table_name="flow_project_stars")
    op.drop_table("flow_project_stars")
