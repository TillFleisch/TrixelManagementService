"""Global database wrappers."""

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
