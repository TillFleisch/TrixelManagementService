"""Database model definitions."""

import enum

from sqlalchemy import Column, Integer, String

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

    id = Column(Integer, unique=True, primary_key=True, nullable=False)
    name = Column(String(32), unique=True, nullable=False)
