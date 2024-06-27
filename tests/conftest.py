"""Pytest configuration, fixtures and db-testing-preamble."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config_schema import Config, GlobalConfig, TestConfig
from crud import init_measurement_type_enum
from database import Base
from tls_manager import TLSManager
from trixelmanagementserver import app, get_db

# Testing preamble based on: https://fastapi.tiangolo.com/advanced/testing-database/
DATABASE_URL = "sqlite://"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def prepare_db():
    """Set up empty temporary test database."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        """Override the default database session retrieval with the test environment db."""
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    init_measurement_type_enum(next(override_get_db()))

    return override_get_db()


@pytest.fixture(scope="function")
def empty_db():
    """Reset the test database before test execution."""
    yield next(prepare_db())


@pytest.fixture(scope="function", name="config")
def get_config() -> Config:
    """Fixture which returns the test configuration."""
    GlobalConfig.config = TestConfig()
    return GlobalConfig.config


@pytest.fixture(scope="function")
def new_tls_manager(config: Config) -> TLSManager:
    """Fixture which returns a new TLSManager which has not been "registered" at the TLS."""
    return TLSManager()


@pytest.fixture(scope="function")
def preset_tls_manager(new_tls_manager: TLSManager) -> TLSManager:
    """Fixture which returns a TLSManager which is already registered at the TLS."""
    new_tls_manager.config.tms_config.id = 1
    new_tls_manager.config.tms_config.active = True
    new_tls_manager.config.tms_config.api_token = "Token"

    return new_tls_manager


prepare_db()
client = TestClient(app)
