"""Tests for VIDAA Smart TV switch platform."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.const import CONF_ENABLE_AUDIO_ONLY
from custom_components.vidaa.switch import (
    HisenseVidaaAudioOnlySwitch,
    HisenseVidaaDebugLoggingSwitch,
    VidaaAudioOnlySwitch,
    VidaaDebugLoggingSwitch,
    async_setup_entry as async_setup_switches,
)


def test_switch_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* switch classes are aliases for Vidaa* switch classes."""
    assert HisenseVidaaAudioOnlySwitch is VidaaAudioOnlySwitch
    assert HisenseVidaaDebugLoggingSwitch is VidaaDebugLoggingSwitch


@pytest.mark.anyio
async def test_switch_entities(mock_client, mock_entry):
    """Test AudioOnly and DebugLogging switch entities."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    sw_audio = VidaaAudioOnlySwitch(mock_client, mock_entry)
    sw_audio.hass = hass
    assert sw_audio.is_on is False
    assert sw_audio.unique_id == "test_entry_id_audio_only"

    # Turn on audio only (idempotent screen off)
    await sw_audio.async_turn_on()
    assert sw_audio.is_on is True
    mock_client.send_key.assert_any_call("KEY_INFO")
    mock_client.send_key.assert_any_call("KEY_AUDIO")

    # Turn off audio only (wake screen)
    mock_client.send_key.reset_mock()
    await sw_audio.async_turn_off()
    assert sw_audio.is_on is False
    mock_client.send_key.assert_called_once_with("KEY_INFO")

    # DebugLogging switch
    sw_debug = VidaaDebugLoggingSwitch(mock_client, mock_entry)
    sw_debug.hass = hass
    assert sw_debug.unique_id == "test_entry_id_debug_logging"

    await sw_debug.async_turn_on()
    assert sw_debug.is_on is True

    await sw_debug.async_turn_off()
    assert sw_debug.is_on is False

    # Platform setup: disabled by default (1 entity: debug_logging)
    mock_entry.options = {CONF_ENABLE_AUDIO_ONLY: False}
    added_switches = []
    await async_setup_switches(hass, mock_entry, lambda entities: added_switches.extend(entities))
    assert len(added_switches) == 1
    assert isinstance(added_switches[0], VidaaDebugLoggingSwitch)

    # Platform setup: enabled (2 entities: debug_logging and audio_only)
    mock_entry.options = {CONF_ENABLE_AUDIO_ONLY: True}
    added_switches_enabled = []
    await async_setup_switches(hass, mock_entry, lambda entities: added_switches_enabled.extend(entities))
    assert len(added_switches_enabled) == 2


def test_switch_disabled_by_default(mock_client, mock_entry):
    """Verify debug logging switch is disabled by default."""
    sw_debug = VidaaDebugLoggingSwitch(mock_client, mock_entry)
    assert sw_debug.entity_registry_enabled_default is False


@pytest.mark.anyio
async def test_switch_action_exceptions(mock_client, mock_entry):
    """Test switch entities raise HomeAssistantError on disconnected or failed actions."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    sw_audio = VidaaAudioOnlySwitch(mock_client, mock_entry)
    sw_audio.hass = hass

    # 1. Audio only switch disconnected: raises not_connected without turning on
    mock_client.connected = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_on()
    assert exc_info.value.translation_key == "not_connected"
    assert sw_audio.is_on is False

    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_off()
    assert exc_info.value.translation_key == "not_connected"

    # 2. Audio only switch connected but send_key fails: raises error without updating is_on
    mock_client.connected = True
    mock_client.async_send_key = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_on()
    assert exc_info.value.translation_key == "send_key_failed"
    assert sw_audio.is_on is False

    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_off()
    assert exc_info.value.translation_key == "send_key_failed"

    # 3. Auth failed raises auth_required
    mock_client.auth_failed = True
    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_on()
    assert exc_info.value.translation_key == "auth_required"

    # 4. When TV is off, turn_on/turn_off raises device_off
    mock_client.auth_failed = False
    mock_client.connected = True
    mock_client.is_on = False

    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_on()
    assert exc_info.value.translation_key == "device_off"

    with pytest.raises(HomeAssistantError) as exc_info:
        await sw_audio.async_turn_off()
    assert exc_info.value.translation_key == "device_off"
