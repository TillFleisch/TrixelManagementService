"""Measurement station and related pydantic schemas."""

import enum
from datetime import datetime
from typing import Annotated

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    field_serializer,
    field_validator,
)

from model import MeasurementTypeEnum
from schema import TrixelID


class TrixelLevelChange(str, enum.Enum):
    """Enum which indicates the actions which should be taken by a client to maintain the k-anonymity requirement."""

    KEEP = "keep"
    INCREASE = "increase"
    DECREASE = "decrease"


class SeeOtherReason(str, enum.Enum):
    """Enum which indicates the reason for a see other status code."""

    WRONG_TMS = "wrong_tms"
    CHANGE_TRIXEL = "change_trixel"


class MeasurementStationBase(BaseModel):
    """Base schema for MeasurementStation endpoints."""

    uuid: UUID4
    active: bool
    k_requirement: PositiveInt


class MeasurementStation(MeasurementStationBase):
    """Schema for generic queries related to measurement stations."""

    model_config = ConfigDict(from_attributes=True)


class MeasurementStationCreate(MeasurementStationBase):
    """Schema for creating measurement stations, which includes tokens."""

    token: SecretStr

    @field_serializer("token", when_used="json")
    def reveal_token(self, v):
        """Get the jwt access token during json conversion."""
        return v.get_secret_value()


class SensorBase(BaseModel):
    """Base schema for describing sensors."""

    ms_uuid: UUID4 = Field(alias="measurement_station_uuid")
    sensor_id: int = Field(alias="id")
    measurement_type: MeasurementTypeEnum

    @field_validator("measurement_type", mode="before")
    def convert_measurement_type(data: int | str | MeasurementTypeEnum) -> MeasurementTypeEnum | str:
        """Automatically convert int enum (originating from db) into their wrapped enum class."""
        if isinstance(data, int):
            return MeasurementTypeEnum.get_from_id(data)
        return data


class Sensor(SensorBase):
    """Generic sensor schema without details."""

    model_config = ConfigDict(from_attributes=True)


class SensorDetails(BaseModel):
    """Schema for describing properties of sensors."""

    accuracy: PositiveFloat | None
    sensor_name: str | None = Field(alias="name", serialization_alias="sensor_name")


class SensorDetailed(SensorBase):
    """Sensor schema which also contains details."""

    model_config = ConfigDict(from_attributes=True)

    details: SensorDetails


class Measurement(BaseModel):
    """Schema which describes a single measurement performed by sensor within a measurement station."""

    # Timestamps to be provided in unix-time
    timestamp: Annotated[
        datetime | PositiveInt, Field(description="Point in time at which the measurement was taken (unix time).")
    ]
    sensor_id: Annotated[
        NonNegativeInt,
        Field(description="The ID of the sensor which took the measurement."),
    ]
    value: Annotated[float | None, Field(description="The updated measurement value.")]

    # TODO: assert timestamp is "reasonable" - not far in the past/future
    # TODO: consider adding a heartbeat option per sensor to prevent value re-transmission


BatchUpdate = Annotated[
    dict[
        Annotated[
            TrixelID,
            Field(description="The ID of the Trixel to which sensors should contribute."),
        ],
        Annotated[list[Measurement], Field(description="Set of measurements performed by the measurements station.")],
    ],
    Field(description="A dictionary where for each trixel, sensors with their updated measurements are described."),
]
