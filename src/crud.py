"""Global database wrappers."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import model


def init_measurement_type_enum(db: Session):
    """Initialize the measurement type reference enum table within the DB."""
    existing_types: model.MeasurementType = db.query(model.MeasurementType).all()
    existing_types: set[int, str] = set([(x.id, x.name) for x in existing_types])

    enum_types: set[int, str] = set()
    for type_ in model.MeasurementTypeEnum:
        enum_types.add((type_.get_id(), type_.value))

    # Assert the local python enum is the same as the one used in the DB
    # Thus, the local enum can be used as a shortcut without retrieving from the enum relation
    if len(existing_types - enum_types) > 0:
        raise (RuntimeError("DB contains unsupported enums!"))

    new_types = enum_types - existing_types
    if len(new_types) > 0:
        for new_type in new_types:
            db.add(model.MeasurementType(id=new_type[0], name=new_type[1]))
        db.commit()


def get_observations(
    db: Session, trixel_id: int, types: list[model.MeasurementTypeEnum] | None = None, age: timedelta | None = None
):
    """
    Get environmental observations limited by the provided types for a trixel.

    :param trixel_id: the trixel for which measurements are retrieved
    :param types: set of types for which measurements are retrieved, if non all types are used
    :param age: timedelta which defined the oldest allowed timestamps
    """
    types = [type.value for type in types] if types is not None else [enum.value for enum in model.MeasurementTypeEnum]

    query = (
        db.query(model.Observation)
        .where(model.Observation.trixel_id == trixel_id)
        .where(model.Observation.measurement_type == model.MeasurementType.id, model.MeasurementType.name.in_(types))
    )

    if age:
        query = query.where(model.Observation.time > datetime.now() - age)

    query = (
        query.group_by(model.Observation.measurement_type, model.Observation.time)
        .order_by(model.Observation.time.desc())
        .limit(len(types))
    )
    result = query.all()

    return result
