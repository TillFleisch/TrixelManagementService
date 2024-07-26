"""Database and session preset configuration."""

from pathlib import Path
from typing import Any, AsyncGenerator

from sqlalchemy import URL, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from config_schema import Config, GlobalConfig

config: Config = GlobalConfig.config

DATABASE_URL = None

# Prefer custom DB definition over custom (partial) definition over default
if db_config := config.tms_config.database:

    if db_config.custom_url is not None:
        DATABASE_URL = db_config.custom_url

    if db_config.dialect is not None:
        DATABASE_URL = URL.create(
            db_config.dialect,
            username=db_config.user,
            password=db_config.password.get_secret_value() if db_config.password is not None else None,
            host=db_config.host,
            port=db_config.port,
            database=db_config.db_name,
        )

# Default local sqlite
connect_args = {}
if DATABASE_URL is None:
    Path("./config").mkdir(parents=True, exist_ok=True)
    DATABASE_URL = "sqlite+aiosqlite:///./config/tms_sqlite.db"
    connect_args = {"check_same_thread": False}

engine = create_async_engine(DATABASE_URL, connect_args=connect_args)

MetaSession = async_sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False, bind=engine)


Base = declarative_base()


# source: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#sqlite-foreign-keys
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Explicitly enable foreign key support (required for cascades)."""
    database_config = config.tms_config.database
    if database_config is not None and database_config.use_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """Instantiate a temporary session for endpoint invocation."""
    async with MetaSession() as db:
        yield db


async def get_db_session():
    """Get a database session."""
    async with engine.begin() as conn:
        yield conn


def except_columns(base, *exclusions: str) -> list[str]:
    """Get a list of column names except the ones provided.

    :param base: model from which columns are retrieved
    :param exclusions: list of column names which should be excluded
    :returns: list of column names which are not present in the exclusions
    """
    return [c for c in base.__table__.c if c.name not in exclusions]
