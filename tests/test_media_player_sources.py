"""Tests for Hisense VIDAA media player sources, apps, and media playback."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.vidaa.const import CONF_SOURCES
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.tv.media import (
    parse_applist_data,
    parse_sourcelist_data,
)


@pytest.mark.anyio
async def test_media_player_play_media(mock_client, mock_entry):
    """Test media player play media with apps, URLs, and direct channel numbers."""
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
    mp._app_dict = {"Netflix": {"appId": "1", "name": "Netflix", "url": "netflix://"}}

    # App launch by name
    await mp.async_play_media("app", "Netflix")
    mock_client.launch_app.assert_called_with("1", "Netflix", "netflix://")

    # Deep link URL
    await mp.async_play_media("url", "https://youtube.com/watch?v=123")
    mock_client.launch_app.assert_called_with("", "https://youtube.com/watch?v=123", "https://youtube.com/watch?v=123")

    # Channel tuning with dot
    mock_client.send_key.reset_mock()
    await mp.async_play_media("channel", "7.1")
    assert mock_client.send_key.call_count == 3


@pytest.mark.anyio
async def test_media_player_cec_source_naming(mock_client, mock_entry):
    """Test dynamic HDMI-CEC source labeling and label stripping on input change."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mock_entry.options = {"enable_cec_names": True, "include_apps_in_sources": True}
    mp = VidaaMediaPlayer(
        client=mock_client,
        entry=mock_entry,
    )
    mp.hass = hass
    mp._source_dict = {
        "HDMI1": {"sourceid": "HDMI1", "sourcename": "HDMI1", "displayname2": "Chromecast"},
        "HDMI2": {"sourceid": "HDMI2", "sourcename": "HDMI2"},
    }
    mp._source = "HDMI2"
    mp._connected_device = "PlayStation 5"

    assert mp.source == "HDMI2 (PlayStation 5)"
    assert "HDMI2 (PlayStation 5)" in mp.source_list
    assert "HDMI1 (Chromecast)" in mp.source_list
    assert mp.extra_state_attributes["raw_source"] == "HDMI2"
    assert mp.extra_state_attributes["custom_labels"] == {"HDMI1": "Chromecast"}

    # Test select_source stripping HDMI-CEC device label
    await mp.async_select_source("HDMI2 (PlayStation 5)")
    mock_client.change_source.assert_called_with("HDMI2", "HDMI2")

    # Test select_source matching by CEC device name directly
    await mp.async_select_source("Chromecast")
    mock_client.change_source.assert_called_with("HDMI1", "HDMI1")


@pytest.mark.anyio
async def test_media_player_cec_source_naming_disabled_by_default(mock_client, mock_entry):
    """Test that HDMI-CEC source labeling is disabled by default."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    # Empty options, should use DEFAULT_ENABLE_CEC_NAMES (False)
    mock_entry.options = {"include_apps_in_sources": True}
    mp = VidaaMediaPlayer(
        client=mock_client,
        entry=mock_entry,
    )
    mp.hass = hass
    mp._source_dict = {
        "HDMI1": {"sourceid": "HDMI1", "sourcename": "HDMI1", "displayname2": "Chromecast"},
        "HDMI2": {"sourceid": "HDMI2", "sourcename": "HDMI2"},
    }
    mp._source = "HDMI2"
    mp._connected_device = "PlayStation 5"

    assert mp.source == "HDMI2"
    assert "HDMI2" in mp.source_list
    assert "HDMI2 (PlayStation 5)" not in mp.source_list
    assert "HDMI1" in mp.source_list
    assert "HDMI1 (Chromecast)" not in mp.source_list


@pytest.mark.anyio
async def test_media_player_select_source_and_play_media_when_off(mock_client, mock_entry):
    """Test that selecting source or playing media when TV is off powers on first."""
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
    mp._source_dict = {
        "HDMI1": {"sourceid": "HDMI1", "sourcename": "HDMI1"},
        "HDMI2": {"sourceid": "HDMI2", "sourcename": "HDMI2"},
    }
    mp._app_dict = {
        "Netflix": {"appId": "1", "name": "Netflix", "url": "url1"},
    }

    # Put TV in off state
    mp._handle_state_update({"statetype": "fake_sleep_0"})
    assert mp.state == "off"

    # Test select_source when off: should turn on then change source
    mock_client.send_key.reset_mock()
    mock_client.change_source.reset_mock()
    await mp.async_select_source("HDMI2")

    mock_client.send_key.assert_called_once_with("KEY_POWER")
    mock_client.change_source.assert_called_once_with("HDMI2", "HDMI2")

    # Put TV in off state again
    mp._handle_state_update({"statetype": "fake_sleep_0"})
    assert mp.state == "off"

    # Test play_media when off: should turn on then launch app
    mock_client.send_key.reset_mock()
    mock_client.async_launch_app = AsyncMock()
    await mp.async_play_media("app", "Netflix")

    mock_client.send_key.assert_called_once_with("KEY_POWER")
    mock_client.async_launch_app.assert_awaited_once_with("1", "Netflix", "url1")


@pytest.mark.anyio
async def test_media_player_parses_camelcase_source_and_app_payloads(mock_client, mock_entry):
    """[F5-leg4] camelCase source/app payloads are keyed like the payload parsers."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass

    mp._handle_sourcelist_update([{"sourceName": "HDMI 1", "sourceid": "HDMI1", "is_active": True}])
    assert "HDMI 1" in mp._source_dict
    assert mp.state == "on"
    assert mp.source == "HDMI 1"

    mp._handle_applist_update([{"appId": "1", "appName": "Netflix", "url": "netflix://"}])
    assert "Netflix" in mp._app_dict


def test_sourcelist_and_applist_parsers_accept_camelcase():
    """[F5-leg4] The data parsers accept the same spellings as the payload parsers."""
    assert parse_sourcelist_data([{"sourceName": "HDMI 1"}]) == {"HDMI 1": {"sourceName": "HDMI 1"}}
    assert parse_sourcelist_data([{"sourcename": "TV"}]) == {"TV": {"sourcename": "TV"}}
    assert parse_applist_data([{"appId": "1", "appName": "Netflix"}])[1] == {
        "Netflix": {"appId": "1", "appName": "Netflix"}
    }
    assert parse_applist_data([{"name": "Stan"}])[1] == {"Stan": {"name": "Stan"}}


@pytest.mark.anyio
async def test_media_player_play_media_accepts_alternate_app_keys(mock_client, mock_entry):
    """[F4-leg4] play_media must not raise KeyError on appId/url spelling variants."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    import asyncio

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass
    mp._app_dict = {"Stan": {"app_id": "123", "name": "Stan", "appUrl": "stan://"}}

    await mp.async_play_media("app", "Stan")
    mock_client.launch_app.assert_called_with("123", "Stan", "stan://")


def test_media_player_dynamic_source_icons(mock_client, mock_entry):
    """Test dynamic MDI icon branding based on active app or source input."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)

    # When off, should return television-off
    mp._state = STATE_OFF
    assert mp.icon == "mdi:television-off"

    # When on, check app and input mappings
    mp._state = STATE_ON
    mp._source = "Netflix"
    assert mp.icon == "mdi:netflix"

    mp._source = "YouTube"
    assert mp.icon == "mdi:youtube"

    mp._source = "Prime Video"
    assert mp.icon == "mdi:amazon"

    mp._source = "Disney+"
    assert mp.icon == "mdi:television-classic"

    mp._source = "Plex"
    assert mp.icon == "mdi:plex"

    mp._source = "Spotify"
    assert mp.icon == "mdi:spotify"

    mp._source = "Apple TV"
    assert mp.icon == "mdi:apple"

    mp._source = "Web Browser"
    assert mp.icon == "mdi:web"

    mp._source = "HDMI 2"
    assert mp.icon == "mdi:hdmi-port"

    mp._source = "Live TV"
    assert mp.icon == "mdi:television-guide"

    mp._source = "AV"
    assert mp.icon == "mdi:video-input-component"

    mp._source = "Other Source"
    assert mp.icon == "mdi:television"


@pytest.mark.anyio
async def test_media_player_source_filtering_option(mock_client, mock_entry):
    """Test user-configured source filtering via CONF_SOURCES option."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp._source_dict = {"HDMI1": {}, "HDMI2": {}, "TV": {}, "AV": {}}
    mp._app_dict = {"Netflix": {}, "YouTube": {}, "Plex": {}, "Prime Video": {}}

    # Default: all sources and apps
    full_sources = mp.source_list
    assert "HDMI1" in full_sources
    assert "Netflix" in full_sources
    assert "YouTube" in full_sources
    assert "Plex" in full_sources

    # Filtered: only select HDMI1, TV, and Netflix
    mock_entry.options[CONF_SOURCES] = ["HDMI1", "TV", "Netflix"]
    filtered_sources = mp.source_list
    assert filtered_sources == ["HDMI1", "TV", "Netflix"]
    assert "YouTube" not in filtered_sources
    assert "Plex" not in filtered_sources

    # If TV is currently on an unselected source (e.g. HDMI2), it must be preserved
    mp._source = "HDMI2"
    preserved_sources = mp.source_list
    assert "HDMI2" in preserved_sources


@pytest.mark.anyio
async def test_play_media_channel_by_name(mock_client, mock_entry):
    """Test play_media tunes channel by resolving name to channel number."""
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mock_client.channels = [
        {"channel_name": "ABC HD", "channel_num": "20"},
        {"channel_name": "SBS ONE", "channel_num": "3"},
    ]
    mock_client.async_send_key.reset_mock()

    await mp.async_play_media("channel", "ABC HD")

    # Should have sent KEY_2 and KEY_0
    calls = [call.args[0] for call in mock_client.async_send_key.call_args_list]
    assert "KEY_2" in calls
    assert "KEY_0" in calls
