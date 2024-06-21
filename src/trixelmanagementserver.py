"""Entry point for the Trixel Management Service API."""

import asyncio
import importlib
import sys
from contextlib import asynccontextmanager

import packaging.version
import uvicorn
from fastapi import FastAPI

from logging_helper import get_logger
from schema import Config, Ping, TestConfig, Version
from tls_manager import TLSManager

api_version = importlib.metadata.version("trixelmanagementserver")
if "pytest" in sys.modules:
    config = TestConfig()
else:
    config = Config()
tls_manger: TLSManager = TLSManager(config)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan actions executed before and after FastAPI."""
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
    lifespan=lifespan,
)


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


# TODO: add (authenticated) /delegations PUT endpoint for delegation updates from the TMS


def main() -> None:
    """Entry point for cli module invocations."""
    uvicorn.main("trixelmanagementserver:app")


if __name__ == "__main__":
    main()
