"""App matching, input source switching, and navigation helpers for VIDAA Smart TV."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from ..artwork import get_app_icon, get_source_icon
from .aliases import KEY_ALIASES

if TYPE_CHECKING:
    from ..client import VidaaClient

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "KEY_ALIASES",
    "change_source_by_name_or_id",
    "cycle_tv_source",
    "get_app_icon",
    "get_next_cycled_source",
    "get_source_icon",
    "launch_app_by_name",
    "match_app",
    "normalize_string",
    "resolve_canonical_app",
    "resolve_command_key",
    "resolve_source",
]


def normalize_string(s: str) -> str:
    """Normalizes a string by stripping non-alphanumeric characters and lowercasing."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def resolve_canonical_app(
    app_name: str | None,
    apps: list[dict[str, Any]] | None = None,
    app_id: str | None = None,
    url: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve an incoming app name/id/url to its canonical applist (name, appId)."""
    clean_name = str(app_name).strip() if isinstance(app_name, str) and app_name.strip() else None
    clean_id = str(app_id).strip() if app_id is not None and str(app_id).strip() else None
    clean_url = str(url).strip() if isinstance(url, str) and url.strip() else None

    if not isinstance(apps, list) or not apps:
        return clean_name, clean_id

    if clean_id:
        for app in apps:
            if not isinstance(app, dict):
                continue
            cand_id = str(app.get("appId") or app.get("appid") or "").strip()
            if cand_id and cand_id == clean_id:
                cand_name = str(app.get("name") or app.get("appName") or "").strip()
                return (cand_name or clean_name), cand_id

    if clean_name:
        target_low = clean_name.lower()
        for app in apps:
            if not isinstance(app, dict):
                continue
            cand_name = str(app.get("name") or app.get("appName") or "").strip()
            if cand_name and cand_name.lower() == target_low:
                cand_id = str(app.get("appId") or app.get("appid") or "").strip() or clean_id
                return cand_name, cand_id

    if clean_url:
        url_low = clean_url.lower()
        for app in apps:
            if not isinstance(app, dict):
                continue
            cand_url = str(app.get("url") or "").strip()
            if cand_url and cand_url.lower() == url_low:
                cand_name = str(app.get("name") or app.get("appName") or "").strip()
                cand_id = str(app.get("appId") or app.get("appid") or "").strip() or clean_id
                return (cand_name or clean_name), cand_id

    return clean_name, clean_id


def match_app(
    apps: list[dict[str, Any]],
    target: str,
) -> dict[str, str] | None:
    """Matches a target app string against a list of installed apps.

    Returns a dict with 'appId', 'name', 'url' if matched, or None.
    """
    if not target or not apps:
        return None

    clean_target = target.strip().lower()
    norm_target = normalize_string(target)

    # 1. Exact match on name or ID
    for app in apps:
        if isinstance(app, dict):
            app_name = str(app.get("name") or app.get("appName") or "").strip().lower()
            app_id = str(app.get("appId") or app.get("id") or "").strip().lower()
            if clean_target in (app_name, app_id):
                return {
                    "appId": str(app.get("appId") or app.get("id") or ""),
                    "name": str(app.get("name") or app.get("appName") or target),
                    "url": str(app.get("url") or app.get("appUrl") or ""),
                }

    # 2. Normalized alphanumeric match
    for app in apps:
        if isinstance(app, dict):
            app_name = str(app.get("name") or app.get("appName") or "")
            app_id = str(app.get("appId") or app.get("id") or "")
            if norm_target and (norm_target == normalize_string(app_name) or norm_target == normalize_string(app_id)):
                return {
                    "appId": str(app.get("appId") or app.get("id") or ""),
                    "name": app_name or target,
                    "url": str(app.get("url") or app.get("appUrl") or ""),
                }

    # 3. Substring match
    for app in apps:
        if isinstance(app, dict):
            app_name = str(app.get("name") or app.get("appName") or "").lower()
            if clean_target in app_name or (norm_target and norm_target in normalize_string(app_name)):
                return {
                    "appId": str(app.get("appId") or app.get("id") or ""),
                    "name": str(app.get("name") or app.get("appName") or target),
                    "url": str(app.get("url") or app.get("appUrl") or ""),
                }

    return None


def resolve_source(
    sources: list[dict[str, Any]],
    target: str,
) -> tuple[str, str | None]:
    """Resolves target source name or ID against list of available sources.

    Returns (source_id, source_name).
    """
    if not target:
        return "", None

    clean_target = target.strip().lower()
    if sources:
        for source_entry in sources:
            if isinstance(source_entry, dict):
                source_name = str(source_entry.get("sourcename") or "").strip()
                display_name = str(source_entry.get("displayname") or "").strip()
                source_id = str(source_entry.get("sourceid") or "").strip()
                if clean_target in (source_name.lower(), display_name.lower(), source_id.lower()):
                    return source_id or source_name, source_name or display_name or source_id
                if clean_target in ("tv", "live tv", "livetv", "dtv", "antenna") and (
                    source_name.lower() in ("tv", "live tv", "livetv", "dtv", "antenna")
                    or source_id.lower() in ("tv", "live tv", "livetv", "dtv", "antenna")
                ):
                    return source_id or source_name, source_name or display_name or source_id

    if clean_target in ("tv", "live tv", "livetv", "dtv", "antenna"):
        return "TV", "TV"

    return target.strip(), None


def _is_hardware_source(source_entry: dict[str, Any]) -> bool:
    """Checks if a source entry represents a physical TV hardware input."""
    source_name = str(source_entry.get("sourcename") or "").strip().lower()
    source_id = str(source_entry.get("sourceid") or "").strip().lower()
    display_name = str(source_entry.get("displayname") or "").strip().lower()
    for identifier in (source_name, source_id, display_name):
        if any(
            identifier.startswith(prefix) for prefix in ("hdmi", "av", "tv", "dtv", "atv", "antenna", "comp", "vga")
        ):
            return True
        if identifier in ("tv", "live tv", "livetv", "av", "avs"):
            return True
    return False


def get_next_cycled_source(
    sources: list[dict[str, Any]],
    current_source: str | None,
) -> tuple[str, str] | None:
    """Calculates the next source in the cycle order based on current source.

    Returns (source_id, source_name) or None if no valid sources.
    """
    if not sources:
        return None

    valid_sources = [
        source
        for source in sources
        if isinstance(source, dict) and (source.get("sourceid") is not None or source.get("sourcename") is not None)
    ]
    if not valid_sources:
        return None

    # Filter for hardware/physical input sources first to prevent cycling into apps (e.g. VIDAA tv ID 284)
    hardware_sources = [source for source in valid_sources if _is_hardware_source(source)]
    candidate_sources = hardware_sources if hardware_sources else valid_sources

    current_clean = str(current_source or "").strip().lower()
    current_index = -1
    for index, source in enumerate(candidate_sources):
        source_name = str(source.get("sourcename") or "").strip().lower()
        display_name = str(source.get("displayname") or "").strip().lower()
        source_id = str(source.get("sourceid") or "").strip().lower()
        if current_clean and (current_clean in (source_name, display_name, source_id)):
            current_index = index
            break
        if current_clean in ("tv", "live tv", "livetv", "dtv", "antenna") and (
            source_name in ("tv", "live tv", "livetv", "dtv", "antenna")
            or source_id in ("tv", "live tv", "livetv", "dtv", "antenna")
        ):
            current_index = index
            break

    next_index = (current_index + 1) % len(candidate_sources)
    next_source = candidate_sources[next_index]
    source_id = str(next_source.get("sourceid") or next_source.get("sourcename") or "")
    source_name = str(next_source.get("sourcename") or next_source.get("displayname") or source_id)
    return source_id, source_name


def resolve_command_key(command: str) -> str:
    """Resolves command string or alias to TV remote key code."""
    cmd_clean = command.strip().lower()
    return KEY_ALIASES.get(cmd_clean, command.strip().upper())


def launch_app_by_name(client: VidaaClient, app_name: str) -> bool:
    """Launches an app on the TV by searching the client's cached app registry."""
    matched = match_app(getattr(client, "apps", []), app_name)
    if matched:
        client.launch_app(matched["appId"], matched["name"], matched["url"])
        return True
    client.launch_app("", app_name, app_name)
    return True


def change_source_by_name_or_id(client: VidaaClient, source_target: str) -> bool:
    """Changes input source on the TV by matching against available sources."""
    sid, sname = resolve_source(getattr(client, "sources", []), source_target)
    client.change_source(sid, sname)
    return True


def cycle_tv_source(client: VidaaClient) -> bool:
    """Cycles through input sources on the TV."""
    cycled = get_next_cycled_source(getattr(client, "sources", []), getattr(client, "current_source", None))
    if cycled:
        sid, sname = cycled
        client.change_source(sid, sname)
        return True
    return False
