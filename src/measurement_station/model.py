"""Measurement station and related database models."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Integer, LargeBinary, Uuid

from database import Base


class MeasurementStation(Base):
    """Common information and management related details for measurement stations."""

    __tablename__ = "measurement_station"

    uuid = Column(Uuid, primary_key=True, nullable=False, default=uuid.uuid4)
    token_secret = Column(LargeBinary(256))
    k_requirement = Column(Integer, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (CheckConstraint(k_requirement > 0, name="check_positive_k"),)
