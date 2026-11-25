"""App artwork reachability tracking and unified MDI fallback icons for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

try:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:
    async_get_clientsession = None  # type: ignore[assignment]

from .const import CONF_ENABLE_APP_ICONS, DEFAULT_ENABLE_APP_ICONS
from .icons import get_app_icon, get_media_player_icon, get_source_icon

_LOGGER = logging.getLogger(__name__)

ARTWORK_PROBE_TIMEOUT = 2.0
ARTWORK_PROBE_TTL = 3600.0

__all__ = [
    "ARTWORK_PROBE_TIMEOUT",
    "ARTWORK_PROBE_TTL",
    "ArtworkReachabilityTracker",
    "extract_http_icon_url",
    "extract_sample_artwork_url",
    "get_app_icon",
    "get_media_player_icon",
    "get_source_icon",
    "register_artwork_reachability_probe",
    "should_use_app_artwork",
]


def extract_http_icon_url(raw_icon: Any) -> str | None:
    """Extract a clean HTTP(S) URL from a raw VIDAA httpIcon string."""
    if not isinstance(raw_icon, str) or "http" not in raw_icon:
        return None
    cleaned = "http" + raw_icon.split("http", 1)[1].strip()
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    return None


def extract_sample_artwork_url(apps: Any) -> str | None:
    """Return the first valid artwork URL from a TV applist payload."""
    if not isinstance(apps, list):
        return None
    for app in apps:
        if isinstance(app, dict) and (url := extract_http_icon_url(app.get("httpIcon"))):
            return url
    return None


def _response_content_type(resp: Any) -> str:
    """Extract lowercase MIME content-type from an aiohttp or mock response."""
    headers = getattr(resp, "headers", None)
    if headers and hasattr(headers, "get"):
        raw = headers.get("Content-Type") or headers.get("content-type") or ""
        if isinstance(raw, str) and raw:
            return raw.split(";", 1)[0].strip().lower()
    ct = getattr(resp, "content_type", "")
    return str(ct).split(";", 1)[0].strip().lower() if isinstance(ct, str) else ""


def _is_valid_image_response(resp: Any) -> bool:
    """Return True if response indicates a reachable image resource (rejects DNS sinkhole HTML)."""
    status = getattr(resp, "status", 0)
    if not (200 <= status < 400):
        return False
    content_type = _response_content_type(resp)
    return not content_type or content_type.startswith("image/")


class ArtworkReachabilityTracker:
    """Tracks whether remote TV app artwork URLs are reachable and notifies entities on change."""

    def __init__(
        self,
        enabled: bool = True,
        ttl: float = ARTWORK_PROBE_TTL,
        timeout: float = ARTWORK_PROBE_TIMEOUT,
    ) -> None:
        """Initialize the reachability tracker."""
        self.enabled = enabled
        self.reachable = True
        self._ttl = ttl
        self._timeout = timeout
        self._last_probe: float | None = None
        self._probing = False
        self._probe_task: asyncio.Task[Any] | None = None
        self._listeners: list[Callable[[], None]] = []

    @property
    def allow_artwork(self) -> bool:
        """Return True when remote app artwork is both enabled and reachable."""
        return self.enabled and self.reachable

    def register_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when reachability changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[], None]) -> None:
        """Unregister a reachability change callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def set_reachable(self, value: bool) -> None:
        """Update reachability state and notify listeners if changed."""
        if self.reachable == value:
            return
        self.reachable = value
        for callback in list(self._listeners):
            try:
                callback()
            except Exception as err:
                _LOGGER.debug("Artwork reachability listener failed: %s", err)

    def cancel(self) -> None:
        """Cancel any active background reachability probe task."""
        if self._probe_task is not None and not self._probe_task.done():
            self._probe_task.cancel()
        self._probe_task = None

    def is_fresh(self) -> bool:
        """Return True if a probe result is still valid within the TTL window."""
        if self._last_probe is None:
            return False
        return (time.monotonic() - self._last_probe) < self._ttl

    async def async_probe_url(self, session: Any, url: str, *, force: bool = False) -> bool:
        """Probe a single sample artwork URL with caching to detect CDN/DNS blocks."""
        if not self.enabled:
            return False
        if not force and self.is_fresh():
            return self.reachable
        if not force and self._probing:
            return self.reachable

        self._probing = True
        is_reachable = False
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with session.head(url, timeout=timeout, allow_redirects=True) as resp:
                if getattr(resp, "status", 0) == 405:
                    async with session.get(
                        url,
                        headers={"Range": "bytes=0-0"},
                        timeout=timeout,
                        allow_redirects=True,
                    ) as get_resp:
                        is_reachable = _is_valid_image_response(get_resp)
                else:
                    is_reachable = _is_valid_image_response(resp)
            if not is_reachable and self.reachable:
                _LOGGER.info(
                    "App artwork CDN unreachable (%s); falling back to Material Design Icons",
                    url,
                )
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            is_reachable = False
            if self.reachable:
                _LOGGER.info(
                    "App artwork CDN unreachable (%s: %s); falling back to Material Design Icons",
                    url,
                    err,
                )
        finally:
            self._last_probe = time.monotonic()
            self._probing = False

        self.set_reachable(is_reachable)
        return is_reachable


def should_use_app_artwork(entry: Any) -> bool:
    """Return True if remote app artwork should be exposed for this config entry."""
    options = getattr(entry, "options", None)
    if isinstance(options, dict) and options.get(CONF_ENABLE_APP_ICONS, DEFAULT_ENABLE_APP_ICONS) is False:
        return False
    rt_data = getattr(entry, "runtime_data", None)
    tracker = getattr(rt_data, "artwork_tracker", None)
    if isinstance(tracker, ArtworkReachabilityTracker):
        return tracker.allow_artwork
    return True


def register_artwork_reachability_probe(
    hass: Any,
    entry: Any,
    client: Any,
    tracker: ArtworkReachabilityTracker,
) -> None:
    """Attach a one-shot/cached CDN reachability probe when TV applist data arrives."""
    if not tracker.enabled:
        return

    def _schedule_probe(apps: Any) -> None:
        sample_url = extract_sample_artwork_url(apps)
        if not sample_url:
            return
        if tracker.is_fresh() or (tracker._probe_task is not None and not tracker._probe_task.done()):
            return
        if async_get_clientsession is None or not hasattr(hass, "async_create_background_task"):
            return

        async def _run() -> None:
            try:
                session = async_get_clientsession(hass)
            except Exception:
                return
            await tracker.async_probe_url(session, sample_url)

        tracker._probe_task = hass.async_create_background_task(
            _run(),
            f"vidaa_artwork_probe_{getattr(entry, 'entry_id', 'entry')}",
        )

    client.register_applist_callback(_schedule_probe)
    entry.async_on_unload(lambda: client.unregister_applist_callback(_schedule_probe))
    entry.async_on_unload(tracker.cancel)

    existing_apps = getattr(client, "apps", None)
    if isinstance(existing_apps, list) and existing_apps:
        _schedule_probe(existing_apps)
