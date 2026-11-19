"""Tests for Hisense VIDAA media player actions and controls."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaType,
)
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.tv.settings import SettingMenuItem


@pytest.mark.anyio
async def test_media_player_sound_mode_and_waking_state(mock_client, mock_entry):
    """Test dynamic sound mode feature registration and fake sleep waking transitions."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(
        client=mock_client,
        entry=mock_entry,
    )
    mp.hass = hass

    # 1. When TV does NOT report sound mode settings: feature is omitted and sound_mode_list is None
    mock_client.sound_settings = {}
    mock_client.sound_mode = None
    assert mp.sound_mode_list is None
    assert bool(mp.supported_features & MediaPlayerEntityFeature.SELECT_SOUND_MODE) is False

    # 2. When TV reports sound mode menu options: feature is enabled dynamically
    sm_item = SettingMenuItem(menu_id=1, name="Sound Mode", value="Standard", options=["Standard", "Theatre", "Music"])
    mock_client.sound_settings = {1: sm_item}
    mock_client.sound_mode = "Theatre"
    assert mp.sound_mode == "Theatre"
    assert mp.sound_mode_list == ["Standard", "Theatre", "Music"]
    assert bool(mp.supported_features & MediaPlayerEntityFeature.SELECT_SOUND_MODE) is True

    # Select sound mode
    await mp.async_select_sound_mode("Music")
    mock_client.set_sound_mode.assert_called_with("Music")

    # Waking state transition: fake_sleep_1
    mp._handle_state_update({"statetype": "fake_sleep_0"})
    assert mp.state == STATE_OFF
    assert mock_client.is_on is False

    mp._handle_state_update({"statetype": "fake_sleep_1"})
    assert mp.state == STATE_ON
    assert mock_client.is_on is True

    # (c) a statetype containing "off" must be off — state.py and the media_player agree
    # (regression for leg4-F3: unknown off-ish statetypes flipping is_on True)
    mp._handle_state_update({"statetype": "poweroff"})
    assert mp.state == STATE_OFF
    assert mock_client.is_on is False

    # Sound update callback
    mp._handle_sound_update({"menu_id": "sound_mode", "value": "Speech"})


@pytest.mark.anyio
async def test_media_player_idempotent_power_control(mock_client, mock_entry):
    """Test idempotent power control on media player."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mp = VidaaMediaPlayer(
        client=mock_client,
        entry=mock_entry,
    )
    mp.hass = hass
    mock_client.connected = True
    assert mp.state == "on"

    # Calling turn_on when already connected & on must NOT send KEY_POWER
    mock_client.send_key.reset_mock()
    await mp.async_turn_on()
    mock_client.send_key.assert_not_called()
    assert mp.state == "on"

    # In fake sleep, turn_on should wake display
    mp._handle_state_update({"statetype": "fake_sleep_0"})
    assert mp.state == "off"
    await mp.async_turn_on()
    mock_client.send_key.assert_called_once_with("KEY_POWER")
    assert mp.state == "on"

    # Turn off when already off must NOT send KEY_POWER (prevent waking TV via toggle)
    mp._handle_state_update({"statetype": "fake_sleep_0"})
    assert mp.state == "off"
    mock_client.send_key.reset_mock()
    mock_client.async_send_key.reset_mock()
    mock_client.is_on = False
    await mp.async_turn_off()
    mock_client.send_key.assert_not_called()
    mock_client.async_send_key.assert_not_called()


@pytest.mark.anyio
async def test_media_player_turn_on_targets_both_mac_interfaces(mock_client, mock_entry):
    """Wake-on-LAN broadcasts to both primary and secondary MAC addresses to support Wi-Fi and wired Ethernet."""
    from custom_components.vidaa.const import CONF_SECONDARY_MAC_ADDRESS

    mock_entry.data[CONF_SECONDARY_MAC_ADDRESS] = "e4:3b:c9:57:f1:4f"
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.auth_failed = False
    mock_client.async_turn_on = AsyncMock(return_value=True)

    await mp.async_turn_on()

    mock_client.async_turn_on.assert_awaited_once()
    woken_macs = mock_client.async_turn_on.await_args[0][0]
    assert "e8:51:77:ec:98:1c" in woken_macs
    assert "e4:3b:c9:57:f1:4f" in woken_macs


@pytest.mark.anyio
async def test_media_player_mute_is_idempotent(mock_client, mock_entry):
    """[F7-leg4] KEY_MUTE is only sent when the requested state differs from tracked."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass

    # Already unmuted → requesting unmute must not toggle the TV.
    mp._muted = False
    await mp.async_mute_volume(False)
    mock_client.send_key.assert_not_called()

    # Requesting mute differs → send KEY_MUTE.
    await mp.async_mute_volume(True)
    mock_client.send_key.assert_called_once_with("KEY_MUTE")

    # Already muted → requesting mute again must not toggle the TV.
    mp._muted = True
    mock_client.send_key.reset_mock()
    await mp.async_mute_volume(True)
    mock_client.send_key.assert_not_called()

    # Requesting unmute differs → send KEY_MUTE.
    await mp.async_mute_volume(False)
    mock_client.send_key.assert_called_once_with("KEY_MUTE")


@pytest.mark.anyio
async def test_media_player_context_aware_track_controls(mock_client, mock_entry):
    """Test next/prev track context switching between Live TV channels and media fast-forward/rewind."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp._state = "on"

    # 1. On Live TV
    mp._source = "TV"
    mock_client.current_source = "TV"
    mock_client.current_source_id = "TV"
    mock_client.statetype = "livetv"

    assert mp.is_live_tv() is True
    assert mp.media_content_type == MediaType.CHANNEL

    await mp.async_media_next_track()
    mock_client.async_send_key.assert_called_with("KEY_CHANNELUP")

    await mp.async_media_previous_track()
    mock_client.async_send_key.assert_called_with("KEY_CHANNELDOWN")

    # 2. On HDMI (e.g. HDMI2 where current_app might report 'TV Input' but source is HDMI)
    mock_client.async_send_key.reset_mock()
    mp._source = "HDMI2"
    mock_client.current_source = "HDMI2"
    mock_client.current_source_id = "2"
    mock_client.current_app = "TV Input"
    mock_client.statetype = "app"

    assert mp.is_live_tv() is False
    assert mp.media_content_type != MediaType.CHANNEL

    await mp.async_media_next_track()
    mock_client.async_send_key.assert_called_with("KEY_FORWARDS")

    await mp.async_media_previous_track()
    mock_client.async_send_key.assert_called_with("KEY_BACK")

    # 3. In Streaming App (e.g. Netflix)
    mock_client.async_send_key.reset_mock()
    mp._source = "Netflix"
    mp._app_dict = {"Netflix": {"appId": "1", "name": "Netflix"}}
    mock_client.current_source = "Netflix"
    mock_client.statetype = "app"

    assert mp.is_live_tv() is False
    assert mp.media_content_type == MediaType.APP

    await mp.async_media_next_track()
    mock_client.async_send_key.assert_called_with("KEY_FORWARDS")

    await mp.async_media_previous_track()
    mock_client.async_send_key.assert_called_with("KEY_BACK")


@pytest.mark.anyio
async def test_media_player_action_exceptions_when_disconnected(mock_client, mock_entry):
    """Test media player entity actions raise HomeAssistantError when TV is disconnected."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.connected = False
    mock_client.is_on = True

    # 1. async_turn_off raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_turn_off()
    assert exc_info.value.translation_key == "not_connected"

    # 2. async_set_volume_level raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_set_volume_level(0.5)
    assert exc_info.value.translation_key == "not_connected"

    # 3. async_volume_up raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_volume_up()
    assert exc_info.value.translation_key == "not_connected"

    # 4. async_volume_down raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_volume_down()
    assert exc_info.value.translation_key == "not_connected"

    # 5. async_mute_volume raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_mute_volume(True)
    assert exc_info.value.translation_key == "not_connected"

    # 6. Playback controls raise not_connected
    for action in (
        mp.async_media_play,
        mp.async_media_pause,
        mp.async_media_stop,
        mp.async_media_next_track,
        mp.async_media_previous_track,
    ):
        with pytest.raises(HomeAssistantError) as exc_info:
            await action()
        assert exc_info.value.translation_key == "not_connected"

    # 7. async_select_sound_mode raises not_connected
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_select_sound_mode("Theater")
    assert exc_info.value.translation_key == "not_connected"


@pytest.mark.anyio
async def test_media_player_action_exceptions_on_delivery_failure(mock_client, mock_entry):
    """Test media player actions raise HomeAssistantError when client command delivery fails."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.connected = True
    mock_client.is_on = True

    # 1. async_set_volume returns False
    mock_client.async_set_volume = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_set_volume_level(0.4)
    assert exc_info.value.translation_key == "send_key_failed"

    # 2. async_send_key returns False for volume_up
    mock_client.async_send_key = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_volume_up()
    assert exc_info.value.translation_key == "send_key_failed"

    # 3. async_turn_off delivery returns False
    mock_client.async_turn_off = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_turn_off()
    assert exc_info.value.translation_key == "send_key_failed"


@pytest.mark.anyio
async def test_media_player_action_exceptions_on_auth_failed(mock_client, mock_entry):
    """Test media player raises auth_required when client.auth_failed is True."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.auth_failed = True
    mock_client.connected = False

    # 1. async_turn_on raises auth_required
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_turn_on()
    assert exc_info.value.translation_key == "auth_required"

    # 2. async_turn_off raises auth_required
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_turn_off()
    assert exc_info.value.translation_key == "auth_required"

    # 3. async_set_volume_level raises auth_required
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_set_volume_level(0.5)
    assert exc_info.value.translation_key == "auth_required"


@pytest.mark.anyio
async def test_media_player_turn_on_failed_wol(mock_client, mock_entry):
    """Test media player raises turn_on_failed when client.async_turn_on returns False."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.auth_failed = False
    mock_client.async_turn_on = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_turn_on()
    assert exc_info.value.translation_key == "turn_on_failed"


@pytest.mark.anyio
async def test_media_player_actions_raise_when_tv_off(mock_client, mock_entry):
    """Test media player actions raise device_off when TV is in standby/off."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.connected = True
    mock_client.is_on = False

    # 1. async_turn_off is a safe no-op when already off
    await mp.async_turn_off()
    mock_client.async_send_key.assert_not_called()

    # 2. Volume actions raise device_off
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_set_volume_level(0.5)
    assert exc_info.value.translation_key == "device_off"

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_volume_up()
    assert exc_info.value.translation_key == "device_off"

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_volume_down()
    assert exc_info.value.translation_key == "device_off"

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_mute_volume(True)
    assert exc_info.value.translation_key == "device_off"

    # 3. Transport controls raise device_off
    for action in (
        mp.async_media_play,
        mp.async_media_pause,
        mp.async_media_stop,
        mp.async_media_next_track,
        mp.async_media_previous_track,
    ):
        with pytest.raises(HomeAssistantError) as exc_info:
            await action()
        assert exc_info.value.translation_key == "device_off"

    # 4. Sound mode selection raises device_off
    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_select_sound_mode("Theater")
    assert exc_info.value.translation_key == "device_off"


@pytest.mark.anyio
async def test_media_player_turn_on_targets_both_primary_and_secondary_mac(mock_client, mock_entry):
    """Test async_turn_on collects both primary MAC and secondary MAC for WoL broadcast."""
    mock_entry.data["mac_address"] = "e8:51:77:ec:98:1c"
    mock_entry.data["secondary_mac_address"] = "e4:3b:c9:57:f1:4f"
    mock_entry.options["enable_wol"] = True

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = MagicMock(spec=HomeAssistant)

    mock_client.async_turn_on = AsyncMock(return_value=True)

    await mp.async_turn_on()

    mock_client.async_turn_on.assert_awaited_once_with(["e8:51:77:ec:98:1c", "e4:3b:c9:57:f1:4f"])


@pytest.mark.anyio
async def test_media_player_select_source_auto_wakes_and_handles_wake_failure(mock_client, mock_entry):
    """Test async_select_source attempts turn_on when TV is off, and raises turn_on_failed if wake times out."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = MagicMock(spec=HomeAssistant)
    mock_client.connected = False
    mock_client.is_on = False
    mock_client.async_turn_on = AsyncMock(return_value=True)
    mock_client.async_wait_until_awake = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_select_source("HDMI 1")
    assert exc_info.value.translation_key == "turn_on_failed"
    mock_client.async_turn_on.assert_awaited_once()


@pytest.mark.anyio
async def test_media_player_play_media_auto_wakes_and_handles_wake_failure(mock_client, mock_entry):
    """Test async_play_media attempts turn_on when TV is off, and raises turn_on_failed if wake times out."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = MagicMock(spec=HomeAssistant)
    mock_client.connected = False
    mock_client.is_on = False
    mock_client.async_turn_on = AsyncMock(return_value=True)
    mock_client.async_wait_until_awake = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await mp.async_play_media("app", "Netflix")
    assert exc_info.value.translation_key == "turn_on_failed"
    mock_client.async_turn_on.assert_awaited_once()


