"""Config entry migration and legacy folder checks for VIDAA Smart TV."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import (
        device_registry as dr,
        entity_registry as er,
        issue_registry as ir,
    )
except ImportError:  # pragma: no cover - non-HA unit test fallback
    ConfigEntry = Any  # type: ignore[misc,assignment]
    HomeAssistant = Any  # type: ignore[misc,assignment]
    dr = Any  # type: ignore[assignment]
    er = Any  # type: ignore[assignment]
    ir = Any  # type: ignore[assignment]

from .const import (
    CONF_AUTH_PROFILE,
    CONF_USE_SSL,
    DOMAIN,
    LEGACY_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "_async_check_and_manage_legacy_repair",
    "_check_and_manage_legacy_repair",
    "async_migrate_entry",
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry to new configuration version."""
    _LOGGER.debug(
        "Migrating config entry '%s' from version %s.%s",
        entry.title,
        entry.version,
        entry.minor_version,
    )

    if entry.version == 1:
        # Migrate entity registry if needed
        try:
            ent_reg = er.async_get(hass)
            entities: list[Any] = []
            if hasattr(er, "async_entries_for_config_entry"):
                entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
            elif hasattr(ent_reg, "entities"):
                if hasattr(ent_reg.entities, "get_entries_for_config_entry_id"):
                    entities = list(ent_reg.entities.get_entries_for_config_entry_id(entry.entry_id))
                elif isinstance(ent_reg.entities, dict):
                    entities = [
                        e for e in ent_reg.entities.values() if getattr(e, "config_entry_id", None) == entry.entry_id
                    ]
            for reg_entry in entities:
                if getattr(reg_entry, "platform", None) == LEGACY_DOMAIN:
                    if hasattr(ent_reg, "async_update_entity_platform"):
                        try:
                            ent_reg.async_update_entity_platform(
                                reg_entry.entity_id,
                                new_platform=DOMAIN,
                                new_config_entry_id=entry.entry_id,
                            )
                        except Exception:
                            object.__setattr__(reg_entry, "platform", DOMAIN)
                    else:
                        object.__setattr__(reg_entry, "platform", DOMAIN)
        except Exception as err:
            _LOGGER.debug("Non-fatal error migrating entity registry entries: %s", err)

        # Migrate device registry identifiers
        try:
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_device(identifiers={(LEGACY_DOMAIN, entry.entry_id)})
            if device:
                dev_reg.async_update_device(
                    device.id,
                    merge_identifiers={(DOMAIN, entry.entry_id), (LEGACY_DOMAIN, entry.entry_id)},
                )
        except Exception as err:
            _LOGGER.debug("Non-fatal error updating device registry: %s", err)

        # Migrate domain attribute if still legacy
        if getattr(entry, "domain", None) == LEGACY_DOMAIN:
            object.__setattr__(entry, "domain", DOMAIN)

        new_data = dict(entry.data)
        if new_data.get(CONF_AUTH_PROFILE) in ("legacy", "static") and new_data.get(CONF_USE_SSL) is False:
            new_data[CONF_USE_SSL] = True

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            version=2,
            minor_version=3,
        )
        _LOGGER.info(
            "Successfully migrated config entry '%s' to version 2.3",
            entry.title,
        )

    if entry.version == 2 and getattr(entry, "minor_version", 1) < 3:
        new_data = dict(entry.data)
        if new_data.get(CONF_AUTH_PROFILE) in ("legacy", "static") and new_data.get(CONF_USE_SSL) is False:
            new_data[CONF_USE_SSL] = True
            _LOGGER.info(
                "Migrated legacy static config entry '%s' to TLS (use_ssl=True) without client certificates",
                entry.title,
            )
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            minor_version=3,
        )
        _LOGGER.info(
            "Successfully migrated config entry '%s' to version 2.3",
            entry.title,
        )

    return True


async def _async_check_and_manage_legacy_repair(hass: HomeAssistant) -> None:
    """Check for leftover legacy custom_components/hisense_vidaa directory off the event loop."""
    try:
        if hasattr(hass, "config") and hasattr(hass.config, "path"):
            import inspect

            legacy_dir = hass.config.path("custom_components", LEGACY_DOMAIN)
            if hasattr(hass, "async_add_executor_job") and callable(hass.async_add_executor_job):
                res = hass.async_add_executor_job(os.path.isdir, legacy_dir)
                is_dir = await res if inspect.isawaitable(res) else res
            else:
                is_dir = os.path.isdir(legacy_dir)
            if is_dir:
                _LOGGER.warning(
                    "Legacy integration directory '%s' detected alongside '%s'. "
                    "Please remove 'custom_components/%s' and restart Home Assistant to avoid conflicts.",
                    legacy_dir,
                    DOMAIN,
                    LEGACY_DOMAIN,
                )
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    "legacy_folder_detected",
                    is_fixable=False,
                    is_persistent=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="legacy_folder_detected",
                    translation_placeholders={
                        "legacy_domain": LEGACY_DOMAIN,
                        "new_domain": DOMAIN,
                    },
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, "legacy_folder_detected")
    except Exception as err:
        _LOGGER.debug("Could not inspect custom_components directory: %s", err)


def _check_and_manage_legacy_repair(hass: HomeAssistant) -> None:
    """Synchronous compatibility wrapper for tests."""
    with contextlib.suppress(Exception):
        loop = hass.loop if hasattr(hass, "loop") else None
        if loop and loop.is_running():
            hass.async_create_background_task(
                _async_check_and_manage_legacy_repair(hass),
                "vidaa_check_legacy_repair",
            )
