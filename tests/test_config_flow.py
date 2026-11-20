"""Tests for Hisense VIDAA config flow and auto-discovery."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import (
    CONF_BRAND,
    CONF_IP_ADDRESS,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SW_VERSION,
)


@pytest.mark.anyio
async def test_ssdp_discovery_vidaa_tv(monkeypatch):
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    # Mock set_unique_id and abort checks
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:12345678-1234-5678-1234-567812345678::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.12:38400/MediaServer/rendererdevicedesc.xml",
        ssdp_headers={"_host": "192.168.50.12"},
        upnp={
            "friendlyName": "Living Room TV",
            "manufacturer": "Hisense",
            "modelName": "65U7G",
            "modelDescription": "vidaa_support=1\nbrand=his\nmacWifi=e8:51:77:ec:98:1c\n",
        },
    )

    result = await flow.async_step_ssdp(discovery_info)
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"
    assert flow.ip_address == "192.168.50.12"
    assert flow.mac_address == "e8:51:77:ec:98:1c"
    assert flow.model == "65U7G"
    assert flow.manufacturer == "Hisense"
    assert flow.brand == "his"


@pytest.mark.anyio
async def test_ssdp_discovery_non_vidaa_ignored():
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:sonos-1234::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.99:1400/xml/device_description.xml",
        ssdp_headers={"_host": "192.168.50.99"},
        upnp={
            "friendlyName": "Sonos Speaker",
            "manufacturer": "Sonos",
            "modelName": "Play:1",
            "modelDescription": "Sonos Smart Speaker",
        },
    )

    result = await flow.async_step_ssdp(discovery_info)
    assert result["type"] == "abort"
    assert result["reason"] == "not_vidaa_tv"


@pytest.mark.anyio
async def test_options_step_creates_entry():
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    flow.ip_address = "192.168.50.12"
    flow.mac_address = "e8:51:77:ec:98:1c"
    flow.discovered_title = "Hisense TV"
    flow.model = "65U7G"
    flow.manufacturer = "Hisense"
    flow.sw_version = "V1.0"

    mock_client = MagicMock()
    mock_client.client_id = "test_client_id"
    mock_client.username = "hisense"
    mock_client.password = "pass"
    mock_client.access_token = "token123"
    mock_client.access_token_time = 1700000000
    mock_client.access_token_duration = 3600
    mock_client.refresh_token = "reftoken123"
    mock_client.refresh_token_time = 1700000000
    mock_client.refresh_token_duration = 86400
    mock_client.async_disconnect = AsyncMock()
    mock_client.disconnect = MagicMock()
    flow.client = mock_client

    result = await flow.async_step_options(
        user_input={
            "enable_wol": True,
            "include_apps_in_sources": True,
            "enable_picture_controls": False,
            "enable_sound_controls": False,
            "enable_audio_only": False,
        }
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Hisense TV"
    assert result["data"][CONF_IP_ADDRESS] == "192.168.50.12"
    assert result["data"][CONF_MAC_ADDRESS] == "e8:51:77:ec:98:1c"
    assert result["data"][CONF_MODEL] == "65U7G"
    assert result["data"][CONF_MANUFACTURER] == "Hisense"
    assert result["data"][CONF_BRAND] == "his"
    assert result["data"][CONF_SW_VERSION] == "V1.0"
    assert result["options"]["enable_picture_controls"] is False
    assert result["options"]["enable_sound_controls"] is False
    assert result["options"]["enable_audio_only"] is False
    assert mock_client.async_disconnect.called or mock_client.disconnect.called
    assert flow.client is None


@pytest.mark.anyio
async def test_capability_probing_in_config_flow(monkeypatch):
    """Test capability probing dynamically updates option defaults."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    flow.ip_address = "192.168.50.12"
    flow.mac_address = "e8:51:77:ec:98:1c"
    flow.discovered_title = "Hisense TV"

    mock_client = MagicMock()
    mock_client.connected = True
    mock_client.picture_settings = {"91": MagicMock()}
    mock_client.sound_settings = {}
    mock_client.async_get_picture_settings = AsyncMock()
    mock_client.async_get_sound_settings = AsyncMock()
    mock_client.get_picture_settings = mock_client.async_get_picture_settings
    mock_client.get_sound_settings = mock_client.async_get_sound_settings
    flow.client = mock_client

    await flow._async_probe_device_capabilities()
    assert mock_client.get_picture_settings.called
    assert mock_client.get_sound_settings.called

    form_result = await flow.async_step_options()
    assert form_result["type"] == "form"
    assert form_result["step_id"] == "options"


@pytest.mark.anyio
async def test_user_step_auto_certs_missing_routes_to_certs(monkeypatch):
    """When certificates are not present on disk, auto profile routes to certs step."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    monkeypatch.setattr(
        "custom_components.vidaa.protocol.check_certs_exist",
        lambda c, k: False,
    )

    result = await flow.async_step_user(user_input={"ip_address": "192.168.50.12", "auth_profile": "auto"})
    assert result["type"] == "form"
    assert result["step_id"] == "certs"


@pytest.mark.anyio
async def test_user_step_explicit_model_routes_to_certs():
    """When an explicit model profile is selected, it routes to certs step."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    result = await flow.async_step_user(user_input={"ip_address": "192.168.50.12", "auth_profile": "modern"})
    assert result["type"] == "form"
    assert result["step_id"] == "certs"


@pytest.mark.anyio
async def test_certs_step_submission_valid(monkeypatch):
    """Submitting valid cert paths connects and transitions to auth step."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.ip_address = "192.168.50.12"
    flow.auth_profile = "modern"
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    monkeypatch.setattr(
        "custom_components.vidaa.protocol.check_certs_exist",
        lambda c, k: True,
    )
    monkeypatch.setattr(
        "custom_components.vidaa.flow.certs.check_certs_exist",
        lambda c, k: True,
    )
    monkeypatch.setattr(
        "custom_components.vidaa.flow.certs.validate_ssl_certs",
        lambda c, k: (True, None),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )

    result = await flow.async_step_certs(
        user_input={
            "use_ssl": True,
            "certfile": "/config/certs/vidaa_2024_cert.pem",
            "keyfile": "/config/certs/vidaa_2024_key.pem",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "auth"


@pytest.mark.anyio
async def test_zeroconf_discovery(monkeypatch):
    """Test mDNS / Zeroconf discovery handling."""
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    monkeypatch.setattr(
        "custom_components.vidaa.flow.helpers.get_arp_mac",
        lambda host: "e8:51:77:ec:98:1c",
    )
    monkeypatch.setattr(
        "custom_components.vidaa.protocol.discovery.get_arp_mac",
        lambda host: "e8:51:77:ec:98:1c",
    )
    monkeypatch.setattr(
        "custom_components.vidaa.tv.fingerprint.get_arp_mac",
        lambda host: "e8:51:77:ec:98:1c",
    )

    discovery_info = ZeroconfServiceInfo(
        ip_address="192.168.50.12",
        ip_addresses=["192.168.50.12"],
        port=36669,
        hostname="hisensetv.local.",
        type="_vidaa._tcp.local.",
        name="Living Room TV._vidaa._tcp.local.",
        properties={},
    )

    result = await flow.async_step_zeroconf(discovery_info)
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"
    assert flow.ip_address == "192.168.50.12"
    assert flow.mac_address == "e8:51:77:ec:98:1c"


@pytest.mark.anyio
async def test_config_flow_async_remove_cleans_up_client():
    """Test async_remove disconnects running flow client."""
    hass = MagicMock(spec=HomeAssistant)
    import asyncio

    hass.async_create_background_task = MagicMock(
        side_effect=lambda coro, *a, **kw: asyncio.get_running_loop().create_task(coro)
    )

    flow = VidaaConfigFlow()
    flow.hass = hass
    mock_client = MagicMock()
    mock_client.async_disconnect = AsyncMock()
    flow.client = mock_client

    flow.async_remove()
    assert hass.async_create_background_task.called
    assert flow.client is None


@pytest.mark.anyio
async def test_config_flow_async_remove_noop_without_client():
    """Test async_remove executes cleanly when client is None."""
    flow = VidaaConfigFlow()
    flow.client = None
    flow.async_remove()
    assert flow.client is None


@pytest.mark.anyio
async def test_config_flow_async_remove_without_hass():
    """Test async_remove calls disconnect synchronously if hass is not set."""
    flow = VidaaConfigFlow()
    flow.hass = None
    mock_client = MagicMock()
    mock_client.disconnect = MagicMock()
    mock_client.async_disconnect = AsyncMock()
    flow.client = mock_client

    flow.async_remove()
    assert mock_client.async_disconnect.called or mock_client.disconnect.called
    assert flow.client is None


@pytest.mark.anyio
async def test_certs_step_submission_invalid_pem(monkeypatch):
    """Submitting corrupted or invalid cert paths displays invalid_ssl_cert error."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.ip_address = "192.168.50.12"
    flow.auth_profile = "modern"

    monkeypatch.setattr(
        "custom_components.vidaa.flow.certs.check_certs_exist",
        lambda c, k: True,
    )
    monkeypatch.setattr(
        "custom_components.vidaa.flow.certs.validate_ssl_certs",
        lambda c, k: (False, "invalid_ssl_cert: PEM lib error"),
    )

    result = await flow.async_step_certs(
        user_input={
            "use_ssl": True,
            "certfile": "/config/certs/corrupted.pem",
            "keyfile": "/config/certs/corrupted.key",
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "certs"
    assert result["errors"]["base"] == "invalid_ssl_cert"


@pytest.mark.anyio
async def test_ssdp_discovery_toshiba_tv(monkeypatch):
    """Test SSDP discovery and entry creation for OEM Toshiba TV preserves brand code."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:toshiba-1234::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.25:38400/MediaServer/rendererdevicedesc.xml",
        ssdp_headers={"_host": "192.168.50.25"},
        upnp={
            "friendlyName": "Toshiba 55C350",
            "manufacturer": "Toshiba",
            "modelName": "55C350",
            "modelDescription": "transport_protocol=3290\nbrand=tos\nmacWifi=00:11:22:33:44:55\n",
        },
    )

    result = await flow.async_step_ssdp(discovery_info)
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"
    assert flow.ip_address == "192.168.50.25"
    assert flow.brand == "tos"
    assert flow.manufacturer == "Toshiba"

    mock_client = MagicMock()
    mock_client.brand = "tos"
    mock_client.client_id = "test_tos_client"
    mock_client.username = "tos123"
    mock_client.password = "pass"
    mock_client.access_token = "token123"
    mock_client.access_token_time = 1700000000
    mock_client.access_token_duration = 3600
    mock_client.refresh_token = "reftoken123"
    mock_client.refresh_token_time = 1700000000
    mock_client.refresh_token_duration = 86400
    mock_client.async_disconnect = AsyncMock()
    mock_client.disconnect = MagicMock()
    flow.client = mock_client

    result_options = await flow.async_step_options(user_input={})
    assert result_options["type"] == "create_entry"
    assert result_options["data"][CONF_BRAND] == "tos"
    assert result_options["data"][CONF_MANUFACTURER] == "Toshiba"


@pytest.mark.anyio
async def test_manual_ip_upnp_brand_autodetect(monkeypatch):
    """Test manual IP entry auto-detects brand from UPnP descriptor before pairing."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    flow.ip_address = "192.168.50.50"
    flow.auth_profile = "auto"
    flow.use_ssl = True

    # Mock query_upnp_descriptor returning Loewe TV descriptor
    mock_upnp = {
        "brand": "loe",
        "manufacturer": "Loewe",
        "model_name": "bild v.65",
        "friendly_name": "Loewe TV",
    }
    monkeypatch.setattr(
        "custom_components.vidaa.tv.fingerprint.query_upnp_descriptor",
        lambda ip, timeout: mock_upnp,
    )

    created_clients = []

    def mock_client_factory(*args, **kwargs):
        client = MagicMock()
        client.brand = kwargs.get("brand", "his")
        client.auth_profile = kwargs.get("auth_profile", "auto")
        client.async_probe_auth_methods = AsyncMock(return_value={})
        client.async_start_auth = AsyncMock()
        created_clients.append(client)
        return client

    monkeypatch.setattr("custom_components.vidaa.config_flow.VidaaClient", mock_client_factory)
    monkeypatch.setattr(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=True))
    monkeypatch.setattr(flow, "async_step_auth", AsyncMock(return_value={"type": "form", "step_id": "auth"}))

    await flow._async_init_client_and_auth()

    assert flow.brand == "loe"
    assert flow.manufacturer == "Loewe"
    assert len(created_clients) == 1
    assert created_clients[0].brand == "loe"


@pytest.mark.anyio
async def test_ssdp_discovery_multi_tv_offers_new_tv():
    """Verify SSDP discovery offers a second TV when a different TV is already configured."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    # Simulate existing TV 1 in config entries
    existing_entry = MagicMock()
    existing_entry.unique_id = "e8:51:77:ec:98:1c"
    existing_entry.data = {CONF_IP_ADDRESS: "192.168.50.12", CONF_MAC_ADDRESS: "e8:51:77:ec:98:1c"}
    flow._async_current_entries = MagicMock(return_value=[existing_entry])

    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    # Discovery arrives for TV 2 (different MAC & IP)
    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:87654321-4321-8765-4321-876543210000::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.15:38400/MediaServer/rendererdevicedesc.xml",
        ssdp_headers={"_host": "192.168.50.15"},
        upnp={
            "friendlyName": "Bedroom TV",
            "manufacturer": "Hisense",
            "modelName": "58A53FXVT",
            "modelDescription": "vidaa_support=1\nbrand=his\nmacWifi=aa:bb:cc:dd:ee:02\n",
        },
    )

    result = await flow.async_step_ssdp(discovery_info)
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"
    assert flow.ip_address == "192.168.50.15"
    assert flow.mac_address == "aa:bb:cc:dd:ee:02"
    flow.async_set_unique_id.assert_awaited_once_with("aa:bb:cc:dd:ee:02")
    flow._abort_if_unique_id_configured.assert_called_once_with(updates={CONF_IP_ADDRESS: "192.168.50.15"})


@pytest.mark.anyio
async def test_ssdp_discovery_dhcp_renewal_updates_ip_and_aborts():
    """Verify SSDP discovery of an existing TV that renewed DHCP IP updates the IP and aborts."""
    from homeassistant.data_entry_flow import AbortFlow

    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    flow.async_set_unique_id = AsyncMock(return_value=None)
    # When unique ID is already configured, HA's _abort_if_unique_id_configured raises AbortFlow("already_configured")
    flow._abort_if_unique_id_configured = MagicMock(side_effect=AbortFlow("already_configured"))

    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:12345678-1234-5678-1234-567812345678::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.99:38400/MediaServer/rendererdevicedesc.xml",
        ssdp_headers={"_host": "192.168.50.99"},
        upnp={
            "friendlyName": "Living Room TV",
            "manufacturer": "Hisense",
            "modelName": "65U7G",
            "modelDescription": "vidaa_support=1\nbrand=his\nmacWifi=e8:51:77:ec:98:1c\n",
        },
    )

    with pytest.raises(AbortFlow) as exc_info:
        await flow.async_step_ssdp(discovery_info)

    assert exc_info.value.reason == "already_configured"
    flow._abort_if_unique_id_configured.assert_called_once_with(updates={CONF_IP_ADDRESS: "192.168.50.99"})


@pytest.mark.anyio
async def test_ssdp_discovery_duplicate_ip_aborts_without_mac():
    """Verify SSDP discovery aborts when IP matches an existing entry even if MAC is not yet resolved."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    existing_entry = MagicMock()
    existing_entry.data = {CONF_IP_ADDRESS: "192.168.50.12"}
    flow._async_current_entries = MagicMock(return_value=[existing_entry])
    flow.async_set_unique_id = AsyncMock()

    discovery_info = SsdpServiceInfo(
        ssdp_usn="uuid:dummy::urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_st="urn:schemas-upnp-org:device:MediaRenderer:1",
        ssdp_location="http://192.168.50.12:38400/MediaServer/rendererdevicedesc.xml",
        ssdp_headers={"_host": "192.168.50.12"},
        upnp={
            "friendlyName": "Living Room TV",
            "manufacturer": "Hisense",
            "modelName": "65U7G",
            "modelDescription": "vidaa_support=1\n",
        },
    )

    result = await flow.async_step_ssdp(discovery_info)
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.anyio
async def test_user_step_legacy_profile_without_certs_proceeds(monkeypatch):
    """Test user flow with legacy profile proceeds without certs (Issue #71)."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    monkeypatch.setattr(
        "custom_components.vidaa.flow.user.async_resolve_mac",
        AsyncMock(return_value="e8:51:77:ec:98:1c"),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.config_flow.VidaaConfigFlow._async_init_client_and_auth",
        AsyncMock(return_value={"type": "form", "step_id": "options"}),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.config_flow.VidaaConfigFlow._async_resolve_ssl_certs",
        AsyncMock(return_value=False),
    )

    result = await flow.async_step_user(user_input={"ip_address": "192.168.1.46", "auth_profile": "legacy"})
    assert result["type"] == "form"
    assert result["step_id"] == "options"
    assert flow.certfile is None
    assert flow.keyfile is None
    assert flow.use_ssl is True
