import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
from app.core.database import Base
import app.models.entities

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def configure(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      include_object=lambda obj, name, type_, reflected, compare_to: not (type_ == "table" and name in {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}))
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(get_settings().database_url, connect_args={"connect_timeout": 5})
    async with engine.connect() as connection:
        await connection.run_sync(configure)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(online())
