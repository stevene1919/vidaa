"""Helper functions for VIDAA Smart TV."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN


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
