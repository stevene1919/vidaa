"""Tests for Hisense VIDAA media player entity lifecycle, state, and attributes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant

from custom_components.vidaa.const import CONF_ENABLE_MEDIA_CONTROLS, DOMAIN, LEGACY_DOMAIN
from custom_components.vidaa.media_player import HisenseVidaaMediaPlayer, VidaaMediaPlayer
from custom_components.vidaa.media_player.controls import MediaPlayerControlsMixin


def test_media_player_backwards_compatibility_alias():
    """Verify HisenseVidaaMediaPlayer is an alias for VidaaMediaPlayer for backwards compatibility."""
    assert HisenseVidaaMediaPlayer is VidaaMediaPlayer


def test_media_player_device_info(mock_client, mock_entry):
    """Test device info registration for media player."""
    mp = VidaaMediaPlayer(
        client=mock_client,
        entry=mock_entry,
    )
    dev_info = mp.device_info
    assert mp.device_class == MediaPlayerDeviceClass.TV
    assert dev_info["identifiers"] == {(DOMAIN, "test_entry_id"), (LEGACY_DOMAIN, "test_entry_id")}
    assert dev_info["model"] == "65U7G"
    assert dev_info["manufacturer"] == "Hisense"
    assert dev_info["sw_version"] == "V1.0"
    assert ("mac", "e8:51:77:aa:bb:cc") in dev_info["connections"]

    # When secondary MAC is configured or client discovers ethernet MAC, both appear in connections
    mock_entry.data["secondary_mac_address"] = "e4:3b:c9:aa:bb:cc"
    dev_info_dual = mp.device_info
    assert ("mac", "e8:51:77:aa:bb:cc") in dev_info_dual["connections"]
    assert ("mac", "e4:3b:c9:aa:bb:cc") in dev_info_dual["connections"]


def test_media_player_availability_on_auth_failure(mock_client, mock_entry):
    """Test media_player reports unavailable when client.auth_failed is True."""
    mock_client.auth_failed = False
    mock_client.connected = False
    mock_client.is_on = False
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)

    # Standby / offline without auth failure remains available and reports off
    assert mp.available is True
    assert mp.state == "off"

    # When TV broker rejects credentials, entity becomes unavailable
    mock_client.auth_failed = True
    assert mp.available is False

    # Test callback handler triggers state update
    mp._schedule_ha_update = MagicMock()
    mp._handle_auth_failed()
    mp._schedule_ha_update.assert_called_once()


def test_media_player_assumed_state(mock_client, mock_entry):
    """Test media player state and features respect enable_media_controls option."""
    # 1. By default (enable_media_controls=False): assumed_state is False, state is STATE_ON
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.is_on = True
    mock_client.connected = True
    assert mp.assumed_state is False
    assert mp.state == STATE_ON
    assert not (mp.supported_features & MediaPlayerEntityFeature.PLAY)

    # 2. When enable_media_controls is explicitly enabled in options:
    # assumed_state is still False (never splits power buttons into | and O),
    # but state becomes STATE_PLAYING so frontend renders channel/track controls cleanly.
    mock_entry.options = {CONF_ENABLE_MEDIA_CONTROLS: True}
    mp_with_controls = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    assert mp_with_controls.assumed_state is False
    assert mp_with_controls.state == STATE_PLAYING
    assert bool(mp_with_controls.supported_features & MediaPlayerEntityFeature.PLAY)

    # Test pause toggle
    mp_with_controls._paused = True
    assert mp_with_controls.state == STATE_PAUSED
    mp_with_controls._paused = False
    assert mp_with_controls.state == STATE_PLAYING

    mock_client.is_on = False
    assert mp_with_controls.state == STATE_OFF


@pytest.mark.anyio
async def test_media_player_string_volume_broadcast(mock_client, mock_entry):
    """[F9-leg4] String volume payloads are coerced like apply_volume_update."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass

    mp._handle_volume_update({"volume_type": "1", "volume_value": "35"})
    assert mp._volume == 35
    assert mp._volume_type == 1
    assert mp.volume_level == 0.35

    # Mute broadcast as a string
    mp._handle_volume_update({"volume_type": "2", "volume_value": "1"})
    assert mp._muted is True


@pytest.mark.anyio
async def test_media_player_playback_state_debounce(mock_client, mock_entry):
    """Test transient state debounce delays state apply until timer expires."""
    import asyncio

    hass = MagicMock(spec=HomeAssistant)
    loop = asyncio.get_running_loop()
    hass.loop = loop
    hass.async_add_executor_job = MagicMock(side_effect=lambda func, *args: func(*args))
    hass.async_create_background_task = MagicMock(side_effect=lambda coro, *a, **kw: loop.create_task(coro))

    mock_entry.options = {"playback_debounce": 0.05}
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass

    # Transient app state update
    mp._handle_state_update({"statetype": "app", "name": "YouTube", "is_on": True})
    assert mp._debounce_handle is not None
    assert mp._source != "YouTube"

    # Wait for debounce duration
    await asyncio.sleep(0.08)
    assert mp._source == "YouTube"
    assert mp.state == STATE_ON

    # Power off: applies immediately without debounce
    mp._handle_state_update({"statetype": "fake_sleep_0", "is_on": False})
    assert mp._debounce_handle is None
    assert mp.state == STATE_OFF


@pytest.mark.anyio
async def test_media_player_disconnected_and_cold_boot_recovery(mock_client, mock_entry):
    """Test powered-off / disconnected states and cold-boot recovery via sourcelist."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass

    # Initially connected and on
    mock_client.connected = True
    mock_client.is_on = True
    assert mp.state == STATE_ON

    # 1. When client is not connected: state must be STATE_OFF
    mock_client.connected = False
    assert mp.state == STATE_OFF

    # Disconnect handler resets is_on and marks state OFF
    mock_client.connected = True
    mock_client.is_on = True
    mp._handle_disconnected()
    assert mock_client.is_on is False
    assert mp.state == STATE_OFF

    # 2. Standby / cold-boot query: TV is in standby (is_on=False) and sends sourcelist
    mock_client.connected = True
    mock_client.is_on = False
    mock_client.current_source = None
    mp._source = None

    sourcelist_data = [
        {"sourceid": "0", "sourcename": "TV", "is_signal": 0, "is_active": False},
        {"sourceid": "1", "sourcename": "HDMI 1", "is_signal": 1, "is_active": True},
    ]
    mp._handle_sourcelist_update(sourcelist_data)

    # Sourcelist updates cached sources, but must NOT falsely wake the TV while in standby
    assert mock_client.is_on is False
    assert mock_client.current_source == "HDMI 1"
    assert mp.source == "HDMI 1"
    assert mp.state == STATE_OFF

    # State update broadcast wakes the TV
    mp._handle_state_update({"statetype": "sourceswitch", "sourcename": "HDMI 1"})
    assert mock_client.is_on is True
    assert mp.state == STATE_ON


def test_media_player_extra_state_attributes_and_standard_properties(mock_client, mock_entry):
    """Test extra_state_attributes omits DeviceInfo duplicates and exposes standard app/title properties."""
    mock_client.device_name = "Hisense Bedroom TV"
    mock_client.model_name = "58A53FXVT"
    mock_client.firmware_version = "V0000.06.30T.N0921"
    mock_client.connected = True
    mock_client.brand = "his"
    mock_client.current_program = None

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp._state = STATE_ON
    mp._source = "HDMI2"
    mp._source_dict = {
        "HDMI1": {"sourceid": "HDMI1", "sourcename": "HDMI1", "displayname2": "Chromecast"},
        "HDMI2": {"sourceid": "HDMI2", "sourcename": "HDMI2"},
    }
    mp._app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "url": "netflix://"},
    }

    attrs = mp.extra_state_attributes
    # DeviceInfo / diagnostic duplicates must NOT be in extra_state_attributes
    for key in (
        "reported_name",
        "model",
        "software_version",
        "mac_address",
        "mqtt_connected",
        "auth_profile",
        "brand_profile",
        "active_brand",
    ):
        assert key not in attrs

    # Source / audio runtime attributes remain present
    assert attrs["audio_output"] == "TV Speakers"
    assert attrs["raw_source"] == "HDMI2"
    assert attrs["custom_labels"] == {"HDMI1": "Chromecast"}

    # On unlabeled HDMI2: media_title, app_name, and app_id are None (no duplicate "HDMI2" title)
    assert mp.media_title is None
    assert mp.app_name is None
    assert mp.app_id is None

    # On labeled HDMI1: media_title resolves to connected CEC/custom label
    mp._source = "HDMI1"
    assert mp.media_title == "Chromecast"
    assert mp.app_name is None
    assert mp.app_id is None

    # When running an app: standard app_name and app_id are populated, media_title is None
    mp._source = "Netflix"
    assert mp.app_name == "Netflix"
    assert mp.app_id == "1"
    assert mp.media_title is None

    # When watching Live TV with EPG program: media_title returns current_program
    mp._source = "TV"
    mock_client.current_program = "Evening News"
    assert mp.media_title == "Evening News"


def test_media_player_audio_output_attribute(mock_client, mock_entry):
    """audio_output attribute tracks volume_type (0=TV Speakers, 1=ARC/eARC); mute does not change it."""
    mock_client.connected = True
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = None
    assert mp.extra_state_attributes["audio_output"] == "TV Speakers"

    mp._handle_volume_update({"volume_type": "1", "volume_value": 5})
    assert mp.extra_state_attributes["audio_output"] == "ARC / eARC"

    mp._handle_volume_update({"volume_type": 2, "volume_value": 0})
    assert mp.extra_state_attributes["audio_output"] == "ARC / eARC"

    mp._handle_volume_update({"volume_type": 0, "volume_value": 5})
    assert mp.extra_state_attributes["audio_output"] == "TV Speakers"


def test_media_player_mro_precedence():
    """Ensure MediaPlayerControlsMixin overrides Home Assistant MediaPlayerEntity stubs."""
    # Check that async control methods resolve to MediaPlayerControlsMixin
    assert VidaaMediaPlayer.async_turn_on == MediaPlayerControlsMixin.async_turn_on
    assert VidaaMediaPlayer.async_turn_off == MediaPlayerControlsMixin.async_turn_off
    assert VidaaMediaPlayer.async_set_volume_level == MediaPlayerControlsMixin.async_set_volume_level
    assert VidaaMediaPlayer.async_mute_volume == MediaPlayerControlsMixin.async_mute_volume
    assert VidaaMediaPlayer.async_select_source == MediaPlayerControlsMixin.async_select_source
    assert VidaaMediaPlayer.async_play_media == MediaPlayerControlsMixin.async_play_media
