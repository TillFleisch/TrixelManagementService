"""Global functions which are can be used by endpoints from different routers."""

from http import HTTPStatus

from fastapi import HTTPException

from config_schema import GlobalConfig


def is_active() -> None:
    """Dependency which restricts endpoints to only be available, if the TMS is enabled by the TLS."""
    if not GlobalConfig.config.tms_config.active:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="TMS not active!")
