"""Alembic env.py — async + auto-import all ORM models for autogenerate.

设计要点:
1. 数据库地址从 OPENVORT_DATABASE_URL(.env / settings)读取,不在 alembic.ini 里硬编码。
2. 启动时显式导入所有插件 models,确保 Base.metadata 能感知全部表(否则 autogenerate
   会把已有表当成"应删除"误生成 drop)。
3. 使用 SQLAlchemy 2.0 async 引擎,与项目运行时一致(asyncpg)。
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Alembic Config 对象,提供 alembic.ini 中各 section 的访问。
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """从环境变量 / .env 读取数据库地址。"""
    # 优先 OPENVORT_DATABASE_URL(运行期),其次 alembic.ini 的 sqlalchemy.url(默认占位符)。
    url = os.environ.get("OPENVORT_DATABASE_URL")
    if url:
        return url
    # 尝试从项目 .env 加载(不依赖 dotenv,简化轻量解析)。
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OPENVORT_DATABASE_URL="):
                    val = line.split("=", 1)[1].strip()
                    val = val.split("#", 1)[0].strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    return val
    return config.get_main_option("sqlalchemy.url", "")


def _import_all_models() -> None:
    """显式导入项目内所有 ORM models,让 Base.metadata 收集全部表。

    保持与 db/engine.py::init_db 同样的导入顺序,优雅处理可选插件。
    """
    import openvort.auth.models  # noqa: F401
    import openvort.contacts.models  # noqa: F401
    import openvort.core.setup  # noqa: F401
    import openvort.db.models  # noqa: F401

    optional = (
        "openvort.services.asr.asr_service",
        "openvort.plugins.knowledge.models",
        "openvort.plugins.vortflow.models",
        "openvort.plugins.vortgit.models",
        "openvort.plugins.jenkins.models",
        "openvort.plugins.report.models",
        "openvort.plugins.vortsketch.models",
        "openvort.plugins.vortcert.models",
    )
    for mod in optional:
        try:
            __import__(mod)
        except ImportError:
            pass


_import_all_models()
from openvort.db.engine import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    生成 SQL 文件而不连接数据库。"""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode (async)."""
    url = _resolve_database_url()
    cfg_section = config.get_section(config.config_ini_section, {}) or {}
    cfg_section["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"ssl": False} if "asyncpg" in url else {},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
