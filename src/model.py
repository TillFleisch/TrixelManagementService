"""Database model definitions."""

import enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from database import Base


class MeasurementTypeEnum(str, enum.Enum):
    """Supported measurement types."""

    # A string enum is used, so that the value can be used in urls.
    # Within the DB the "id" is used but the enum name can also be retrieved via the relation
    AMBIENT_TEMPERATURE = "ambient_temperature"
    RELATIVE_HUMIDITY = "relative_humidity"

    def get_id(self):
        """Get the index of the measurement type instance within this enum."""
        return [x for x in MeasurementTypeEnum].index(self) + 1

    def get_from_id(id_: int):
        """
        Get an enum instance from this enum which has the given id.

        :param id_: target enum index
        :return: enum which has index id_
        """
        return [x for x in MeasurementTypeEnum][id_ - 1]


class MeasurementType(Base):
    """Enum-like table which contains all available measurement types."""

    __tablename__ = "measurement_type"

    id = Column(Integer, unique=True, primary_key=True, nullable=False, index=True)
    name = Column(String(32), unique=True, nullable=False)


class Observation(Base):
    """Table which hold environmental observations within trixels."""

    __tablename__ = "observation"

    time = Column(DateTime(timezone=True), primary_key=True)
    trixel_id = Column(BigInteger, primary_key=True)
    measurement_type = Column(Integer, ForeignKey("measurement_type.id"))
    value = Column(Float)
    sensor_count = Column(Integer, default=0, nullable=False)
    measurement_station_count = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(time, trixel_id, measurement_type, name="unique_constraint_single_measurement"),
        CheckConstraint(sensor_count >= 0, name="check_non_negative_sensor_count"),
        CheckConstraint(measurement_station_count >= 0, name="check_non_negative_measurement_station_count"),
        {"timescaledb_hypertable": {"time_column_name": "time"}},
    )
