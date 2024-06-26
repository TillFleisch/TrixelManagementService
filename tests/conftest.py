"""Pytest configuration, fixtures and db-testing-preamble."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from crud import init_measurement_type_enum
from database import Base
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


prepare_db()
client = TestClient(app)
