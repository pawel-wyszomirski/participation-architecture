import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Import Twoich modeli
from app.db.models import Base

config = context.config

# DATABASE_URL wins over the ini default (the ini points at the docker-compose
# Postgres; production runs SQLite inside the image, and migration 002 has to
# reach THAT file). Same precedence as app/db/session.py.
import os
_env_url = os.getenv("DATABASE_URL")
if _env_url:
    if "+asyncpg" in _env_url:
        _env_url = _env_url.replace("+asyncpg", "")
    config.set_main_option("sqlalchemy.url", _env_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online_sync() -> None:
    """Synchronous path for drivers without async support (SQLite in the
    production image). The async branch below predates it and stays for the
    docker-compose Postgres setup."""
    from sqlalchemy import engine_from_config
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif config.get_main_option("sqlalchemy.url", "").startswith("sqlite:"):
    run_migrations_online_sync()
else:
    asyncio.run(run_migrations_online())