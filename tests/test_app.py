"""Global tests for the Trixel Management Server app."""

import pytest
from conftest import client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import model


@pytest.mark.order(100)
def test_ping():
    """Test ping endpoint."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ping": "pong"}


@pytest.mark.order(100)
def test_version():
    """Test version endpoint."""
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()


@pytest.mark.order(100)
@pytest.mark.asyncio
async def test_measurement_type_enums(empty_db, db: AsyncSession):
    """Test if the measurement enum relation contains entries."""
    db = await db
    query = select(model.MeasurementType.name)
    types_ = (await db.execute(query)).scalars().all()

    for enum in model.MeasurementTypeEnum:
        assert enum.value in types_
    await db.aclose()
