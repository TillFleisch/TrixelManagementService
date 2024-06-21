"""Collection of global pydantic schemata."""

import logging
from enum import IntEnum
from typing import Any, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, SecretStr
from pydantic_core import CoreSchema, core_schema
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)
from trixellookupclient.models import TMSDelegation


class LogLevel(IntEnum):
    """Enum for user-defined logging levels."""

    NOTSET = logging.NOTSET
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARN = logging.WARN
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    FATAL = logging.CRITICAL
    CRITICAL = logging.CRITICAL

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        """Set custom validator for this enum."""
        return core_schema.with_info_before_validator_function(cls._validate, handler(int))

    @classmethod
    def _validate(cls, v, info):
        """Validate config input, return logging level int."""
        try:
            return {enum.name: enum.value for enum in cls}[str(v).upper()]
        except KeyError:
            raise ValueError(f"invalid value, must be one of: {[enum.name for enum in cls]}")


class TLSConfig(BaseModel):
    """TLS related configurations."""

    host: str
    use_ssl: bool = True


class TMSConfig(BaseModel):
    """TMS related configurations."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    id: int = Field(None)
    active: bool = Field(False)
    host: str
    api_token: SecretStr | None = Field(None)
    delegations: list[TMSDelegation] = Field(list())


class Config(BaseSettings):
    """Base Model for global settings within the TOML configuration file."""

    log_level: LogLevel = "NOTSET"
    tls_config: TLSConfig
    tms_config: TMSConfig
    model_config = SettingsConfigDict(toml_file="config/config.toml")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Load config from TOML resource."""
        return (TomlConfigSettingsSource(settings_cls),)


class TestConfig(Config):
    """Config model which utilizes the test configuration file."""

    __test__ = False
    model_config = SettingsConfigDict(toml_file=None)
    tls_config: TLSConfig = TLSConfig(host="sausage.dog.local")
    tms_config: TMSConfig = TMSConfig(host="wiener.dog.local")


class Ping(BaseModel):
    """Response schema for ping requests."""

    ping: str = "pong"


class Version(BaseModel):
    """Response schema for version requests."""

    version: str
