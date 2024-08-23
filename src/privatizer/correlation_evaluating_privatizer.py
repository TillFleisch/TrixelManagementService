"""Partial privatizer implementation which evaluates sensors based on their correlation to other sensors/trixels."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, ClassVar, Coroutine, Tuple

from pydantic import UUID4, NonNegativeInt, PositiveInt
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

import privatizer.crud as crud
from config_schema import GlobalConfig
from database import get_db
from logging_helper import get_logger
from measurement_station.schema import Measurement
from model import MeasurementTypeEnum
from privatizer.config_schema import (
    CorrelationEvaluatingPrivatizerConfig,
    MedianCorrelationSettings,
)
from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, UniqueSensorId

logger = get_logger(__name__)


class SensorLifeCycleDetailed(SensorLifeCycleBase):
    """A correlation evaluating privatizer specific sensor life cycle object."""

    class ExclusionReason(StrEnum):
        """Different exclusion reason which describe why a sensor cannot contribute at this privatizer."""

        UNKNOWN = "unknown"
        TOO_YONG = "too_young"
        UPTIME_UNRELIABLE = "unreliable_uptime"
        INSIGNIFICANT_CORRELATION = "insignificant_correlation"
        LOW_UPDATE_INTERVAL = "low_update_interval"

    exclusion_reason: ExclusionReason | None = None

    average_update_interval: float | None = None

    uptime: float | None = None
    last_uptime_update: datetime | None = None

    age: timedelta | None = None
    age_last_update: datetime | None = None

    # Cache for sensor median values
    sensor_median: dict[PositiveInt, float | None] | None = None

    # Timestamp at which sensors were last evaluated
    sensor_median_last_update: dict[PositiveInt, datetime] | None = None

    local_correlation_score: float | None = None

    trixel_correlation_score: float | None = None

    exponential_moving_average: float | None = None


class CorrelationEvaluatingPrivatizer(Privatizer):
    """
    The correlation evaluating privatizer evaluates sensor quality based on their past correlation with other sensors.

    The specific criteria as to when a sensor is marked as `reliable` and `trustworthy` are laid out in
    `evaluate_sensor_quality`.
    """

    config: ClassVar[CorrelationEvaluatingPrivatizerConfig] = GlobalConfig.config.privatizer_config

    # Cache for median value of all local sensors for different time periods (in seconds)
    local_sensor_median: dict[PositiveInt, float | None]

    # Timestamp at which the local median was last updated
    local_sensor_median_last_update: dict[PositiveInt, datetime]

    # Cache for median value of this trixels output value for different time periods (in seconds)
    trixel_median: dict[PositiveInt, float | None]

    # Timestamp at which the trixel median was last updated
    trixel_median_last_update: dict[PositiveInt, datetime]

    # Cache for the trixel observation count (nr of generated output values per timeframe)
    trixel_observation_count: dict[PositiveInt, PositiveInt]

    # Timestamp at which the observation count of this trixel was last cached
    trixel_observation_count_last_update: dict[PositiveInt, datetime]

    def __init__(
        self,
        trixel_id: int,
        measurement_type: crud.MeasurementTypeEnum,
        get_privatizer_method: Callable[[int, MeasurementTypeEnum, bool], Any],
        get_lifecycle_method: Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Any],
        get_k_requirement_method: Callable[[UniqueSensorId | UUID4], int],
        remove_sensor_method: Callable[[UniqueSensorId], Coroutine[Any, Any, None]],
    ):
        """Initialize this privatizer instance and related variables."""
        super().__init__(
            trixel_id,
            measurement_type,
            get_privatizer_method,
            get_lifecycle_method,
            get_k_requirement_method,
            remove_sensor_method,
        )
        self.local_sensor_median = dict()
        self.local_sensor_median_last_update = dict()
        self.trixel_median = dict()
        self.trixel_median_last_update = dict()
        self.trixel_observation_count = dict()
        self.trixel_observation_count_last_update = dict()

    @override
    async def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> bool:
        """
        Determine if the provided sensor meets the quality requirements of this privatizer.

        A sensor must meet the following requirements:

        * A sensor must have a certain minimum age, to ensure that correlations can be determined and that the
          trixels are only populated by reliable sensors.
        * The uptime/availability of a sensor must exceed a threshold to prevent unreliable sensors from counting
          toward the k-requirement.
        * The sensors' measurements need to correlate with other sensors over multiple time periods (or)
            * Measurements must correlate with other sensors within the same trixel
            * Measurements must correlate with the (parent-/neighbor-)trixels measurements
        * Local correlation
            * At the root level (or other higher levels), a comparison with the parent or neighbor trixels is not
              possible/feasible
            * A sensors correlation is determined based on the deviation between the sensors median and the median of
              all senors within this privatizer
            * Once a set of correlating sensors has been chosen, at lower levels the trixel correlation will be used
        * Trixel correlation
            * Determine if a sensor's median correlated with the median of the parent trixel and further ancestors
            * Enforces local similarity
            * (the aggregated trixel measurements **should** only contain valid sensors, otherwise a cascade of
              decreasing quality may be started)
            * The correlation must be weaker at higher trixels, as they cover larger areas, which may not correlate
        """
        logger.debug(f"Evaluating {unique_sensor_id} from privatizer: ({self._id},{self.measurement_type})")
        config: CorrelationEvaluatingPrivatizerConfig = CorrelationEvaluatingPrivatizer.config
        sensor_life_cycle: SensorLifeCycleDetailed = self.get_lifecycle(
            unique_sensor_id=unique_sensor_id, lifecycle=SensorLifeCycleDetailed()
        )

        sensor_age = await self.get_sensor_age(unique_sensor_id=unique_sensor_id, sensor_life_cycle=sensor_life_cycle)
        if sensor_age is None or sensor_age <= config.minimum_sensor_age:
            sensor_life_cycle.contributing = False
            sensor_life_cycle.exclusion_reason = SensorLifeCycleDetailed.ExclusionReason.TOO_YONG
            logger.debug(
                (
                    f"Excluded {unique_sensor_id} with reason: {sensor_life_cycle.exclusion_reason} - "
                    f"age/minimum age: ({sensor_age}/{config.minimum_sensor_age})"
                )
            )
            return sensor_life_cycle.contributing

        uptime, average_update_interval = await self.evaluate_uptime(
            unique_sensor_id=unique_sensor_id, sensor_life_cycle=sensor_life_cycle
        )

        if uptime <= config.uptime_requirement:
            sensor_life_cycle.contributing = False
            sensor_life_cycle.exclusion_reason = SensorLifeCycleDetailed.ExclusionReason.UPTIME_UNRELIABLE
            logger.debug(
                (
                    f"Excluded {unique_sensor_id} with reason: {sensor_life_cycle.exclusion_reason} - "
                    f"uptime/uptime requirement: ({uptime}/{config.uptime_requirement})"
                )
            )
            return sensor_life_cycle.contributing
        if average_update_interval is None or average_update_interval >= config.max_update_interval:
            sensor_life_cycle.contributing = False
            sensor_life_cycle.exclusion_reason = SensorLifeCycleDetailed.ExclusionReason.LOW_UPDATE_INTERVAL
            logger.debug(
                (
                    f"Excluded {unique_sensor_id} with reason: {sensor_life_cycle.exclusion_reason} - "
                    f"average_update_interval/max interval: ({average_update_interval}/{config.max_update_interval})"
                )
            )
            return sensor_life_cycle.contributing

        if self._level < self.config.local_trixel_median_check_split_level:
            # Choose sensors that correlate with the median of all local sensors within this trixel, as long as there is
            # still an unpopulated child trixel
            # Thus, 'valid' sensors will be determined and they move on, the remaining sensors may get lucky in the next
            # round, when the median changes.
            # Even if a sensor is deemed trustworthy, when it's not, at lower levels with higher spatial accuracy it may
            # be deemed untrustworthy but it helped in bootstrapping the system.

            # skip evaluation and wait if not enough sensors are present
            if len(self._sensors) < self.config.local_check_minimum_sensor_count:
                return sensor_life_cycle.contributing

            score = await self.local_correlation_score(
                unique_sensor_id=unique_sensor_id, sensor_life_cycle=sensor_life_cycle
            )

            if score <= config.root_level_median_correlation_threshold:
                sensor_life_cycle.contributing = False
                sensor_life_cycle.exclusion_reason = SensorLifeCycleDetailed.ExclusionReason.INSIGNIFICANT_CORRELATION
                logger.debug(
                    (
                        f"Excluded {unique_sensor_id} with reason: {sensor_life_cycle.exclusion_reason} (local) - "
                        f"score/correlation threshold: ({score}/{config.root_level_median_correlation_threshold})"
                    )
                )
                return sensor_life_cycle.contributing
        else:
            score = await self.trixel_correlation_score(
                unique_sensor_id=unique_sensor_id, sensor_life_cycle=sensor_life_cycle
            )

            if score <= config.trixel_median_correlation_threshold:
                sensor_life_cycle.contributing = False
                sensor_life_cycle.exclusion_reason = SensorLifeCycleDetailed.ExclusionReason.INSIGNIFICANT_CORRELATION
                logger.debug(
                    (
                        f"Excluded {unique_sensor_id} with reason: {sensor_life_cycle.exclusion_reason} (trixel) - "
                        f"score/correlation threshold: ({score}/{config.root_level_median_correlation_threshold})"
                    )
                )
                return sensor_life_cycle.contributing

        sensor_life_cycle.contributing = True
        sensor_life_cycle.exclusion_reason = None
        return sensor_life_cycle.contributing

    @override
    async def new_value(self, unique_sensor_id: UniqueSensorId, measurement: Measurement) -> None:
        """
        Apply additional filters to a sensors input measurement.

        This privatizer implementation filters out outliers based on a sensors recent performance.

        Impulse noise (single spikes) are filtered out using a simple threshold operation in comparison to the sensor
        exponential moving average.
        """
        # The lifecycle object MUST be retrieved so that the correct class is used which can hold additional information
        sensor_life_cycle: SensorLifeCycleDetailed = self.get_lifecycle(
            unique_sensor_id=unique_sensor_id, lifecycle=SensorLifeCycleDetailed()
        )

        outlier: bool = False
        if sensor_life_cycle.exponential_moving_average is None or measurement.value is None:
            sensor_life_cycle.exponential_moving_average = measurement.value
        else:
            threshold = CorrelationEvaluatingPrivatizer.config.sensor_impact_noise_threshold[self.measurement_type]
            smooth_factor = CorrelationEvaluatingPrivatizer.config.sensor_ema_smoothing_factor

            if abs(measurement.value - sensor_life_cycle.exponential_moving_average) > threshold:
                outlier = True

            sensor_life_cycle.exponential_moving_average = (
                sensor_life_cycle.exponential_moving_average * (1 - smooth_factor) + smooth_factor * measurement.value
            )
        if outlier:
            measurement.value = None

        await super().new_value(unique_sensor_id, measurement)

    async def evaluate_uptime(
        self, unique_sensor_id: UniqueSensorId, sensor_life_cycle: SensorLifeCycleDetailed
    ) -> Tuple[float, float]:
        """
        Evaluate a sensors quality by determining if a sensor experiences outages/disconnects.

        The 'uptime' is determined by intra/extrapolating the number of samples between different time periods.
        They should be similar under the assumption that a sensors update interval does not change and that it regularly
        publishes updates.

        :param unique_sensor_id: The unique ID of sensor that should be evaluated
        :param sensor_life_cycle: A reference to the sensor lifecycle object which belongs to the sensor
        :returns: Tuple containing the uptime score and (1..available) and the sensors average update interval
        """
        config: CorrelationEvaluatingPrivatizerConfig = CorrelationEvaluatingPrivatizer.config

        if (
            sensor_life_cycle.last_uptime_update is None
            or datetime.now() - sensor_life_cycle.last_uptime_update > config.uptime_evaluation_interval
        ):
            async for db in get_db():
                time_range = config.uptime_base_time_range
                long_time_multiplier = config.uptime_long_time_multiplier
                total_count, valid_count = await crud.get_measurement_count(
                    db, unique_sensor_id=unique_sensor_id, time_period=time_range
                )

                if valid_count == 0:
                    return (0.0, None)

                average_update_interval = time_range / valid_count

                long_time_range = time_range * long_time_multiplier
                long_total_count, long_valid_count = await crud.get_measurement_count(
                    db, unique_sensor_id=unique_sensor_id, time_period=long_time_range
                )

                extrapolated_count = valid_count * long_time_multiplier
                extrapolated_uptime = 1 - min(1, max(0, (extrapolated_count - long_total_count) / extrapolated_count))

                interpolated_count = long_valid_count / long_time_multiplier
                interpolated_uptime = 1 - min(1, max(0, (interpolated_count - total_count) / interpolated_count))

                uptime = min(interpolated_uptime, extrapolated_uptime)

                sensor_life_cycle.uptime = uptime
                sensor_life_cycle.average_update_interval = average_update_interval
                sensor_life_cycle.last_uptime_update = datetime.now()
                return (uptime, average_update_interval)
        else:
            return (sensor_life_cycle.uptime, sensor_life_cycle.average_update_interval)

    async def get_sensor_age(
        self, unique_sensor_id: UniqueSensorId, sensor_life_cycle: SensorLifeCycleDetailed
    ) -> timedelta | None:
        """
        Get the age of a sensor.

        The age representation can be the time since the first contribution (naive approach), but it must not be.
        A better choice as a sensors age would be the last long contribution time period, which also allows for drop-out
        in between.
        If a sensors disappears for several days, the naive approach would be misleading once the sensor reappears.
        An approximation for this is the time since the first measurement within a limited time frame in the past.

        :param unique_sensor_id: The unique ID of sensor that should be evaluated
        :param sensor_life_cycle: A reference to the sensor lifecycle object which belongs to the sensor
        :returns: A time period which described for how long the sensor has been contributing or None the sensor has not
        contributed yet
        """
        config: CorrelationEvaluatingPrivatizerConfig = CorrelationEvaluatingPrivatizer.config

        max_time_range = max(config.trixel_median_correlation_settings.keys())

        if (
            sensor_life_cycle.age_last_update is None
            or datetime.now() - sensor_life_cycle.age_last_update > config.age_evaluation_interval
        ):
            async for db in get_db():
                sensor_life_cycle.age = await crud.get_sensor_age(
                    db, unique_sensor_id=unique_sensor_id, time_period=max_time_range
                )
                sensor_life_cycle.age_last_update = datetime.now()

        return sensor_life_cycle.age

    async def local_correlation_score(
        self, unique_sensor_id: UniqueSensorId, sensor_life_cycle: SensorLifeCycleDetailed
    ) -> float:
        """
        Determine a sensors median correlation score in comparison to all other local sensors.

        :param unique_sensor_id: The ID of the sensor that is being evaluated
        :param sensor_life_cycle: the sensors lifecycle object
        :returns: correlation score between 0..1
        """
        config: CorrelationEvaluatingPrivatizerConfig = CorrelationEvaluatingPrivatizer.config

        # Check if cached which are used in the following have become invalid
        valid_cache: bool = True
        time_range: timedelta
        for time_range in config.root_level_median_correlation_settings.keys():
            if (
                datetime.now() - self.local_sensor_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
                > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
                or sensor_life_cycle.sensor_median_last_update is None
                or datetime.now()
                - sensor_life_cycle.sensor_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
                > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
            ):
                valid_cache = False
                break
        if valid_cache:
            return sensor_life_cycle.local_correlation_score

        async for db in get_db():

            sub_scores: list[float] = list()
            time_range: timedelta
            settings: MedianCorrelationSettings
            for time_range, settings in config.root_level_median_correlation_settings.items():
                local_sensor_median: float | None = await self.get_cached_local_median(db, time_range)
                sensor_median: float | None = await self.get_cached_sensor_median(
                    db, unique_sensor_id, sensor_life_cycle, time_range
                )

                if sensor_median is None or local_sensor_median is None:
                    sensor_life_cycle.local_correlation_score = 0.0
                    return 0.0

                delta = abs(local_sensor_median - sensor_median)
                max_delta = settings.max_delta[self.measurement_type]

                if delta <= max_delta:
                    sub_scores.append(1 - (delta / max_delta))
                else:
                    sensor_life_cycle.local_correlation_score = 0.0
                    return 0.0

            sensor_life_cycle.local_correlation_score = min(sub_scores)
            return sensor_life_cycle.local_correlation_score

        sensor_life_cycle.local_correlation_score = 0.0
        return 0.0

    async def trixel_correlation_score(
        self, unique_sensor_id: UniqueSensorId, sensor_life_cycle: SensorLifeCycleDetailed
    ) -> float:
        """
        Determine a sensors median correlation score in comparison to parent/ancestor trixels.

        :param unique_sensor_id: The ID of the sensor that is being evaluated
        :param sensor_life_cycle: the sensors lifecycle object
        :returns: correlation score between 0..1
        """
        config: CorrelationEvaluatingPrivatizerConfig = CorrelationEvaluatingPrivatizer.config

        # Check if cached which are used in the following have become invalid
        valid_cache: bool = True
        time_range: timedelta
        for time_range in config.trixel_median_correlation_settings.keys():
            if (
                sensor_life_cycle.sensor_median_last_update is None
                or datetime.now()
                - sensor_life_cycle.sensor_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
                > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
            ):
                valid_cache = False
                break
            privatizer: CorrelationEvaluatingPrivatizer | None = self
            for i in range(0, config.trixel_median_check_generations + 2):
                if privatizer._parent is None:
                    break

                privatizer = self.get_privatizer(trixel_id=privatizer._parent, measurement_type=self.measurement_type)
                if privatizer is None:
                    break
                if i == 0:
                    continue

                if (
                    datetime.now()
                    - privatizer.trixel_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
                    > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
                ):
                    valid_cache = False
                    break
            if not valid_cache:
                break

        if valid_cache:
            return sensor_life_cycle.trixel_correlation_score

        async for db in get_db():

            sub_scores: list[float] = list()
            time_range: timedelta
            settings: MedianCorrelationSettings
            for time_range, settings in config.trixel_median_correlation_settings.items():
                sensor_median: float | None = await self.get_cached_sensor_median(
                    db, unique_sensor_id, sensor_life_cycle, time_range
                )

                if sensor_median is None:
                    sensor_life_cycle.trixel_correlation_score = 0.0
                    return 0.0

                privatizer: CorrelationEvaluatingPrivatizer | None = self
                for i in range(0, config.trixel_median_check_generations + 2):

                    if privatizer._parent is None:
                        break

                    privatizer = self.get_privatizer(
                        trixel_id=privatizer._parent, measurement_type=self.measurement_type
                    )
                    if privatizer is None:
                        break
                    # Skip the "parent" as the evaluation is usually happening in a child and the parent may not
                    # be populated yet, but grandparents should be
                    # Furthermore, a comparison with the "parent" is in some cases just a comparison with the sensor it-
                    # self or other local neighbors due to the fact that sensors are usually contributing to the parent
                    if i == 0:
                        continue

                    trixel_median: float | None = await privatizer.get_cached_trixel_median(db, time_range)

                    if trixel_median is None:
                        sensor_life_cycle.trixel_correlation_score = 0.0
                        return 0.0

                    delta = abs(trixel_median - sensor_median)
                    max_delta = settings.max_delta[self.measurement_type]

                    # If the privatizers level is higher than the target level of the trixel median correlation check
                    # setting, increase the setting's tolerance
                    if privatizer._level < config.local_trixel_median_check_split_level:
                        max_delta = (
                            max_delta
                            + (config.local_trixel_median_check_target_level - privatizer._level)
                            * config.trixel_median_level_scale_factor
                            * max_delta
                        )

                    if delta <= max_delta:
                        sub_scores.append(1 - (delta / max_delta))
                    else:
                        sensor_life_cycle.trixel_correlation_score = 0.0
                        return 0.0

            # Cannot determine score, ancestor unavailable
            if len(sub_scores) == 0:
                sensor_life_cycle.trixel_correlation_score = 0.0
                return 0.0

            sensor_life_cycle.trixel_correlation_score = min(sub_scores)
            return sensor_life_cycle.trixel_correlation_score

        sensor_life_cycle.trixel_correlation_score = 0.0
        return 0.0

    async def get_cached_sensor_median(
        self,
        db: AsyncSession,
        unique_sensor_id: UniqueSensorId,
        sensor_life_cycle: SensorLifeCycleDetailed,
        time_range: timedelta,
    ) -> float | None:
        """
        Get a sensors median measurement either from cache or from DB.

        :param unique_sensor_id: The unique identifier of the sensor in question
        :param sensor_life_cycle: A reference to the sensors lifecycle object
        :param time_range: The time range for which the median is determined
        :returns: The median value or None if unknown
        """
        if sensor_life_cycle.sensor_median is None:
            sensor_life_cycle.sensor_median = dict()
            sensor_life_cycle.sensor_median_last_update = dict()

        if (
            datetime.now()
            - sensor_life_cycle.sensor_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
            > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
        ):
            sensor_life_cycle.sensor_median[time_range.seconds] = await crud.get_sensors_median(
                db, {unique_sensor_id}, time_range
            )
            sensor_life_cycle.sensor_median_last_update[time_range.seconds] = datetime.now()

        return sensor_life_cycle.sensor_median.get(time_range.seconds, None)

    async def get_cached_local_median(
        self,
        db: AsyncSession,
        time_range: timedelta,
    ) -> float | None:
        """
        Get the median measurement of all sensors within this trixel either from cache or DB.

        :param time_range: The time range for which the median is determined
        :return: The median measurement or None if unknown
        """
        # TODO: perform evaluation (and caching) using a privatizer-specific lock to prevent redundant/multiple eval.
        if (
            datetime.now() - self.local_sensor_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
            > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
        ):
            self.local_sensor_median[time_range.seconds] = await crud.get_sensors_median(db, self._sensors, time_range)
            self.local_sensor_median_last_update[time_range.seconds] = datetime.now()

        return self.local_sensor_median.get(time_range.seconds, None)

    async def get_cached_trixel_median(self, db: AsyncSession, time_range: timedelta) -> float | None:
        """
        Get the median of the resulting output value of this trixel either from cache or DB.

        :param time_range: The time range for which the median is determined
        :returns: The median value of the observations generated by this trixel or none if unavailable
        """
        # TODO: perform evaluation (and caching) using a privatizer-specific lock to prevent redundant/multiple eval.
        if (
            datetime.now() - self.trixel_median_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
            > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
        ):
            self.trixel_median[time_range.seconds] = await crud.get_trixel_median(
                db, trixel_id=self._id, measurement_type=self._measurement_type, time_period=time_range
            )
            self.trixel_median_last_update[time_range.seconds] = datetime.now()

        return self.trixel_median.get(time_range.seconds, None)

    async def get_cached_observation_count(self, db: AsyncSession, time_range: timedelta) -> NonNegativeInt:
        """
        Get the observation count for this trixel for the given time range either from cache or DB.

        :param time_range: The time range for which the observation count of the trixel is determined
        :returns: The number of observation which were generated for this trixel within the given time period
        """
        if (
            datetime.now()
            - self.trixel_observation_count_last_update.get(time_range.seconds, datetime.fromtimestamp(0))
            > time_range / CorrelationEvaluatingPrivatizer.config.cache_invalidation_factor
        ):
            _, self.trixel_observation_count[time_range.seconds] = await crud.get_observation_count(
                db, self._parent, self.measurement_type, time_period=time_range
            )
            self.trixel_observation_count_last_update[time_range.seconds] = datetime.now()
        return self.trixel_observation_count.get(time_range.seconds, 0)

    async def can_subdivide(self) -> bool:
        """
        Determine if this privatizer is allowed to sub-divide based on the number of observations it has made recently.

        A privatizer is not allowed to sub-divide if it is 'too young'. If this were allowed, subsequent trixel
        comparisons would fail, as this privatizer has not generated enough data for a valid comparison.

        :returns: True if the privatizer has made enough observations based on the config file
        """
        if self._level == 0:
            return True
        else:
            async for db in get_db():
                time_period = self.config.privatizer_subdivision_time_requirement
                samples = await self.get_cached_observation_count(db, time_period)
                expected_samples = time_period / timedelta(seconds=GlobalConfig.config.trixel_update_frequency)

                return samples / expected_samples > self.config.privatizer_subdivision_time_threshold

            return False
