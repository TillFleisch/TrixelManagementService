"""Tests related to management station endpoints."""

import uuid
from http import HTTPStatus
from typing import Callable

import pytest
from conftest import client

from tls_manager import TLSManager

pytest.ms_token = None


@pytest.mark.order(301)
def test_ms_add(empty_db, preset_tls_manager: TLSManager):
    """Testcase for adding a new measurement station."""
    response = client.post("/measurement_station?k_requirement=4")
    assert response.status_code == HTTPStatus.CREATED, response.text
    data = response.json()
    assert "token" in data
    pytest.ms_token = data["token"]
    assert uuid.UUID(data["uuid"]) is not None
    assert data["k_requirement"] == 4


@pytest.mark.order(302)
def test_ms_add_invalid():
    """Test MS instantiation with invalid k requirement."""
    response = client.post("/measurement_station?k_requirement=-1")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text


@pytest.mark.order(302)
def test_ms_update():
    """Happy path for updating a measurement station."""
    response = client.put("/measurement_station?k_requirement=7", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert "token" not in data
    assert data["k_requirement"] == 7


@pytest.mark.order(303)
def test_get_ms_count():
    """Test get ms count endpoint."""
    response = client.get("/measurement_stations")
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["value"] == 1

    response = client.get("/measurement_stations?active=false")
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["value"] == 0


@pytest.mark.order(304)
def test_ms_delete():
    """Happy path for removing a measurement station."""
    response = client.delete("/measurement_station", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text

    response = client.get("/measurement_stations")
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["value"] == 0


@pytest.mark.order(301)
@pytest.mark.parametrize(
    "method,endpoint",
    {
        (client.put, "/measurement_station"),
        (client.delete, "/measurement_station"),
    },
)
def test_endpoints_invalid_token(method: Callable, endpoint: str):
    """Test endpoints with invalid token."""
    response = method(endpoint, headers={"token": "fake_token"})
    assert response.status_code == HTTPStatus.UNAUTHORIZED, response.text


@pytest.mark.order(300)
@pytest.mark.parametrize(
    "method,endpoint",
    {
        (client.post, "/measurement_station"),
        (client.put, "/measurement_station"),
        (client.delete, "/measurement_station"),
    },
)
def test_add_ms_inactive(method: Callable, endpoint: str, empty_db, new_tls_manager: TLSManager):
    """Test endpoints while TMS inactive."""
    response = method(endpoint)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE, response.text
