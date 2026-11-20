"""Tests for VIDAA Smart TV button platform."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.button import (
    HisenseVidaaForceReconnectButton,
    HisenseVidaaProbeCapabilitiesButton,
    HisenseVidaaSyncClockButton,
    HisenseVidaaTriggerReauthButton,
    VidaaForceReconnectButton,
    VidaaProbeCapabilitiesButton,
    VidaaSyncClockButton,
    VidaaTriggerReauthButton,
    async_setup_entry as async_setup_buttons,
)


def test_button_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* button classes are aliases for Vidaa* button classes."""
    assert HisenseVidaaForceReconnectButton is VidaaForceReconnectButton
    assert HisenseVidaaSyncClockButton is VidaaSyncClockButton
    assert HisenseVidaaProbeCapabilitiesButton is VidaaProbeCapabilitiesButton
    assert HisenseVidaaTriggerReauthButton is VidaaTriggerReauthButton


@pytest.mark.anyio
async def test_button_entities(mock_client, mock_entry):
    """Test button entity execution and setup registration."""
    import threading

    hass = MagicMock(spec=HomeAssistant)
    hass.loop_thread_id = threading.get_ident()
    hass.loop = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    b_reconnect = VidaaForceReconnectButton(mock_client, mock_entry)
    b_reconnect.hass = hass
    await b_reconnect.async_press()
    mock_client.disconnect.assert_called_once()
    mock_client.connect_and_run.assert_called_once()

    b_sync = VidaaSyncClockButton(mock_client, mock_entry)
    b_sync.hass = hass
    await b_sync.async_press()
    mock_client.sync_clock.assert_called_once()

    b_reauth = VidaaTriggerReauthButton(mock_client, mock_entry)
    b_reauth.hass = hass
    assert b_reauth.unique_id == "test_entry_id_trigger_reauth"
    await b_reauth.async_press()
    mock_client._dispatch_auth_failed.assert_called_once()
    mock_entry.async_start_reauth.assert_called_once_with(hass)
    assert "vidaa_reauth_test_entry_id" in hass.data.get("persistent_notification", {})

    added_buttons = []
    await async_setup_buttons(hass, mock_entry, lambda entities: added_buttons.extend(entities))
    assert len(added_buttons) == 4
    assert any(isinstance(b, VidaaTriggerReauthButton) for b in added_buttons)


def test_button_disabled_by_default(mock_client, mock_entry):
    """Verify specialized probe capabilities button is disabled by default."""
    b_probe = VidaaProbeCapabilitiesButton(mock_client, mock_entry)
    assert b_probe.entity_registry_enabled_default is False


@pytest.mark.anyio
async def test_button_action_exceptions(mock_client, mock_entry):
    """Test button entities raise HomeAssistantError on disconnected or failed actions."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    b_sync = VidaaSyncClockButton(mock_client, mock_entry)
    b_sync.hass = hass

    b_probe = VidaaProbeCapabilitiesButton(mock_client, mock_entry)
    b_probe.hass = hass

    # 1. Clock sync button raises error when UPnP sync fails (returns None)
    mock_client.async_sync_clock = AsyncMock(return_value=None)
    with pytest.raises(HomeAssistantError) as exc_info:
        await b_sync.async_press()
    assert exc_info.value.translation_key == "send_key_failed"

    # 2. Probe capabilities button raises not_connected when TV disconnected
    mock_client.connected = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await b_probe.async_press()
    assert exc_info.value.translation_key == "not_connected"

    # 3. Auth failed raises auth_required
    mock_client.auth_failed = True
    with pytest.raises(HomeAssistantError) as exc_info:
        await b_probe.async_press()
    assert exc_info.value.translation_key == "auth_required"

    # 4. Probe capabilities button raises device_off when TV is off
    mock_client.auth_failed = False
    mock_client.connected = True
    mock_client.is_on = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await b_probe.async_press()
    assert exc_info.value.translation_key == "device_off"
