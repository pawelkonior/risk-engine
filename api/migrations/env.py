import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy.engine import Connection

from app.core.config import DatabaseSettings
from app.modules.ai.models import AIIndexRecord
from app.modules.items.models import Item
from app.platform.database import create_engine
from app.platform.persistence import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Register every application's model here before autogenerating migrations.
registered_models = (Item, AIIndexRecord)
target_metadata: MetaData = Base.metadata


def configure_migration_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    settings = DatabaseSettings()
    context.configure(
        url=settings.migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=settings.migration_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_engine(DatabaseSettings(), migrations=True)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(configure_migration_context)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
