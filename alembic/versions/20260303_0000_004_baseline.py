"""Baseline placeholder — pre-existing schema as of revision 004.

Revision ID: 004
Revises:
Create Date: 2026-03-03

历史背景:
    项目曾使用 Alembic 迁移到版本 004(add `members.position`),后切换为
    `Base.metadata.create_all` + `engine.py` 启动期 ALTER TABLE 模式,所有 alembic
    版本文件被删除,但数据库的 `alembic_version` 表残留 `004` 标记。

本次重新引入 Alembic 时,以 `004` 作为新的基线占位:
- `upgrade` 与 `downgrade` 均为空,因为现有数据库已处于 004 之后的状态。
- 后续对 ORM 的所有变更通过 `alembic revision --autogenerate -m "..."` 在此基础上累加。
- engine.py 中残留的 ALTER TABLE / CREATE TABLE 历史 DDL 暂时保留为兼容兜底,
  新增 schema 变更**必须走 Alembic**。
"""

from typing import Sequence, Union


revision: str = "004"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
