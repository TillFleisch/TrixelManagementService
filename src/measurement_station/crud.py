"""Measurement station and related database wrappers."""

import uuid
from datetime import datetime
from secrets import token_bytes

import jwt
from pydantic import UUID4, PositiveFloat, PositiveInt
from sqlalchemy import delete, or_, update
from sqlalchemy.orm import Session

from database import except_columns
from model import MeasurementTypeEnum

from . import model, schema


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

    result = db.execute(stmt)

    if result.rowcount == 0:
        raise ValueError(f"Measurement Station with uuid {uuid_} does not exist!")

    db.commit()
    return (
        db.query(*except_columns(model.MeasurementStation, "token_secret"))
        .where(model.MeasurementStation.uuid == uuid_)
        .first()
    ) is None


def get_measurement_station(db: Session, uuid_: UUID4) -> model.MeasurementStation:
    """
    Get details about a measurement station.

    :param: The UUID of the measurement station for which details are retrieved
    :return: Details about the measurement station.
    """
    return (
        db.query(*except_columns(model.MeasurementStation, "token_secret"))
        .where(model.MeasurementStation.uuid == uuid_)
        .one()
    )


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


def create_sensor(
    db: Session,
    ms_uuid: UUID4,
    type_: MeasurementTypeEnum,
    accuracy: PositiveFloat | None = None,
    sensor_name=str | None,
) -> model.Sensor:
    """
    Add a new sensors to a measurement station.

    :param ms_uuid: The uuid of the measurement station to which the new sensor should be added
    :param type_: Type of measurement acquired by this sensor
    :param accuracy: The accuracy of the new sensor
    :param name: The name of the sensor which takes measurements
    :return: newly created sensor
    """
    stmt = (
        update(model.MeasurementStation)
        .where(model.MeasurementStation.uuid == ms_uuid)
        .values(sensor_index=model.MeasurementStation.sensor_index + 1)
        .returning(model.MeasurementStation.sensor_index)
    )
    sensor_id = db.execute(stmt).one()[0]

    # use existing sensor details or add new entry
    existing_detail_id = (
        db.query(model.SensorDetail.id)
        .where(model.SensorDetail.name == sensor_name)
        .where(model.SensorDetail.accuracy == accuracy)
        .first()
    )
    if existing_detail_id is not None:
        existing_detail_id = existing_detail_id[0]
    else:
        sensor_details = model.SensorDetail(name=sensor_name, accuracy=accuracy)
        db.add(sensor_details)
        db.commit()
        db.refresh(sensor_details)
        existing_detail_id = sensor_details.id

    sensor = model.Sensor(
        id=sensor_id - 1,
        measurement_station_uuid=ms_uuid,
        measurement_type=type_.get_id(),
        sensor_detail_id=existing_detail_id,
    )
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def delete_sensor(db: Session, ms_uuid: UUID4, sensor_id: int) -> bool:
    """
    Delete an existing sensor form a measurement station.

    :param ms_uuid: The uuid of the measurement station from which the sensor is removed
    :param sensor_id: The ID of the sensor which should be removed
    :return: True if removal was successful, False otherwise
    :raises ValueError: if the given sensor does not exist
    """
    stmt = delete(model.Sensor).where(model.Sensor.measurement_station_uuid == ms_uuid, model.Sensor.id == sensor_id)
    result = db.execute(stmt)

    if result.rowcount == 0:
        raise ValueError(f"Sensor with ID {sensor_id} does not exist!")

    db.commit()
    return (
        db.query(model.Sensor.id)
        .where(model.Sensor.measurement_station_uuid == ms_uuid, model.Sensor.id == sensor_id)
        .first()
    ) is None


def get_sensors(db: Session, ms_uuid: UUID4, sensor_id: int | None = None) -> list[model.Sensor]:
    """
    Get details about sensors for a measurement station.

    :param ms_uuid: The uuid of the measurement station for which sensors are retrieved
    :param sensor_id: Optional filter which restricts results to the provided sensor id
    :return: List of sensors with details
    :raises ValueError: If the provided sensor does not exist
    """
    stmt = db.query(model.Sensor).where(model.Sensor.measurement_station_uuid == ms_uuid)

    if sensor_id is not None:
        if (
            db.query(model.Sensor)
            .where(model.Sensor.measurement_station_uuid == ms_uuid, model.Sensor.id == sensor_id)
            .first()
            is None
        ):
            raise ValueError(f"Sensor with ID {sensor_id} does not exist!")

        stmt = stmt.where(model.Sensor.id == sensor_id)

    return stmt.all()


def insert_sensor_updates(db: Session, ms_uuid: UUID4, updates: schema.BatchUpdate):
    """
    Add multiple measurements for different sensors to a measurement station within the DB.

    :param ms_uuid: the measurement station for which updates are provided
    :param update: sensor updates
    :raises ValueError: if at least one of the measurement stations does not exist
    :raises ValueError: if multiple updates are included for a single sensor
    """
    sensor_ids = list()
    clauses = list()
    for measurements in updates.values():
        for measurement in measurements:
            clauses.append(model.Sensor.id == measurement.sensor_id)
            sensor_ids.append(measurement.sensor_id)

            new_sensor_measurement: model.SensorMeasurement = model.SensorMeasurement(
                time=(
                    measurement.timestamp
                    if isinstance(measurement.timestamp, datetime)
                    else datetime.fromtimestamp(measurement.timestamp)
                ),
                measurement_station_uuid=ms_uuid,
                sensor_id=measurement.sensor_id,
                value=measurement.value,
            )
            db.add(new_sensor_measurement)

    stmt = db.query(model.Sensor.id).where(model.Sensor.measurement_station_uuid == ms_uuid).where(or_(False, *clauses))
    valid_sensors = set([x[0] for x in stmt.all()])

    if len(invalid_sensors := set(sensor_ids) - valid_sensors) > 0:
        raise ValueError(f"Invalid sensors provided: {invalid_sensors}")

    if len(sensor_ids) != len(set(sensor_ids)):
        raise ValueError("Only one update per sensor allowed!")

    db.commit()


def get_sensor_types(db: Session, ms_uuid: UUID4, sensor_ids: set[int]) -> dict[int, MeasurementTypeEnum]:
    """
    Retrieve the sensor type for sensors within a measurement station.

    :param ms_uuid: The measurement station for which sensor types are retrieved
    :param sensor_ids: list of sensor id's for which the type is resolved
    :returns: dictionary containing the measurement type for each provided sensor
    """
    lookup = dict()
    result = (
        db.query(model.Sensor.id, model.Sensor.measurement_type)
        .where(model.Sensor.measurement_station_uuid == ms_uuid)
        .where(model.Sensor.id.in_(sensor_ids))
        .all()
    )

    for sensor_id, type_ in result:
        lookup[sensor_id] = MeasurementTypeEnum.get_from_id(type_)
    return lookup
