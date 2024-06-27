"""Tests related to the TLS Manager."""

import importlib
from http import HTTPStatus
from urllib.parse import urlencode

import packaging.version
import pytest
import respx
from httpx import ConnectError, Response
from trixellookupclient.models.tms_delegation import TMSDelegation

from config_schema import Config, TestConfig
from exception import TLSCriticalError
from tls_manager import TLSManager

pytest_plugins = ("pytest_asyncio",)

api_version = importlib.metadata.version("trixellookupclient")
tls_prefix = f"https://{TestConfig().tls_config.host}/v{packaging.version.Version(api_version).major}"


@pytest.mark.order(200)
def test_read_config(config: Config):
    """Test that the test configuration was loaded correctly."""
    assert config.tls_config.host == "sausage.dog.local"
    assert config.tms_config.host == "wiener.dog.local"


@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_fetch_delegation_invalid_config(new_tls_manager: TLSManager):
    """Test fetching delegations when the TLS is unreachable."""
    with pytest.raises(ConnectError):
        await new_tls_manager.fetch_delegations()


@respx.mock
@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_fetch_delegations(preset_tls_manager: TLSManager):
    """Test trixel delegation retrieval."""
    manager = preset_tls_manager
    config = manager.config

    delegation_request = respx.get(f"{tls_prefix}/TMS/1/delegations").mock(
        return_value=Response(
            status_code=HTTPStatus.OK,
            json=[
                {"tms_id": 1, "trixel_id": 8, "exclude": False},
            ],
        )
    )

    await manager.fetch_delegations()
    assert delegation_request.called
    assert config.tms_config.delegations[0] == TMSDelegation(tms_id=1, trixel_id=8, exclude=False)


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", {HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY})
@pytest.mark.order(200)
async def test_fetch_delegations_wrong_trixel(status_code: int, preset_tls_manager: TLSManager):
    """Test delegation retrieval with an invalid tms id."""
    manager = preset_tls_manager

    request = respx.get(f"{tls_prefix}/TMS/1/delegations").mock(
        Response(
            status_code=status_code,
            json={},
        )
    )

    with pytest.raises(TLSCriticalError):
        await manager.fetch_delegations()

    assert request.called


@respx.mock
@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_register_tls(new_tls_manager: TLSManager):
    """Test successful registration process at the TLS."""
    manager = new_tls_manager
    tms_config = manager.config.tms_config

    request = respx.post(f"{tls_prefix}/TMS?{urlencode({'host':tms_config.host})}").mock(
        Response(
            status_code=HTTPStatus.OK,
            json={"id": 1, "active": True, "host": tms_config.host, "token": "token"},
        )
    )

    await manager.register()

    assert request.called

    assert tms_config.id == 1
    assert tms_config.api_token.get_secret_value() == "token"
    assert tms_config.active is True


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", {HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT, HTTPStatus.UNPROCESSABLE_ENTITY})
@pytest.mark.order(200)
async def test_register_tls_invalid(status_code: int, new_tls_manager: TLSManager):
    """Test registration with critical exits."""
    manager = new_tls_manager
    tms_config = manager.config.tms_config

    request = respx.post(f"{tls_prefix}/TMS?{urlencode({'host':tms_config.host})}").mock(
        Response(
            status_code=status_code,
            json={},
        )
    )

    with pytest.raises(TLSCriticalError):
        await manager.register()

    assert request.called


@respx.mock
@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_sync_tls_config(preset_tls_manager: TLSManager):
    """Test successful TMS detail synchronization."""
    manager = preset_tls_manager
    tms_config = manager.config.tms_config

    get_request = respx.get(f"{tls_prefix}/TMS/{tms_config.id}").mock(
        Response(
            status_code=HTTPStatus.OK,
            json={"id": tms_config.id, "active": True, "host": tms_config.host},
        )
    )

    put_request = respx.put(f"{tls_prefix}/TMS/{tms_config.id}?{urlencode({'host':tms_config.host})}").mock(
        Response(
            status_code=HTTPStatus.OK,
            json={"id": tms_config.id, "active": True, "host": tms_config.host},
        )
    )

    await manager.sync_tls_config()

    assert get_request.called
    assert put_request.called

    assert tms_config.active is True


@respx.mock
@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_sync_tls_config_deactivated(preset_tls_manager: TLSManager):
    """Test config synchronization when TLS responds with a deactivated status."""
    manager = preset_tls_manager
    tms_config = manager.config.tms_config

    request = respx.get(f"{tls_prefix}/TMS/{tms_config.id}").mock(
        Response(
            status_code=HTTPStatus.OK,
            json={"id": tms_config.id, "active": False, "host": tms_config.host},
        )
    )

    with pytest.raises(TLSCriticalError):
        await manager.sync_tls_config()

    assert request.called


@pytest.mark.asyncio
@pytest.mark.order(200)
async def test_sync_tls_invalid_config(new_tls_manager: TLSManager):
    """Assert fail when used with invalid configuration."""
    manager = new_tls_manager

    with pytest.raises(TLSCriticalError):
        await manager.sync_tls_config()


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", {HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT, HTTPStatus.UNPROCESSABLE_ENTITY})
@pytest.mark.parametrize("path", {True, False})
@pytest.mark.order(200)
async def test_sync_tls_invalid_responses(status_code: int, path: bool, preset_tls_manager: TLSManager):
    """Assert critical error with invalid responses."""
    manager = preset_tls_manager
    tms_config = manager.config.tms_config

    respx.get(f"{tls_prefix}/TMS/{tms_config.id}").mock(
        Response(
            status_code=HTTPStatus.OK if path else status_code,
            json={"id": tms_config.id, "active": True, "host": tms_config.host},
        )
    )

    respx.put(f"{tls_prefix}/TMS/{tms_config.id}?{urlencode({'host':tms_config.host})}").mock(
        Response(
            status_code=HTTPStatus.OK if not path else status_code,
            json={"id": tms_config.id, "active": True, "host": tms_config.host},
        )
    )

    with pytest.raises(TLSCriticalError):
        await manager.sync_tls_config()
