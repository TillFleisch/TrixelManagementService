"""Example implementation of a privatizer which does not properly ensure measurements are private."""

from typing import Any, Callable

from pydantic import UUID4, PositiveInt
from typing_extensions import override

from config_schema import GlobalConfig
from logging_helper import get_logger
from measurement_station.schema import Measurement
from model import MeasurementTypeEnum
from privatizer.config_schema import LatestPrivatizerConfig
from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, UniqueSensorId

logger = get_logger(__name__)


class LatestPrivatizer(Privatizer):
    """
    A not-so-privatizing implementation of a privatizer, which accepts every sensor and uses the latest raw measurement.

    The output value is the last received measurement from any contributing sensor. If there are children, the average
    value of those is used.
    This class serves as a usage-example for privatizer implementations.
    """

    _last_value = None
    _current_contributors: set[UniqueSensorId]

    def __init__(
        self,
        trixel_id: PositiveInt,
        measurement_type: MeasurementTypeEnum,
        get_privatizer_method: Callable[[int, MeasurementTypeEnum, bool], Any],
        get_lifecycle_method: Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Any],
        get_k_requirement_method: Callable[[UniqueSensorId | UUID4], int],
        remove_sensor_method: Callable[[UniqueSensorId], None],
    ):
        """Initialize the latest privatizer."""
        super().__init__(
            trixel_id,
            measurement_type,
            get_privatizer_method,
            get_lifecycle_method,
            get_k_requirement_method,
            remove_sensor_method,
        )
        self._current_contributors = set()

        privatizer_config: LatestPrivatizerConfig = GlobalConfig.config.privatizer_config
        logger.disabled = not privatizer_config.logging

    @override
    async def pre_processing(self):
        """Delete stale sensors, where stale means, the sensor missed a single update."""
        missing_contributors = self._sensors.difference(self._current_contributors)

        for sensor in missing_contributors:
            logger.warning(f"Deleting stale sensor: {sensor}")
            await self.manager_remove_sensor(sensor)
        self._current_contributors = set()

    @override
    async def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> None:
        """Perform sensor evaluation, accept every sensor."""
        logger.debug(f"{self._id}&{self._measurement_type}: Evaluating sensor quality ({unique_sensor_id})")

        sensor_life_cycle: SensorLifeCycleBase = self.get_lifecycle(unique_sensor_id=unique_sensor_id)
        sensor_life_cycle.contributing = True
        return sensor_life_cycle.contributing

    @override
    async def new_value(self, unique_sensor_id: UniqueSensorId, measurement: Measurement) -> None:
        """Process incoming sensor updates."""
        logger.debug(f"{self._id}&{self._measurement_type}: Processing update for ({unique_sensor_id})")

        if not self.sensor_in_shadow_mode(unique_sensor_id) and (value := measurement.value) is not None:
            self._last_value = value

        self._current_contributors.add(unique_sensor_id)

    @override
    async def get_value(self) -> float | None:
        """Generate trixel output value."""
        logger.debug(
            f"""{self._id}&{self._measurement_type}: Getting value for trixel ({self._id}, {self._measurement_type}) \
            with {len(self.sensors)} sensors."""
        )

        # Use the avg. value of all children or the latest one form this sensor if no valid children are present
        child_sum = 0
        child_count = 0
        for child in self._children or []:
            child_privatizer = self.get_privatizer(trixel_id=child)
            if child_privatizer is not None and child_privatizer.value is not None:
                child_count += 1
                child_sum += child_privatizer.value

        return self._last_value if child_count == 0 else (child_sum / child_count)
