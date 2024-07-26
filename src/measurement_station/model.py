"""Measurement station and related database models."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from database import Base


class MeasurementStation(Base):
    """Common information and management related details for measurement stations."""

    __tablename__ = "measurement_station"

    uuid = Column(Uuid, primary_key=True, nullable=False, default=uuid.uuid4, index=True)
    token_secret = Column(LargeBinary(256))
    k_requirement = Column(Integer, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    sensor_index = Column(Integer, default=0, nullable=False)

    sensors = relationship("Sensor", back_populates="measurement_station")

    __table_args__ = (CheckConstraint(k_requirement > 0, name="check_positive_k"),)


class Sensor(Base):
    """Database model which describes sensors which are associated with a measurement station."""

    __tablename__ = "sensor"

    id = Column(Integer, primary_key=True, nullable=False)
    measurement_station_uuid = Column(
        Uuid, ForeignKey("measurement_station.uuid", ondelete="CASCADE"), primary_key=True, nullable=False, index=True
    )
    sensor_detail_id = Column(Integer, ForeignKey("sensor_detail.id"), nullable=False)
    measurement_type = Column(Integer, ForeignKey("measurement_type.id"), nullable=False)

    measurement_station = relationship("MeasurementStation", back_populates="sensors")
    details = relationship("SensorDetail", back_populates="sensors", lazy="selectin")  # codespell:ignore
    measurements = relationship("SensorMeasurement", back_populates="sensor")

    Index("measurement_station_sensor", measurement_station_uuid, id)

    __table_args__ = (
        UniqueConstraint(measurement_station_uuid, id, name="unique_constraint_measurement_station_uuid_sensor_id"),
    )


class SensorDetail(Base):
    """Database model which describes sensors (their properties) in detail."""

    __tablename__ = "sensor_detail"

    id = Column(Integer, autoincrement=True, nullable=False, unique=True, primary_key=True, index=True)
    # Null means "unknown"/"generic" - the sensor name can be used for sensor-specific correction/scoring
    name = Column(String(256), default=None)
    accuracy = Column(Float)
    sensors = relationship("Sensor", back_populates="details")


class SensorMeasurement(Base):
    """Table which holds environmental observations made by sensors."""

    __tablename__ = "sensor_measurement"

    time = Column(DateTime(timezone=True), primary_key=True)
    measurement_station_uuid = Column(Uuid, nullable=False, primary_key=True)
    sensor_id = Column(Integer, primary_key=True)
    value = Column(Float)

    sensor = relationship("Sensor", back_populates="measurements")

    Index("measurements_stations_sensor", time.desc(), measurement_station_uuid, sensor_id)

    __table_args__ = (
        ForeignKeyConstraint(
            [measurement_station_uuid, sensor_id],
            [Sensor.measurement_station_uuid, Sensor.id],
            name="composite_foreign_key_ms_uuid_sensor_id",
            ondelete="CASCADE",
        ),
        UniqueConstraint(measurement_station_uuid, sensor_id, time, name="unique_constraint_single_sensor_measurement"),
        {"timescaledb_hypertable": {"time_column_name": "time"}},
    )
