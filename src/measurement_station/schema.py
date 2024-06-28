"""Measurement station and related pydantic schemas."""

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    field_serializer,
    field_validator,
)

from model import MeasurementTypeEnum


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
