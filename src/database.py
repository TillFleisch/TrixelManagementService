"""Database and session preset configuration."""

import sys
from pathlib import Path

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config_schema import Config, TestConfig

if "pytest" in sys.modules:
    config = TestConfig()
else:
    config = Config()

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
    DATABASE_URL = "sqlite:///./config/tms_sqlite.db"
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

MetaSession = sessionmaker(autoflush=False, autocommit=False, bind=engine)

Base = declarative_base()


def get_db():
    """Instantiate a temporary session for endpoint invocation."""
    db = MetaSession()
    try:
        yield db
    finally:
        db.close()


def except_columns(base, *exclusions: str) -> list[str]:
    """Get a list of column names except the ones provided.

    :param base: model from which columns are retrieved
    :param exclusions: list of column names which should be excluded
    :returns: list of column names which are not present in the exclusions
    """
    return [c for c in base.__table__.c if c.name not in exclusions]
