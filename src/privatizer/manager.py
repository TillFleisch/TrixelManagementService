"""Management class which coordinates and organizes updates to trixels and privatizers."""

import asyncio
from typing import ClassVar, Type

from pydantic import UUID4, NonNegativeInt, PositiveInt
from pynyhtm import HTM
from trixellookupclient.models import TrixelMapUpdate

from config_schema import GlobalConfig
from exception import TLSError
from logging_helper import get_logger
from measurement_station.schema import BatchUpdate, Measurement, TrixelLevelChange
from model import MeasurementTypeEnum
from privatizer.privatizer import Privatizer
from privatizer.schema import SensorLifeCycleBase, TrixelUpdate, UniqueSensorId
from schema import TrixelID
from tls_manager import TLSManager

logger = get_logger(__name__)
MAX_LEVEL = 20
UPDATE_FREQUENCY = GlobalConfig.config.trixel_update_frequency


class PrivacyManager:
    """
    Manages the privatizers for trixels which are in use and their parents, as well as sensors and their life cycles.

    When a value is submitted from a sensor, the target trixel is usually one level below what it considers k-anonymity
    guaranteeing (according to the trixel map from the TLS).
    This manager contributes the value to the target trixel. If the sensor cannot contribute in this trixel (because it
    is of bad quality or because it's k-requirement cannot be met), the manager will also contribute the measurement to
    the parent trixel (the trixel intended by the client). A contribution to the parent does also only happen if the
    k-requirement can be satisfied. If the sensor cannot contribute to the parent, nor the child, the client is advised
    to re-negotiate a new target trixel, which meets their k-requirement.

    To determine if the k-requirement can be satisfied for a sensors, sensors are also 'shadow' contributing to their
    trixels.

    See `contribute` for more details.
    """

    # The lifecycle reference object for each sensor. These can persist through privatizer changes, when a sensor
    # changes it's target trixel
    _life_cycles: dict[UniqueSensorId, SensorLifeCycleBase]

    # The type of privatizer which used used by this manager
    _privatizer_class: Type[Privatizer]

    # A dictionary containing the responsible privatizer by type and trixel id
    _privatizers = dict[MeasurementTypeEnum, dict[TrixelID, Privatizer]]

    # Describes which sensors are contributing to which trixels&type
    _sensor_map: dict[UniqueSensorId, Privatizer]

    # dictionary which holds a set of known (active in any type) trixels per level
    _level_lookup: dict[NonNegativeInt, set[TrixelID]]

    # A reference to the TLSManager which is used by this TMS
    _tls_manager: ClassVar[TLSManager]

    # LUT which contains the k requirement for different measurement stations.
    _k_map: dict[UUID4, int]
    # TODO: should also be updated if the client changes the value (via endpoint)

    def __init__(self, tls_manager: TLSManager, privatizer_class: Type[Privatizer]):
        """Initialize the Privacy manager with no privatizers and sensors."""
        PrivacyManager._tls_manager = tls_manager
        self._privatizer_class = privatizer_class
        self._life_cycles = dict()
        self._sensor_map = dict()
        self._level_lookup = dict()
        self._k_map = dict()

        self._privatizers = dict()
        for type_ in MeasurementTypeEnum:
            self._privatizers.setdefault(type_, dict())

    def get_privatizer(
        self, trixel_id: TrixelID, measurement_type: MeasurementTypeEnum, instantiate: bool = False
    ) -> Privatizer:
        """
        Get the privatizer responsible for a single trixel&type.

        :trixel_id: The trixel for which the privatizer is retrieved
        :measurement_type: the measurement type of the privatizer which should be retrieved
        :param instantiate: indicates if a new instance should be instantiated if not already present
        :returns: reference to the requested privatizer
        """
        privatizers = self._privatizers[measurement_type]
        if trixel_id not in privatizers and instantiate:

            self._level_lookup.setdefault(HTM.get_level(trixel_id), set()).add(trixel_id)
            new_privatizer = self._privatizer_class(
                trixel_id=trixel_id,
                measurement_type=measurement_type,
                get_privatizer_method=self.get_privatizer,
                get_lifecycle_method=self.get_lifecycle,
                get_k_requirement_method=self.get_k_requirement,
                remove_sensor_method=self.remove_sensor,
            )
            privatizers[trixel_id] = new_privatizer

        return privatizers.get(trixel_id, None)

    def get_lifecycle(
        self, unique_sensor_id: UniqueSensorId, instantiate: bool = True, lifecycle: SensorLifeCycleBase | None = None
    ) -> SensorLifeCycleBase:
        """
        Get the lifecycle object for a unique sensor.

        :param unique_sensor_id: The sensor for which the lifecycle object is retrieved
        :param instantiate: indicates if a new SensorLifeCycleBase class should be instantiated
        :param lifecycle: custom lifecycle object which used if no object is present for the given sensor
        :return: the life cycle object associated with the sensors
        """
        if unique_sensor_id not in self._life_cycles and instantiate:
            self._life_cycles[unique_sensor_id] = lifecycle if lifecycle is not None else SensorLifeCycleBase()
        return self._life_cycles.get(unique_sensor_id, None)

    def get_k_requirement(self, id_: UniqueSensorId | UUID4) -> PositiveInt:
        """
        Get the k requirement for a sensor.

        :param id_: Unique sensor id or the ID of the measurement station to which the sensor belongs
        :returns: k requirement which must be met for the sensor
        """
        if isinstance(id_, UniqueSensorId):
            return self._k_map.get(id_.ms_uuid, None)
        else:
            return self._k_map.get(id_, None)

    def remove_sensor(self, unique_sensor_id: UniqueSensorId):
        """
        Remove a sensor from all privatizers in which they contribute.

        Should be called by privatizers when a sensor has gone missing.
        Does not consider whether a sensor is actively or shadow contributing.
        Removes from the target privatizer and it's parent.

        :param unique_sensor_id: The ID of the sensor which should be removed
        """
        if existing_privatizer := self._sensor_map[unique_sensor_id]:
            existing_privatizer.remove_sensor(unique_sensor_id)
            if existing_parent_privatizer := existing_privatizer._parent_privatizer:
                existing_parent_privatizer.remove_sensor(unique_sensor_id)
            del self._sensor_map[unique_sensor_id]

    def contribute(
        self,
        sub_trixel_id: TrixelID,
        unique_sensor_id: UniqueSensorId,
        measurement: Measurement,
        measurement_type: MeasurementTypeEnum,
        k_requirement: int,
    ) -> TrixelLevelChange:
        """
        Process a single contribution provided by a sensor.

        Decides to which privatizers a sensor contributes.

        A sensors should always use a the trixel right blow the one which satisfies it's k-requirement for
        `sub_trixel_id`.
        A sensors is usually contributing to the parent of the target trixel. If it does, it is also
        'shadow-contributing' to the child trixel. This is done to determine when a child-trixel can be populated and to
        determine when clients should start contributing to a new trixel id.

        By default, a sensors is always 'shadow-contributing' to a privatizer.
        Based on the number of contribution within the privatizers (and their k-requirements), the privatizer will allow
        sensors to make real contributions which count towards the sensors(/measurement station) count within a trixel.
        If this happens, the sensor is removed from the parent trixel, and it does not perform any shadow-contributions.
        The sensor will remain within the child-privatizer until the client decides to change the target trixel id.

        Within the manager sensors can have the following states:

        (1) If the sensor is actively contribution to the child, no 'shadow-contributions' are made

        (2) If the sensor is actively contributing to the parent, 'shadow-contribution' are made to the child-trixel.

        (3) If the sensors is not actively contributing to the parent and not to the child in any form (since it's k-
            requirement is not met), it will shadow-contribute to the parent. The client is also recommended to re-
            negotiate the target trixel-id so that (2) can be used. At the root level this is not possible and sensors
            will remain shadow-contributing to the parent (which is a root trixel) until it has been populated to meet
            the k-requirement.

        Most of the time (2) should be the case, as this is the state in which the child cannot be populated, but it
        must be maintained in a sort of shadow mode to know when to start populating it.

        A privatizer MUST evaluate the quality (and set the `contributing` flag) when a sensor is actively contributing
        or when a sensor is not actively contributing to any privatizer. This condition is accessible within the
        `evaluation_map` of privatizers.
        Privatizers within different level should generate the same `contributing` state for a sensor to prevent them
        from hopping between two levels.

        Within privatizers, the `contributing` flag of sensors is used to determine which k-requirement can be met by a
        privatizer. Subsequently, this also impacts the dynamic distribution of sensors within trixels.

        :param sub_trixel_id: The trixel one level below the one that satisfies the sensors k-anonymity requirement
        :param unique_sensor_id: The id of sensor which contributes
        :param measurement: the new measurement
        :param measurement_type: the measurement type to which a contribution is made
        :param k_requirement: the k-requirement which must be met for the contributing sensors
        :returns: recommended level direction change for the client
        """
        target_level = HTM.get_level(sub_trixel_id)
        if target_level == 0:
            raise ValueError("TMS does not accept contribution to the root level")
        elif target_level >= MAX_LEVEL:
            raise ValueError(f"TMS does not accept contributions above level {MAX_LEVEL}")

        child_privatizer: Privatizer = self.get_privatizer(
            trixel_id=sub_trixel_id, measurement_type=measurement_type, instantiate=True
        )
        parent_privatizer: Privatizer | None = self.get_privatizer(
            trixel_id=child_privatizer._parent, measurement_type=measurement_type, instantiate=True
        )

        # Remove sensor from old privatizer if the sensor has changed it's target trixel
        first_contribution: bool = False
        if unique_sensor_id in self._sensor_map:
            existing_privatizer = self._sensor_map[unique_sensor_id]

            if existing_privatizer._id != sub_trixel_id:
                self.remove_sensor(unique_sensor_id)
        else:
            first_contribution = True
        self._sensor_map[unique_sensor_id] = child_privatizer

        contribute_to_child: bool = child_privatizer.get_total_contributing_ms_count() >= k_requirement
        contribute_to_parent: bool = parent_privatizer.get_total_contributing_ms_count() >= k_requirement

        shadow_contributing_to_child: bool = child_privatizer.sensor_in_shadow_mode(unique_sensor_id=unique_sensor_id)
        shadow_contributing_to_parent: bool = parent_privatizer.sensor_in_shadow_mode(unique_sensor_id=unique_sensor_id)
        is_only_shadow_contributing = shadow_contributing_to_child and shadow_contributing_to_parent
        # A shadow contribution to the parent should really only happen if there is no ancestor trixel which can satisfy
        # the k-requirement. In that case the 'parent' will be the first one include sensors with the k-requirement

        # Suppress contribution, if already performing valid contribution to child trixel
        contribute_to_parent = contribute_to_parent and not contribute_to_child

        if (contribute_to_child and not shadow_contributing_to_child) or (
            shadow_contributing_to_child and not shadow_contributing_to_parent
        ):
            # Submit measurement to child privatizer (usually a shadow contribution, except when the sensor has not
            # re-negotiated a new trixel-id, in that case the contribution is "proxied" to the child)
            should_evaluate = not shadow_contributing_to_child or is_only_shadow_contributing
            child_privatizer.add_sensor(unique_sensor_id=unique_sensor_id, should_evaluate=should_evaluate)
            child_privatizer.new_value(unique_sensor_id=unique_sensor_id, measurement=measurement)
        else:
            child_privatizer.remove_sensor(unique_sensor_id=unique_sensor_id)

        if contribute_to_parent or shadow_contributing_to_parent:
            # Submit measurement to parent privatizer (default case, or when no trixel exists which can satisfy k
            # (shadow-contribution))
            should_evaluate = not shadow_contributing_to_parent or is_only_shadow_contributing
            parent_privatizer.add_sensor(unique_sensor_id=unique_sensor_id, should_evaluate=should_evaluate)
            parent_privatizer.new_value(unique_sensor_id=unique_sensor_id, measurement=measurement)
        else:
            parent_privatizer.remove_sensor(unique_sensor_id=unique_sensor_id)

        # Recommend a trixel-change if the sensor is contributing to the child or the parent cannot satisfy the
        # k-requirement
        change_direction: TrixelLevelChange
        if contribute_to_child and not shadow_contributing_to_child:
            change_direction = TrixelLevelChange.INCREASE
        elif not first_contribution and parent_privatizer._level > 0 and not contribute_to_parent:
            change_direction = TrixelLevelChange.DECREASE
        else:
            change_direction = TrixelLevelChange.KEEP

        return change_direction

    def batch_contribute(
        self,
        ms_uuid: UUID4,
        updates: BatchUpdate,
        measurement_type_reference: dict[int, MeasurementTypeEnum],
        k_requirement: int,
    ) -> dict[int, TrixelLevelChange]:
        """
        Process a batch sensor update using all related privatizers.

        :param ms_uuid: The id of measurement station which took the measurements.
        :param updates: updates for different sensors within a measurement station.
        :param measurement_type_reference: lookup table which contains the measurement type for different sensors
        :returns: a map containing the recommended trixel level change for each sensor
        """
        # map which holds the level change recommendation for each sensor
        adjust_trixel_map: dict[int, TrixelLevelChange] = dict()

        for trixel_id, measurements in updates.items():
            for measurement in measurements:
                unique_sensor_id = UniqueSensorId(ms_uuid=ms_uuid, sensor_id=measurement.sensor_id)
                self._k_map[ms_uuid] = k_requirement
                direction = self.contribute(
                    sub_trixel_id=trixel_id,
                    unique_sensor_id=unique_sensor_id,
                    measurement=measurement,
                    measurement_type=measurement_type_reference[unique_sensor_id.sensor_id],
                    k_requirement=k_requirement,
                )

                # Use implicit KEEPs
                # TODO: add option for clients to suppress see other response
                if direction != TrixelLevelChange.KEEP:
                    adjust_trixel_map[measurement.sensor_id] = direction

        return adjust_trixel_map

    @classmethod
    async def _publish_measurement_station_count(
        cls, privatizer: Privatizer, ms_count: NonNegativeInt
    ) -> NonNegativeInt | None:
        """
        Publish the measurement station count for a measurement type and trixel to the TLS.

        :param privatizer: The privatizer for which the measurement station count is updated at the TLS
        :param ms_count: the new measurement station count value
        :returns: updated measurement station count or None if unsuccessful
        """
        id_ = privatizer._id
        measurement_type = privatizer._measurement_type

        # TODO: replace with batch update endpoint
        logger.debug(
            f"Publishing measurement station count {ms_count} for (trixel: {id_} type: {measurement_type}) to TLS."
        )
        try:
            tls_update_result: TrixelMapUpdate = await cls._tls_manager.publish_trixel_map_entry(
                trixel_id=id_, type_=measurement_type, measurement_station_count=ms_count
            )
            return tls_update_result.sensor_count
        except TLSError:
            logger.critical(
                f"Failed to publish measurement station count {ms_count} for (trixel: {id_} type: {measurement_type})."
            )
        return None

    async def process(self):
        """
        Process privatizers in a bottom-up fashion.

        Starting at the trixels with the highest level, privatizers are executed in batches towards the root-level.
        Thus, the output of smaller trixels can be used in higher-level trixel.

        This procedure is performed for each measurement type individually.
        """
        # Process privatizers by type, and increasing levels
        for type_ in self._privatizers:
            privatizers_type_subset = self._privatizers[type_]

            for level in sorted(self._level_lookup.keys(), reverse=True):
                stale_privatizers: set[int] = set()

                # TODO: process trixels within same level in parallel
                new_trixel_values: dict[int, float] = dict()
                for trixel_id in self._level_lookup[level]:

                    if trixel_id not in privatizers_type_subset:
                        continue

                    privatizer: Privatizer = privatizers_type_subset[trixel_id]
                    trixel_update: TrixelUpdate = await privatizer.process()

                    if trixel_update.measurement_station_count is not None:
                        result = await self._publish_measurement_station_count(
                            privatizer=privatizer,
                            ms_count=trixel_update.measurement_station_count,
                        )
                        if result is not None:
                            privatizer.set_tls_ms_count(result)

                    if trixel_update.available:
                        new_trixel_values[level] = trixel_update.value

                    if privatizer.stale:
                        stale_privatizers.add(trixel_id)

                # Remove stale privatizers
                for trixel_id in stale_privatizers:
                    del self._privatizers[type_][trixel_id]

                # TODO: publish measurement station counts in batches after each level (use batch update at TLS)

            # TODO: persist new_trixel_values in db
            # TODO: what about timestamps? - should a TrixelUpdate contain a timestamp and the other methods
            #       also (calls to privatizer)?

    async def periodic_processing(self):
        """
        Background task which performs periodic evaluation of privatizers.

        While sensors are added and removed from privatizers as updates roll in, the output values of a privatizer and
        the quality of contributing sensors is determined in fixed intervals.
        A privatizer implementation may choose to determine the contribution property when new values arrive, but the
        evaluation function is called in regular intervals.
        """
        while True:
            # Wait for TMS to be active (and for delegation to be loaded)
            while not GlobalConfig.config.tms_config.active:
                await asyncio.sleep(0.1)
                # TODO: replace spin lock with asyncio events

            # Determine where existing sensors are located using the TLS, instantiate privatizers for them
            trixel_overview = await PrivacyManager._tls_manager.get_trixel_map_overview()
            for type_, trixels in trixel_overview.items():
                for trixel in trixels:
                    self.get_privatizer(trixel_id=trixel, measurement_type=type_, instantiate=True)

            while GlobalConfig.config.tms_config.active:
                logger.debug("Performing periodic evaluation for trixels!")

                task = asyncio.create_task(self.process())
                await asyncio.sleep(UPDATE_FREQUENCY)
                while not task.done():
                    logger.warning("Processing of trixels did not finish in time, skipping periodic evaluation!")
                    await asyncio.sleep(UPDATE_FREQUENCY)
