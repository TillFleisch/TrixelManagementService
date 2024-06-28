"""Entry point for the Trixel Management Service API."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from http import HTTPStatus

import packaging.version
import uvicorn
from fastapi import Depends, FastAPI
from starlette.responses import Response

import model
from common import is_active
from config_schema import Config, GlobalConfig
from crud import init_measurement_type_enum
from database import engine, get_db
from logging_helper import get_logger
from measurement_station.measurement_station import TAG_MEASUREMENT_STATION
from measurement_station.measurement_station import router as measurement_station_router
from schema import Ping, Version
from tls_manager import TLSManager

api_version = importlib.metadata.version("trixelmanagementserver")
config: Config = GlobalConfig.config

model.Base.metadata.create_all(bind=engine)

tls_manger: TLSManager = TLSManager()
logger = get_logger(__name__)

openapi_tags = [
    {"name": TAG_MEASUREMENT_STATION},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan actions executed before and after FastAPI."""
    init_measurement_type_enum(next(get_db()))
    asyncio.create_task(tls_manger.start())
    yield


app = FastAPI(
    title="Trixel Management Service",
    summary="""
            Manages Trixels and participating measurement stations to provide anonymized environmental observations
            for trixels.
            """,
    version=api_version,
    root_path=f"/v{packaging.version.Version(api_version).major}",
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)
app.include_router(measurement_station_router)


@app.get(
    "/ping",
    name="Ping",
    summary="ping ... pong",
)
def ping() -> Ping:
    """Return a basic ping message."""
    return Ping()


@app.get(
    "/version",
    name="Version",
    summary="Get the precise current semantic version.",
)
def get_semantic_version() -> Version:
    """Get the precise version of the currently running API."""
    return Version(version=api_version)


@app.get(
    "/active",
    name="is_active",
    summary="Get the active status of this TMS.",
    responses={
        200: {"content": None},
        503: {"content": {"application/json": {"example": {"detail": "TMS not active!"}}}},
    },
    dependencies=[Depends(is_active)],
)
def get_active() -> Response:
    """Get the active status of this TMS."""
    return Response(status_code=HTTPStatus.OK)


# TODO: add (authenticated) /delegations PUT endpoint for delegation updates from the TMS


def main() -> None:
    """Entry point for cli module invocations."""
    uvicorn.main("trixelmanagementserver:app")


if __name__ == "__main__":
    main()
