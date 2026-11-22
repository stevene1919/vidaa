"""Tests for TV input actions mixin and navigation/app launching handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.vidaa.tv.actions_input import (
    TvInputActionsMixin,
    async_change_source,
    async_change_source_by_name_or_id,
    async_cycle_source,
    async_launch_app,
    async_launch_app_by_name,
    async_send_command,
    async_send_key,
    async_send_text_input,
    change_source,
    change_source_by_name_or_id,
    cycle_source,
    launch_app,
    launch_app_by_name,
    send_command,
    send_key,
    send_text_input,
)


class DummyClient(TvInputActionsMixin):
    """Dummy client inheriting TvInputActionsMixin for testing."""

    def __init__(self):
        self.connected = True
        self.mqtt_client = MagicMock()
        self.async_publish = AsyncMock(return_value=True)
        self.topics = MagicMock()
        self.topics.remote = "/remoteapp/tv/remote_service/test/"
        self.topics.ui = "/remoteapp/tv/ui_service/test/"
        self.topics.platform = "/remoteapp/tv/platform_service/test/"
        self.sources = [
            {"sourceid": "0", "sourcename": "TV"},
            {"sourceid": "1", "sourcename": "HDMI1"},
            {"sourceid": "2", "sourcename": "HDMI2"},
        ]
        self.apps = [
            {"appId": "1", "name": "Netflix", "url": "netflix://"},
            {"appId": "2", "name": "YouTube", "url": "youtube://"},
        ]
        self.current_source = "HDMI1"
        self.hotel_mode = False
        self.ip = "192.168.1.100"


def test_send_key():
    client = DummyClient()
    send_key(client, "KEY_HOME")
    client.mqtt_client.publish.assert_called_once_with(f"{client.topics.remote}actions/sendkey", "KEY_HOME")

    client.connected = False
    client.mqtt_client.reset_mock()
    send_key(client, "KEY_HOME")
    client.mqtt_client.publish.assert_not_called()


@pytest.mark.anyio
async def test_async_send_key():
    client = DummyClient()
    res = await async_send_key(client, "KEY_HOME")
    assert res is True
    client.async_publish.assert_awaited_once_with(f"{client.topics.remote}actions/sendkey", "KEY_HOME")

    client.connected = False
    assert await async_send_key(client, "KEY_HOME") is False


def test_send_command_text_and_special():
    client = DummyClient()
    client.send_text_input = MagicMock()
    client.cycle_source = MagicMock(return_value=True)
    client._launch_app_by_name = MagicMock(return_value=True)
    client._change_source_by_name_or_id = MagicMock(return_value=True)

    # Empty command
    assert send_command(client, "") is False

    # Text input: insert
    assert send_command(client, "text:hello world") is True
    client.send_text_input.assert_called_with("hello world", action="insert")

    # Text input: replace
    assert send_command(client, "type:replace:new text") is True
    client.send_text_input.assert_called_with("new text", action="replace")

    # Text input: clear:with prefix
    assert send_command(client, "text:clear:some text") is True
    client.send_text_input.assert_called_with("some text", action="clear")

    # Text input: clear
    assert send_command(client, "type:clear") is True
    client.send_text_input.assert_called_with("", action="clear")

    # Clear text keywords
    assert send_command(client, "clear_text") is True
    client.send_text_input.assert_called_with("", action="clear")
    assert send_command(client, "text_clear") is True

    # App command
    assert send_command(client, "app:Netflix") is True
    client._launch_app_by_name.assert_called_with("Netflix")

    # Source command
    assert send_command(client, "source:HDMI2") is True
    client._change_source_by_name_or_id.assert_called_with("HDMI2")

    # Cycle source aliases
    for alias in ("input", "source", "cycle_source", "input_cycle", "source_cycle", "key_input", "key_source"):
        assert send_command(client, alias) is True
    assert client.cycle_source.call_count == 7

    # Menu aliases
    for alias in ("input_menu", "source_menu", "key_input_menu", "key_source_menu"):
        assert send_command(client, alias) is True
    assert client.mqtt_client.publish.call_count == 4

    # Standard key command
    assert send_command(client, "home") is True


@pytest.mark.anyio
async def test_async_send_command_all_branches():
    client = DummyClient()
    client.async_send_text_input = AsyncMock(return_value=True)
    client.async_launch_app_by_name = AsyncMock(return_value=True)
    client.async_change_source_by_name_or_id = AsyncMock(return_value=True)
    client.async_cycle_source = AsyncMock(return_value=True)

    # Empty
    assert await async_send_command(client, "") is False

    # Text insert
    assert await async_send_command(client, "text:testing") is True
    client.async_send_text_input.assert_awaited_with("testing", action="insert")

    # Text replace
    assert await async_send_command(client, "type:replace:replacement") is True
    client.async_send_text_input.assert_awaited_with("replacement", action="replace")

    # Text clear:val
    assert await async_send_command(client, "text:clear:val") is True
    client.async_send_text_input.assert_awaited_with("val", action="clear")

    # Text clear
    assert await async_send_command(client, "text:clear") is True
    client.async_send_text_input.assert_awaited_with("", action="clear")

    # Keywords clear_text
    assert await async_send_command(client, "clear_text") is True
    assert await async_send_command(client, "text_clear") is True

    # App
    assert await async_send_command(client, "app:YouTube") is True
    client.async_launch_app_by_name.assert_awaited_with("YouTube")

    # Source
    assert await async_send_command(client, "source:HDMI1") is True
    client.async_change_source_by_name_or_id.assert_awaited_with("HDMI1")

    # Cycle source
    assert await async_send_command(client, "cycle_source") is True
    client.async_cycle_source.assert_awaited_once()

    # Input menu
    assert await async_send_command(client, "source_menu") is True

    # Standard key
    assert await async_send_command(client, "volume_up") is True


def test_cycle_source_and_launch_app_by_name():
    client = DummyClient()
    client.change_source = MagicMock()

    # Cycle to next source
    client.current_source = "HDMI1"
    assert cycle_source(client) is True
    client.change_source.assert_called_with("2", "HDMI2")

    # No sources -> falls back to KEY_MENU
    client.sources = []
    assert cycle_source(client) is True
    client.mqtt_client.publish.assert_called_with(f"{client.topics.remote}actions/sendkey", "KEY_MENU")

    # Launch app by name: match
    client.launch_app = MagicMock()
    assert launch_app_by_name(client, "Netflix") is True
    client.launch_app.assert_called_with("1", "Netflix", "netflix://")

    # Launch app by name: fallback buttons
    client.apps = []
    assert launch_app_by_name(client, "netflix") is True
    assert launch_app_by_name(client, "youtube") is True
    assert launch_app_by_name(client, "prime video") is True
    assert launch_app_by_name(client, "unknown_app") is False


@pytest.mark.anyio
async def test_async_cycle_source_and_launch_app_by_name():
    client = DummyClient()
    client.async_change_source = AsyncMock(return_value=True)

    # Next source
    client.current_source = "HDMI1"
    assert await async_cycle_source(client) is True
    client.async_change_source.assert_awaited_with("2", "HDMI2")

    # No sources
    client.sources = []
    assert await async_cycle_source(client) is True
    client.async_publish.assert_awaited_with(f"{client.topics.remote}actions/sendkey", "KEY_MENU")

    # Launch app by name
    client.async_launch_app = AsyncMock(return_value=True)
    client.apps = [{"appId": "10", "name": "Plex", "url": "plex://"}]
    assert await async_launch_app_by_name(client, "Plex") is True
    client.async_launch_app.assert_awaited_with("10", "Plex", "plex://")

    # Fallback keys
    client.apps = []
    assert await async_launch_app_by_name(client, "app_netflix") is True
    assert await async_launch_app_by_name(client, "app_youtube") is True
    assert await async_launch_app_by_name(client, "app_prime") is True
    assert await async_launch_app_by_name(client, "unknown_app") is False


def test_change_source_variations():
    client = DummyClient()

    # Disconnected early return
    client.connected = False
    change_source(client, "HDMI1")
    client.mqtt_client.publish.assert_not_called()

    # Connected: numeric source_id and clean_source_name -> dual publish
    client.connected = True
    change_source(client, "1", "HDMI 1")
    assert client.mqtt_client.publish.call_count == 2
    first_call = json.loads(client.mqtt_client.publish.call_args_list[0][0][1])
    assert first_call == {"sourceid": "1", "sourcename": "HDMI 1"}
    second_call = json.loads(client.mqtt_client.publish.call_args_list[1][0][1])
    assert second_call == {"sourceid": "HDMI 1", "sourcename": "HDMI 1"}

    # Switching to TV sends KEY_LIVETV
    client.mqtt_client.reset_mock()
    change_source(client, "0", "TV")
    # changesource + sendkey KEY_LIVETV
    assert client.mqtt_client.publish.call_count >= 2
    assert any("KEY_LIVETV" in str(call) for call in client.mqtt_client.publish.call_args_list)

    # Change source by name or ID
    client.change_source = MagicMock()
    assert change_source_by_name_or_id(client, "HDMI1") is True
    client.change_source.assert_called_with("1", "HDMI1")


@pytest.mark.anyio
async def test_async_change_source_variations():
    client = DummyClient()

    # Disconnected
    client.connected = False
    assert await async_change_source(client, "HDMI1") is False

    # Connected with hotel mode warning
    client.connected = True
    client.hotel_mode = True
    assert await async_change_source(client, "1", "HDMI 1") is True
    assert client.async_publish.await_count == 2

    # Switching to TV sends KEY_LIVETV
    client.hotel_mode = False
    client.async_publish.reset_mock()
    assert await async_change_source(client, "TV") is True
    assert any("KEY_LIVETV" in str(call) for call in client.async_publish.await_args_list)

    # Async change source by name or ID
    client.async_change_source = AsyncMock(return_value=True)
    assert await async_change_source_by_name_or_id(client, "HDMI1") is True
    client.async_change_source.assert_awaited_with("1", "HDMI1")


def test_launch_app_and_send_text_input():
    client = DummyClient()

    # Disconnected
    client.connected = False
    launch_app(client, "app1", "Netflix", "url1")
    send_text_input(client, "text", "insert")
    client.mqtt_client.publish.assert_not_called()

    # Connected
    client.connected = True
    launch_app(client, "app1", "Netflix", "url1")
    client.mqtt_client.publish.assert_called_once()
    payload = json.loads(client.mqtt_client.publish.call_args[0][1])
    assert payload["appId"] == "app1"
    assert payload["name"] == "Netflix"

    client.mqtt_client.reset_mock()
    send_text_input(client, "hello", "replace")
    assert client.mqtt_client.publish.call_count == 2


@pytest.mark.anyio
async def test_async_launch_app_and_send_text_input():
    client = DummyClient()

    # Disconnected
    client.connected = False
    assert await async_launch_app(client, "app1", "Netflix", "url1") is False
    assert await async_send_text_input(client, "text") is False

    # Connected with hotel mode
    client.connected = True
    client.hotel_mode = True
    assert await async_launch_app(client, "app1", "Netflix", "url1") is True
    payload = json.loads(client.async_publish.await_args[0][1])
    assert payload["appId"] == "app1"

    client.async_publish.reset_mock()
    assert await async_send_text_input(client, "test") is True
    assert client.async_publish.await_count == 2


@pytest.mark.anyio
async def test_tv_input_actions_mixin_methods():
    client = DummyClient()

    client.send_key("KEY_HOME")
    assert await client.async_send_key("KEY_HOME") is True
    assert client.send_command("home") is True
    assert await client.async_send_command("home") is True
    assert client.cycle_source() is True
    assert await client.async_cycle_source() is True
    assert client._launch_app_by_name("Netflix") is True
    assert await client.async_launch_app_by_name("Netflix") is True
    assert client._change_source_by_name_or_id("HDMI1") is True
    assert await client.async_change_source_by_name_or_id("HDMI1") is True
    client.change_source("HDMI1")
    assert await client.async_change_source("HDMI1") is True
    client.launch_app("1", "App", "url")
    assert await client.async_launch_app("1", "App", "url") is True
    client.send_text_input("hello")
    assert await client.async_send_text_input("hello") is True
