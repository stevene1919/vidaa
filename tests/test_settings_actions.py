"""Tests for TV settings models, parsers, and synchronous/asynchronous action handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.vidaa.tv.actions_settings import TvSettingsActionsMixin
from custom_components.vidaa.tv.settings import (
    DEFAULT_MENU_ID_BRIGHTNESS,
    DEFAULT_MENU_ID_PICTURE_MODE,
    DEFAULT_MENU_ID_SOUND_MODE,
    SettingMenuItem,
    async_get_picture_settings,
    async_get_sound_settings,
    async_set_backlight,
    async_set_brightness,
    async_set_contrast,
    async_set_picture_mode,
    async_set_picture_setting,
    async_set_sound_mode,
    async_set_sound_setting,
    find_menu_item_by_name,
    get_picture_settings,
    get_sound_settings,
    parse_settings_payload,
    set_backlight,
    set_brightness,
    set_contrast,
    set_picture_mode,
    set_picture_setting,
    set_sound_mode,
    set_sound_setting,
)


class DummySettingsClient(TvSettingsActionsMixin):
    """Dummy client inheriting TvSettingsActionsMixin for testing."""

    def __init__(self):
        self.connected = True
        self.mqtt_client = MagicMock()
        self.async_publish = AsyncMock(return_value=True)
        self.topics = MagicMock()
        self.topics.platform = "/remoteapp/tv/platform_service/test/"
        self.picture_settings: dict[int, SettingMenuItem] = {}
        self.sound_settings: dict[int, SettingMenuItem] = {}
        self.picture_mode = "Standard"
        self.sound_mode = "Standard"
        self.backlight = 50
        self.brightness = 50
        self.contrast = 50


def test_setting_menu_item_dataclass_and_from_dict():
    # from_dict invalid
    assert SettingMenuItem.from_dict("invalid") is None
    assert SettingMenuItem.from_dict({}) is None
    assert SettingMenuItem.from_dict({"menu_id": "not_an_int"}) is None

    # item with select options (names and values)
    data = {
        "id": 91,
        "name": "Picture Mode",
        "value": "Dynamic",
        "options": [
            "Standard",
            {"name": "Cinema"},
            {"value": "Game"},
        ],
    }
    item = SettingMenuItem.from_dict(data)
    assert item is not None
    assert item.menu_id == 91
    assert item.menu_name == "Picture Mode"
    assert item.menu_value == "Dynamic"
    assert item.options == ["Standard", "Cinema", "Game"]
    assert item.is_select is True
    assert item.is_slider is False
    assert item.menu_type == "select"

    # item with slider
    slider_data = {
        "menuid": "92",
        "menu_name": "Backlight",
        "menu_value": 70,
        "min": 0,
        "max": 100,
        "step": 1,
    }
    slider_item = SettingMenuItem.from_dict(slider_data)
    assert slider_item is not None
    assert slider_item.menu_id == 92
    assert slider_item.is_slider is True
    assert slider_item.is_select is False
    assert slider_item.menu_type == "slider"

    # plain value item
    val_data = {"menu_id": 100, "menu_name": "Version", "menu_value": "1.0"}
    val_item = SettingMenuItem.from_dict(val_data)
    assert val_item.menu_type == "value"


def test_parse_settings_payload_structures():
    # list input
    items = parse_settings_payload([{"menu_id": 1, "menu_name": "Test"}])
    assert len(items) == 1

    # dict with "items"
    items2 = parse_settings_payload({"items": [{"menu_id": 2}]})
    assert len(items2) == 1

    # dict with "data"
    items3 = parse_settings_payload({"data": [{"menu_id": 3}]})
    assert len(items3) == 1

    # dict with single item
    items4 = parse_settings_payload({"menu_id": 4, "menu_name": "Single"})
    assert len(items4) == 1


def test_find_menu_item_by_name():
    item1 = SettingMenuItem(menu_id=91, name="Picture Mode", value="Standard")
    item2 = SettingMenuItem(menu_id=92, name="Backlight Level", value=80)
    menu_dict = {91: item1, 92: item2}

    # Empty list/dict
    assert find_menu_item_by_name([], "Backlight") is None

    # Exact normalized match
    assert find_menu_item_by_name(menu_dict, "picture mode") == item1

    # Substring match
    assert find_menu_item_by_name(menu_dict, "Backlight") == item2

    # Fallback by default_id
    assert find_menu_item_by_name(menu_dict, "Unknown", default_id=91) == item1
    assert find_menu_item_by_name(menu_dict, "Unknown", default_id=999) is None


def test_picture_settings_actions_sync():
    client = DummySettingsClient()

    # get_picture_settings
    get_picture_settings(client)
    client.mqtt_client.publish.assert_called_with(
        f"{client.topics.platform}actions/picturesetting",
        json.dumps({"action": "get_menu_info"}),
    )

    # set_picture_setting
    item = SettingMenuItem(menu_id=DEFAULT_MENU_ID_PICTURE_MODE, name="Picture Mode", value="Standard")
    client.picture_settings[DEFAULT_MENU_ID_PICTURE_MODE] = item
    set_picture_setting(client, DEFAULT_MENU_ID_PICTURE_MODE, "Dynamic")
    assert item.value == "Dynamic"

    # set_picture_mode
    set_picture_mode(client, "Cinema")
    assert client.picture_mode == "Cinema"

    # set_backlight (clamped)
    set_backlight(client, 150)
    assert client.backlight == 100
    set_backlight(client, -10)
    assert client.backlight == 0

    # set_brightness (clamped)
    set_brightness(client, 75)
    assert client.brightness == 75

    # set_contrast (clamped)
    set_contrast(client, 65)
    assert client.contrast == 65

    # Disconnected check
    client.connected = False
    client.mqtt_client.reset_mock()
    get_picture_settings(client)
    set_picture_setting(client, 1, "test")
    client.mqtt_client.publish.assert_not_called()


@pytest.mark.anyio
async def test_picture_settings_actions_async():
    client = DummySettingsClient()

    # async_get_picture_settings
    await async_get_picture_settings(client)
    client.async_publish.assert_awaited_with(
        f"{client.topics.platform}actions/picturesetting",
        json.dumps({"action": "get_menu_info"}),
    )

    # async_set_picture_setting
    item = SettingMenuItem(menu_id=DEFAULT_MENU_ID_BRIGHTNESS, name="Brightness", value=50)
    client.picture_settings[DEFAULT_MENU_ID_BRIGHTNESS] = item
    res = await async_set_picture_setting(client, DEFAULT_MENU_ID_BRIGHTNESS, 60)
    assert res is True
    assert item.value == 60

    # async_set_picture_mode
    assert await async_set_picture_mode(client, "Filmmaker Mode") is True
    assert client.picture_mode == "Filmmaker Mode"

    # async_set_backlight
    assert await async_set_backlight(client, 85) is True
    assert client.backlight == 85

    # async_set_brightness
    assert await async_set_brightness(client, 45) is True
    assert client.brightness == 45

    # async_set_contrast
    assert await async_set_contrast(client, 55) is True
    assert client.contrast == 55

    # Disconnected async
    client.connected = False
    assert await async_set_picture_setting(client, 1, 1) is False
    assert await async_set_picture_mode(client, "Standard") is False
    assert await async_set_backlight(client, 50) is False
    assert await async_set_brightness(client, 50) is False
    assert await async_set_contrast(client, 50) is False


def test_sound_settings_actions_sync():
    client = DummySettingsClient()

    # get_sound_settings
    get_sound_settings(client)
    client.mqtt_client.publish.assert_called_with(
        f"{client.topics.platform}actions/soundsetting",
        json.dumps({"action": "get_menu_info"}),
    )

    # set_sound_setting
    item = SettingMenuItem(menu_id=DEFAULT_MENU_ID_SOUND_MODE, name="Sound Mode", value="Standard")
    client.sound_settings[DEFAULT_MENU_ID_SOUND_MODE] = item
    set_sound_setting(client, DEFAULT_MENU_ID_SOUND_MODE, "Theatre")
    assert item.value == "Theatre"

    # set_sound_mode
    set_sound_mode(client, "Music")
    assert client.sound_mode == "Music"

    # Disconnected
    client.connected = False
    client.mqtt_client.reset_mock()
    get_sound_settings(client)
    set_sound_setting(client, 1, "test")
    client.mqtt_client.publish.assert_not_called()


@pytest.mark.anyio
async def test_sound_settings_actions_async():
    client = DummySettingsClient()

    # async_get_sound_settings
    await async_get_sound_settings(client)
    client.async_publish.assert_awaited_with(
        f"{client.topics.platform}actions/soundsetting",
        json.dumps({"action": "get_menu_info"}),
    )

    # async_set_sound_setting
    item = SettingMenuItem(menu_id=DEFAULT_MENU_ID_SOUND_MODE, name="Sound Mode", value="Standard")
    client.sound_settings[DEFAULT_MENU_ID_SOUND_MODE] = item
    res = await async_set_sound_setting(client, DEFAULT_MENU_ID_SOUND_MODE, "Speech")
    assert res is True
    assert item.value == "Speech"

    # async_set_sound_mode
    assert await async_set_sound_mode(client, "Late Night") is True
    assert client.sound_mode == "Late Night"

    # Disconnected
    client.connected = False
    assert await async_set_sound_setting(client, 1, "test") is False
    assert await async_set_sound_mode(client, "Standard") is False


@pytest.mark.anyio
async def test_tv_settings_actions_mixin_delegation():
    client = DummySettingsClient()

    client.get_picture_settings()
    await client.async_get_picture_settings()
    client.set_picture_setting(1, "val")
    assert await client.async_set_picture_setting(1, "val") is True
    client.set_picture_mode("Cinema")
    assert await client.async_set_picture_mode("Cinema") is True
    client.set_backlight(80)
    assert await client.async_set_backlight(80) is True
    client.set_brightness(50)
    assert await client.async_set_brightness(50) is True
    client.set_contrast(50)
    assert await client.async_set_contrast(50) is True

    client.get_sound_settings()
    await client.async_get_sound_settings()
    client.set_sound_setting(1, "val")
    assert await client.async_set_sound_setting(1, "val") is True
    client.set_sound_mode("Theatre")
    assert await client.async_set_sound_mode("Theatre") is True
