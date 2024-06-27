"""API endpoints related to measurement stations."""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import UUID4, PositiveInt
from sqlalchemy.orm import Session

from common import is_active
from database import get_db

from . import crud, schema

TAG_MEASUREMENT_STATION = "Measurement Station"

router = APIRouter(tags=[TAG_MEASUREMENT_STATION])


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
        503: {"content": {"application/json": {"detail": "TMS not active!"}}},
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
    name="Update measurement station properties",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"detail": "TMS not active!"}}},
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
    name="Delete an existing measurement station",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"detail": "TMS not active!"}}},
        401: {
            "content": {
                "application/json": {"example": {"detail": "Invalid measurement station authentication token!"}}
            }
        },
    },
    dependencies=[Depends(is_active)],
    status_code=HTTPStatus.NO_CONTENT,
)
def delete_measurement_station(
    ms_uuid: UUID4 = Depends(verify_ms_token),
    db: Session = Depends(get_db),
):
    """Delete an existing measurement station from the DB."""
    if crud.delete_measurement_station(db, ms_uuid):
        return
    raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR)


@router.get(
    "/measurement_stations",
    name="Get the number of measurement station registered at this TMS",
    tags=[TAG_MEASUREMENT_STATION],
    responses={
        503: {"content": {"application/json": {"detail": "TMS not active!"}}},
        200: {"content": {"application/json": {"value": 0}}},
    },
    dependencies=[Depends(is_active)],
)
def get_measurement_station_count(
    active: Annotated[bool | None, Query(description="Filters by active state. Use both states if None.")] = None,
    db: Session = Depends(get_db),
):
    """Get the current number of registered measurement stations."""
    return {"value": crud.get_measurement_station_count(db, active=active)}
