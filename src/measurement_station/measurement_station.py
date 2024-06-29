"""API endpoints related to measurement stations."""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import UUID4, NonNegativeInt, PositiveFloat, PositiveInt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common import is_active, is_delegated
from config_schema import Config, GlobalConfig
from database import get_db
from model import MeasurementTypeEnum

from . import crud, schema

TAG_MEASUREMENT_STATION = "Measurement Station"
TAG_TRIXELS = "Trixels"

router = APIRouter()
config: Config = GlobalConfig.config


def verify_ms_token(
    token: Annotated[str, Header(description="Measurement station authentication token.")],
    db: Session = Depends(get_db),
) -> UUID4:
    """
    Dependency which adds the token header attribute for measurement station authentication and performs validation.

    :returns: Measurement station UUID of the valid token
    :raises PermissionError: if the provided token is invalid
    """
    try:
        ms_uuid = crud.verify_ms_token(db, jwt_token=token)
        return ms_uuid
    except PermissionError:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail="Invalid measurement station authentication token!"
        )


@router.post(
    "/measurement_station",
    name="Create measurement station",
    summary="Register a new measurement station.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
    },
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(is_active)],
)
def post_measurement_station(
    k_requirement: Annotated[
        PositiveInt,
        Query(
            description="The k-anonymity requirement, which is enforced for this measurement station and it's sensors.",
        ),
    ] = 3,
    db: Session = Depends(get_db),
) -> schema.MeasurementStationCreate:
    """
    Register a new measurement station at this TMS.

    The measurement station token can be used to register and update sensors.
    Store the token properly, it is only transferred once!
    """
    result = crud.create_measurement_station(db, k_requirement=k_requirement)

    payload = {"iat": datetime.now(tz=timezone.utc), "ms_uuid": result.uuid.hex}
    jwt_token = jwt.encode(payload, result.token_secret, algorithm="HS256")

    return schema.MeasurementStationCreate(
        uuid=result.uuid, active=result.active, k_requirement=result.k_requirement, token=jwt_token
    )


@router.put(
    "/measurement_station",
    name="Add Measurement Station",
    summary="Update measurement station properties.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
    },
    dependencies=[Depends(is_active)],
)
def put_measurement_station(
    k_requirement: Annotated[
        PositiveInt,
        Query(
            description="The k-anonymity requirement, which is enforced for this measurement station and it's sensors.",
        ),
    ] = 3,
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
) -> schema.MeasurementStation:
    """Update an existing measurement station."""
    return crud.update_measurement_station(db, uuid_=ms_uuid, k_requirement=k_requirement)


@router.delete(
    "/measurement_station",
    name="Delete Measurement Station",
    summary="Delete an existing measurement station.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
        404: {"content": {"application/json": {"example": {"detail": "Measurement station does not exist!"}}}},
    },
    dependencies=[Depends(is_active)],
    status_code=HTTPStatus.NO_CONTENT,
)
def delete_measurement_station(
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
):
    """Delete an existing measurement station from the DB."""
    try:
        if crud.delete_measurement_station(db, ms_uuid):
            return
    except ValueError:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Measurement station does not exist!")
    raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR)


@router.get(
    "/measurement_stations",
    name="Get Measurement Station Count",
    summary="Get the number of measurement station registered at this TMS.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        200: {"content": {"application/json": {"example": {"value": 0}}}},
    },
    dependencies=[Depends(is_active)],
)
def get_measurement_station_count(
    active: Annotated[bool | None, Query(description="Filters by active state. Use both states if None.")] = None,
    db: Session = Depends(get_db),
):
    """Get the current number of registered measurement stations."""
    return {"value": crud.get_measurement_station_count(db, active=active)}


@router.post(
    "/measurement_station/sensor",
    name="Add Sensor To Measurement Station",
    summary="Add a new sensor to an existing measurement station.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
    },
    dependencies=[Depends(is_active)],
)
def post_sensor(
    type: Annotated[MeasurementTypeEnum, Query(description="Type of measurement acquired by this sensor.")],
    accuracy: Annotated[
        PositiveFloat | None, Query(description="Accuracy of the sensor (true observation within +/- accuracy).")
    ] = None,
    sensor_name: Annotated[str | None, Query(description="Name of the sensor which takes measurements.")] = None,
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
) -> schema.SensorDetailed:
    """Create a new sensor for a measurement station."""
    return crud.create_sensor(db, ms_uuid=ms_uuid, type_=type, accuracy=accuracy, sensor_name=sensor_name)


@router.get(
    "/measurement_station/sensors",
    name="Get Sensors For Measurement Station",
    summary="Get a list of all registered sensors and their details for the measurement station.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
    },
    dependencies=[Depends(is_active)],
)
def get_sensors(
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
) -> list[schema.SensorDetailed]:
    """Get a list of sensors which are registered for a measurement station."""
    return crud.get_sensors(db, ms_uuid=ms_uuid)


@router.delete(
    "/measurement_station/sensor/{sensor_id}",
    name="Delete Sensor From Measurement Station",
    summary="Delete an existing sensor from a measurement station.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
        404: {"content": {"application/json": {"example": {"detail": "Sensor with the given ID does not exist!"}}}},
    },
    dependencies=[Depends(is_active)],
    status_code=HTTPStatus.NO_CONTENT,
)
def delete_sensor(
    sensor_id: Annotated[NonNegativeInt, Path(description="ID of the sensor which should be removed.")],
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
):
    """Delete a sensor form a measurement station."""
    try:
        if crud.delete_sensor(db, ms_uuid=ms_uuid, sensor_id=sensor_id):
            return
    except ValueError:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Sensor with the given ID does not exist!")
    raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR)


@router.get(
    "/measurement_station/sensor/{sensor_id}",
    name="Get Sensor Detail For Measurement Station",
    summary="Get details for a registered sensor.",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
        404: {"content": {"application/json": {"example": {"detail": "Sensor with the given ID does not exist!"}}}},
    },
    dependencies=[Depends(is_active)],
)
def get_sensor(
    sensor_id: Annotated[NonNegativeInt, Path(description="ID of the sensor for which details are retrieved.")],
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
) -> schema.SensorDetailed:
    """Get details about a specific sensor for a measurement station."""
    try:
        return crud.get_sensors(db, ms_uuid=ms_uuid, sensor_id=sensor_id)[0]
    except ValueError:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Sensor with the given ID does not exist!")


def store_and_process_updates(db: Session, ms_uuid: UUID4, updates: schema.BatchUpdate) -> None | JSONResponse:
    """
    Process incoming sensor updates by storing them to the DB and invoking the privatizer.

    :param ms_uuid: The measurement station which took the measurements
    :param updates: The updated values in combination with the trixel IDs to which they belong
    :raises HTTPException: on invalid input
    :return: None or JSONResponse if the client should adjust settings
    """
    # TODO: optional - ascertain that all trixels have the same parent - should not be possible if clients are behaving

    invalid_trixels = set()
    for trixel in updates.keys():
        if not is_delegated(trixel):
            invalid_trixels.add(trixel)

    # Remove invalid trixels for further processing
    for trixel in invalid_trixels:
        updates.pop(trixel)

    try:
        crud.insert_sensor_updates(db, ms_uuid=ms_uuid, updates=updates)
        # TODO: add purge job for old data - keep statistics

        # TODO: process via privatizer, call privatizer update/callback

        # TODO: use 303 redirect if a different trixel id should be used according to k requirement
    except ValueError as e:
        raise HTTPException(HTTPStatus.BAD_REQUEST, detail=str(e))
    except IntegrityError:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "Timestamps must be unique!")

    if len(invalid_trixels) != 0:
        return JSONResponse(
            status_code=HTTPStatus.SEE_OTHER,
            content={"detail": "Trixel not managed by this TMS!", "trixel_ids": list(invalid_trixels)},
        )


# TODO: add endpoint(s) for (partial) measurement station migration to different TMS
# (in case Topology changes or a TMS is not responsible for sub-pixels)
# (partial meaning that only some sensors are transferred - clients also need to support this)


@router.put(
    "/trixel/{trixel_id}/update/{sensor_id}",
    name="Publish Single Sensor Value",
    summary="Publish a single sensor value update to the TMS.",
    tags=[TAG_TRIXELS],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
        404: {"content": {"application/json": {"example": {"detail": "Sensor with the given ID does not exist!"}}}},
        400: {"content": {"application/json": {"example": {"detail": "Invalid sensors provided: {0, 1}"}}}},
        303: {
            "content": {
                "application/json": {"example": {"detail": "Trixel not managed by this TMS!", "trixel_ids": [8, 9]}}
            }
        },
    },
    dependencies=[Depends(is_active)],
    status_code=HTTPStatus.OK,
)
def put_sensor_update(
    trixel_id: Annotated[schema.TrixelID, Path(description="The Trixel to which the sensor contributes.")],
    sensor_id: Annotated[
        NonNegativeInt,
        Path(description="The ID of the sensor which took the measurement."),
    ],
    value: Annotated[float, Query(description="The updated measurement value.")],
    timestamp: Annotated[
        datetime | NonNegativeInt, Query(description="Point in time at which the measurement was taken (unix time).")
    ],
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
):
    """Publish a single sensor value update to the TMS which is stored and processed within the desired trixel."""
    measurement = schema.Measurement(sensor_id=sensor_id, value=value, timestamp=timestamp)
    batch_update: schema.BatchUpdate = {trixel_id: [measurement]}

    return store_and_process_updates(db, ms_uuid, batch_update)


@router.put(
    "/trixel/update",
    name="Publish Sensor Updates To Trixels",
    summary="Publish multiple sensor updates to the TMS.",
    tags=[TAG_TRIXELS],
    responses={
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
        404: {"content": {"application/json": {"example": {"detail": "Sensor with the given ID does not exist!"}}}},
        400: {"content": {"application/json": {"example": {"detail": "Invalid sensors provided: {0, 1}"}}}},
        303: {
            "content": {
                "application/json": {"example": {"detail": "Trixel not managed by this TMS!", "trixel_ids": [8, 9]}}
            }
        },
    },
    dependencies=[Depends(is_active)],
    status_code=HTTPStatus.OK,
)
def put_sensor_batch_update(
    updates: schema.BatchUpdate,
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
):
    """Publish multiple sensor updates to the TMS which are stored and processed within the desired trixels."""
    return store_and_process_updates(db, ms_uuid, updates)
