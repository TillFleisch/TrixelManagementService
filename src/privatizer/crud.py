"""Database wrappers which are related to privatizer implementations."""

from datetime import datetime, timedelta
from typing import Tuple

from pydantic import PositiveInt
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import measurement_station.model as ms_model
import model
from model import MeasurementTypeEnum
from privatizer.schema import UniqueSensorId
from schema import TrixelID


async def get_sensor_average(
    db: AsyncSession, unique_sensor_ids: set[UniqueSensorId], time_period: timedelta
) -> float | None:
    """
    Get the average value for the given sensor(s) within the provided time period.

    :param unique_sensor_ids: A set of sensors for which the average is determined
    :param time_period: The time period in the past starting from now
    :returns: The average value of the sensor(s) over the provided time period or None if unknown
    """
    if len(unique_sensor_ids) == 0:
        return None

    clauses: list = list()
    for sensor in unique_sensor_ids:
        clauses.append(
            ms_model.SensorMeasurement.measurement_station_uuid == sensor.ms_uuid
            and ms_model.SensorMeasurement.sensor_id == sensor.sensor_id
        )

    query = (
        select(func.avg(ms_model.SensorMeasurement.value))
        .where(or_(*clauses))
        .where(ms_model.SensorMeasurement.time > datetime.now() - time_period)
    )

    return (await db.execute(query)).scalar_one_or_none()


async def get_trixel_average(
    db: AsyncSession, trixel_id: TrixelID, measurement_type: MeasurementTypeEnum, time_period: timedelta
) -> float | None:
    """
    Get the average value for the given trixel within the provided time period.

    :param trixel_id: The ID of the trixel for which the average is determined
    :param measurement_type: The type of measurement for which the average is determined
    :param time_period: The time period in the past starting from now
    :returns: The average value of the trixel over time or None if unknown
    """
    query = (
        select(func.avg(model.Observation.value))
        .where(model.Observation.trixel_id == trixel_id)
        .where(
            model.Observation.measurement_type == model.MeasurementType.id,
            model.MeasurementType.name == measurement_type,
        )
        .where(model.Observation.time > datetime.now() - time_period)
    )

    return (await db.execute(query)).scalar_one_or_none()


async def get_measurement_count(
    db: AsyncSession, unique_sensor_id: UniqueSensorId, time_period: timedelta
) -> Tuple[PositiveInt, PositiveInt]:
    """
    Get the number of measurements for a given sensors within the provided time period.

    :param unique_sensor_id: The ID of the sensor for which the measurement count is determined
    :param time_period: The period of time in the past where measurements are counted
    :returns: Number of samples, Number of non-NULL samples
    """
    query = (
        select(func.count(ms_model.SensorMeasurement.time), func.count(ms_model.SensorMeasurement.value))
        .where(ms_model.SensorMeasurement.measurement_station_uuid == unique_sensor_id.ms_uuid)
        .where(ms_model.SensorMeasurement.sensor_id == unique_sensor_id.sensor_id)
        .where(ms_model.SensorMeasurement.time > datetime.now() - time_period)
    )

    return (await db.execute(query)).one()


async def get_observation_count(
    db: AsyncSession, trixel_id: TrixelID, measurement_type: MeasurementTypeEnum, time_period: timedelta
) -> Tuple[PositiveInt, PositiveInt]:
    """
    Get the number of observations for a given trixel within the provided time period.

    :param trixel_id: The ID of the trixel for which the observation count is determined
    :param measurement_type: The type of measurement for which the count is determined
    :param time_period: The period of time in the past where measurements are counted
    :returns: Number of samples, Number of non-NULL samples
    """
    query = (
        select(func.count(model.Observation.time), func.count(model.Observation.value))
        .where(model.Observation.trixel_id == trixel_id)
        .where(model.Observation.measurement_type == measurement_type.get_id())
        .where(model.Observation.time > datetime.now() - time_period)
    )

    return (await db.execute(query)).one()


async def get_trixel_median(
    db: AsyncSession, trixel_id: TrixelID, measurement_type: MeasurementTypeEnum, time_period: timedelta
) -> float | None:
    """
    Get the median value for the given trixel within the provided time period.

    :param trixel_id: The ID of the trixel for which the median is determined
    :param measurement_type: The type of measurement for which the median is determined
    :param time_period: The time period in the past starting from now
    :returns: The median value of the trixel over time or None if unknown
    """
    sub_observation = aliased(model.Observation, name="sub_observation")
    sub_type = aliased(model.MeasurementType, name="sub_type")
    sub_query = (
        select(func.count(sub_observation.value))
        .where(sub_observation.trixel_id == trixel_id)
        .where(
            sub_observation.measurement_type == sub_type.id,
            sub_type.name == measurement_type,
        )
        .where(sub_observation.value != None)  # noqa: 711
        .where(sub_observation.time > datetime.now() - time_period)
        .scalar_subquery()
    )

    query = (
        select(model.Observation.value)
        .where(model.Observation.trixel_id == trixel_id)
        .where(
            model.Observation.measurement_type == model.MeasurementType.id,
            model.MeasurementType.name == measurement_type,
        )
        .where(model.Observation.value != None)  # noqa: 711
        .where(model.Observation.time > datetime.now() - time_period)
        .order_by(model.Observation.value)
        .offset(cast(sub_query / 2.0, Integer))
        .limit(1)
    )

    return (await db.execute(query)).scalar_one_or_none()


async def get_sensors_median(
    db: AsyncSession, unique_sensor_ids: set[UniqueSensorId], time_period: timedelta
) -> float | None:
    """
    Get the median value for the given sensor(s) within the provided time period.

    :param unique_sensor_ids: A set of sensors for which the median is determined
    :param time_period: The time period in the past starting from now
    :returns: The median value of the sensor(s) over time or None if unknown
    """
    if len(unique_sensor_ids) == 0:
        return None

    clauses: list = list()
    for sensor in unique_sensor_ids:
        clauses.append(
            ms_model.SensorMeasurement.measurement_station_uuid == sensor.ms_uuid
            and ms_model.SensorMeasurement.sensor_id == sensor.sensor_id
        )

    sub_query = (
        select(func.count(ms_model.SensorMeasurement.value))
        .where(or_(*clauses))
        .where(ms_model.SensorMeasurement.value != None)  # noqa: 711
        .where(ms_model.SensorMeasurement.time > datetime.now() - time_period)
        .scalar_subquery()
    )

    query = (
        select(ms_model.SensorMeasurement.value)
        .where(or_(*clauses))
        .where(ms_model.SensorMeasurement.value != None)  # noqa: 711
        .where(ms_model.SensorMeasurement.time > datetime.now() - time_period)
        .order_by(ms_model.SensorMeasurement.value)
        .offset(cast(sub_query / 2.0, Integer))
        .limit(1)
    )

    return (await db.execute(query)).scalar_one_or_none()


async def get_sensor_age(
    db: AsyncSession, unique_sensor_id: UniqueSensorId, time_period: timedelta
) -> timedelta | None:
    """
    Get the oldest timestamp of a sensors contribution within the given time period.

    :param unique_sensor_id: The ID of the sensor for which the age is determined
    :param time_period: The maximum time_period in the past where measurements are considered
    :returns: Time period since the sensors first measurement or None if there are no measurements
    """
    query = (
        select(func.min(ms_model.SensorMeasurement.time))
        .where(ms_model.SensorMeasurement.measurement_station_uuid == unique_sensor_id.ms_uuid)
        .where(ms_model.SensorMeasurement.sensor_id == unique_sensor_id.sensor_id)
        .where(ms_model.SensorMeasurement.time > datetime.now() - time_period)
    )
    if result := (await db.execute(query)).scalar_one_or_none():
        return datetime.now() - result
    return None
