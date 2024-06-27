"""Measurement station and related database wrappers."""

import uuid
from secrets import token_bytes

import jwt
from pydantic import UUID4, PositiveInt
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from database import except_columns

from . import model


def verify_ms_token(db: Session, jwt_token: bytes) -> UUID4:
    """
    Check measurement station authentication token validity.

    :param jwt_token: user provided token
    :return: measurement station uuid associated with the token
    :raises PermissionError: if the provided token does not exist or is invalid
    """
    try:
        unverified_payload = jwt.decode(jwt_token, options={"verify_signature": False}, algorithms=["HS256"])
        uuid_: UUID4 = uuid.UUID(hex=unverified_payload["ms_uuid"])
        if (
            token_secret := db.query(model.MeasurementStation.token_secret)
            .where(model.MeasurementStation.uuid == uuid_)
            .first()
        ):
            jwt.decode(jwt_token, token_secret[0], algorithms=["HS256"])
            return uuid_
    except jwt.PyJWTError:
        raise PermissionError("Invalid MS authentication token.")
    raise PermissionError("Invalid MS authentication token.")


def create_measurement_station(db: Session, k_requirement: int) -> model.MeasurementStation:
    """
    Generate and insert a new measurement station into the DB.

    :param k_requirement: user provided k-anonymity requirement
    :return: inserted measurement station object
    """
    ms = model.MeasurementStation(k_requirement=k_requirement, token_secret=token_bytes(256))
    db.add(ms)
    db.commit()
    db.refresh(ms)
    return ms


def update_measurement_station(
    db: Session, uuid_: UUID4, k_requirement: PositiveInt | None = None, active: bool | None = None
) -> model.MeasurementStation:
    """
    Update the properties of an existing measurement station.

    :param uuid_: uuid of the measurement station which should be modified
    :param k_requirement: user provided k-anonymity requirement
    :param active: the new active status of this measurement station
    :return: updated measurement station object
    :raises ValueError: if none of the arguments are updated
    """
    stmt = update(model.MeasurementStation).where(model.MeasurementStation.uuid == uuid_)

    if k_requirement is None and active is None:
        raise ValueError("At least one of [k_requirement, active] must be provided.")

    if k_requirement is not None:
        stmt = stmt.values(k_requirement=k_requirement)
    if active is not None:
        stmt = stmt.values(active=active)

    db.execute(stmt)
    db.commit()

    return (
        db.query(*except_columns(model.MeasurementStation, "token_secret"))
        .where(model.MeasurementStation.uuid == uuid_)
        .one()
    )


def delete_measurement_station(db: Session, uuid_: UUID4) -> bool:
    """
    Remove a measurement station and related entities from the DB.

    :param uuid_: the uuid of the measurement station which should be modified
    :returns: True if deletion succeeded
    """
    stmt = delete(model.MeasurementStation).where(model.MeasurementStation.uuid == uuid_)

    db.execute(stmt)
    db.commit()

    return (
        db.query(*except_columns(model.MeasurementStation, "token_secret"))
        .where(model.MeasurementStation.uuid == uuid_)
        .first()
    ) is None


def get_measurement_station_count(db: Session, active: bool | None = None) -> int:
    """
    Get the number of registered measurement stations.

    :param active: filter by active state, use both states if None
    :return: number of measurement stations
    """
    stmt = db.query(model.MeasurementStation)
    if active is not None:
        stmt = stmt.where(model.MeasurementStation.active == active)
    return stmt.count()
