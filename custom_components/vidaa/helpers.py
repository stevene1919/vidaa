"""Helper functions for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.trigger import PluggableAction

from .const import (
    CONF_ENABLE_WOL,
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
    DEFAULT_ENABLE_WOL,
    DEFAULT_WOL_TIMEOUT,
    DOMAIN,
)


@callback
def check_client_command_readiness(client: Any, *, require_on: bool = False) -> None:
    """Validate client readiness before executing an action.

    Raises HomeAssistantError with translation_key='auth_required' if authentication failed.
    Raises HomeAssistantError with translation_key='not_connected' if client is disconnected.
    Raises HomeAssistantError with translation_key='device_off' if require_on is True and TV is off.
    """
    if getattr(client, "auth_failed", False) is True:
        raise HomeAssistantError(
            "Authentication required: Re-pair TV in Settings > Integrations.",
            translation_domain=DOMAIN,
            translation_key="auth_required",
        )
    if client is None or getattr(client, "connected", True) is False:
        raise HomeAssistantError(
            "TV offline: Device unreachable.",
            translation_domain=DOMAIN,
            translation_key="not_connected",
        )
    if require_on and getattr(client, "is_on", True) is False:
        raise HomeAssistantError(
            "Cannot perform action: TV is currently turned off.",
            translation_domain=DOMAIN,
            translation_key="device_off",
        )


async def async_ensure_tv_on(
    client: Any,
    *,
    turn_on_coro: Any = None,
    timeout: float = DEFAULT_WOL_TIMEOUT,
    action_description: str | None = None,
) -> None:
    """Ensure the TV is powered on and connected before executing an action.

    If the TV is off, triggers power-on and awaits wake state before proceeding.
    Raises HomeAssistantError if power-on fails or TV does not wake up.
    """
    if getattr(client, "auth_failed", False) is True:
        raise HomeAssistantError(
            "Authentication required: Re-pair TV in Settings > Integrations.",
            translation_domain=DOMAIN,
            translation_key="auth_required",
        )

    if getattr(client, "is_on", True) is False:
        if turn_on_coro is not None:
            res = turn_on_coro() if callable(turn_on_coro) else turn_on_coro
            if asyncio.iscoroutine(res):
                await res
        elif hasattr(client, "async_turn_on"):
            await client.async_turn_on()

        wait_fn = getattr(client, "async_wait_until_awake", None)
        if wait_fn is not None and callable(wait_fn):
            res = wait_fn(timeout=timeout)
            awake = await res if (asyncio.iscoroutine(res) or isinstance(res, asyncio.Future)) else bool(res)
            if not awake:
                desc = f" before {action_description}" if action_description else ""
                raise HomeAssistantError(
                    f"Failed to power on TV{desc}: TV did not wake up",
                    translation_domain=DOMAIN,
                    translation_key="turn_on_failed",
                )
        await asyncio.sleep(0.5)

    check_client_command_readiness(client, require_on=True)


def resolve_wol_mac_targets(
    entry: Any,
    *,
    fallback_mac: str | None = None,
    client: Any = None,
) -> list[str]:
    """Return deduplicated Wake-on-LAN MAC targets for an entry, or [] when disabled."""
    options = getattr(entry, "options", None) if entry is not None else None
    options_dict = options if isinstance(options, dict) else {}
    if not options_dict.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL):
        return []

    data = getattr(entry, "data", None) if entry is not None else None
    data_dict = data if isinstance(data, dict) else {}

    client_mac = getattr(client, "mac", None) if client is not None else None
    client_sec_mac = getattr(client, "secondary_mac", None) if client is not None else None

    primary = fallback_mac or data_dict.get(CONF_MAC_ADDRESS) or (client_mac if isinstance(client_mac, str) else None)
    secondary = (
        options_dict.get(CONF_SECONDARY_MAC_ADDRESS)
        or data_dict.get(CONF_SECONDARY_MAC_ADDRESS)
        or (client_sec_mac if isinstance(client_sec_mac, str) else None)
    )

    targets: list[str] = []
    for candidate in (primary, secondary):
        if isinstance(candidate, str) and candidate and candidate not in targets:
            targets.append(candidate)
    return targets


async def async_turn_on_entry(
    hass: HomeAssistant | None,
    entry: Any,
    client: Any,
    *,
    fallback_mac: str | None = None,
    context: Any = None,
) -> None:
    """Turn on a TV entry via custom Turn On trigger or client Wake-on-LAN/power."""
    if getattr(client, "auth_failed", False) is True:
        raise HomeAssistantError(
            "Authentication required: Re-pair TV in Settings > Integrations.",
            translation_domain=DOMAIN,
            translation_key="auth_required",
        )

    runtime_data = getattr(entry, "runtime_data", None) if entry is not None else None
    turn_on_action = getattr(runtime_data, "turn_on", None) if runtime_data is not None else None
    if isinstance(turn_on_action, PluggableAction) and bool(turn_on_action):
        await turn_on_action.async_run(hass, context)
        return

    mac_targets = resolve_wol_mac_targets(entry, fallback_mac=fallback_mac, client=client)
    success = await client.async_turn_on(mac_targets)
    if success is False:
        raise HomeAssistantError(
            "Wake-on-LAN failed: TV did not wake up.",
            translation_domain=DOMAIN,
            translation_key="turn_on_failed",
        )


@callback
def async_get_device_entry_by_device_id(hass: HomeAssistant, device_id: str) -> DeviceEntry:
    """Get Device Entry from Device Registry by device ID.

    Raises ValueError if device ID is invalid.
    """
    device_reg = dr.async_get(hass)
    device = device_reg.async_get(device_id, include_child_devices=False) if hasattr(device_reg, "async_get") else None
    if device is None:
        raise ValueError(f"Device {device_id} is not a valid {DOMAIN} device.")

    return device


@callback
def async_get_device_id_from_entity_id(hass: HomeAssistant, entity_id: str) -> str:
    """Get device ID from an entity ID.

    Raises HomeAssistantError if entity or device ID is invalid.
    """
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get(entity_id) if hasattr(ent_reg, "async_get") else None

    if (
        entity_entry is None
        or getattr(entity_entry, "device_id", None) is None
        or getattr(entity_entry, "platform", None) != DOMAIN
    ):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="invalid_entity_id",
            translation_placeholders={"entity_id": entity_id},
        )

    return entity_entry.device_id
