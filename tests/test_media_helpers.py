"""Tests for media helper functions, source resolution, and payload parsers in tv/media.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.vidaa.tv.media import (
    async_execute_play_media,
    async_execute_select_source,
    build_media_channel_label,
    build_media_player_current_source,
    build_media_player_source_list,
    clean_source_label,
    execute_play_media,
    execute_select_source,
    is_live_tv_source,
    is_physical_input_source,
    parse_applist_data,
    parse_applist_payload,
    parse_media_state_broadcast,
    parse_sourcelist_data,
    parse_sourcelist_payload,
    parse_volume_broadcast,
)


def test_parse_applist_payload():
    # None or empty
    assert parse_applist_payload(None) == ({}, {}, [])
    assert parse_applist_payload([]) == ({}, {}, [])

    apps = [
        {"appId": "netflix_id", "appName": "Netflix", "isFav": "1", "httpIcon": "prefixhttp://icons.tv/netflix.png"},
        {"app_id": "youtube_id", "name": "YouTube", "isFav": True, "httpIcon": "http://icons.tv/yt.png"},
        {"appId": "prime_id", "name": "Prime", "isFav": 0},
        {"not_an_app": True},
        "invalid_item",
    ]
    app_dict, app_icons, favs = parse_applist_payload(apps)
    assert app_dict["netflix_id"] == "Netflix"
    assert app_dict["youtube_id"] == "YouTube"
    assert app_dict["prime_id"] == "Prime"
    assert "Netflix" in favs
    assert "YouTube" in favs
    assert "Prime" not in favs
    assert app_icons["Netflix"] == "http://icons.tv/netflix.png"
    assert app_icons["netflix_id"] == "http://icons.tv/netflix.png"


def test_is_physical_input_source():
    assert is_physical_input_source(None) is False
    assert is_physical_input_source("") is False
    assert is_physical_input_source("HDMI 1") is True
    assert is_physical_input_source("hdmi2") is True
    for src in ("tv", "dtv", "atv", "tuner", "antenna", "cable", "av", "component", "composite", "vga"):
        assert is_physical_input_source(src) is True
    assert is_physical_input_source("Netflix") is False


def test_parse_sourcelist_payload():
    # None or empty
    assert parse_sourcelist_payload(None) == ([], [], {}, None)
    assert parse_sourcelist_payload([]) == ([], [], {}, None)

    sources = [
        {"sourcename": "HDMI 1", "has_signal": 1, "displayname2": "Apple TV", "is_signal": 1},
        {"sourceName": "HDMI 2", "has_signal": "1", "is_active": True},
        {"displayname": "AV", "has_signal": False},
        {"name": "TV", "active": True},
        {"sourcename": "Netflix App"},  # filtered out by is_physical_input_source
        "invalid_element",
    ]
    avail, connected, labels, active = parse_sourcelist_payload(sources)
    assert avail == ["HDMI 1", "HDMI 2", "AV", "TV"]
    assert connected == ["HDMI 1", "HDMI 2"]
    assert labels == {"HDMI 1": "Apple TV"}
    assert active in ("HDMI 1", "HDMI 2", "TV")


def test_clean_source_label_and_channel_label():
    assert clean_source_label("HDMI 2 (PlayStation 5)") == "HDMI 2"
    assert clean_source_label("HDMI 1") == "HDMI 1"

    assert build_media_channel_label("Seven HD", "70") == "70 Seven HD"
    assert build_media_channel_label("Seven HD", None) == "Seven HD"
    assert build_media_channel_label(None, "70") == "70"
    assert build_media_channel_label(None, None) is None


def test_is_live_tv_source():
    # HDMI / AV inputs must never be Live TV
    assert is_live_tv_source("HDMI 1") is False
    assert is_live_tv_source("AV") is False
    assert is_live_tv_source("TV", source_id="1") is False

    # TV sources
    for src in ("tv", "live tv", "livetv", "dtv", "atv", "antenna", "cable", "tuner"):
        assert is_live_tv_source(src) is True

    # statetype livetv
    assert is_live_tv_source("", statetype="livetv") is True
    assert is_live_tv_source("TV", statetype="live_tv") is True
    assert is_live_tv_source("HDMI 1", statetype="livetv") is False


def test_build_media_player_current_source():
    assert build_media_player_current_source("HDMI 1", "PS5", enable_cec=False) == "HDMI 1"
    assert build_media_player_current_source("TV", "PS5", enable_cec=True) == "TV"
    assert build_media_player_current_source("HDMI 1", "PS5", enable_cec=True) == "HDMI 1 (PS5)"
    assert build_media_player_current_source(None, "PS5", enable_cec=True) is None


def test_build_media_player_source_list():
    source_dict = {
        "HDMI 1": {"displayname2": "Apple TV"},
        "HDMI 2": {},
        "TV": {},
    }
    app_dict = {"Netflix": {}, "YouTube": {}}

    # CEC enabled with connected_device on current_source
    sources = build_media_player_source_list(
        source_dict=source_dict,
        app_dict=app_dict,
        current_source="HDMI 2",
        connected_device="Xbox",
        enable_cec=True,
        include_apps=True,
    )
    assert "HDMI 1 (Apple TV)" in sources
    assert "HDMI 2 (Xbox)" in sources
    assert "Netflix" in sources
    assert "YouTube" in sources

    # include_apps False
    sources_no_apps = build_media_player_source_list(
        source_dict=source_dict,
        app_dict=app_dict,
        enable_cec=False,
        include_apps=False,
    )
    assert "Netflix" not in sources_no_apps

    # Configured sources filter
    filtered = build_media_player_source_list(
        source_dict=source_dict,
        app_dict=app_dict,
        include_apps=True,
        configured_sources=["HDMI 1", "Netflix"],
    )
    assert filtered == ["HDMI 1", "Netflix"]


def test_execute_play_media():
    client = MagicMock()
    app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "url": "netflix://"},
        "YouTube": {"appId": "2", "name": "YouTube", "url": "youtube://"},
    }

    # App match direct
    execute_play_media(client, app_dict, "app", "Netflix")
    client.launch_app.assert_called_with("1", "Netflix", "netflix://")

    # App match case-insensitive / url match
    client.launch_app.reset_mock()
    execute_play_media(client, app_dict, "app", "youtube")
    client.launch_app.assert_called_with("2", "YouTube", "youtube://")

    # Direct URL
    client.launch_app.reset_mock()
    execute_play_media(client, app_dict, "url", "https://example.com/stream.m3u8")
    client.launch_app.assert_called_with("", "https://example.com/stream.m3u8", "https://example.com/stream.m3u8")

    # Channel match by channel_name
    client.channels = [{"channel_name": "ABC", "channel_num": "20"}]
    execute_play_media(client, app_dict, "channel", "ABC")
    assert client.send_key.call_count == 2
    assert client.send_key.call_args_list[0][0][0] == "KEY_2"
    assert client.send_key.call_args_list[1][0][0] == "KEY_0"

    # Channel with dot
    client.send_key.reset_mock()
    execute_play_media(client, app_dict, "channel", "9.1")
    assert client.send_key.call_count == 3
    assert client.send_key.call_args_list[1][0][0] == "KEY_CHANNELDOT"

    # Fallback send_command
    execute_play_media(client, app_dict, "key", "KEY_HOME")
    client.send_command.assert_called_with("KEY_HOME")


@pytest.mark.anyio
async def test_async_execute_play_media():
    client = MagicMock()
    client.async_launch_app = AsyncMock(return_value=True)
    client.async_send_key = AsyncMock(return_value=True)
    client.async_send_command = AsyncMock(return_value=True)
    client.async_change_source = AsyncMock(return_value=True)
    app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "url": "netflix://"},
    }

    # App
    assert await async_execute_play_media(client, app_dict, "app", "Netflix") is True
    client.async_launch_app.assert_awaited_with("1", "Netflix", "netflix://")

    # Deep link
    assert await async_execute_play_media(client, app_dict, "deep_link", "myapp://play") is True

    # Source input
    client.source_dict = {"HDMI 1": {"sourcename": "HDMI 1", "sourceid": "1"}}
    assert await async_execute_play_media(client, app_dict, "source", "HDMI 1") is True

    # Channel with dot and channel lookup
    client.channels = [{"name": "SBS", "num": "30"}]
    assert await async_execute_play_media(client, app_dict, "channel", "SBS") is True
    assert client.async_send_key.await_count == 2

    # Channel dot key delivery failure
    client.async_send_key = AsyncMock(return_value=False)
    assert await async_execute_play_media(client, app_dict, "channel", "1-1") is False

    # Other command
    assert await async_execute_play_media(client, app_dict, "key", "KEY_BACK") is True


def test_execute_select_source():
    client = MagicMock()
    source_dict = {
        "HDMI 1": {"sourcename": "HDMI 1", "sourceid": "1", "displayname2": "Apple TV"},
        "HDMI 2": {"sourcename": "HDMI 2", "sourceid": "2"},
    }
    app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "url": "netflix://"},
    }

    # Empty source
    execute_select_source(client, source_dict, app_dict, "")
    client.launch_app.assert_not_called()
    client.change_source.assert_not_called()

    # App match
    execute_select_source(client, source_dict, app_dict, "Netflix")
    client.launch_app.assert_called_with("1", "Netflix", "netflix://")

    # Source match direct
    execute_select_source(client, source_dict, app_dict, "HDMI 2")
    client.change_source.assert_called_with("2", "HDMI 2")

    # CEC match
    execute_select_source(client, source_dict, app_dict, "Apple TV")
    client.change_source.assert_called_with("1", "HDMI 1")

    # Unknown source fallback
    execute_select_source(client, source_dict, app_dict, "Component")
    client.change_source.assert_called_with("Component")


@pytest.mark.anyio
async def test_async_execute_select_source():
    client = MagicMock()
    client.async_launch_app = AsyncMock(return_value=True)
    client.async_change_source = AsyncMock(return_value=True)

    source_dict = {
        "HDMI 1": {"sourcename": "HDMI 1", "sourceid": "1", "source_detail": "Roku"},
    }
    app_dict = {
        "Prime": {"appId": "2", "name": "Prime", "url": "prime://"},
    }

    # Empty
    assert await async_execute_select_source(client, source_dict, app_dict, "") is False

    # App match
    assert await async_execute_select_source(client, source_dict, app_dict, "prime") is True
    client.async_launch_app.assert_awaited_with("2", "Prime", "prime://")

    # Source CEC match
    assert await async_execute_select_source(client, source_dict, app_dict, "Roku") is True
    client.async_change_source.assert_awaited_with("1", "HDMI 1")

    # Fallback
    assert await async_execute_select_source(client, source_dict, app_dict, "HDMI 3") is True
    client.async_change_source.assert_awaited_with("HDMI 3")


def test_parse_media_state_broadcast():
    # fake_sleep_0 / off
    s0 = parse_media_state_broadcast({"statetype": "fake_sleep_0"})
    assert s0["is_on"] is False and s0["state"] == "off"

    s_off = parse_media_state_broadcast({"statetype": "power_off"})
    assert s_off["is_on"] is False and s_off["state"] == "off"

    # fake_sleep_1
    s1 = parse_media_state_broadcast({"statetype": "fake_sleep_1"})
    assert s1["is_on"] is True and s1["state"] == "on"

    # sourceswitch
    ss = parse_media_state_broadcast({"statetype": "sourceswitch", "sourcename": "HDMI 1", "displayname2": "Apple TV"})
    assert ss["source"] == "HDMI 1"
    assert ss["connected_device"] == "Apple TV"

    # app
    sapp = parse_media_state_broadcast({"statetype": "app", "appName": "Disney+", "activeAppId": 123})
    assert sapp["source"] == "Disney+"
    assert sapp["app_id"] == "123"

    # livetv
    slive = parse_media_state_broadcast({"statetype": "livetv", "channel_name": "7 News", "channel_num": "7"})
    assert slive["source"] == "TV"
    assert slive["channel_name"] == "7 News"


def test_parse_volume_broadcast():
    # volume change int
    vol, vtype, mute = parse_volume_broadcast({"volume_type": 0, "volume_value": 25}, 10, 0, False)
    assert vol == 25 and vtype == 0 and mute is False

    # volume change string
    vol, vtype, mute = parse_volume_broadcast({"volume_type": "1", "volume_value": "30"}, 10, 0, False)
    assert vol == 30 and vtype == 1

    # mute toggle
    vol, vtype, mute = parse_volume_broadcast({"volume_type": 2, "volume_value": 1}, 20, 0, False)
    assert vol == 20 and mute is True

    # unmute string
    vol, vtype, mute = parse_volume_broadcast({"volume_type": "2", "volume_value": "0"}, 20, 0, True)
    assert mute is False


def test_parse_sourcelist_and_applist_data():
    # None or empty
    assert parse_sourcelist_data(None) == {}
    assert parse_applist_data(None) == ([], {})

    # Data parsing
    s_data = parse_sourcelist_data([{"sourcename": "HDMI 1"}, "invalid", {"name": "AV"}])
    assert "HDMI 1" in s_data
    assert "AV" in s_data

    raw_apps, a_data = parse_applist_data([{"name": "Netflix"}, "invalid", {"appName": "YouTube"}])
    assert len(raw_apps) == 3
    assert "Netflix" in a_data
    assert "YouTube" in a_data
