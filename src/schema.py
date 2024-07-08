"""Collection of global pydantic schemata."""

import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
)
from pynyhtm import HTM

from model import MeasurementTypeEnum


def validate_trixel_id(value: int) -> int:
    """Validate that the TrixelId is valid."""
    try:
        HTM.get_level(value)
        return value
    except Exception:
        raise ValueError(f"Invalid trixel id: {value}!")


class Ping(BaseModel):
    """Response schema for ping requests."""

    ping: str = "pong"


class Version(BaseModel):
    """Response schema for version requests."""

    version: str


TrixelID = Annotated[
    PositiveInt,
    AfterValidator(validate_trixel_id),
    Field(description="A valid Trixel ID.", examples={8, 9, 15, 35}, serialization_alias="trixel_id"),
]


class Observation(BaseModel):
    """Schema which describes a single observation (at a point in time) for trixel&type."""

    model_config = ConfigDict(from_attributes=True)

    time: int  # unix-time
    trixel_id: TrixelID
    measurement_type: MeasurementTypeEnum
    value: float | None
    sensor_count: NonNegativeInt
    measurement_station_count: NonNegativeInt

    @field_validator("time", mode="before")
    def convert_datetime(data: int | datetime.datetime) -> int:
        """Automatically convert datetimes to unix timestamps."""
        if isinstance(data, datetime.datetime):
            return int(data.timestamp())
        return data

    @field_validator("measurement_type", mode="before")
    def convert_measurement_type(data: int | str | MeasurementTypeEnum) -> MeasurementTypeEnum:
        """Automatically convert int enum (originating from db) into their wrapped enum class."""
        if isinstance(data, int):
            return MeasurementTypeEnum.get_from_id(data)
        return data
