"""Schemata related to configuration variables of privatizers."""

import enum
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt

AvailablePrivatizers = Literal[
    "blank",
    "latest",
    "naive_average",
    "naive_smoothing_average",
    "average",
    "smoothing_average",
    "naive_kalman",
    "kalman",
]


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
    """Additional configuration variables regarding the exponential smoothing naive average privatizer."""

    privatizer: Literal["naive_smoothing_average"] = "naive_smoothing_average"

    # Exponential smoothing factor which is applied to the aggregate local measurements.
    local_smooth_factor: float = Field(0.5, ge=0, le=1)

    # Exponential smoothing factor which is applied to the aggregate subtrixel measurements.
    child_smooth_factor: float = Field(1, ge=0, le=1)


class MeasurementTypeEnum(enum.StrEnum):
    """Supported measurement types."""

    AMBIENT_TEMPERATURE = "ambient_temperature"
    RELATIVE_HUMIDITY = "relative_humidity"


class StatisticCorrelationSettings(BaseModel):
    """Settings which are applied to the median correlation setting."""

    max_delta: dict[MeasurementTypeEnum, PositiveFloat]


class CorrelationEvaluatingPrivatizerConfig(PrivatizerConfig):
    """Configuration variables required by the correlation evaluating privatizer."""

    privatizer: Literal["correlation_evaluation"] = "correlation_evaluation"

    statistic_type: Literal["median", "average"] = "average"

    # Minimum time requirement which determines after what time a trixel is allowed to be sub-divided
    # The trixel must have generated an output value for at least the specified amount of time
    privatizer_subdivision_time_requirement: timedelta = timedelta(days=2)

    # Minimum threshold that must be met for a trixel to be sub-divided. This variable provides a margin of for the
    # `privatizer_subdivision_time_requirement` such that a trixels sub-division is not prevented if it temporarily does
    # not meet the the requirement above given that it has been reliable in the past.
    privatizer_subdivision_time_threshold: float = Field(0.8, ge=0, le=1)

    # The minimum time that a sensor must have provided measurement for, in order to be further evaluated
    minimum_sensor_age: timedelta = timedelta(days=1)

    # The interval in which a sensors age is evaluated; in-between cached values are used
    age_evaluation_interval: timedelta = timedelta(days=0.5)

    # Minimum uptime score requirement that must be met by sensor; The score is evaluated according to `evaluate_uptime`
    uptime_requirement: float = Field(0.95, ge=0, le=1)

    # The minimum interval between measurement updates that must be met by a sensor in order for it to not be excluded
    max_update_interval: timedelta = timedelta(minutes=10)

    # The interval in which a sensors uptime is evaluated; in between cached values are used
    uptime_evaluation_interval: timedelta = timedelta(days=0.5)

    # The base time range which is used during uptime evaluation
    # The sensors uptime is determined based on the interpolated/extrapolated update count between the base period and
    # the extended time range based on the time multiplier
    uptime_base_time_range: timedelta = timedelta(days=1)

    # The extended time range multiplier which is used during sensor uptime evaluation to determine the larger timeframe
    uptime_long_time_multiplier: PositiveInt = 7

    # Determines from which trixel level on the trixel statistic (median/average) check is executed instead of the local
    # correlation check
    # Must be at least one, as the local correlation check is required for the root level
    local_trixel_statistic_check_split_level: PositiveInt = 2

    # The minimum number of sensor which are required by a privatizer before the local minimum check is executed
    # If this requirement is not satisfied a sensor will retain it's lifecycle status
    local_check_minimum_sensor_count: PositiveInt = 15

    # The local correlation is determined by comparing a sensors statistic (median/average) to that of the statistic of
    # all sensors within a privatizer. The score is calculated by checking the mean similarity across multiple time
    # ranges. The score is 0 if the difference between a sensors mean and the local mean is larger than the specified
    # value. Otherwise a score score between 0 and 1 is determined which is 0 if the delta between the two values is 0
    # and 1 if it's equal to the value specified below.
    # The final score is the largest score of any of the specified time ranges
    root_level_statistic_correlation_settings: dict[timedelta, StatisticCorrelationSettings] = {
        timedelta(days=1): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 1.75, MeasurementTypeEnum.RELATIVE_HUMIDITY: 1.75}
        ),
        timedelta(days=7): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 1, MeasurementTypeEnum.RELATIVE_HUMIDITY: 1}
        ),
        timedelta(weeks=2): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 0.8, MeasurementTypeEnum.RELATIVE_HUMIDITY: 0.8}
        ),
    }

    # A further threshold can be required which filters sensors with high deviations from mean. 0.2 means, the sensors
    # mean deviation must at least be smaller than 60% of the setting above. A smaller value will allow more sensors
    # to pass, while a large value will only select those sensor which have very high correlation. Use 0 to disable.
    root_level_statistic_correlation_threshold: float = 0.6

    # The trixel correlation is determined by comparing a sensors statistic (median/average) to that of the privatizers
    # output.
    # The score is calculated by checking the mean similarity across multiple time ranges. The score is 0
    # if the difference between a sensors mean and the trixel mean is larger than the specified value. Otherwise a score
    # score between 0 and 1 is determined which is 0 if the delta between the two values is 0 and 1 if it's equal to the
    # value specified below.
    # The final score is the largest score of any of the specified time ranges
    trixel_statistic_correlation_settings: dict[timedelta, StatisticCorrelationSettings] = {
        timedelta(days=1): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 2, MeasurementTypeEnum.RELATIVE_HUMIDITY: 2}
        ),
        timedelta(days=7): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 1, MeasurementTypeEnum.RELATIVE_HUMIDITY: 1}
        ),
        timedelta(weeks=2): StatisticCorrelationSettings(
            max_delta={MeasurementTypeEnum.AMBIENT_TEMPERATURE: 0.75, MeasurementTypeEnum.RELATIVE_HUMIDITY: 0.75}
        ),
    }

    # A further threshold can be required which filters sensors with high deviations from mean. 0.3 means, the sensors
    # mean deviation must at least be smaller than 70% of the setting above. A smaller value will allow more sensors
    # to pass, while a large value will only select those sensor which have very high correlation. Use 0 to disable.
    trixel_statistic_correlation_threshold: float = 0.3

    # Determines how many layers of (grand-)parent trixels are checked during the trixel similarity evaluation
    # A value of 1 is equal to only the grand-parent trixel (assumption: a trixel is contributing to the parent trixel,
    # therefore, this is essentially equal to comparing with 1 layer up rather than 2 layers up (in most cases))
    trixel_statistic_check_generations: PositiveInt = 2

    # Determines at which level the `trixel_statistic_correlation_settings` apply. At lower levels the exact settings
    # are used. At higher levels, the `max_deltas` are multiplied with the `trixel_statistic_level_scale_factor`
    # depending on how far they are away from `local_trixel_statistic_check_target_level`. Thus, at higher levels lower
    # tolerance is required to pass the correlation check.
    # The largest tolerance is dependent on this `local_trixel_statistic_check_target_level` value.
    # Given `local_trixel_statistic_check_target_level=8` and `trixel_statistic_level_scale_factor=0.1` and a
    # correlation setting with a `max_delta` of `2`, the largest tolerance at level 1 would be: 2 + (8-1) * 0.1 * 2 =3.4
    local_trixel_statistic_check_target_level: int = 8

    # The factor by which the max_delta requirement is multiplied for each increased level
    trixel_statistic_level_scale_factor: float = 0.1

    # Determines how often a cached value for time based metrics is invalidated. A value of 4 means, a cached value for
    # a time frame of 1 hour will be invalidated every 15 minutes
    cache_invalidation_factor: PositiveInt = 4

    # The smoothing factor which is used during sensor impact noise removal for a sensors exponential moving average
    sensor_ema_smoothing_factor: PositiveFloat = Field(0.2, ge=0.0, le=1.0)

    # The threshold which must be exceeded (in comparison to ema) by in order for a measurement to be discarded
    sensor_impact_noise_threshold: dict[MeasurementTypeEnum, PositiveFloat] = {
        MeasurementTypeEnum.AMBIENT_TEMPERATURE: 7,
        MeasurementTypeEnum.RELATIVE_HUMIDITY: 7,
    }


class NaiveKalmanPrivatizerConfig(PrivatizerConfig):
    """Configuration options for the native kalman filter based privatizer."""

    privatizer: Literal["naive_kalman"] = "naive_kalman"

    # The oldest allowed age for incoming measurement and stale measurement station detection
    max_measurement_age: timedelta = timedelta(minutes=5)

    # The oldest allowed age of measurements, which used during averaging
    max_measurement_age_averaging: timedelta = timedelta(minutes=2.5)

    # Number of allowed missed sensor updates in comparison to the average update interval of the sensor
    missed_update_threshold: float = 2

    # Smoothing weight which is used for new values while determining the average update interval
    update_interval_weight: float = Field(0.1, ge=0, le=1)

    # The process uncertainty of the kalman filter for the time frame of one trixel_update_frequency
    process_std_deviation_per_time_step: float = 1

    # Default accuracy which is used if a sensor does not provide it's accuracy
    default_sensor_accuracy: dict[MeasurementTypeEnum, float] = {
        MeasurementTypeEnum.AMBIENT_TEMPERATURE: 1,
        MeasurementTypeEnum.RELATIVE_HUMIDITY: 1,
    }

    # Default accuracy which is used if the average accuracy of a trixel is not known
    default_child_trixel_accuracy: dict[MeasurementTypeEnum, float] = {
        MeasurementTypeEnum.AMBIENT_TEMPERATURE: 0.1,
        MeasurementTypeEnum.RELATIVE_HUMIDITY: 0.1,
    }


class KalmanPrivatizerConfig(CorrelationEvaluatingPrivatizerConfig, NaiveKalmanPrivatizerConfig):
    """Additional configuration variables required by the (non-native) kalman privatizer."""

    privatizer: Literal["kalman"] = "kalman"


class AveragePrivatizerConfig(CorrelationEvaluatingPrivatizerConfig, NaiveAveragePrivatizerConfig):
    """Additional configuration variables required by the (non-naive) average privatizer."""

    privatizer: Literal["average"] = "average"


class SmoothingAveragePrivatizerConfig(CorrelationEvaluatingPrivatizerConfig, NaiveSmoothingAveragePrivatizerConfig):
    """Additional configuration variables regarding the exponential smoothing average privatizer."""

    privatizer: Literal["smoothing_average"] = "smoothing_average"


AvailablePrivatizerConfigs = (
    BlankPrivatizerConfig
    | LatestPrivatizerConfig
    | NaiveAveragePrivatizerConfig
    | NaiveSmoothingAveragePrivatizerConfig
    | AveragePrivatizerConfig
    | SmoothingAveragePrivatizerConfig
    | NaiveKalmanPrivatizerConfig
)
