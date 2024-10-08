"""Tests related to management station endpoints."""

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Callable
from urllib.parse import urlencode

import jwt
import pytest
from conftest import client
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from trixellookupclient.models.tms_delegation import TMSDelegation

import measurement_station.model as ms_model
from config_schema import Config
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
def test_get_own_station_detail():
    """Test get own measurement station detail endpoint."""
    response = client.get("/measurement_station", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["k_requirement"] == 7
    assert uuid.UUID(data["uuid"]) is not None


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
def test_get_sensor_empty():
    """Test get sensor empty/non-existent."""
    response = client.get("/measurement_station/sensors", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert isinstance(data, list)

    response = client.get("/measurement_station/sensor/0", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


@pytest.mark.order(305)
@pytest.mark.parametrize("type_", {"ambient_temperature", "relative_humidity"})
@pytest.mark.parametrize("accuracy", {None, 5.5})
@pytest.mark.parametrize("sensor_name", {None, "tmp117"})
def test_add_get_sensor(type_: str, accuracy: float | None, sensor_name: str | None):
    """Test adding and getting specific sensor to/from measurement stations."""
    params = {"type": type_}
    if accuracy is not None:
        params["accuracy"] = accuracy
    if sensor_name is not None:
        params["sensor_name"] = sensor_name

    response = client.post(
        f"/measurement_station/sensor?{urlencode(params)}",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    data = response.json()
    id_ = data["id"]
    assert data["measurement_type"] == type_
    assert data["details"]["accuracy"] == accuracy
    assert data["details"]["sensor_name"] == sensor_name

    response = client.get(f"/measurement_station/sensor/{id_}", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["id"] == id_
    assert data["measurement_type"] == type_
    assert data["details"]["accuracy"] == accuracy
    assert data["details"]["sensor_name"] == sensor_name


@pytest.mark.order(306)
def test_get_sensor_present():
    """Test get sensors for station with registered sensors."""
    response = client.get("/measurement_station/sensors", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 8


@pytest.mark.order(307)
def test_delete_sensor():
    """Test sensor delete procedure."""
    response = client.delete("/measurement_station/sensor/0", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text

    response = client.get("/measurement_station/sensor/0", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


@pytest.mark.order(308)
@pytest.mark.parametrize("trixel_id", {61, 245, 35, 4015772})
def test_sensor_put(trixel_id: int):
    """Happy path for putting a single update."""
    # Trixel id is subtracted from time to prevent duplicate timestamps for the same sensors
    response = client.put(
        f"/trixel/{trixel_id}/update/1?value=1.1&timestamp={int(datetime.now().timestamp()-trixel_id)}",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.OK or response.status_code == HTTPStatus.SEE_OTHER, response.text


@pytest.mark.order(308)
def test_sensor_put_update_invalid_time():
    """Test repeated value insertion."""
    response = client.put(
        "/trixel/61/update/1?value=1.1&timestamp=0",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.OK, response.text

    response = client.put(
        "/trixel/61/update/1?value=1.1&timestamp=0",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.text


@pytest.mark.order(308)
def test_sensor_put_invalid_trixel_id():
    """Test putting an update to an invalid trixel id."""
    response = client.put(
        "/trixel/16/update/1?value=1.1&timestamp=1",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code != HTTPStatus.CREATED, response.text


@pytest.mark.order(309)
def test_sensor_put_non_delegated_trixel_id(config: Config):
    """Test sensor update to trixel which is not delegated to the TMS."""
    config.tms_config.delegations.append(TMSDelegation(tms_id=1, trixel_id=35, exclude=True))
    response = client.put(
        "/trixel/35/update/1?value=1.1&timestamp=2",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text


@pytest.mark.order(310)
def test_sensor_put_non_delegated_trixel_id_root(config: Config):
    """Test sensor update to trixel which is not delegated to the TMS."""
    config.tms_config.delegations = list()
    response = client.put(
        "/trixel/8/update/0?value=2&timestamp=0",
        headers={"token": pytest.ms_token},
    )
    assert response.status_code == HTTPStatus.SEE_OTHER, response.text


@pytest.mark.order(311)
@pytest.mark.asyncio
async def test_ms_delete(db: AsyncSession, preset_tls_manager: TLSManager):
    """Happy path for removing a measurement station."""
    db = await db
    response = client.delete("/measurement_station", headers={"token": pytest.ms_token})
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text

    response = client.get("/measurement_stations")
    assert response.status_code == HTTPStatus.OK, response.text
    data = response.json()
    assert data["value"] == 0

    # Assert related sensors have been removed
    ms_uuid = uuid.UUID(
        hex=jwt.decode(pytest.ms_token, options={"verify_signature": False}, algorithms=["HS256"])["ms_uuid"]
    )
    query = select(func.count(ms_model.Sensor.id)).where(ms_model.Sensor.measurement_station_uuid == ms_uuid)
    sensor_count = (await db.execute(query)).scalar_one_or_none()
    assert sensor_count == 0

    ms_uuid = uuid.UUID(
        hex=jwt.decode(pytest.ms_token, options={"verify_signature": False}, algorithms=["HS256"])["ms_uuid"]
    )
    query = select(func.count(ms_model.SensorMeasurement.sensor_id)).where(
        ms_model.SensorMeasurement.measurement_station_uuid == ms_uuid
    )
    sensor_count = (await db.execute(query)).scalar_one_or_none()
    assert sensor_count == 0
    await db.aclose()


@pytest.mark.order(301)
@pytest.mark.parametrize(
    "method,endpoint",
    {
        (client.put, "/measurement_station"),
        (client.delete, "/measurement_station"),
        (client.get, "/measurement_station"),
        (client.post, "/measurement_station/sensor"),
        (client.delete, "/measurement_station/sensor/0"),
        (client.get, "/measurement_station/sensor/0"),
        (client.put, "/trixel/1/update/0"),
        (client.put, "/trixel/update"),
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
        (client.get, "/measurement_station"),
        (client.get, "/measurement_station/sensors"),
        (client.post, "/measurement_station/sensor"),
        (client.delete, "/measurement_station/sensor/0"),
        (client.get, "/measurement_station/sensor/0"),
        (client.put, "/trixel/1/update/0"),
        (client.put, "/trixel/update"),
    },
)
def test_add_ms_inactive(method: Callable, endpoint: str, empty_db, new_tls_manager: TLSManager):
    """Test endpoints while TMS inactive."""
    response = method(endpoint)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE, response.text
