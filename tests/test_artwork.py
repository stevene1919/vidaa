"""Tests for app artwork toggle, CDN reachability probing, and MDI fallbacks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.vidaa.artwork import (
    ArtworkReachabilityTracker,
    extract_http_icon_url,
    extract_sample_artwork_url,
    get_app_icon,
    get_media_player_icon,
    register_artwork_reachability_probe,
)
from custom_components.vidaa.const import CONF_ENABLE_APP_ICONS
from custom_components.vidaa.flow import VidaaOptionsFlowHandler
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.sensor import VidaaActiveAppSensor


class _FakeRespCtx:
    """Minimal async context manager wrapping a fake aiohttp response or exception."""

    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        content_type: str = "",
        error: Exception | None = None,
    ) -> None:
        self._resp = SimpleNamespace(
            status=status,
            headers=headers or {},
            content_type=content_type,
        )
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self._resp

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    """Fake aiohttp ClientSession recording HEAD/GET probe calls."""

    def __init__(self, head_ctx: _FakeRespCtx, get_ctx: _FakeRespCtx | None = None) -> None:
        self._head_ctx = head_ctx
        self._get_ctx = get_ctx or _FakeRespCtx(status=404)
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []

    def head(self, url: str, **_kwargs):
        self.head_calls.append(url)
        return self._head_ctx

    def get(self, url: str, **_kwargs):
        self.get_calls.append(url)
        return self._get_ctx


def test_extract_http_icon_url_and_sample():
    """Extract clean HTTP(S) URLs from raw VIDAA applist entries."""
    assert extract_http_icon_url("data:image/png;base64,iconDownloadhttps://img.vidaahub.com/a.png") == (
        "https://img.vidaahub.com/a.png"
    )
    assert extract_http_icon_url("http://192.168.1.5/icon.png ") == "http://192.168.1.5/icon.png"
    assert extract_http_icon_url("not_a_url") is None
    assert extract_http_icon_url(None) is None

    apps = [
        {"name": "LocalOnly", "httpIcon": ""},
        {"name": "Netflix", "httpIcon": "iconDownloadhttps://img.vidaahub.com/nf.png"},
        {"name": "YouTube", "httpIcon": "https://img.vidaahub.com/yt.png"},
    ]
    assert extract_sample_artwork_url(apps) == "https://img.vidaahub.com/nf.png"
    assert extract_sample_artwork_url([]) is None
    assert extract_sample_artwork_url(None) is None


@pytest.mark.anyio
async def test_artwork_tracker_probe_outcomes_and_ttl():
    """Verify HEAD 200 image, 405->ranged GET, sinkhole HTML rejection, network error, and TTL."""
    url = "https://img.vidaahub.com/vidaa/nf.png"

    # 1. 200 image/png -> reachable
    tracker = ArtworkReachabilityTracker(enabled=True, ttl=3600.0)
    session_ok = _FakeSession(_FakeRespCtx(status=200, headers={"Content-Type": "image/png"}))
    assert await tracker.async_probe_url(session_ok, url) is True
    assert tracker.allow_artwork is True
    assert len(session_ok.head_calls) == 1

    # TTL cache prevents duplicate network probe
    assert await tracker.async_probe_url(session_ok, url) is True
    assert len(session_ok.head_calls) == 1

    # 2. 405 on HEAD -> falls back to ranged GET 206 image/png
    tracker_405 = ArtworkReachabilityTracker(enabled=True, ttl=3600.0)
    session_405 = _FakeSession(
        _FakeRespCtx(status=405),
        _FakeRespCtx(status=206, headers={"Content-Type": "image/png"}),
    )
    assert await tracker_405.async_probe_url(session_405, url) is True
    assert len(session_405.head_calls) == 1
    assert len(session_405.get_calls) == 1

    # 3. 200 text/html (AdGuard/DNS sinkhole blockpage) -> False & listener notified
    notified: list[str] = []
    tracker_html = ArtworkReachabilityTracker(enabled=True, ttl=3600.0)
    tracker_html.register_listener(lambda: notified.append("changed"))
    session_html = _FakeSession(_FakeRespCtx(status=200, headers={"Content-Type": "text/html; charset=utf-8"}))
    assert await tracker_html.async_probe_url(session_html, url) is False
    assert tracker_html.allow_artwork is False
    assert notified == ["changed"]

    # 4. Network error / TimeoutError -> False & listener notified
    notified_err: list[str] = []
    tracker_err = ArtworkReachabilityTracker(enabled=True, ttl=3600.0)
    tracker_err.register_listener(lambda: notified_err.append("changed"))
    session_err = _FakeSession(_FakeRespCtx(error=aiohttp.ClientError("DNS failed")))
    assert await tracker_err.async_probe_url(session_err, url) is False
    assert tracker_err.allow_artwork is False
    assert notified_err == ["changed"]

    tracker_timeout = ArtworkReachabilityTracker(enabled=True, ttl=3600.0)
    session_timeout = _FakeSession(_FakeRespCtx(error=TimeoutError()))
    assert await tracker_timeout.async_probe_url(session_timeout, url) is False

    # 5. Disabled tracker never touches session
    tracker_disabled = ArtworkReachabilityTracker(enabled=False)
    assert await tracker_disabled.async_probe_url(session_ok, url) is False
    assert len(session_ok.head_calls) == 1


@pytest.mark.anyio
async def test_artwork_suppression_across_entities(mock_client, mock_entry):
    """Sensor, Media Player, and Media Browser respect enable_app_icons and tracker reachability."""
    mock_client.connected = True
    mock_client.is_on = True
    mock_client.current_app = "Netflix"
    mock_client.current_app_id = "1"
    mock_client.apps = [
        {"appId": "1", "name": "Netflix", "isFav": True, "httpIcon": "iconDownloadhttps://img.vidaahub.com/nf.png"},
    ]

    tracker = ArtworkReachabilityTracker(enabled=True)
    mock_entry.options = {CONF_ENABLE_APP_ICONS: True}
    mock_entry.runtime_data = SimpleNamespace(client=mock_client, options=mock_entry.options, artwork_tracker=tracker)

    app_sensor = VidaaActiveAppSensor(mock_client, mock_entry)
    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp._source = "Netflix"
    mp._app_dict = {"Netflix": {"appId": "1", "httpIcon": "iconDownloadhttps://img.vidaahub.com/nf.png"}}

    # 1. Enabled & reachable -> artwork URLs returned
    assert app_sensor.entity_picture == "https://img.vidaahub.com/nf.png"
    assert mp.media_image_url == "https://img.vidaahub.com/nf.png"
    apps_node = mp._build_apps_browser()
    assert apps_node.children[0].thumbnail == "https://img.vidaahub.com/nf.png"

    # 2. Power off -> media_image_url returns None
    mock_client.is_on = False
    mp._state = "off"
    assert mp.media_image_url is None
    mock_client.is_on = True
    mp._state = "on"

    # 3. CDN unreachable -> all artwork suppressed while MDI icon remains intact
    tracker.set_reachable(False)
    assert app_sensor.entity_picture is None
    assert app_sensor.icon == "mdi:netflix"
    assert mp.media_image_url is None
    assert mp.icon == "mdi:netflix"
    assert mp._build_apps_browser().children[0].thumbnail is None

    # 4. Manually disabled in options -> suppressed even if tracker was reachable
    tracker.set_reachable(True)
    mock_entry.options = {CONF_ENABLE_APP_ICONS: False}
    assert app_sensor.entity_picture is None
    assert mp.media_image_url is None
    assert mp._build_apps_browser().children[0].thumbnail is None


def test_expanded_mdi_fallback_icons():
    """Verify expanded MDI icon fallbacks when artwork is disabled or unreachable."""
    assert get_app_icon("Apple TV") == "mdi:apple"
    assert get_app_icon("Twitch") == "mdi:twitch"
    assert get_app_icon("TV Browser") == "mdi:web"
    assert get_app_icon("DEEZER") == "mdi:music"
    assert get_app_icon("Couchplay Games") == "mdi:gamepad-variant"
    assert get_app_icon("Kayo") == "mdi:trophy"
    assert get_app_icon("Stan.") == "mdi:television-play"
    assert get_app_icon("Disney+") == "mdi:movie-open"

    assert get_media_player_icon(True, "Twitch") == "mdi:twitch"
    assert get_media_player_icon(True, "DEEZER") == "mdi:music"
    assert get_media_player_icon(True, "Couchplay Games") == "mdi:gamepad-variant"
    assert get_media_player_icon(True, "Kayo") == "mdi:trophy"
    assert get_media_player_icon(False, "Netflix") == "mdi:television-off"


def test_register_artwork_reachability_probe_disabled_registers_no_callback():
    """When enable_app_icons is False, no applist callback or network probe is registered."""
    tracker = ArtworkReachabilityTracker(enabled=False)
    client = MagicMock()
    entry = MagicMock()
    register_artwork_reachability_probe(MagicMock(), entry, client, tracker)
    client.register_applist_callback.assert_not_called()


@pytest.mark.anyio
async def test_options_flow_saves_enable_app_icons():
    """Verify Playback & Sources options step saves enable_app_icons=False."""
    config_entry = MagicMock()
    config_entry.options = {CONF_ENABLE_APP_ICONS: True}
    config_entry.data = {}

    handler = VidaaOptionsFlowHandler(config_entry)
    form_res = await handler.async_step_playback_sources()
    assert form_res["type"] == "form"
    assert CONF_ENABLE_APP_ICONS in form_res["data_schema"].schema

    submit_res = await handler.async_step_playback_sources(
        user_input={
            "include_apps_in_sources": True,
            "enable_media_controls": False,
            "enable_cec_names": False,
            CONF_ENABLE_APP_ICONS: False,
            "playback_debounce": 0.5,
        }
    )
    assert submit_res["type"] == "create_entry"
    assert submit_res["data"][CONF_ENABLE_APP_ICONS] is False
