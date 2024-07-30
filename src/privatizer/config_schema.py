"""Schemata related to configuration variables of privatizers."""

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field

AvailablePrivatizers = Literal["blank", "latest", "naive_average", "naive_smoothing_average"]


class PrivatizerConfig(BaseModel):
    """Base configuration class for privatizer specific settings."""

    privatizer: AvailablePrivatizers
    logging: bool = False


class BlankPrivatizerConfig(PrivatizerConfig):
    """Configuration variables related to the blank privatizer."""

    privatizer: Literal["blank"] = "blank"


class LatestPrivatizerConfig(PrivatizerConfig):
    """Configuration variables related to the latest privatizer."""

    privatizer: Literal["latest"] = "latest"


class NaiveAveragePrivatizerConfig(PrivatizerConfig):
    """Configuration variables required by the naive average privatizer."""

    privatizer: Literal["naive_average"] = "naive_average"

    # The oldest allowed age for incoming measurement and stale measurement station detection
    max_measurement_age: timedelta = timedelta(minutes=5)

    # The oldest allowed age of measurements, which used during averaging
    max_measurement_age_averaging: timedelta = timedelta(minutes=2.5)

    # Number of allowed missed sensor updates in comparison to the average update interval of the sensor
    missed_update_threshold: float = 2

    # Smoothing weight which is used for new values while determining the average update interval
    update_interval_weight: float = Field(0.1, ge=0, le=1)


class NaiveSmoothingAveragePrivatizerConfig(NaiveAveragePrivatizerConfig):
    """Additional configuration variables regarding the exponential smoothing average privatizer."""

    privatizer: Literal["naive_smoothing_average"] = "naive_smoothing_average"

    # Exponential smoothing factor which is applied to the aggregate local measurements.
    local_smooth_factor: float = Field(0.5, ge=0, le=1)

    # Exponential smoothing factor which is applied to the aggregate subtrixel measurements.
    child_smooth_factor: float = Field(1, ge=0, le=1)


AvailablePrivatizerConfigs = (
    BlankPrivatizerConfig
    | LatestPrivatizerConfig
    | NaiveAveragePrivatizerConfig
    | NaiveSmoothingAveragePrivatizerConfig
)
