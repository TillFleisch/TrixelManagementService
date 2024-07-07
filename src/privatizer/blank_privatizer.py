"""Privatizer for test cases which does nothing."""

from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, UniqueSensorId


class BlankPrivatizer(Privatizer):
    """
    A blank privatizer which does not generate any output but accepts any sensor.

    It could be used for testing purposes where a privatizer is not required.
    """

    def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> bool:
        """Accept every sensor as a contributor."""
        sensor_life_cycle: SensorLifeCycleBase = self.get_lifecycle(unique_sensor_id=unique_sensor_id)
        sensor_life_cycle.contributing = True
        return sensor_life_cycle.contributing

    def get_value(self) -> float | None:
        """Return 'unknown' state."""
        return None
