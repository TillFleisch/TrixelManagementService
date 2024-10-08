"""Pydantic schemata related to the TMS configuration file."""

import logging
import sys
from datetime import timedelta
from enum import IntEnum
from typing import Any, Optional, Tuple, Type

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
    model_validator,
)
from pydantic_core import CoreSchema, core_schema
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)
from trixellookupclient.models import TMSDelegation

from privatizer.config_schema import AvailablePrivatizerConfigs, BlankPrivatizerConfig


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


class TMSDatabaseConfig(BaseModel):
    """TMS Database related configurations."""

    model_config = ConfigDict(validate_assignment=True)

    custom_url: Optional[str] = None
    dialect: Optional[str] = None
    user: Optional[str] = None
    password: Optional[SecretStr] = None
    host: Optional[str] = None
    port: Optional[int] = None
    db_name: Optional[str] = None
    use_sqlite: bool = False

    @model_validator(mode="before")
    def validate_mutual_exlusion(data: Any) -> Any:
        """Validate that custom_url is mutually exclusive with all other options."""
        attributes = ["dialect", "user", "password", "host", "db_name", "port"]

        for attribute in attributes:
            if data.get(attribute, None) is not None and data.get("custom_url", None):
                raise ValueError(f"Config: '{attribute}' and 'custom_url' mutually exclude each other.")

        return data


class TMSConfig(BaseModel):
    """TMS related configurations."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    id: int = Field(None)
    active: bool = Field(False)
    host: str
    api_token: SecretStr | None = Field(None)
    delegations: list[TMSDelegation] = Field(list())
    database: Optional[TMSDatabaseConfig] = None


class Config(BaseSettings):
    """Base Model for global settings within the TOML configuration file."""

    log_level: LogLevel = "NOTSET"
    tls_config: TLSConfig
    tms_config: TMSConfig
    model_config = SettingsConfigDict(toml_file="config/config.toml")
    trixel_update_frequency: NonNegativeInt = 60
    max_level: PositiveInt = Field(24, ge=1, le=24)
    privatizer_config: AvailablePrivatizerConfigs
    sensor_data_purge_interval: timedelta = timedelta(hours=1)
    sensor_data_keep_interval: timedelta = timedelta(weeks=2)

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
    privatizer_config: BlankPrivatizerConfig = BlankPrivatizerConfig()
    tls_config: TLSConfig = TLSConfig(host="sausage.dog.local")
    tms_config: TMSConfig = TMSConfig(host="wiener.dog.local", database=TMSDatabaseConfig(use_sqlite=True))


class GlobalConfig:
    """Class which hold the global configuration reference."""

    config: Config = None

    def __init__(self):
        """
        Initialize the global config reference.

        When pytest is loaded, a mock test-config will be loaded instead of the user-defined configuration.
        """
        if GlobalConfig.config is None:
            if "pytest" in sys.modules:
                GlobalConfig.config = TestConfig()
            else:
                GlobalConfig.config = Config()


GlobalConfig()
