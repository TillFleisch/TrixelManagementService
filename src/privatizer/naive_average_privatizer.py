"""Naive average privatizer, which determines the average of all contributing sensors without further considerations."""

from datetime import datetime, timedelta
from typing import Any, Callable

from pydantic import UUID4, NonNegativeInt
from typing_extensions import override

from logging_helper import get_logger
from measurement_station.schema import Measurement
from model import MeasurementTypeEnum
from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, UniqueSensorId

logger = get_logger(__name__)

"""The oldest allowed age for incoming measurement and stale measurement station detection"""
MAX_MEASUREMENT_AGE = timedelta(minutes=5)

"""The oldest allowed age of measurements, which used during averaging."""
MAX_MEASUREMENT_AGE_AVERAGING = timedelta(minutes=2.5)

"""Number of allowed missed sensor updates in comparison to the average update interval of the sensor."""
MISSED_UPDATE_THRESHOLD = 2

"""Smoothing weight which is used for new values while determining the average update interval."""
UPDATE_INTERVAL_WEIGHT = 0.1

"""Exponential smoothing factor which is applied to the aggregate local measurements."""
SMOOTH_FACTOR_LOCAL = 0.5

"""Exponential smoothing factor which is applied to the aggregate subtrixel measurements."""
SMOOTH_FACTOR_CHILD_TRIXEL = 1


class NaiveAveragePrivatizer(Privatizer):
    """
    A privatizer which averages the measurements from all sensors and children equally.

    All sensors are marked as contributors immediately.
    A sensor is deemed stale if the number of missed updated exceeds MISSED_UPDATE_THRESHOLD when comparing to the
    sensors average update interval.
    A sensor is deemed stale if last update exceeds the MAX_MEASUREMENT_AGE threshold.
    """

    last_measurement: dict[UniqueSensorId, float | None]
    last_measurement_timestamp: dict[UniqueSensorId, datetime]
    update_interval: dict[UniqueSensorId, timedelta]

    def __init__(
        self,
        trixel_id: int,
        measurement_type: MeasurementTypeEnum,
        get_privatizer_method: Callable[[int, MeasurementTypeEnum, bool], Any],
        get_lifecycle_method: Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Any],
        get_k_requirement_method: Callable[[UniqueSensorId | UUID4], int],
        remove_sensor_method: Callable[[UniqueSensorId], None],
    ):
        """Initialize the native average privatizer."""
        super().__init__(
            trixel_id,
            measurement_type,
            get_privatizer_method,
            get_lifecycle_method,
            get_k_requirement_method,
            remove_sensor_method,
        )
        self.last_measurement = dict()
        self.last_measurement_timestamp = dict()
        self.update_interval = dict()

    @override
    def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> bool:
        """Accept every sensor as a contributor."""
        sensor_life_cycle: SensorLifeCycleBase = self.get_lifecycle(unique_sensor_id=unique_sensor_id)
        sensor_life_cycle.contributing = True
        return sensor_life_cycle.contributing

    @override
    def pre_processing(self):
        """Detect and remove stale sensors."""
        sensors_to_remove: set[UniqueSensorId] = set()
        for sensor in self.sensors:
            if sensor not in self.last_measurement:
                continue

            last_timestamp = self.last_measurement_timestamp[sensor]
            time_delta = datetime.now() - last_timestamp
            if sensor in self.update_interval and time_delta > self.update_interval[sensor] * MISSED_UPDATE_THRESHOLD:
                sensors_to_remove.add(sensor)
            elif time_delta > MAX_MEASUREMENT_AGE * MISSED_UPDATE_THRESHOLD:
                sensors_to_remove.add(sensor)

        for sensor in sensors_to_remove:
            logger.debug(f"Removing stale sensor {sensor} from privatizer ({self._id},{self._measurement_type})")
            self.manager_remove_sensor(sensor)

    def remove_sensor(self, unique_sensor_id: UniqueSensorId) -> None:
        """Remove sensor related details, if a sensor is removed from this privatizer."""
        super().remove_sensor(unique_sensor_id)

        if unique_sensor_id in self.last_measurement:
            del self.last_measurement[unique_sensor_id]
        if unique_sensor_id in self.last_measurement_timestamp:
            del self.last_measurement_timestamp[unique_sensor_id]
        if unique_sensor_id in self.update_interval:
            del self.update_interval[unique_sensor_id]

    @override
    def new_value(self, unique_sensor_id: UniqueSensorId, measurement: Measurement) -> None:
        """Store and update measurement related information (update interval, time of measurement)."""
        self.last_measurement[unique_sensor_id] = measurement.value
        timestamp = (
            measurement.timestamp
            if isinstance(measurement.timestamp, datetime)
            else datetime.fromtimestamp(measurement.timestamp)
        )

        # Skip old measurements
        if datetime.now() - timestamp > MAX_MEASUREMENT_AGE:
            # Adding the timestamp will result in the sensors being removed as 'stale'
            self.last_measurement_timestamp[unique_sensor_id] = timestamp
            return

        if unique_sensor_id in self.last_measurement_timestamp:
            update_interval: timedelta = timestamp - self.last_measurement_timestamp[unique_sensor_id]

            if unique_sensor_id in self.update_interval:
                self.update_interval[unique_sensor_id] = self.update_interval[unique_sensor_id] * (
                    1 - UPDATE_INTERVAL_WEIGHT
                ) + update_interval * (UPDATE_INTERVAL_WEIGHT)
            else:
                self.update_interval[unique_sensor_id] = update_interval

        self.last_measurement_timestamp[unique_sensor_id] = timestamp

    def filter_local_sum(self, value: float | None, contributor_count: NonNegativeInt) -> float | None:
        """Filter operation which is applied to the sum of local measurements before combination with child values."""
        return value

    def filter_child_sum(self, value: float | None, contributor_count: NonNegativeInt) -> float | None:
        """Filter operation which is applied to the sum of child measurements before combination with local values."""
        return value

    @override
    def get_value(self) -> float | None:
        """
        Determine the average output value based on local and child contributors.

        Contributions through child trixels are weight in based on the number of sensors within them.
        The trixel returns the 'unknown'(None) state if there are no contributors within the (sub-)trixel.
        """
        local_sum: float | None = None
        total_local_contributor_count: int = 0
        total_child_contributor_count: int = 0

        for sensor in self.sensors:
            if not self.sensor_in_shadow_mode(sensor):
                # The contributing property of a sensor must not be checked, as all sensors always contribute
                measurement_timestamp = self.last_measurement_timestamp.get(sensor, None)
                if datetime.now() - measurement_timestamp > MAX_MEASUREMENT_AGE_AVERAGING:
                    continue

                measurement = self.last_measurement.get(sensor, None)
                if measurement is not None:
                    local_sum = 0 if local_sum is None else local_sum
                    local_sum += measurement
                    total_local_contributor_count += 1

        child_sum: float | None = None
        for child in self._children or set():
            child_privatizer = self.get_privatizer(trixel_id=child)

            if child_privatizer is not None and child_privatizer.value is not None:
                child_contributor_count = child_privatizer.get_total_contributing_sensor_count()
                child_sum = 0 if child_sum is None else child_sum
                child_sum += child_privatizer.value * child_contributor_count
                total_child_contributor_count += child_contributor_count

        if local_sum is None and child_sum is None:
            return None

        local_sum = self.filter_local_sum(local_sum, total_local_contributor_count)
        child_sum = self.filter_child_sum(child_sum, total_child_contributor_count)

        local_sum = 0 if local_sum is None else local_sum
        child_sum = 0 if child_sum is None else child_sum

        return (local_sum + child_sum) / (total_local_contributor_count + total_child_contributor_count)


class NaiveSmoothingAveragePrivatizer(NaiveAveragePrivatizer):
    """Like NAP, additionally applies exponential smoothing separately to local and subtrixel measurements."""

    last_value: float | None = None
    last_contributor_count: NonNegativeInt | None = None

    last_value_child: float | None = None
    last_contributor_count_child: NonNegativeInt | None = None

    @override
    def filter_local_sum(self, value: float | None, contributor_count: NonNegativeInt) -> float | None:
        """Apply exponential smoothing to local measurements."""
        if SMOOTH_FACTOR_LOCAL == 1:
            return value

        if value is None:
            self.last_value = None
            self.last_contributor_count = None
            return None
        elif self.last_value is None:
            self.last_value = value
            self.last_contributor_count = contributor_count
            return value
        else:
            # Compensate for sum size when the number of contributors changes
            if contributor_count != self.last_contributor_count and self.last_contributor_count > 0:
                self.last_value = (self.last_value / self.last_contributor_count) * contributor_count

            value = self.last_value * (1 - SMOOTH_FACTOR_LOCAL) + value * SMOOTH_FACTOR_LOCAL
            self.last_value = value
            self.last_contributor_count = contributor_count
            return value

    @override
    def filter_child_sum(self, value: float | None, contributor_count: NonNegativeInt) -> float | None:
        """Apply exponential smoothing to child trixel measurements."""
        if SMOOTH_FACTOR_CHILD_TRIXEL == 1:
            return value

        if value is None:
            self.last_value_child = None
            self.last_contributor_count_child = None
            return None
        elif self.last_value_child is None:
            self.last_value_child = value
            self.last_contributor_count_child = contributor_count
            return value
        else:
            # Compensate for sum size when the number of contributors changes
            if contributor_count != self.last_contributor_count_child and self.last_contributor_count_child > 0:
                self.last_value_child = (self.last_value_child / self.last_contributor_count_child) * contributor_count

            value = self.last_value_child * (1 - SMOOTH_FACTOR_CHILD_TRIXEL) + value * SMOOTH_FACTOR_CHILD_TRIXEL
            self.last_value_child = value
            self.last_contributor_count_child = contributor_count
            return value
