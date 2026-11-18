"""Tests for VIDAA Smart TV number platform."""

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.const import (
    CONF_ENABLE_PICTURE_CONTROLS,
    DOMAIN,
)
from custom_components.vidaa.number import (
    HisenseVidaaBacklightNumber,
    HisenseVidaaBrightnessNumber,
    HisenseVidaaContrastNumber,
    VidaaBacklightNumber,
    VidaaBrightnessNumber,
    VidaaContrastNumber,
    async_setup_entry as async_setup_number_entry,
)


def test_number_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* classes are aliases for Vidaa* number classes."""
    assert HisenseVidaaBacklightNumber is VidaaBacklightNumber
    assert HisenseVidaaBrightnessNumber is VidaaBrightnessNumber
    assert HisenseVidaaContrastNumber is VidaaContrastNumber


@pytest.mark.anyio
async def test_picture_calibration_numbers(mock_client, mock_entry):
    """Test Picture calibration number slider entities (Backlight, Brightness, Contrast)."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop_thread_id = threading.get_ident()
    hass.loop = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    bl = VidaaBacklightNumber(
        client=mock_client,
        entry=mock_entry,
    )
    bl.hass = hass
    bl.entity_id = "number.backlight"
    assert bl.unique_id == "test_entry_id_backlight"
    assert bl.native_min_value == 0
    assert bl.native_max_value == 100
    await bl.async_set_native_value(85)
    mock_client.set_backlight.assert_called_with(85)

    br = VidaaBrightnessNumber(
        client=mock_client,
        entry=mock_entry,
    )
    br.hass = hass
    br.entity_id = "number.brightness"
    assert br.unique_id == "test_entry_id_brightness"
    await br.async_set_native_value(52)
    mock_client.set_brightness.assert_called_with(52)

    ct = VidaaContrastNumber(
        client=mock_client,
        entry=mock_entry,
    )
    ct.hass = hass
    ct.entity_id = "number.contrast"
    assert ct.unique_id == "test_entry_id_contrast"
    await ct.async_set_native_value(90)
    mock_client.set_contrast.assert_called_with(90)


@pytest.mark.anyio
async def test_number_platform_lifecycle(mock_client, mock_entry, monkeypatch):
    """Test number platform creation, options gating, and lifecycle registration."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {mock_entry.entry_id: {"client": mock_client}}}
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_reg = MagicMock()
    mock_reg.async_get_entity_id.return_value = None
    monkeypatch.setattr("homeassistant.helpers.entity_registry.async_get", lambda h: mock_reg)

    # 1. Default options: picture controls disabled
    mock_entry.options = {}
    default_number_entities = []
    await async_setup_number_entry(hass, mock_entry, lambda entities: default_number_entities.extend(entities))
    assert len(default_number_entities) == 0

    # 2. Enabled options: picture controls enabled
    mock_entry.options = {CONF_ENABLE_PICTURE_CONTROLS: True}
    number_entities = []
    await async_setup_number_entry(hass, mock_entry, lambda entities: number_entities.extend(entities))
    assert len(number_entities) == 3

    for num in number_entities:
        await num.async_added_to_hass()
        await num.async_will_remove_from_hass()


@pytest.mark.anyio
async def test_number_availability_and_callbacks(mock_client, mock_entry):
    """Test number availability during online/offline states and callback registration."""
    bl = VidaaBacklightNumber(mock_client, mock_entry)

    mock_client.connected = True
    assert bl.available is True

    mock_client.connected = False
    assert bl.available is False

    await bl.async_added_to_hass()
    mock_client.register_connected_callback.assert_called()
    mock_client.register_disconnected_callback.assert_called()


@pytest.mark.anyio
async def test_number_action_exceptions_and_no_optimistic_update(mock_client, mock_entry):
    """Verify number entities raise HomeAssistantError and do not desync state on failure."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop_thread_id = threading.get_ident()
    hass.loop = MagicMock()
    hass.data = {}
    hass.states = MagicMock()

    bl = VidaaBacklightNumber(client=mock_client, entry=mock_entry)
    bl.hass = hass
    bl.entity_id = "number.backlight"
    mock_client.backlight = None

    # 1. When disconnected, setting value raises not_connected without updating value
    mock_client.connected = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await bl.async_set_native_value(30)
    assert exc_info.value.translation_key == "not_connected"
    assert bl.native_value == 80.0

    # 2. When connected but client publish returns False: raises error without updating cached state
    mock_client.connected = True
    mock_client.async_set_backlight = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await bl.async_set_native_value(30)
    assert exc_info.value.translation_key == "set_picture_setting_failed"
    assert bl.native_value == 80.0

    # 3. When auth_failed is True, setting value raises auth_required
    mock_client.auth_failed = True
    with pytest.raises(HomeAssistantError) as exc_info:
        await bl.async_set_native_value(30)
    assert exc_info.value.translation_key == "auth_required"

    # 4. When TV is off, setting value raises device_off
    mock_client.auth_failed = False
    mock_client.connected = True
    mock_client.is_on = False

    with pytest.raises(HomeAssistantError) as exc_info:
        await bl.async_set_native_value(30)
    assert exc_info.value.translation_key == "device_off"
