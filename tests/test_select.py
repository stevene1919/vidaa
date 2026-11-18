"""Tests for VIDAA Smart TV select platform."""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.const import (
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_SOUND_CONTROLS,
    DOMAIN,
)
from custom_components.vidaa.select import (
    HisenseVidaaPictureModeSelect,
    HisenseVidaaSoundModeSelect,
    VidaaPictureModeSelect,
    VidaaSoundModeSelect,
    async_setup_entry as async_setup_select_entry,
)


def test_select_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* classes are aliases for Vidaa* select classes."""
    assert HisenseVidaaPictureModeSelect is VidaaPictureModeSelect
    assert HisenseVidaaSoundModeSelect is VidaaSoundModeSelect


@pytest.mark.anyio
async def test_select_platform_prunes_audio_output_select(mock_client, mock_entry):
    """Test select platform setup prunes retired audio_output_select from entity registry."""
    hass = MagicMock(spec=HomeAssistant)
    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.side_effect = lambda domain, platform, uid: (
        "select.hisense_tv_audio_output_mode" if "audio_output_select" in uid else None
    )

    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_registry):
        async_add_entities = MagicMock()
        mock_entry.options = {
            "enable_picture_controls": False,
            "enable_sound_controls": False,
        }
        await async_setup_select_entry(hass, mock_entry, async_add_entities)

    mock_registry.async_remove.assert_called_with("select.hisense_tv_audio_output_mode")
    async_add_entities.assert_not_called()


@pytest.mark.anyio
async def test_picture_and_sound_mode_selects(mock_client, mock_entry):
    """Test Picture Mode and Sound Mode select dropdowns."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop_thread_id = threading.get_ident()
    hass.loop = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    pic_sel = VidaaPictureModeSelect(
        client=mock_client,
        entry=mock_entry,
    )
    pic_sel.hass = hass
    pic_sel.entity_id = "select.picture_mode"
    assert pic_sel.unique_id == "test_entry_id_picture_mode"
    assert "Standard" in pic_sel.options

    await pic_sel.async_select_option("Cinema Day")
    mock_client.set_picture_mode.assert_called_with("Cinema Day")

    snd_sel = VidaaSoundModeSelect(
        client=mock_client,
        entry=mock_entry,
    )
    snd_sel.hass = hass
    snd_sel.entity_id = "select.sound_mode"
    assert snd_sel.unique_id == "test_entry_id_sound_mode"
    assert "Standard" in snd_sel.options

    await snd_sel.async_select_option("Theater")
    mock_client.set_sound_mode.assert_called_with("Theater")


@pytest.mark.anyio
async def test_select_platform_lifecycle(mock_client, mock_entry, monkeypatch):
    """Test select platform creation, options gating, and lifecycle registration."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {mock_entry.entry_id: {"client": mock_client}}}
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_reg = MagicMock()
    mock_reg.async_get_entity_id.return_value = None
    monkeypatch.setattr("homeassistant.helpers.entity_registry.async_get", lambda h: mock_reg)

    # 1. Default options: picture and sound controls disabled
    mock_entry.options = {}
    default_select_entities = []
    await async_setup_select_entry(hass, mock_entry, lambda entities: default_select_entities.extend(entities))
    assert len(default_select_entities) == 0

    # 2. Enabled options: picture and sound controls enabled
    mock_entry.options = {
        CONF_ENABLE_PICTURE_CONTROLS: True,
        CONF_ENABLE_SOUND_CONTROLS: True,
    }
    select_entities = []
    await async_setup_select_entry(hass, mock_entry, lambda entities: select_entities.extend(entities))
    assert len(select_entities) == 2

    for sel in select_entities:
        await sel.async_added_to_hass()
        await sel.async_will_remove_from_hass()


@pytest.mark.anyio
async def test_select_availability_and_callbacks(mock_client, mock_entry):
    """Test select availability during online/offline states and callback registration."""
    pic_sel = VidaaPictureModeSelect(mock_client, mock_entry)
    snd_sel = VidaaSoundModeSelect(mock_client, mock_entry)

    mock_client.connected = True
    assert pic_sel.available is True
    assert snd_sel.available is True

    mock_client.connected = False
    assert pic_sel.available is False
    assert snd_sel.available is False

    await pic_sel.async_added_to_hass()
    mock_client.register_connected_callback.assert_called()
    mock_client.register_disconnected_callback.assert_called()

    await snd_sel.async_added_to_hass()
    mock_client.register_sound_callback.assert_called()


@pytest.mark.anyio
async def test_select_action_exceptions_and_no_optimistic_update(mock_client, mock_entry):
    """Verify select entities raise HomeAssistantError and do not desync state on failure."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop_thread_id = threading.get_ident()
    hass.loop = MagicMock()
    hass.data = {}
    hass.states = MagicMock()

    pic_sel = VidaaPictureModeSelect(client=mock_client, entry=mock_entry)
    pic_sel.hass = hass
    pic_sel.entity_id = "select.picture_mode"

    snd_sel = VidaaSoundModeSelect(client=mock_client, entry=mock_entry)
    snd_sel.hass = hass
    snd_sel.entity_id = "select.sound_mode"

    mock_client.picture_mode = None
    mock_client.sound_mode = None

    # 1. When disconnected, selecting an option raises not_connected without updating mode
    mock_client.connected = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await pic_sel.async_select_option("Dynamic")
    assert exc_info.value.translation_key == "not_connected"
    assert pic_sel.current_option == "Standard"

    with pytest.raises(HomeAssistantError) as exc_info:
        await snd_sel.async_select_option("Music")
    assert exc_info.value.translation_key == "not_connected"
    assert snd_sel.current_option == "Standard"

    # 2. When connected but client publish returns False: raises error without updating cached state
    mock_client.connected = True
    mock_client.async_set_picture_mode = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await pic_sel.async_select_option("Dynamic")
    assert exc_info.value.translation_key == "set_picture_setting_failed"
    assert pic_sel.current_option == "Standard"

    mock_client.async_set_sound_mode = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await snd_sel.async_select_option("Music")
    assert exc_info.value.translation_key == "set_sound_setting_failed"
    assert snd_sel.current_option == "Standard"

    # 3. When auth_failed is True, selecting an option raises auth_required
    mock_client.auth_failed = True
    with pytest.raises(HomeAssistantError) as exc_info:
        await pic_sel.async_select_option("Dynamic")
    assert exc_info.value.translation_key == "auth_required"

    # 4. When TV is off, selecting an option raises device_off
    mock_client.auth_failed = False
    mock_client.connected = True
    mock_client.is_on = False

    with pytest.raises(HomeAssistantError) as exc_info:
        await pic_sel.async_select_option("Dynamic")
    assert exc_info.value.translation_key == "device_off"

    with pytest.raises(HomeAssistantError) as exc_info:
        await snd_sel.async_select_option("Music")
    assert exc_info.value.translation_key == "device_off"
