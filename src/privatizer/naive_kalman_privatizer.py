"""Naive kalman privatizer, which determines an output using a kalman filter without further considerations."""

from datetime import datetime, timedelta
from typing import Any, Callable, ClassVar

import numpy as np
from filterpy.common import Q_discrete_white_noise
from filterpy.kalman import KalmanFilter
from pydantic import UUID4
from typing_extensions import override

from config_schema import GlobalConfig
from database import get_db
from logging_helper import get_logger
from measurement_station.schema import Measurement
from model import MeasurementTypeEnum
from privatizer import crud
from privatizer.config_schema import NaiveKalmanPrivatizerConfig
from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, UniqueSensorId

logger = get_logger(__name__)


class NaiveKalmanPrivatizer(Privatizer):
    """
    A privatizer which combines measurements using a kalman filter.

    All sensors are marked as contributors immediately.
    A sensor is deemed stale if the number of missed updated exceeds MISSED_UPDATE_THRESHOLD when comparing to the
    sensors average update interval.
    A sensor is deemed stale if last update exceeds the MAX_MEASUREMENT_AGE threshold.
    """

    last_measurement: dict[UniqueSensorId, float | None]
    last_measurement_timestamp: dict[UniqueSensorId, datetime]
    update_interval: dict[UniqueSensorId, timedelta]
    sensor_accuracies: dict[UniqueSensorId, float | None]
    kalman_filter: KalmanFilter
    average_accuracy: float | None = None

    config: ClassVar[NaiveKalmanPrivatizerConfig] = GlobalConfig.config.privatizer_config

    def __init__(
        self,
        trixel_id: int,
        measurement_type: MeasurementTypeEnum,
        get_privatizer_method: Callable[[int, MeasurementTypeEnum, bool], Any],
        get_lifecycle_method: Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Any],
        get_k_requirement_method: Callable[[UniqueSensorId | UUID4], int],
        remove_sensor_method: Callable[[UniqueSensorId], None],
    ):
        """Initialize the native kalman privatizer."""
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
        self.sensor_accuracies = dict()

        self.kalman_filter = KalmanFilter(dim_x=2, dim_z=1)
        self.kalman_filter.x = np.array([[1.0], [0.0]])
        self.kalman_filter.F = np.array([[1.0, 0.0], [0.0, 1.0]])
        self.kalman_filter.H = np.array([[1.0, 0.0]])
        self.kalman_filter.P *= 1000.0
        self.kalman_filter.Q = Q_discrete_white_noise(
            dim=2,
            dt=GlobalConfig.config.trixel_update_frequency,
            var=NaiveKalmanPrivatizer.config.process_std_deviation_per_time_step,
        )

        logger.disabled = not NaiveKalmanPrivatizer.config.logging

    @override
    async def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> bool:
        """Accept every sensor as a contributor."""
        sensor_life_cycle: SensorLifeCycleBase = self.get_lifecycle(unique_sensor_id=unique_sensor_id)
        sensor_life_cycle.contributing = True
        return sensor_life_cycle.contributing

    @override
    async def pre_processing(self):
        """Detect and remove stale sensors."""
        config: NaiveKalmanPrivatizerConfig = NaiveKalmanPrivatizer.config
        sensors_to_remove: set[UniqueSensorId] = set()
        for sensor in self.sensors:
            if sensor not in self.last_measurement:
                continue

            last_timestamp = self.last_measurement_timestamp[sensor]
            time_delta = datetime.now() - last_timestamp
            if (
                sensor in self.update_interval
                and time_delta > self.update_interval[sensor] * config.missed_update_threshold
            ):
                sensors_to_remove.add(sensor)
            elif time_delta > config.max_measurement_age * config.missed_update_threshold:
                sensors_to_remove.add(sensor)

        for sensor in sensors_to_remove:
            logger.debug(f"Removing stale sensor {sensor} from privatizer ({self._id},{self._measurement_type})")
            await self.manager_remove_sensor(sensor)
            await self.remove_sensor(sensor)

    async def add_sensor(self, unique_sensor_id: UniqueSensorId, should_evaluate: bool) -> None:
        """Retrieve sensor details if they are added to this privatizer."""
        async for db in get_db():
            self.sensor_accuracies[unique_sensor_id] = await crud.get_sensor_accuracy(db, unique_sensor_id)
        return await super().add_sensor(unique_sensor_id, should_evaluate)

    async def remove_sensor(self, unique_sensor_id: UniqueSensorId) -> None:
        """Remove sensor related details, if a sensor is removed from this privatizer."""
        await super().remove_sensor(unique_sensor_id)

        if unique_sensor_id in self.last_measurement:
            del self.last_measurement[unique_sensor_id]
        if unique_sensor_id in self.last_measurement_timestamp:
            del self.last_measurement_timestamp[unique_sensor_id]
        if unique_sensor_id in self.update_interval:
            del self.update_interval[unique_sensor_id]
        if unique_sensor_id in self.sensor_accuracies:
            del self.sensor_accuracies[unique_sensor_id]

    @override
    async def new_value(self, unique_sensor_id: UniqueSensorId, measurement: Measurement) -> None:
        """Store and update measurement related information (update interval, time of measurement)."""
        config: NaiveKalmanPrivatizerConfig = NaiveKalmanPrivatizer.config

        self.last_measurement[unique_sensor_id] = measurement.value
        timestamp = (
            measurement.timestamp
            if isinstance(measurement.timestamp, datetime)
            else datetime.fromtimestamp(measurement.timestamp)
        )

        # Skip old measurements
        if datetime.now() - timestamp > config.max_measurement_age:
            # Adding the timestamp will result in the sensors being removed as 'stale'
            self.last_measurement_timestamp[unique_sensor_id] = timestamp
            return

        if unique_sensor_id in self.last_measurement_timestamp:
            update_interval: timedelta = timestamp - self.last_measurement_timestamp[unique_sensor_id]

            if unique_sensor_id in self.update_interval:
                self.update_interval[unique_sensor_id] = self.update_interval[unique_sensor_id] * (
                    1 - config.update_interval_weight
                ) + update_interval * (config.update_interval_weight)
            else:
                self.update_interval[unique_sensor_id] = update_interval

        self.last_measurement_timestamp[unique_sensor_id] = timestamp

    @override
    async def get_value(self) -> float | None:
        """
        Determine the output value using a kalman filter based on local and child contributors.

        Contributions through child trixels are weight in based on the average accuracy of the senors within the child
        trixel (includes sensors and sub-children). If the accuracy is not know for a sensor/trixel, the config default
        value is used.
        The trixel returns the 'unknown'(None) state if there are no contributors within the (sub-)trixel.
        """
        config: NaiveKalmanPrivatizerConfig = NaiveKalmanPrivatizer.config

        valid_measurement: bool = False
        average_accuracy: float | None = None
        contributing_sensor_count: int = 0

        sensor: UniqueSensorId
        for sensor in self.sensors:
            if not self.sensor_in_shadow_mode(sensor):
                measurement_timestamp = self.last_measurement_timestamp.get(sensor, None)
                if (
                    measurement_timestamp is None
                    or datetime.now() - measurement_timestamp > config.max_measurement_age_averaging
                ):
                    continue

                # Non-contributing sensors are filtered out, in case some derived class implements sensor evaluation
                # For the naive kalman privatizer all by itself, this step is not strictly necessary
                sensor_life_cycle: SensorLifeCycleBase | None = self.get_lifecycle(
                    unique_sensor_id=sensor, instantiate=False
                )
                if sensor_life_cycle is None or not sensor_life_cycle.contributing:
                    continue

                measurement = self.last_measurement.get(sensor, None)
                if measurement is not None:
                    valid_measurement = True
                    sensor_accuracy = self.sensor_accuracies[sensor]
                    if sensor_accuracy is None:
                        sensor_accuracy = config.default_sensor_accuracy[self.measurement_type]

                    if average_accuracy is None:
                        average_accuracy = sensor_accuracy
                    else:
                        average_accuracy += sensor_accuracy
                    contributing_sensor_count += 1

                    self.kalman_filter.predict()
                    self.kalman_filter.update(measurement, R=np.array([[sensor_accuracy]]))

        for child in self._children or set():
            child_privatizer = self.get_privatizer(trixel_id=child)

            if child_privatizer is not None and child_privatizer.value is not None:
                child_contributor_count = child_privatizer.get_total_contributing_sensor_count()
                valid_measurement = True
                if child_privatizer.average_accuracy is None:
                    sensor_accuracy = config.default_child_trixel_accuracy[self.measurement_type]
                else:
                    sensor_accuracy = child_privatizer.average_accuracy

                if average_accuracy is None:
                    average_accuracy = sensor_accuracy * child_contributor_count
                else:
                    average_accuracy += sensor_accuracy * child_contributor_count
                contributing_sensor_count += child_contributor_count

                self.kalman_filter.predict()
                self.kalman_filter.update(child_privatizer.value, R=np.array([[sensor_accuracy]]))

        self.average_accuracy = None if average_accuracy is None else average_accuracy / contributing_sensor_count

        if not valid_measurement:
            self.kalman_filter.P = np.array([[100.0, 0.0], [0.0, 100.0]])
            return None

        return self.kalman_filter.x[0][0]
