"""Entry point for the Trixel Management Service API."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from datetime import timedelta
from http import HTTPStatus
from typing import Annotated, List

import packaging.version
import uvicorn
from fastapi import Depends, FastAPI, Path, Query
from pydantic import NonNegativeInt
from sqlalchemy.orm import Session
from starlette.responses import Response

import crud
import model
import schema
from common import is_active
from config_schema import Config, GlobalConfig
from crud import init_measurement_type_enum
from database import engine, get_db
from logging_helper import get_logger
from measurement_station.measurement_station import TAG_MEASUREMENT_STATION, TAG_TRIXELS
from measurement_station.measurement_station import router as measurement_station_router
from privatizer.blank_privatizer import BlankPrivatizer
from privatizer.latest_privatizer import LatestPrivatizer
from privatizer.manager import PrivacyManager
from privatizer.privatizer import Privatizer
from schema import TrixelID
from tls_manager import TLSManager

api_version = importlib.metadata.version("trixelmanagementserver")
config: Config = GlobalConfig.config

model.Base.metadata.create_all(bind=engine)

logger = get_logger(__name__)

openapi_tags = [{"name": TAG_MEASUREMENT_STATION}, {"name": TAG_TRIXELS}]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan actions executed before and after FastAPI."""
    init_measurement_type_enum(next(get_db()))
    asyncio.create_task(app.tls_manger.start())
    asyncio.create_task(app.privacy_manager.periodic_processing())
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
app.tls_manger = TLSManager()

privatizer_class: type[Privatizer]
if config.privatizer == "blank":
    privatizer_class = BlankPrivatizer
elif config.privatizer == "latest":
    privatizer_class = LatestPrivatizer
app.privacy_manager = PrivacyManager(tls_manager=app.tls_manger, privatizer_class=privatizer_class)


@app.get(
    "/ping",
    name="Ping",
    summary="ping ... pong",
)
def ping() -> schema.Ping:
    """Return a basic ping message."""
    return schema.Ping()


@app.get(
    "/version",
    name="Version",
    summary="Get the precise current semantic version.",
)
def get_semantic_version() -> schema.Version:
    """Get the precise version of the currently running API."""
    return schema.Version(version=api_version)


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


# TODO: add (authenticated) /delegations PUT endpoint for delegation updates from the TLS


@app.get(
    "/trixel/{trixel_id}",
    name="Get Observations",
    summary="Gets the current environmental observations for a trixel.",
    tags=[TAG_TRIXELS],
    responses={
        503: {"content": {"application/json": {"detail": "TMS not active!"}}},
    },
    dependencies=[Depends(is_active)],
)
def get_observation(
    trixel_id: Annotated[TrixelID, Path(description="The trixel for which observations are retrieved.")],
    types: Annotated[
        List[model.MeasurementTypeEnum],
        Query(
            description="List of measurement types which restrict results. If none are provided, all types are used."
        ),
    ] = None,
    age: Annotated[
        NonNegativeInt | None, Query(description="Maximum age of measurement timestamps in seconds.")
    ] = None,
    db: Session = Depends(get_db),
) -> list[schema.Observation]:
    """Retrieve the latest measurement for the provided types for a trixel from the DB."""
    return crud.get_observations(db, trixel_id, types, age=None if age is None else timedelta(seconds=int(age)))


def main() -> None:
    """Entry point for cli module invocations."""
    uvicorn.main("trixelmanagementserver:app")


if __name__ == "__main__":
    main()
