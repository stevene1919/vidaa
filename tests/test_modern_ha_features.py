"""Tests for new modern Home Assistant features in VIDAA integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.media_player import MediaType
from homeassistant.components.remote import RemoteEntityFeature

from custom_components.vidaa.entity import VidaaEntity
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.remote import VidaaRemote
from custom_components.vidaa.repairs import CertificateMissingRepairFlow


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.connected = True
    client.is_on = True
    client.auth_failed = False
    client.ip = "192.168.1.100"
    client.model_name = "58A53FXVT"
    client.manufacturer = "Hisense"
    client.firmware_version = "V0000.01.00a.N1234"
    client.hw_version = "HW_REV_2"
    client.serial_number = "VIDAA_SN_987654"
    client.upnp_location = "http://192.168.1.100:38400/MediaServer/rendererdevicedesc.xml"
    client.app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "httpIcon": "http://192.168.1.100/icons/netflix.png"},
        "YouTube": {"appId": "2", "name": "YouTube", "httpIcon": "http://192.168.1.100/icons/youtube.png"},
    }
    client.source_dict = {
        "HDMI 1": {"sourcename": "HDMI 1", "displayname2": "Apple TV"},
        "HDMI 2": {"sourcename": "HDMI 2", "displayname2": "PlayStation 5"},
    }
    client.current_app = "Netflix"
    client.current_source = "Netflix"
    client.connected_device = None
    client.sound_mode = None
    client.sound_mode_list = None
    client.async_turn_on = AsyncMock(return_value=True)
    client.async_wait_until_awake = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Living Room TV"
    entry.data = {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "ip_address": "192.168.1.100",
        "model": "VIDAA TV",
        "brand": "his",
        "hw_version": "HW_REV_2",
        "serial_number": "VIDAA_SN_987654",
    }
    entry.options = {}
    return entry


@pytest.mark.anyio
async def test_entity_enriched_device_info(mock_client, mock_entry):
    """Test DeviceInfo contains hw_version, serial_number, and configuration_url."""
    entity = VidaaEntity(client=mock_client, entry=mock_entry)
    info = entity.device_info

    assert info.get("hw_version") == "HW_REV_2"
    assert info.get("serial_number") == "VIDAA_SN_987654"
    assert info.get("configuration_url") == "http://192.168.1.100:38400/MediaServer/rendererdevicedesc.xml"


@pytest.mark.anyio
async def test_media_player_browse_media(mock_client, mock_entry):
    """Test media browser tree for applications, inputs, and channels."""
    player = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    player._app_dict = mock_client.app_dict
    player._source_dict = mock_client.source_dict
    player._channel_infos = {"701": {"name": "ABC HD", "number": 701}}

    # Root browser
    root = await player.async_browse_media()
    assert root.can_expand is True
    child_ids = [c.media_content_id for c in root.children]
    assert "apps" in child_ids
    assert "inputs" in child_ids
    assert "channels" in child_ids

    # Apps browser
    apps_node = await player.async_browse_media(media_content_type="apps", media_content_id="apps")
    assert apps_node.title == "Applications"
    app_titles = [c.title for c in apps_node.children]
    assert "Netflix" in app_titles
    assert "YouTube" in app_titles
    assert apps_node.children[0].thumbnail == "http://192.168.1.100/icons/netflix.png"

    # Inputs browser
    inputs_node = await player.async_browse_media(media_content_type="inputs", media_content_id="inputs")
    assert inputs_node.title == "Inputs & Sources"
    assert len(inputs_node.children) >= 2

    # Channels browser
    channels_node = await player.async_browse_media(media_content_type=MediaType.CHANNEL, media_content_id="channels")
    assert channels_node.title == "Live Channels"
    assert any("ABC HD" in c.title for c in channels_node.children)


@pytest.mark.anyio
async def test_remote_activity_feature(mock_client, mock_entry):
    """Test RemoteEntityFeature.ACTIVITY, activity_list, and async_turn_on with activity."""
    remote = VidaaRemote(client=mock_client, entry=mock_entry)
    assert remote.supported_features & RemoteEntityFeature.ACTIVITY

    # Current activity matches active app
    assert remote.current_activity == "Netflix"

    # Activity list contains sources and apps
    act_list = remote.activity_list
    assert act_list is not None
    assert "Netflix" in act_list

    # async_turn_on with activity delegates to async_execute_select_source
    with patch("custom_components.vidaa.remote.async_execute_select_source", new_callable=AsyncMock) as mock_sel:
        mock_sel.return_value = True
        await remote.async_turn_on(activity="YouTube")
        mock_sel.assert_awaited_once_with(mock_client, mock_client.source_dict, mock_client.app_dict, "YouTube")


@pytest.mark.anyio
async def test_repairs_certificate_missing_upload(mock_client, mock_entry):
    """Test interactive certificate upload directly inside CertificateMissingRepairFlow."""
    flow = CertificateMissingRepairFlow(entry_id="test_entry_123")
    hass = MagicMock()
    hass.config.path.return_value = "/mock/storage/vidaa/certs"
    hass.config_entries.async_get_entry.return_value = mock_entry
    flow.hass = hass

    with (
        patch("custom_components.vidaa.repairs.process_uploaded_file") as mock_proc,
        patch("custom_components.vidaa.repairs.extract_and_install_certs") as mock_ext,
    ):
        mock_proc.return_value.__enter__.return_value = "/tmp/upload.p12"
        mock_ext.return_value = ("/mock/certs/hisense.crt", "/mock/certs/hisense.key")

        res = await flow.async_step_confirm(user_input={"cert_file": "file_id_abc"})
        assert res["type"] == "create_entry"
        hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = hass.config_entries.async_update_entry.call_args[1]
        assert call_kwargs["options"]["certfile"] == "/mock/certs/hisense.crt"
        assert call_kwargs["options"]["keyfile"] == "/mock/certs/hisense.key"
        hass.config_entries.async_reload.assert_called_once_with("test_entry_123")
