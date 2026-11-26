"""Targeted unit tests closing entity-platform and artwork branch coverage."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_OFF
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.artwork import (
    ArtworkReachabilityTracker,
    extract_http_icon_url,
    register_artwork_reachability_probe,
)
from custom_components.vidaa.binary_sensor import (
    VidaaAuthProblemBinarySensor,
    VidaaInUseBinarySensor,
    VidaaMqttConnectedBinarySensor,
)
from custom_components.vidaa.button import VidaaForceReconnectButton, VidaaProbeCapabilitiesButton
from custom_components.vidaa.const import CONF_ENABLE_PICTURE_CONTROLS, CONF_ENABLE_SOUND_CONTROLS
from custom_components.vidaa.media_player import VidaaMediaPlayer, async_setup_entry as mp_setup_entry
from custom_components.vidaa.number import VidaaBacklightNumber, VidaaBrightnessNumber, VidaaContrastNumber
from custom_components.vidaa.select import VidaaPictureModeSelect, VidaaSoundModeSelect
from custom_components.vidaa.sensor import VidaaActiveAppSensor, VidaaActiveSourceSensor
from custom_components.vidaa.sensor.diagnostic import (
    VidaaClockDriftSensor,
    VidaaReportedNameSensor,
    VidaaSessionStatusSensor,
)


@pytest.mark.anyio
async def test_binary_sensor_lifecycle_and_standby_states(mock_client, mock_entry) -> None:
    """Cover callback registration/unregistration and standby checks on binary sensors."""
    s_conn = VidaaMqttConnectedBinarySensor(mock_client, mock_entry)
    s_use = VidaaInUseBinarySensor(mock_client, mock_entry)
    s_auth = VidaaAuthProblemBinarySensor(mock_client, mock_entry)

    for ent in (s_conn, s_use, s_auth):
        await ent.async_added_to_hass()
        await ent.async_will_remove_from_hass()

    mock_client.connected = True
    mock_client.is_on = True
    mock_client.state = "standby"
    assert s_use.is_on is False


@pytest.mark.anyio
async def test_media_player_lifecycle_properties_and_control_errors(mock_client, mock_entry) -> None:
    """Cover media_player lifecycle hooks, off-state properties, and control failure branches."""
    hass = MagicMock()
    hass.loop = asyncio.get_running_loop()
    hass.async_create_background_task = MagicMock(side_effect=lambda coro, *a, **kw: hass.loop.create_task(coro))

    tracker = ArtworkReachabilityTracker(enabled=True)
    turn_on_action = MagicMock()
    turn_on_action.async_register = MagicMock(return_value=lambda: None)
    mock_entry.runtime_data = SimpleNamespace(client=mock_client, artwork_tracker=tracker, turn_on=turn_on_action)
    mock_entry.options = {"enable_media_controls": True}

    mock_client.connected = True
    mock_client.is_on = True
    mock_client.source_dict = {}
    mock_client.app_dict = {}
    mock_client.apps = []
    mock_client.async_query_initial_state = AsyncMock()

    added: list = []
    await mp_setup_entry(hass, mock_entry, added.extend)
    assert len(added) == 1
    mp: VidaaMediaPlayer = added[0]
    mp.hass = hass
    mp.registry_entry = SimpleNamespace(device_id="dev_123")

    await mp.async_added_to_hass()
    mock_client.async_query_initial_state.assert_awaited_once()
    mp._debounce_handle = MagicMock()
    await mp.async_will_remove_from_hass()
    mp._debounce_handle is None

    assert mp.unique_id == f"{mock_entry.entry_id}_media_player"
    mp._channel_infos = {"1": {"name": "ABC"}}
    mp._channel_name = "ABC"
    mp._channel_num = "2"
    assert mp.media_channel == "2 ABC"
    assert "channel_infos" in mp.extra_state_attributes

    # When off, media metadata properties return None
    mp._state = STATE_OFF
    assert mp.app_name is None
    assert mp.app_id is None
    assert mp.media_content_type is None
    assert mp.media_title is None
    assert mp.media_series_title is None

    # Playback controls: success + failure paths
    mp._state = "on"
    mock_client.async_send_key = AsyncMock(return_value=True)
    await mp.async_media_play()
    await mp.async_media_pause()
    await mp.async_media_stop()

    mock_client.async_send_key = AsyncMock(return_value=False)
    for call in (
        mp.async_volume_up(),
        mp.async_volume_down(),
        mp.async_mute_volume(True),
        mp.async_media_play(),
        mp.async_media_pause(),
        mp.async_media_stop(),
        mp.async_media_next_track(),
        mp.async_media_previous_track(),
    ):
        with pytest.raises(HomeAssistantError):
            await call

    mock_client.async_set_sound_mode = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError):
        await mp.async_select_sound_mode("Theatre")

    with (
        patch("custom_components.vidaa.media_player.controls.async_execute_play_media", AsyncMock(return_value=False)),
        pytest.raises(HomeAssistantError),
    ):
        await mp.async_play_media("app", "Netflix")

    with (
        patch(
            "custom_components.vidaa.media_player.controls.async_execute_select_source", AsyncMock(return_value=False)
        ),
        pytest.raises(HomeAssistantError),
    ):
        await mp.async_select_source("HDMI1")


@pytest.mark.anyio
async def test_buttons_sensors_select_number_and_artwork_branches(mock_client, mock_entry) -> None:
    """Cover button press error/probe paths, sensor/select/number lifecycles, and artwork tracker edges."""
    hass = MagicMock()
    hass.loop = asyncio.get_running_loop()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=lambda coro, *a, **kw: hass.loop.create_task(coro))

    # Buttons: ForceReconnect & ProbeCapabilities
    btn_reconn = VidaaForceReconnectButton(mock_client, mock_entry)
    mock_client.auth_failed = True
    with pytest.raises(HomeAssistantError):
        await btn_reconn.async_press()

    mock_client.auth_failed = False
    mock_client.connected = False
    mock_client.async_disconnect = AsyncMock()
    mock_client.async_connect_and_run = AsyncMock()
    with (
        patch("asyncio.sleep", AsyncMock()),
        pytest.raises(HomeAssistantError),
    ):
        await btn_reconn.async_press()

    mock_client.async_connect_and_run = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(HomeAssistantError):
        await btn_reconn.async_press()

    btn_probe = VidaaProbeCapabilitiesButton(mock_client, mock_entry)
    btn_probe.hass = hass
    mock_client.connected = True
    mock_client.is_on = True
    mock_client.picture_settings = {91: MagicMock()}
    mock_client.sound_settings = {1: MagicMock()}
    mock_client.async_get_picture_settings = AsyncMock()
    mock_client.async_get_sound_settings = AsyncMock()
    with patch("asyncio.sleep", AsyncMock()):
        await btn_probe.async_press()
    assert hass.config_entries.async_update_entry.call_args.kwargs["options"][CONF_ENABLE_PICTURE_CONTROLS] is True
    assert hass.config_entries.async_update_entry.call_args.kwargs["options"][CONF_ENABLE_SOUND_CONTROLS] is True

    # Sensors lifecycle & state branches
    tracker = ArtworkReachabilityTracker(enabled=True)
    mock_entry.runtime_data = SimpleNamespace(client=mock_client, artwork_tracker=tracker)
    app_sensor = VidaaActiveAppSensor(mock_client, mock_entry)
    src_sensor = VidaaActiveSourceSensor(mock_client, mock_entry)
    sess_sensor = VidaaSessionStatusSensor(mock_client, mock_entry)
    name_sensor = VidaaReportedNameSensor(mock_client, mock_entry)
    drift_sensor = VidaaClockDriftSensor(mock_client, mock_entry)

    for s in (app_sensor, src_sensor, sess_sensor, name_sensor, drift_sensor):
        await s.async_added_to_hass()
        await s.async_will_remove_from_hass()

    app_sensor._handle_state_update({"statetype": "livetv"})
    assert app_sensor.native_value == "Live TV"
    app_sensor._handle_state_update({"statetype": "fake_sleep_0"})
    assert app_sensor.native_value == "Standby"
    app_sensor._handle_state_update({"statetype": "other", "appId": "99"})
    assert app_sensor.native_value == "99"

    src_sensor._handle_state_update({"statetype": "livetv"})
    assert src_sensor.native_value == "TV"
    src_sensor._handle_state_update({"statetype": "launcher"})
    assert src_sensor.native_value == "Home Launcher"
    src_sensor._handle_state_update({"sourcename": "HDMI3"})
    assert src_sensor.native_value == "HDMI3"

    name_sensor._handle_state_or_info({"friendly_name": "Den TV"})
    mock_client.clock_offset = None
    drift_sensor._update_state()
    assert drift_sensor.extra_state_attributes["synchronized"] is False

    # Select & Number fallback properties
    pic_sel = VidaaPictureModeSelect(mock_client, mock_entry)
    snd_sel = VidaaSoundModeSelect(mock_client, mock_entry)
    mock_client.picture_settings = {}
    mock_client.sound_settings = {}
    mock_client.picture_mode = None
    mock_client.sound_mode = None
    assert "Standard" in pic_sel.options
    assert "Standard" in snd_sel.options
    assert pic_sel.current_option == "Standard"
    assert snd_sel.current_option == "Standard"

    for num_cls in (VidaaBacklightNumber, VidaaBrightnessNumber, VidaaContrastNumber):
        n = num_cls(mock_client, mock_entry)
        n._update_value_from_client()

    # Artwork edge helpers
    assert extract_http_icon_url("ftp://example.com/icon.png") is None

    def _bad_cb() -> None:
        raise RuntimeError("cb fail")

    tracker.register_listener(_bad_cb)
    tracker.set_reachable(False)
    tracker.unregister_listener(_bad_cb)
    tracker._probe_task = asyncio.create_task(asyncio.sleep(0))
    tracker.cancel()
    await asyncio.sleep(0)

    mock_client.apps = [{"name": "Netflix", "httpIcon": "https://img.vidaahub.com/nf.png"}]
    with (
        patch("custom_components.vidaa.artwork.async_get_clientsession", return_value=MagicMock()),
        patch.object(tracker, "async_probe_url", AsyncMock(return_value=True)),
    ):
        register_artwork_reachability_probe(hass, mock_entry, mock_client, tracker)
        await asyncio.sleep(0)
