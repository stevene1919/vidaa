"""Remote platform for VIDAA Smart TV integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaClient
from .const import (
    CONF_ENABLE_WOL,
    CONF_KEY_DELAY,
    CONF_KEY_REPEAT,
    CONF_SECONDARY_MAC_ADDRESS,
    DEFAULT_ENABLE_WOL,
    DEFAULT_KEY_DELAY,
    DEFAULT_KEY_REPEAT,
    DOMAIN,
    POWER_KEYS,
)
from .entity import VidaaEntity
from .helpers import check_client_command_readiness

if TYPE_CHECKING:
    from . import VidaaConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Home Assistant's remote.send_command schema *always* supplies num_repeats
# (default 1), so a plain kwargs.get() would permanently shadow the key_repeat
# option. Treat the service default as "caller left it unset".
SERVICE_DEFAULT_NUM_REPEATS = 1


class VidaaRemote(VidaaEntity, RemoteEntity):
    """VIDAA Remote entity."""

    _attr_name = None

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_remote"

    async def async_added_to_hass(self) -> None:
        """Register callbacks and query initial state when entity is added to hass."""
        self._client.register_connected_callback(self._handle_connected)
        self._client.register_state_callback(self._handle_state_update)
        self._client.register_volume_callback(self._handle_update)
        self._client.register_sourcelist_callback(self._handle_update)
        self._client.register_applist_callback(self._handle_update)
        self._client.register_disconnected_callback(self._handle_disconnected)
        self._client.register_auth_failed_callback(self._handle_update)

        # Sync state immediately if client is already connected
        if getattr(self._client, "connected", False):
            self._is_on = bool(self._client.is_on)
            self._current_app = self._client.current_app

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        self._client.unregister_connected_callback(self._handle_connected)
        self._client.unregister_state_callback(self._handle_state_update)
        self._client.unregister_volume_callback(self._handle_update)
        self._client.unregister_sourcelist_callback(self._handle_update)
        self._client.unregister_applist_callback(self._handle_update)
        self._client.unregister_disconnected_callback(self._handle_disconnected)
        self._client.unregister_auth_failed_callback(self._handle_update)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def is_on(self) -> bool:
        """Return true if TV is on."""
        return bool(self._client and self._client.connected and self._client.is_on)

    @property
    def available(self) -> bool:
        """Return true if remote is available."""
        if getattr(self._client, "auth_failed", False) is True:
            return False
        return bool(self._entry_id and (self._client.access_token or self._mac))

    async def _async_exec(self, func: Any, *args: Any) -> Any:
        """Execute a client function."""
        res = func(*args)
        if asyncio.iscoroutine(res):
            return await res
        return res

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the TV on."""
        if getattr(self._client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        mac_targets = []
        if self._options.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL):
            if self._mac:
                mac_targets.append(self._mac)
            sec_mac = self._options.get(CONF_SECONDARY_MAC_ADDRESS) or getattr(self._entry, "data", {}).get(
                CONF_SECONDARY_MAC_ADDRESS
            )
            if sec_mac and sec_mac not in mac_targets:
                mac_targets.append(sec_mac)

        success = await self._client.async_turn_on(mac_targets if mac_targets else None)
        if success is False:
            raise HomeAssistantError(
                "Wake-on-LAN failed: TV did not wake up.",
                translation_domain=DOMAIN,
                translation_key="turn_on_failed",
            )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the TV off."""
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
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send a list of commands to the TV."""
        has_power_key = any(str(c).strip().lower() in POWER_KEYS for c in command)
        check_client_command_readiness(self._client, require_on=not has_power_key)
        try:
            default_delay = float(self._options.get(CONF_KEY_DELAY, DEFAULT_KEY_DELAY))
        except (ValueError, TypeError):
            default_delay = DEFAULT_KEY_DELAY

        try:
            default_repeats = int(self._options.get(CONF_KEY_REPEAT, DEFAULT_KEY_REPEAT))
        except (ValueError, TypeError):
            default_repeats = DEFAULT_KEY_REPEAT

        raw_repeats = kwargs.get("num_repeats", default_repeats)
        try:
            num_repeats = int(raw_repeats)
        except (ValueError, TypeError):
            num_repeats = default_repeats

        if num_repeats == SERVICE_DEFAULT_NUM_REPEATS:
            # HA always sends the service default; fall back to the key_repeat option.
            num_repeats = default_repeats

        try:
            delay_secs = float(kwargs.get("delay_secs", default_delay))
        except (ValueError, TypeError):
            delay_secs = default_delay

        try:
            hold_secs = float(kwargs.get("hold_secs", 0.0))
        except (ValueError, TypeError):
            hold_secs = 0.0

        for _ in range(num_repeats):
            for single_cmd in command:
                if hold_secs and hold_secs > 0:
                    cmd_lower = single_cmd.strip().lower()
                    if cmd_lower in ("ok", "enter", "select", "key_ok"):
                        res = await self._client.async_send_key("KEY_OK_LONG_PRESS")
                    elif cmd_lower in ("mute", "key_mute"):
                        res = await self._client.async_send_key("KEY_MUTE_LONG_PRESS")
                    else:
                        # Emulate key hold by rapid repetition over hold_secs
                        steps = max(1, round(hold_secs / 0.1))
                        res = True
                        for _ in range(steps):
                            step_res = await self._client.async_send_command(single_cmd)
                            if step_res is False:
                                res = False
                            await asyncio.sleep(0.1)
                else:
                    res = await self._client.async_send_command(single_cmd)

                if res is False:
                    raise HomeAssistantError(
                        f"Failed to send remote command {single_cmd}: command delivery failed",
                        translation_domain=DOMAIN,
                        translation_key="send_key_failed",
                        translation_placeholders={"key": str(single_cmd), "error": "command delivery failed"},
                    )

                if delay_secs > 0:
                    await asyncio.sleep(delay_secs)

    def _handle_update(self, *args: Any) -> None:
        """Handle state update from TV."""
        self.schedule_update_ha_state()

    def _handle_connected(self, *args: Any) -> None:
        self._handle_update()

    def _handle_disconnected(self, *args: Any) -> None:
        self._handle_update()

    def _handle_state_update(self, data: dict[str, Any]) -> None:
        # Keep this in lock-step with tv/state.py and tv/media.py: only fake_sleep_0
        # (exact) or a statetype containing "off" is off; fake_sleep_1 is the TV waking.
        if isinstance(data, dict) and self._client:
            statetype_l = str(data.get("statetype") or "").lower()
            self._client.is_on = not (statetype_l == "fake_sleep_0" or "off" in statetype_l)
        self._handle_update()


# Backwards-compatible alias during migration
HisenseVidaaRemote = VidaaRemote


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the VIDAA remote entity."""
    client: VidaaClient = config_entry.runtime_data.client
    async_add_entities([VidaaRemote(client=client, entry=config_entry)])
