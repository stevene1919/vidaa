"""Material Design Icon fallback helpers for VIDAA Smart TV apps, inputs, and media player."""

from __future__ import annotations

__all__ = [
    "get_app_icon",
    "get_media_player_icon",
    "get_source_icon",
]

_SPORTS_KEYWORDS = ("kayo", "dazn", "nba", "ufc", "uefa", "espn", "sport")
_MUSIC_KEYWORDS = ("deezer", "tidal", "music", "soundcloud")
_GAME_KEYWORDS = ("game", "couchplay")
_STREAMING_KEYWORDS = (
    "stan",
    "binge",
    "paramount",
    "hbo",
    "max",
    "foxtel",
    "crunchyroll",
    "mubi",
    "tubi",
    "britbox",
    "filmzie",
    "9now",
    "7plus",
    "10 play",
    "iview",
    "sbs",
    "wetv",
    "iwant",
    "vidaa",
)

_COMMON_APP_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("netflix",), "mdi:netflix"),
    (("youtube",), "mdi:youtube"),
    (("spotify",), "mdi:spotify"),
    (("plex",), "mdi:plex"),
    (("apple",), "mdi:apple"),
    (("twitch",), "mdi:twitch"),
    (("browser", "web"), "mdi:web"),
    (_MUSIC_KEYWORDS, "mdi:music"),
    (_GAME_KEYWORDS, "mdi:gamepad-variant"),
    (_SPORTS_KEYWORDS, "mdi:trophy"),
)

_APP_ICON_EXTRA_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("disney",), "mdi:movie-open"),
    (("prime", "amazon"), "mdi:video"),
    (("home launcher", "launcher"), "mdi:view-dashboard"),
    (("hdmi input", "tv input", "none"), "mdi:video-input-hdmi"),
    (("av input",), "mdi:video-input-component"),
    (("standby",), "mdi:television-ambient-light"),
    (("off",), "mdi:television-off"),
    (_STREAMING_KEYWORDS, "mdi:television-play"),
)

_SOURCE_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("standby",), "mdi:power-sleep"),
    (("off",), "mdi:television-off"),
    (("home", "launcher"), "mdi:view-dashboard"),
    (("hdmi",), "mdi:video-input-hdmi"),
    (("tv",), "mdi:television-classic"),
    (("av", "component"), "mdi:video-input-component"),
)


def _match_icon_rule(val: str, rules: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    """Return the first matching MDI icon from a keyword-rule table."""
    for keywords, icon in rules:
        if any(kw in val for kw in keywords):
            return icon
    return None


def get_app_icon(app_name: str | None) -> str:
    """Return dynamic MDI icon based on active application or input state."""
    val = (app_name or "").lower()
    if "disney" in val:
        return "mdi:movie-open"
    if "prime" in val or "amazon" in val:
        return "mdi:video"
    if "live tv" in val or val == "tv":
        return "mdi:television-box"
    return (
        _match_icon_rule(val, _COMMON_APP_ICON_RULES)
        or _match_icon_rule(val, _APP_ICON_EXTRA_RULES)
        or "mdi:application"
    )


def get_source_icon(source_name: str | None) -> str:
    """Return dynamic MDI icon based on active input source name."""
    val = (source_name or "").lower()
    if val == "app":
        return "mdi:application"
    return _match_icon_rule(val, _SOURCE_ICON_RULES) or "mdi:video-input-hdmi"


def get_media_player_icon(is_on: bool, source: str | None) -> str:
    """Return dynamic MDI icon for VidaaMediaPlayer based on power and source."""
    if not is_on:
        return "mdi:television-off"
    src = (source or "").lower()
    if "youtube" in src or "yt" in src:
        return "mdi:youtube"
    if "prime" in src or "amazon" in src:
        return "mdi:amazon"
    if "disney" in src:
        return "mdi:television-classic"
    if matched := _match_icon_rule(src, _COMMON_APP_ICON_RULES):
        return matched
    if "hdmi" in src:
        return "mdi:hdmi-port"
    if "tv" in src or "tuner" in src or "live" in src:
        return "mdi:television-guide"
    if "av" in src or "component" in src:
        return "mdi:video-input-component"
    return "mdi:television"
