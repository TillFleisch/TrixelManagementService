"""Privatizer, which takes measurements of a measurement type within a trixel and determines an output value."""

from typing import Any, Callable, ClassVar, Coroutine

from pydantic import UUID4, NonNegativeInt, PositiveInt
from pynyhtm import HTM
from typing_extensions import Self, final

from config_schema import GlobalConfig
from logging_helper import get_logger
from measurement_station.schema import Measurement
from model import MeasurementTypeEnum
from privatizer.schema import SensorLifeCycleBase, TrixelUpdate, UniqueSensorId
from schema import TrixelID

logger = get_logger(__name__)


class Privatizer:
    """
    Interface/Base class for different privatizer implementations.

    See `LatestPrivatizer` for a sample implementation.

    Each trixel has it's 'own' privatizers for each measurement type supported by the system.
    A privatizer takes input values from sensors and generates a output value for the trixel while determining which
    sensors are good enough to contribute to the system which ensures k-anonymity.

    The `measurement_type` property can be used to implement different behaviors or (pre-)processing for different
    measurement types. The values of sub-trixels or neighbors can be referenced via the `get_privatizer` method and
    their trixel ids which are attributes of the privatizer.
    Note that during evaluation, when `get_value` is called, all sub-trixels have already been evaluated. This is not
    the case for neighboring or parent trixels, as the evaluation happens in a bottom up fashion for trixel levels.
    Therefore, using the value property of sub-privatizers is acceptable.

    The `get_privatizer` method can also be used to access custom properties of related privatizers.
    It is recommended for privatizers to implement a sensor life-cycle schema, in which the quality of sensors is
    evaluated over time. Only reliable and trustworthy sensors should set the `contributing` property on the sensors
    `SensorLifeCycleBase` object.
    This ensures that the k-anonymity requirement is met for all sensors.

    A privatizer MUST evaluate the quality (and set the `contributing` flag) when a sensor is actively contributing
    or when a sensor is not actively contributing to any privatizer. This condition is accessible within the
    `evaluation_map` of privatizers.
    Privatizers within different level should generate the same `contributing` state for a sensor to prevent them
    from hopping between two levels.

    A privatizer MUST remove old sensor which have stopped contributing from the manager using the
    `manager_remove_sensor` method.
    """

    __get_privatizer_method: ClassVar[Callable[[TrixelID, MeasurementTypeEnum, bool], Self | None]]
    __get_lifecycle_method: ClassVar[Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Self | None]]
    __get_k_requirement_method: ClassVar[Callable[[UniqueSensorId | UUID4], PositiveInt]]
    __remove_sensor: ClassVar[Callable[[UniqueSensorId], Coroutine[Any, Any, None]]]

    _id: TrixelID
    _measurement_type: MeasurementTypeEnum
    _children: set[TrixelID] | None = None
    _neighbors: set[TrixelID]
    _parent: TrixelID | None = None
    _parent_privatizer: Self | None = None
    _level: NonNegativeInt

    # Set of sensors which are registered, but not necessarily contributing to this privatizer
    _sensors = set[UniqueSensorId]

    # Describes which sensors are actively/shadow contributing to this privatizer
    _shadow_map: dict[UniqueSensorId, bool]

    # Contains flags which describe if a privatizer should evaluate a sensor
    __evaluation_map: dict[UniqueSensorId, bool]

    __contributing_ms_count: NonNegativeInt = 0
    __contributing_sensor_count: NonNegativeInt = 0

    # The measurement station count used at the TLS, which is visible to clients
    __tls_ms_count: NonNegativeInt | None = None
    __last_update: TrixelUpdate | None = None

    __stale: bool = False

    @property
    def value(self) -> float | None:
        """The last calculated (current) measurement value for trixel&type managed by this privatizer."""
        return None if self.__last_update is None else self.__last_update.value

    @property
    def measurement_type(self) -> MeasurementTypeEnum:
        """The measurement type used by this privatizer."""
        return self._measurement_type

    @property
    def sensors(self) -> set[UniqueSensorId]:
        """Sensors which are utilized by this privatizer."""
        return self._sensors

    @property
    def stale(self) -> bool:
        """Get the stale property of this privatizer, which is True when the privatizer does not serve any purpose."""
        return self.__stale

    @property
    def contributing_measurement_station_count(self) -> NonNegativeInt:
        """
        Get the number of contributing measurement stations within the trixel&type of this privatizer.

        This values does not include measurement stations within sub-trixels.
        """
        return self.__contributing_ms_count

    @property
    def contributing_sensor_count(self) -> NonNegativeInt:
        """
        Get the number of sensors within the trixel&type of this privatizer.

        This value does not include sensors within sub-trixels.
        """
        return self.__contributing_sensor_count

    def __init__(
        self,
        trixel_id: TrixelID,
        measurement_type: MeasurementTypeEnum,
        get_privatizer_method: Callable[[TrixelID, MeasurementTypeEnum, bool], Any],
        get_lifecycle_method: Callable[[UniqueSensorId, bool, SensorLifeCycleBase | None], Any],
        get_k_requirement_method: Callable[[UniqueSensorId | UUID4], PositiveInt],
        remove_sensor_method: Callable[[UniqueSensorId], Coroutine[Any, Any, None]],
    ):
        """
        Initialize this privatizer to work for the given trixel&type.

        :param trixel_id: The ID of the trixel for which this privatizer works
        :param measurement_type: The measurement type of this privatizer
        :param get_privatizer_method: a reference to the `get_privatizer` method of the privatizer manager
        :param get_lifecycle_method: a reference to the `get_lifecycle` method of the privatizer manager
        :param remove_sensor_method: a reference to the `remove_sensor_method` of the privatizer manager
        """
        Privatizer.__get_privatizer_method = get_privatizer_method
        Privatizer.__get_lifecycle_method = get_lifecycle_method
        Privatizer.__get_k_requirement_method = get_k_requirement_method
        Privatizer.__remove_sensor = remove_sensor_method

        self._id = trixel_id
        self._measurement_type = measurement_type
        self._level = HTM.get_level(trixel_id)
        self._children = set(HTM.children(trixel_id)) if self._level < GlobalConfig.config.max_level else None
        self._neighbors = set(HTM.neighbors(trixel_id))
        self._parent = HTM.parent(trixel_id) if self._level > 0 else None
        self._parent_privatizer = (
            None if self._parent is None else self.get_privatizer(trixel_id=self._parent, instantiate=True)
        )

        self._sensors = set()
        self._shadow_map = dict()
        self.__evaluation_map = dict()

    @final
    def get_privatizer(
        self, trixel_id: TrixelID, measurement_type: MeasurementTypeEnum | None = None, instantiate: bool = False
    ) -> Self | None:
        """
        Wrap the `get_privatizer` method of the manager in charge of this privatizer.

        This method can be used to retrieve related privatizers.

        :trixel_id: The trixel for which the privatizer is retrieved
        :measurement_type: the measurement type of the privatizer which should be retrieved, if None the type of this
        privatizer is used
        :param instantiate: indicates if a new instance should be instantiated if not already present
        :returns: reference to the requested privatizer
        """
        return Privatizer.__get_privatizer_method(
            trixel_id, self._measurement_type if measurement_type is None else measurement_type, instantiate
        )

    @final
    @classmethod
    def get_lifecycle(
        cls, unique_sensor_id: UniqueSensorId, instantiate: bool = True, lifecycle: SensorLifeCycleBase | None = None
    ) -> SensorLifeCycleBase | None:
        """
        Wrap the `get_lifecycle` method of the manager in charge of this privatizer.

        :param unique_sensor_id: The sensor for which the lifecycle object is retrieved
        :param instantiate: indicates if a new SensorLifeCycleBase class should be instantiated
        :param lifecycle: custom lifecycle object which used if no object is present for the given sensor
        :return: the life cycle object associated with the sensors
        """
        return cls.__get_lifecycle_method(unique_sensor_id, instantiate, lifecycle)

    @final
    @classmethod
    def get_k_requirement(cls, id_: UniqueSensorId | UUID4) -> PositiveInt:
        """
        Wrap the `get_k_requirement` method of the manager in charge of this privatizer.

        :param id_: Unique sensor id or the ID of the measurement station to which the sensor belongs
        :returns: k requirement which must be met for the sensor
        """
        return cls.__get_k_requirement_method(id_)

    @final
    @classmethod
    async def manager_remove_sensor(cls, unique_sensor_id: UniqueSensorId) -> None:
        """
        Wrap the `remove_sensor` method of the manager in charge of this privatizer.

        :param unique_sensor_id: The sensor which should be removed from the manager
        """
        await cls.__remove_sensor(unique_sensor_id)

    @final
    def set_tls_ms_count(self, value: NonNegativeInt) -> None:
        """
        Set the measurement station count reference on this privatizer, to the value known at the TLS.

        Note: should only be invoked by the privacy manager
        :param: the updated value
        """
        self.__tls_ms_count = value

    @final
    def get_total_contributing_ms_count(self) -> NonNegativeInt:
        """
        Get the number of measurement stations, which are contributing to this trixel and type.

        Note that not all sensors must contribute to a trixel.
        A sensor can be in a trixel (and potentially contribute partially) for instance, if the quality is insufficient.
        The k anonymity guaranteeing property is checked using the "verified" contributor count, which is returned by
        this method.

        :return: number of valid measurement stations within the trixel and measurement type managed by this privatizer.
        This value can be used for k-anonymity checking.
        """
        sub_trixel_count = 0
        for trixel_id in self._children:
            child_privatizer: Privatizer | None = self.get_privatizer(trixel_id)
            if child_privatizer is not None:
                sub_trixel_count += child_privatizer.get_total_contributing_ms_count()
        # TODO: add caching to avoid recursive calls

        return self.__contributing_ms_count + sub_trixel_count

    @final
    def get_total_contributing_sensor_count(self) -> NonNegativeInt:
        """
        Get the number of sensors, which are contributing to this trixel and type.

        Like `get_total_contributing_ms_count` but for sensors instead o measurement stations.

        :return: number of valid sensors within the trixel and measurement type managed by this privatizer.
        """
        sub_trixel_count = 0
        for trixel_id in self._children:
            child_privatizer: Privatizer | None = self.get_privatizer(trixel_id)
            if child_privatizer is not None:
                sub_trixel_count += child_privatizer.get_total_contributing_sensor_count()
        # TODO: add caching to avoid recursive calls

        return self.__contributing_sensor_count + sub_trixel_count

    async def remove_sensor(self, unique_sensor_id: UniqueSensorId) -> None:
        """
        Remove a sensor for this privatizer.

        Called when the manager asserts that a sensor is not contributing to the trixel&type managed by this privatizer.
        This can be the case if the sensors moves to a different trixel or if it disappears.

        Note: The actual contribution worthiness of the sensor must be evaluated by the privatizer. This method MUST NOT
        be called to remove a stale sensor (see `manager_remove_sensor`).

        When overridden, super method must be called!
        """
        if unique_sensor_id in self._sensors:
            self._sensors.remove(unique_sensor_id)
        if unique_sensor_id in self._shadow_map:
            del self._shadow_map[unique_sensor_id]

    async def add_sensor(self, unique_sensor_id: UniqueSensorId, should_evaluate: bool) -> None:
        """
        Add a sensor to this privatizer.

        This method is called by the privatizer manager when a sensors starts contributing to the trixel&type managed
        by this privatizer. This method is called before the first call to `new_value()`.
        Note: The actual contribution worthiness of the sensor must be evaluated by the privatizer

        When overridden, super method must be called!

        :param unique_sensor_id: The sensor which is added to this privatizer
        :param should_evaluate: If this privatizer should evaluate this sensor
        """
        self._sensors.add(unique_sensor_id)
        if unique_sensor_id not in self._shadow_map:
            self._shadow_map[unique_sensor_id] = True
        self.__evaluation_map[unique_sensor_id] = should_evaluate

    async def new_value(self, unique_sensor_id: UniqueSensorId, measurement: Measurement) -> None:
        """
        Process incoming sensor values every time a new sensor value is published to this privatizer.

        Can be overridden, to retrieve incoming measurement which can be used to determine the trixels value.
        If this method is not overridden, values must be retrieved through other means, i.e. by reading sensor history
        from the DB.

        Important implementation Note:
        To determine the output value of the privatizer, only sensors where `sensor_in_shadow_mode()` is false MUST be
        used. Otherwise the k-requirement cannot be satisfied.
        """
        pass

    async def get_value(self) -> float | None:
        """
        Retrieve the current value for the trixel&type managed by this privatizer.

        This method is periodically fetched to determine the state of the trixel.
        Values for sub-trixels can be retrieved via their trixel IDs and the `get_privatizer` method.
        The output-value can be determined based on calls to `new_value` or by reading from the DB.

        Important implementation Note:
        To determine the output value of the privatizer, only sensors where `sensor_in_shadow_mode()` is false MUST be
        used. Otherwise the k-requirement cannot be satisfied.

        :returns: measurement value for the trixel&type or None if unavailable
        """
        raise NotImplementedError()

    async def evaluate_sensor_quality(self, unique_sensor_id: UniqueSensorId) -> bool:
        """
        Determine the quality of a sensor and other properties.

        Set the `contributing` flag for sensors to indicate that they are valid contributors.
        MUST update the lifecycle object associate with the sensor.

        :returns: True if the contributing flag is set for the sensor, false otherwise
        """
        raise NotImplementedError()

    async def pre_processing(self):
        """
        Pre-processing method which is invoked before sensor evaluation and `get_value`.

        Either `pre_processing` or `post_processing` should remove stale sensor using `manager_remove_sensor` to
        guarantee the k-requirement can be satisfied for all sensors.
        """
        pass

    async def post_processing(self):
        """
        Post-processing which is invoked after all sensors have been evaluated and once `get_value` has been called.

        Either `pre_processing` or `post_processing` should remove stale sensor using `manager_remove_sensor` to
        guarantee the k-requirement can be satisfied for all sensors.
        """
        pass

    async def can_subdivide(self) -> bool:
        """
        Determine if this privatizer is allowed to subdivide further.

        Some privatizer implementation may use this to prevent sub-division in case a privatizers output or other
        properties are required (to determine sensor quality), which are only determined after some time.

        :returns: True if the privatizer is allowed to subdivide, False otherwise
        """
        return True

    def sensor_in_shadow_mode(self, unique_sensor_id: UniqueSensorId):
        """
        Get the shadow mode state of a sensor within this privatizer.

        :param unique_sensor_id: the id of the sensor for which the shadow state is returned
        :return: True if the sensor is contributing in shadow mode, False otherwise
        """
        if unique_sensor_id in self._shadow_map:
            return self._shadow_map[unique_sensor_id]
        return True

    # TODO: method which gets a standardized "quality" statement about a sensor

    @final
    async def process(self) -> tuple[TrixelUpdate, bool]:
        """
        Process incoming data for the trixel and measurement type to determine the output value of the trixel.

        Assess the quality of sensors participating in the trixel managed by this privatizer.
        Based on the `contributing` property of sensors the number of valid sensors within the trixel is determined.
        This information is synchronized with the TLS.

        Sensors which have been added to this privatizer are by default 'shadow-contributing', until this privatizer
        asserts that the k-requirement for the sensor/station can be satisfied.
        When this happens, the sensors is removed from the parent privatizer. The successful contribution within this
        privatizer will eventually lead to the client choosing a different trixel, yielding the original situation.

        Shadow contributions are disabled, once enough sensors are present within this privatizer which can meet the k-
        requirement.

        Based on the (not-shadow-)`contributing` sensors, the output value for the trixel&type represented by this
        privatizer is determined.

        This method is called periodically to evaluate sensors and determine the output value.
        This method is called for all child privatizers before this privatizer is called.

        :return: Updated information about the output state of this trixel and weather the TLS state should be updated
        """
        await self.pre_processing()

        # Evaluate the quality of all sensors within this trixel
        contributing_sensor_set: set[UniqueSensorId] = set()
        for sensor in frozenset(self._sensors):
            if self.__evaluation_map[sensor]:
                # Perform evaluation if required
                if await self.evaluate_sensor_quality(sensor):
                    contributing_sensor_set.add(sensor)
            else:
                # Get contribution state from lifecycle object which is updated by a different (parent) privatizer
                lifecycle: SensorLifeCycleBase | None = self.get_lifecycle(sensor, instantiate=False)
                if lifecycle is not None and lifecycle.contributing:
                    contributing_sensor_set.add(sensor)

        # Determine how many sensor (including shadow sensors) can contribute to this trixel
        shadow_contributing_ms: set[UUID4] = set()
        for sensor in contributing_sensor_set:
            shadow_contributing_ms.add(sensor.ms_uuid)

        child_ms_count = self.get_total_contributing_ms_count() - self.__contributing_ms_count

        if await self.can_subdivide():
            # Map k-requirements and how many contributors there are to each k-level
            shadow_k_satisfiers: dict[int, int] = dict()
            for ms_uuid in shadow_contributing_ms:
                k = self.get_k_requirement(ms_uuid)
                shadow_k_satisfiers.setdefault(k, 0)
                shadow_k_satisfiers[k] += 1

            # add k-over-satisfiers to lower k-levels (sensor which requires k=2 also counts towards a k=3 requirement)
            for k in shadow_k_satisfiers.keys():
                for other_k in shadow_k_satisfiers.keys():
                    if k > other_k:
                        shadow_k_satisfiers[k] += shadow_k_satisfiers[other_k]

            # Determine highest k which can be achieved when using shadow contributions
            shadow_max_k = 0
            for k, satisfier_count in shadow_k_satisfiers.items():
                # Child contributions counts are included as those must already be k-satisfied
                if (satisfier_count + child_ms_count) >= k and k >= shadow_max_k:
                    shadow_max_k = k

            # Unlock sensors from shadow contributing if their k-requirement can be satisfied
            for sensor in frozenset(self._sensors):
                k = self.get_k_requirement(sensor)
                if k <= shadow_max_k:
                    self._shadow_map[sensor] = False

                    if self._parent_privatizer is not None:
                        await self._parent_privatizer.remove_sensor(sensor)
                else:
                    self._shadow_map[sensor] = True

        contributing_ms: set[UUID4] = set()
        contributing_sensor_count = 0
        sensor: UniqueSensorId
        for sensor in contributing_sensor_set:
            if sensor in self._shadow_map and not self._shadow_map[sensor]:
                # Count real contributions only if the sensor is not in shadow mode
                contributing_ms.add(sensor.ms_uuid)
                contributing_sensor_count += 1

        self.__contributing_ms_count = len(contributing_ms)

        new_measurement_station_count = self.__contributing_ms_count + child_ms_count
        self.__stale = False if new_measurement_station_count > 0 or len(self._sensors) > 0 else True

        self.__contributing_sensor_count = contributing_sensor_count
        new_sensor_count = self.get_total_contributing_sensor_count()

        update_tls: bool = False
        if new_measurement_station_count != self.__tls_ms_count:
            update_tls = True

        new_value = await self.get_value()

        changed: bool = False
        if self.__last_update is not None and (
            self.__last_update.value != new_value
            or self.__last_update.measurement_station_count != new_measurement_station_count
            or self.__last_update.sensor_count != new_sensor_count
        ):
            changed = True

        update = TrixelUpdate(
            changed=changed,
            value=new_value,
            measurement_station_count=new_measurement_station_count,
            sensor_count=new_sensor_count,
        )
        self.__last_update = update

        await self.post_processing()
        return (update, update_tls)
