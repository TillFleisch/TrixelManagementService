"""Collection of global pydantic schemata."""

from pydantic import BaseModel


class Ping(BaseModel):
    """Response schema for ping requests."""

    ping: str = "pong"


class Version(BaseModel):
    """Response schema for version requests."""

    version: str
