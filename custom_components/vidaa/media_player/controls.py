"""Control actions mixin for VIDAA media player platform."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN
from ..helpers import (
    async_ensure_tv_on,
    async_turn_on_entry,
    check_client_command_readiness,
)
from ..tv.media import async_execute_play_media, async_execute_select_source

if TYPE_CHECKING:
    from . import VidaaMediaPlayer

_LOGGER = logging.getLogger(__name__)


class MediaPlayerControlsMixin:
    """Control and command mixin for VidaaMediaPlayer."""

    async def async_turn_on(self: VidaaMediaPlayer) -> None:
        """Turn on or wake the TV."""
        await async_turn_on_entry(
            getattr(self, "hass", None),
            self._entry,
            self._client,
            fallback_mac=self._mac,
            context=getattr(self, "_context", None),
        )
        self.async_write_ha_state()

    async def async_turn_off(self: VidaaMediaPlayer) -> None:
        """Turn off the TV."""
        if getattr(self._client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(self._client, "connected", True) is False and getattr(self._client, "is_on", True):
            raise HomeAssistantError(
                "TV offline: Device unreachable.",
                translation_domain=DOMAIN,
                translation_key="not_connected",
            )
        if not getattr(self._client, "is_on", True):
            return
        success = await self._client.async_turn_off()
        if success is False:
            raise HomeAssistantError(
                "Failed to send power off command to TV",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_POWER", "error": "command delivery failed"},
            )
        self._paused = False
        self.async_write_ha_state()

    async def async_set_volume_level(self: VidaaMediaPlayer, volume: float) -> None:
        """Set volume level (0.0 to 1.0)."""
        check_client_command_readiness(self._client, require_on=True)
        res = await self._client.async_set_volume(int(volume * 100))
        if res is False:
            raise HomeAssistantError(
                "Failed to set volume level: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "changevolume", "error": "command delivery failed"},
            )

    async def async_volume_up(self: VidaaMediaPlayer) -> None:
        """Step volume up."""
        check_client_command_readiness(self._client, require_on=True)
        if await self._client.async_send_key("KEY_VOLUMEUP") is False:
            raise HomeAssistantError(
                "Failed to send volume up: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_VOLUMEUP", "error": "command delivery failed"},
            )

    async def async_volume_down(self: VidaaMediaPlayer) -> None:
        """Step volume down."""
        check_client_command_readiness(self._client, require_on=True)
        if await self._client.async_send_key("KEY_VOLUMEDOWN") is False:
            raise HomeAssistantError(
                "Failed to send volume down: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_VOLUMEDOWN", "error": "command delivery failed"},
            )

    async def async_mute_volume(self: VidaaMediaPlayer, mute: bool) -> None:
        """Mute or unmute volume idempotently."""
        # KEY_MUTE is a toggle: only send it when the requested state differs from
        # the state tracked from TV broadcasts, so idempotent automations don't flip
        # the TV on every run.
        check_client_command_readiness(self._client, require_on=True)
        if bool(mute) == bool(self._muted):
            return
        if await self._client.async_send_key("KEY_MUTE") is False:
            raise HomeAssistantError(
                "Failed to toggle mute: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_MUTE", "error": "command delivery failed"},
            )

    async def async_media_play(self: VidaaMediaPlayer) -> None:
        """Send play command."""
        check_client_command_readiness(self._client, require_on=True)
        if await self._client.async_send_key("KEY_PLAY") is False:
            raise HomeAssistantError(
                "Failed to send play: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_PLAY", "error": "command delivery failed"},
            )
        self._paused = False
        self.async_write_ha_state()

    async def async_media_pause(self: VidaaMediaPlayer) -> None:
        """Send pause command."""
        check_client_command_readiness(self._client, require_on=True)
        if await self._client.async_send_key("KEY_PAUSE") is False:
            raise HomeAssistantError(
                "Failed to send pause: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_PAUSE", "error": "command delivery failed"},
            )
        self._paused = True
        self.async_write_ha_state()

    async def async_media_stop(self: VidaaMediaPlayer) -> None:
        """Send stop command."""
        check_client_command_readiness(self._client, require_on=True)
        if await self._client.async_send_key("KEY_STOP") is False:
            raise HomeAssistantError(
                "Failed to send stop: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": "KEY_STOP", "error": "command delivery failed"},
            )
        self._paused = False
        self.async_write_ha_state()

    async def async_media_next_track(self: VidaaMediaPlayer) -> None:
        """Send next track command: Channel Up on Live TV, fast-forward/skip in media apps."""
        check_client_command_readiness(self._client, require_on=True)
        key = "KEY_CHANNELUP" if (hasattr(self, "is_live_tv") and self.is_live_tv()) else "KEY_FORWARDS"
        if await self._client.async_send_key(key) is False:
            raise HomeAssistantError(
                f"Failed to send {key}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": key, "error": "command delivery failed"},
            )

    async def async_media_previous_track(self: VidaaMediaPlayer) -> None:
        """Send previous track command: Channel Down on Live TV, rewind/skip in media apps."""
        check_client_command_readiness(self._client, require_on=True)
        key = "KEY_CHANNELDOWN" if (hasattr(self, "is_live_tv") and self.is_live_tv()) else "KEY_BACK"
        if await self._client.async_send_key(key) is False:
            raise HomeAssistantError(
                f"Failed to send {key}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": key, "error": "command delivery failed"},
            )

    async def async_play_media(self: VidaaMediaPlayer, media_type: str, media_id: str, **kwargs: Any) -> None:
        """Launch an app, tune to channel, open URL/deep-link, or execute key command."""
        await async_ensure_tv_on(
            self._client,
            turn_on_coro=self.async_turn_on,
            action_description=f"playing media '{media_id}'",
        )

        res = await async_execute_play_media(self._client, self._app_dict, media_type, media_id)
        if res is False:
            raise HomeAssistantError(
                f"Failed to play media {media_id}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="launch_app_failed",
                translation_placeholders={"app_name": str(media_id), "error": "command delivery failed"},
            )

    async def async_select_source(self: VidaaMediaPlayer, source: str) -> None:
        """Select input source or smart application."""
        await async_ensure_tv_on(
            self._client,
            turn_on_coro=self.async_turn_on,
            action_description=f"selecting source '{source}'",
        )

        res = await async_execute_select_source(self._client, self._source_dict, self._app_dict, source)
        if res is False:
            raise HomeAssistantError(
                f"Failed to select source {source}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="launch_app_failed",
                translation_placeholders={"app_name": str(source), "error": "command delivery failed"},
            )

    async def async_select_sound_mode(self: VidaaMediaPlayer, sound_mode: str) -> None:
        """Select sound mode."""
        check_client_command_readiness(self._client, require_on=True)
        res = await self._client.async_set_sound_mode(sound_mode)
        if res is False:
            raise HomeAssistantError(
                f"Failed to set sound mode to {sound_mode}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="set_sound_setting_failed",
                translation_placeholders={"menu_id": "sound_mode", "error": "command delivery failed"},
            )
        self.async_write_ha_state()
