"""Wrapping class responsible for TLS related communication."""

import asyncio
import importlib
import os
import signal
import sys
from http import HTTPStatus
from pathlib import Path

import packaging.version
import toml
from httpx import ConnectError
from pydantic import NonNegativeInt
from trixellookupclient import Client
from trixellookupclient.api.trixel_information import (
    get_sub_trixels_which_have_registered_sensors_trixel_trixel_id_get as get_sub_trixels,
)
from trixellookupclient.api.trixel_information import (
    update_trixel_count_trixel_trixel_id_sensor_count_type_put as update_trixel_map_entry,
)
from trixellookupclient.api.trixel_management_servers import add_tms_tms_post
from trixellookupclient.api.trixel_management_servers import (
    get_all_delegations_for_the_provided_tms_tms_tms_id_delegations_get as get_delegation_for_tms,
)
from trixellookupclient.api.trixel_management_servers import (
    get_tms_info_tms_tms_id_get as get_tms_detail,
)
from trixellookupclient.api.trixel_management_servers import (
    update_tms_details_tms_tms_id_put as update_tms_detail,
)
from trixellookupclient.models import (
    TMSDelegation,
    TrixelManagementServer,
    TrixelManagementServerCreate,
    TrixelMapUpdate,
)
from trixellookupclient.types import Response

from config_schema import Config, GlobalConfig
from exception import TLSCriticalError, TLSError
from logging_helper import get_logger
from model import MeasurementTypeEnum

api_version = importlib.metadata.version("trixellookupclient")
logger = get_logger(__name__)
MAX_CONNECTION_ATTEMPTS = 10


def update_config_file(config: Config):
    """Update the TOML config partially with information from the current config."""
    if "pytest" in sys.modules:
        return

    file = Path("config/config.toml")
    existing_config = toml.load(file)
    existing_config["tms_config"]["id"] = config.tms_config.id
    existing_config["tms_config"]["active"] = config.tms_config.active
    existing_config["tms_config"]["api_token"] = config.tms_config.api_token.get_secret_value()

    new_config = open(file, "w")
    toml.dump(existing_config, new_config)
    new_config.close()


class TLSManager:
    """Wrapping class responsible for TLS related communication."""

    def __init__(self):
        """Initialize the TLSManager with a trixellookupclient."""
        self.config: Config = GlobalConfig.config

        # Assume the TMS is deactivated until synchronized with the TLS.
        self.config.tms_config.active = False

        secure = "" if self.config.tls_config.use_ssl is False else "s"
        self.tls_client = Client(
            base_url=f"http{secure}://{self.config.tls_config.host}/v{packaging.version.Version(api_version).major}/"
        )

    async def start(self):
        """Start the TLSManager, which registers the TMS at the TLS and retrieves it's configuration."""
        retries = 0
        while True:
            try:
                await asyncio.sleep(0.1)

                if self.config.tms_config.api_token is None:
                    await self.register()

                await self.sync_tls_config()
                await self.fetch_delegations()

                logger.info("Synchronized with TLS.")
                delegation_detail = [
                    (x.trixel_id, "exclude" if x.exclude else "include") for x in self.config.tms_config.delegations
                ]
                logger.info(f"Trixel-delegations: {delegation_detail}")
                return
            except ConnectError as e:
                await asyncio.sleep(5)
                retries += 1
                if retries >= MAX_CONNECTION_ATTEMPTS:
                    logger.critical(e)
                    os.kill(os.getpid(), signal.SIGINT)
                    return
            except (TLSCriticalError, Exception) as e:
                logger.critical(e)
                os.kill(os.getpid(), signal.SIGINT)
                return

    async def register(self):
        """Register this TMS at the TLS."""
        logger.info("Signing up at TLS.")
        tms_config = self.config.tms_config

        result: Response[TrixelManagementServerCreate] = await add_tms_tms_post.asyncio_detailed(
            client=self.tls_client, host=tms_config.host
        )
        if result.status_code != HTTPStatus.CREATED:
            raise TLSCriticalError("TLS sign-up", result)

        result: TrixelManagementServerCreate = result.parsed

        self.config.tms_config.id = result.id
        self.config.tms_config.active = result.active
        self.config.tms_config.api_token = result.token
        update_config_file(config=self.config)

    async def sync_tls_config(self):
        """Synchronize TMS details with the TLS."""
        logger.debug("Fetching TMS details")
        tms_config = self.config.tms_config

        if tms_config.id is None:
            raise TLSCriticalError("Own TMS ID unknown!")

        result: Response[TrixelManagementServer] = await get_tms_detail.asyncio_detailed(
            client=self.tls_client,
            tms_id=tms_config.id,
        )

        if result.status_code != HTTPStatus.OK:
            raise TLSCriticalError("TMS info retrieval", result)

        result: TrixelManagementServer = result.parsed

        self.config.tms_config.id = result.id
        self.config.tms_config.active = result.active
        tms_config = self.config.tms_config

        if not tms_config.active:
            raise TLSCriticalError("TMS is deactivated by the TLS.")

        # Update new information on TLS
        # TODO: the update is always executed to validate the token (replace with auth validation endpoint)
        if result.host != tms_config.host or True:
            logger.debug("Posting new host address to TLS")

            result: Response[TrixelManagementServer] = await update_tms_detail.asyncio_detailed(
                client=self.tls_client,
                tms_id=tms_config.id,
                host=tms_config.host,
                token=tms_config.api_token.get_secret_value(),
            )
            if result.status_code != HTTPStatus.OK:
                raise TLSCriticalError("TMS update-details", result)
            result: TrixelManagementServerCreate = result.parsed

            self.config.tms_config.id = result.id
            self.config.tms_config.active = result.active

        update_config_file(config=self.config)

    async def fetch_delegations(self) -> list[TMSDelegation]:
        """Retrieve all relevant delegations for this TMS."""
        logger.debug("Fetching trixel delegations")

        result: Response[list[TMSDelegation]] = await get_delegation_for_tms.asyncio_detailed(
            client=self.tls_client, tms_id=self.config.tms_config.id
        )

        if result.status_code != HTTPStatus.OK:
            raise TLSCriticalError("TMS fetch-delegations", result)
        result: list[TMSDelegation] = result.parsed

        self.config.tms_config.delegations = result
        return result

    async def publish_trixel_map_entry(
        self,
        trixel_id: int,
        type_: MeasurementTypeEnum,
        measurement_station_count: NonNegativeInt,
    ) -> TrixelMapUpdate:
        """
        Update the sensor count for a trixel and measurement type at the TLS.

        :param trixel_id: The trixel for which the sensor count is updated
        :param type_: The measurement type for which the sensor count is updated
        :param measurement_station_count: The new sensor count
        :return: updated trixel map entry
        :raises TLSError: if updating the value failed
        :raises TLSCriticalError: if authentication failed
        """
        result: Response[TrixelMapUpdate] = await update_trixel_map_entry.asyncio_detailed(
            client=self.tls_client,
            trixel_id=trixel_id,
            type=type_,
            sensor_count=measurement_station_count,
            token=self.config.tms_config.api_token.get_secret_value(),
        )

        if result.status_code == HTTPStatus.UNAUTHORIZED:
            raise TLSCriticalError("Authentication failed during trixel map update!")

        if result.status_code != HTTPStatus.OK:
            raise TLSError("TMS fetch-delegations", result)

        return result.parsed

    async def get_trixel_map_overview(self) -> dict[MeasurementTypeEnum, set[int]]:
        """
        Retrieve trixels which have at least one measurement station according to the TLS.

        Results are separated by measurement type for all trixels delegated to this TMS.

        :returns: dict containing all trixels which have at least one sensor for each measurement type
        """
        # TODO: does not consider delegation exclusion
        delegations = self.config.tms_config.delegations

        if len(delegations) == 0:
            raise TLSCriticalError("Failed to fetch trixel sensor count overview. Delegations unknown.")

        overview: dict[MeasurementTypeEnum, set[int]] = dict()
        for type_ in MeasurementTypeEnum:
            for delegation in delegations:

                if delegation.exclude is False:
                    result: Response[list[int]] = await get_sub_trixels.asyncio_detailed(
                        client=self.tls_client,
                        types=[type_],
                        trixel_id=delegation.trixel_id,
                    )

                if result.status_code != HTTPStatus.OK:
                    raise TLSCriticalError("TMS fetch trixel overview failed!", result)

                overview.setdefault(type_, set()).update(result.parsed)

        return overview
