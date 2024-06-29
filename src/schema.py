"""Collection of global pydantic schemata."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, PositiveInt
from pynyhtm import HTM


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
