"""Measurement station and related pydantic schemas."""

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    PositiveInt,
    SecretStr,
    field_serializer,
)


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
