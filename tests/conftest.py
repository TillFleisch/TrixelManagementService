"""Pytest configuration, fixtures and db-testing-preamble."""

import asyncio
from typing import Any, AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from trixellookupclient.models.tms_delegation import TMSDelegation

from config_schema import Config, GlobalConfig, TestConfig
from crud import init_measurement_type_enum
from database import Base
from tls_manager import TLSManager
from trixelmanagementserver import app, get_db

# Testing preamble based on: https://fastapi.tiangolo.com/advanced/testing-database/
DATABASE_URL = "sqlite+aiosqlite://"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
    """Instantiate a temporary session for endpoint invocation."""
    async with TestingSessionLocal() as db:
        yield db


@pytest.fixture(scope="function", name="db")
async def get_db_session():
    """Get a database session which can be used in tests."""
    async for db in override_get_db():
        return db


async def reset_db():
    """Drop all tables within the DB and re-instantiates the model."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def prepare_db():
    """Set up empty temporary test database."""
    loop = asyncio.get_event_loop()
    loop.run_until_complete(reset_db())

    TestingSessionLocal = async_sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False, bind=engine)

    async def override_get_db() -> AsyncGenerator[AsyncSession, Any]:
        """Override the default database session retrieval with the test environment db."""
        async with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    async def init_enums():
        """Initialize/synchronize enum tables within the DB."""
        async for db in override_get_db():
            await init_measurement_type_enum(db)

    loop.run_until_complete(init_enums())


@pytest.fixture(scope="function")
def empty_db():
    """Reset the test database before test execution."""
    prepare_db()
    yield


@pytest.fixture(scope="function", name="config")
def get_config() -> Config:
    """Fixture which returns a reference to the config."""
    return GlobalConfig.config


@pytest.fixture(scope="function", name="new_config")
def get_new_config() -> Config:
    """Fixture which returns a new test configuration."""
    GlobalConfig.config = TestConfig()
    return GlobalConfig.config


@pytest.fixture(scope="function")
def new_tls_manager(new_config: Config) -> TLSManager:
    """Fixture which returns a new TLSManager which has not been "registered" at the TLS."""
    return TLSManager()


@pytest.fixture(scope="function")
def preset_tls_manager(new_tls_manager: TLSManager) -> TLSManager:
    """Fixture which returns a TLSManager which is already registered at the TLS."""
    new_tls_manager.config.tms_config.id = 1
    new_tls_manager.config.tms_config.active = True
    new_tls_manager.config.tms_config.api_token = "Token"
    new_tls_manager.config.tms_config.delegations = list()

    # Mock delegation of root nodes
    for i in range(8, 16):
        new_tls_manager.config.tms_config.delegations.append(TMSDelegation(tms_id=1, trixel_id=i, exclude=False))

    return new_tls_manager


prepare_db()
client = TestClient(app)
