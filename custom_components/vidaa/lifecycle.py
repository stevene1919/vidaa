"""Post-setup lifecycle helpers for VIDAA Smart TV (TLS/repair checks, pruning, clock sync, enrichment)."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
    from homeassistant.helpers.event import async_track_time_interval
except ImportError:  # pragma: no cover - non-HA unit test fallback
    ConfigEntry = Any  # type: ignore[misc,assignment]
    HomeAssistant = Any  # type: ignore[misc,assignment]
    dr = Any  # type: ignore[assignment]
    er = Any  # type: ignore[assignment]
    ir = Any  # type: ignore[assignment]
    async_track_time_interval = Any  # type: ignore[assignment]

from .const import (
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_SW_VERSION,
    DOMAIN,
    LEGACY_DOMAIN,
)

if TYPE_CHECKING:
    from .client import VidaaClient

_LOGGER = logging.getLogger(__name__)

DEFAULT_CLOCK_SYNC_INTERVAL = timedelta(hours=2)

__all__ = [
    "DEFAULT_CLOCK_SYNC_INTERVAL",
    "async_ensure_entry_mac",
    "async_resolve_entry_tls",
    "async_sync_certificate_repair_issue",
    "prune_retired_entities",
    "register_clock_sync_hooks",
    "register_device_info_enrichment",
]


async def async_ensure_entry_mac(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the entry MAC address, resolving via ARP and persisting if missing."""
    data = entry.data
    mac = data.get(CONF_MAC_ADDRESS)
    if mac:
        return mac
    with contextlib.suppress(Exception):
        from .tv.fingerprint import get_arp_mac

        raw_mac = await hass.async_add_executor_job(get_arp_mac, data[CONF_IP_ADDRESS])
        if raw_mac:
            mac = dr.format_mac(raw_mac)
            new_unique_id = entry.unique_id or mac
            if (
                not entry.unique_id
                and hasattr(hass, "config_entries")
                and hasattr(hass.config_entries, "async_entries")
            ):
                for other in hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id != entry.entry_id and getattr(other, "unique_id", None) == mac:
                        _LOGGER.warning(
                            "[%s] Resolved MAC %s already belongs to entry '%s'; keeping existing unique_id",
                            data.get(CONF_IP_ADDRESS),
                            mac,
                            other.title,
                        )
                        new_unique_id = entry.unique_id
                        break
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_MAC_ADDRESS: mac},
                unique_id=new_unique_id,
            )
    return mac


async def async_resolve_entry_tls(
    hass: HomeAssistant,
    entry: ConfigEntry,
    auth_profile: str,
    use_ssl: bool,
    *,
    resolve_certificates_fn: Callable[..., tuple[str | None, str | None]],
    resolve_ca_certificate_fn: Callable[..., str | None],
) -> tuple[bool, str | None, str | None, str | None]:
    """Resolve client TLS certificates, private key, and CA certificate off the event loop."""
    certfile = entry.options.get(CONF_CERTFILE, entry.data.get(CONF_CERTFILE))
    keyfile = entry.options.get(CONF_KEYFILE, entry.data.get(CONF_KEYFILE))
    if auth_profile in ("legacy", "static") and not use_ssl:
        use_ssl = True

    ca_cert = None
    if use_ssl and auth_profile not in ("legacy", "static"):
        raw_config_dir = getattr(getattr(hass, "config", None), "config_dir", None)
        config_dir = os.fspath(raw_config_dir) if isinstance(raw_config_dir, (str, os.PathLike)) else None
        certfile, keyfile = await hass.async_add_executor_job(
            resolve_certificates_fn, auth_profile, certfile, keyfile, None, config_dir
        )
        ca_cert = await hass.async_add_executor_job(resolve_ca_certificate_fn, None, None, config_dir)
    elif auth_profile in ("legacy", "static"):

        def _check_legacy_files(c: str | None, k: str | None) -> tuple[str | None, str | None]:
            return (c if (c and os.path.isfile(c)) else None, k if (k and os.path.isfile(k)) else None)

        certfile, keyfile = await hass.async_add_executor_job(_check_legacy_files, certfile, keyfile)

    return use_ssl, certfile, keyfile, ca_cert


async def async_sync_certificate_repair_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: VidaaClient,
    *,
    use_ssl: bool,
    auth_profile: str,
) -> None:
    """Create or clear the missing-certificate repair issue off the event loop."""
    is_legacy_static = auth_profile in ("legacy", "static")
    certs_valid = (
        await hass.async_add_executor_job(
            lambda: bool(
                client.certfile
                and client.keyfile
                and os.path.isfile(client.certfile)
                and os.path.isfile(client.keyfile)
            )
        )
        if (use_ssl and not is_legacy_static)
        else True
    )

    issue_id = f"certificate_missing_{entry.entry_id}"
    if use_ssl and not is_legacy_static and not certs_valid:
        ip_addr = str(entry.data.get(CONF_IP_ADDRESS, ""))
        tv_name = str(entry.title or ip_addr or "VIDAA TV")
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="certificate_missing",
            translation_placeholders={"name": tv_name, "ip_address": ip_addr},
            data={"entry_id": entry.entry_id},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _remove_legacy_entity_if_present(entity_reg: Any, platform: str, unique_id: str) -> None:
    """Remove an obsolete entity across current and legacy domains if registered."""
    for domain in (DOMAIN, LEGACY_DOMAIN):
        if entity_id := entity_reg.async_get_entity_id(platform, domain, unique_id):
            entity_reg.async_remove(entity_id)


def prune_retired_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    enable_picture_controls: bool,
) -> None:
    """Remove retired or disabled entity registry entries for a config entry."""
    entity_reg = er.async_get(hass)

    for suffix in ("brand_profile", "auth_profile"):
        _remove_legacy_entity_if_present(entity_reg, "sensor", f"{entry.entry_id}_{suffix}")

    if not enable_picture_controls:
        for suffix in ("backlight", "brightness", "contrast"):
            _remove_legacy_entity_if_present(entity_reg, "number", f"{entry.entry_id}_{suffix}")

    _remove_legacy_entity_if_present(entity_reg, "notify", f"{entry.entry_id}_notify")
    _remove_legacy_entity_if_present(entity_reg, "select", f"{entry.entry_id}_audio_output_select")


def register_clock_sync_hooks(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: VidaaClient,
    *,
    track_time_interval: Any = None,
) -> None:
    """Attach periodic and wake-transition UPnP clock synchronization callbacks."""

    async def _async_sync_tv_clock(_now: Any = None) -> None:
        if not client.connected or not client.is_on:
            return
        try:
            await client.async_sync_clock(2.0)
        except Exception as err:
            _LOGGER.debug("[%s] Periodic clock sync failed: %s", client.ip, err)

    tracker = track_time_interval or async_track_time_interval
    entry.async_on_unload(tracker(hass, _async_sync_tv_clock, DEFAULT_CLOCK_SYNC_INTERVAL))

    last_power_state = [client.is_on]

    def _on_state_change(_state: dict[str, Any]) -> None:
        was_on = last_power_state[0]
        now_on = client.is_on
        last_power_state[0] = now_on
        if not was_on and now_on:
            hass.async_create_background_task(
                _async_sync_tv_clock(),
                f"vidaa_wake_clock_sync_{entry.entry_id}",
            )

    client.register_state_callback(_on_state_change)
    entry.async_on_unload(lambda: client.unregister_state_callback(_on_state_change))


def register_device_info_enrichment(hass: HomeAssistant, entry: ConfigEntry, client: VidaaClient) -> None:
    """Attach live MQTT device registry and dual-MAC config entry enrichment callback."""

    def _on_device_info_update(_data: dict[str, Any]) -> None:
        try:
            dev_reg = dr.async_get(hass)
            device = None
            if hasattr(dev_reg, "async_get_device_by_identifier"):
                device = dev_reg.async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id)
            if not device and hasattr(dev_reg, "async_get_device"):
                device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
            if not device:
                return

            updates: dict[str, Any] = {}
            if client.model_name and client.model_name != device.model:
                updates["model"] = client.model_name
            if client.manufacturer and client.manufacturer != device.manufacturer:
                updates["manufacturer"] = client.manufacturer
            if client.firmware_version and client.firmware_version != device.sw_version:
                updates["sw_version"] = client.firmware_version
            if client.mac_wifi or client.mac_ethernet:
                new_connections = (
                    set(device.connections)
                    if isinstance(getattr(device, "connections", None), (set, list, tuple))
                    else set()
                )
                for mac_candidate in (client.mac_wifi, client.mac_ethernet):
                    if mac_candidate:
                        new_connections.add((dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac_candidate)))
                if isinstance(getattr(device, "connections", None), set) and new_connections != device.connections:
                    updates["merge_connections"] = new_connections

            if updates:
                dev_reg.async_update_device(device.id, **updates)

            new_data = dict(entry.data)
            data_changed = False

            if not new_data.get(CONF_MAC_ADDRESS) and (client.mac_wifi or client.mac_ethernet):
                new_data[CONF_MAC_ADDRESS] = dr.format_mac(client.mac_wifi or client.mac_ethernet)
                data_changed = True

            primary_mac = new_data.get(CONF_MAC_ADDRESS)
            detected_sec = None
            if client.mac_wifi and client.mac_ethernet and client.mac_wifi != client.mac_ethernet:
                if primary_mac == client.mac_wifi:
                    detected_sec = client.mac_ethernet
                elif primary_mac == client.mac_ethernet:
                    detected_sec = client.mac_wifi
                else:
                    detected_sec = client.mac_ethernet
            elif client.mac_ethernet and primary_mac != client.mac_ethernet:
                detected_sec = client.mac_ethernet
            elif client.mac_wifi and primary_mac != client.mac_wifi:
                detected_sec = client.mac_wifi

            if (
                detected_sec
                and not entry.options.get(CONF_SECONDARY_MAC_ADDRESS)
                and new_data.get(CONF_SECONDARY_MAC_ADDRESS) != detected_sec
            ):
                new_data[CONF_SECONDARY_MAC_ADDRESS] = detected_sec
                data_changed = True

            for update_key, conf_key in (
                ("model", CONF_MODEL),
                ("manufacturer", CONF_MANUFACTURER),
                ("sw_version", CONF_SW_VERSION),
            ):
                if update_key in updates and updates[update_key] != new_data.get(conf_key):
                    new_data[conf_key] = updates[update_key]
                    data_changed = True

            if data_changed:
                hass.config_entries.async_update_entry(entry, data=new_data)
        except Exception as err:
            _LOGGER.debug("[%s] Dynamic device registry enrichment failed: %s", client.ip, err)

    client.register_device_info_callback(_on_device_info_update)
    entry.async_on_unload(lambda: client.unregister_device_info_callback(_on_device_info_update))
