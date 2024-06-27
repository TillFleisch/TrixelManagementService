"""Global tests for the Trixel Management Server app."""

import pytest
from conftest import client
from sqlalchemy.orm import Session

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
def test_measurement_type_enums(empty_db: Session):
    """Test if the measurement enum relation contains entries."""
    types = empty_db.query(model.MeasurementType.name).all()
    types = [type_[0] for type_ in types]

    for enum in model.MeasurementTypeEnum:
        assert enum.value in types
