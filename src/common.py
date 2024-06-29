"""Global functions which are can be used by endpoints from different routers."""

from http import HTTPStatus

from fastapi import HTTPException
from pynyhtm import HTM

from config_schema import GlobalConfig


def is_active() -> None:
    """Dependency which restricts endpoints to only be available, if the TMS is enabled by the TLS."""
    if not GlobalConfig.config.tms_config.active:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="TMS not active!")


def is_delegated(trixel_id: int):
    """
    Determine if a trixel is delegated to this TMS.

    :param trixel_id: ID of the trixel for which the check if performed
    :returns: True if the trixel is delegated to this TMS, False otherwise
    """
    delegations = GlobalConfig.config.tms_config.delegations

    level = HTM.get_level(trixel_id)

    # Determine those delegations which are "above" the trixel id
    super_trixels = list()
    for delegation in delegations:
        delegation_level = HTM.get_level(delegation.trixel_id)

        if level >= delegation_level:
            sub_id = trixel_id >> ((level - delegation_level) * 2)

            if sub_id == delegation.trixel_id:
                super_trixels.append((delegation, delegation_level))

    if len(super_trixels) == 0:
        return False

    super_trixel = max(super_trixels, key=lambda x: x[1])[0]
    if not super_trixel.exclude:
        return True
