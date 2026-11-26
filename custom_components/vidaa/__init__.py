"""VIDAA Smart TV custom component integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

try:
    from homeassistant.components import persistent_notification
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import (
        config_validation as cv,
        device_registry as dr,
        entity_registry as er,
        issue_registry as ir,
    )
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.event import async_track_time_interval
    from homeassistant.helpers.trigger import PluggableAction

    _HAS_HA = True
except ImportError:
    _HAS_HA = False
    ConfigEntry = Any  # type: ignore[misc,assignment]
    HomeAssistant = Any  # type: ignore[misc,assignment]
    ConfigEntryNotReady = Exception  # type: ignore[misc,assignment]
    PluggableAction = Any  # type: ignore[misc,assignment]

from .artwork import ArtworkReachabilityTracker, register_artwork_reachability_probe
from .client import VidaaClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCESS_TOKEN_DURATION,
    CONF_ACCESS_TOKEN_TIME,
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CLIENT_ID,
    CONF_ENABLE_APP_ICONS,
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_DURATION,
    CONF_REFRESH_TOKEN_TIME,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_USE_SSL,
    CONF_USERNAME,
    DEFAULT_BRAND,
    DEFAULT_BRAND_OPTION,
    DEFAULT_ENABLE_APP_ICONS,
    DEFAULT_ENABLE_PICTURE_CONTROLS,
    DEFAULT_USE_SSL,
    DOMAIN,
    LEGACY_DOMAIN,
)
from .lifecycle import (
    DEFAULT_CLOCK_SYNC_INTERVAL,
    async_ensure_entry_mac,
    async_resolve_entry_tls,
    async_sync_certificate_repair_issue,
    prune_retired_entities,
    register_clock_sync_hooks,
    register_device_info_enrichment,
)
from .migration import (
    _async_check_and_manage_legacy_repair,
    _check_and_manage_legacy_repair,
    async_migrate_entry,
)
from .protocol import resolve_ca_certificate, resolve_certificates
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = [
    "media_player",
    "remote",
    "sensor",
    "binary_sensor",
    "button",
    "switch",
    "select",
    "number",
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN) if _HAS_HA else None

__all__ = [
    "CONFIG_SCHEMA",
    "DEFAULT_CLOCK_SYNC_INTERVAL",
    "DOMAIN",
    "PLATFORMS",
    "HisenseVidaaConfigEntry",
    "HisenseVidaaData",
    "VidaaConfigEntry",
    "VidaaData",
    "_async_check_and_manage_legacy_repair",
    "_check_and_manage_legacy_repair",
    "async_migrate_entry",
    "async_remove_config_entry_device",
    "async_remove_entry",
    "async_setup",
    "async_setup_entry",
    "async_track_time_interval",
    "async_unload_entry",
    "dr",
    "er",
    "ir",
    "update_listener",
]


@dataclass
class VidaaData:
    """Runtime data for VIDAA Smart TV integration."""

    client: VidaaClient
    platforms: list[str]
    options: dict[str, Any]
    turn_on: PluggableAction | None = None
    artwork_tracker: ArtworkReachabilityTracker | None = None


HisenseVidaaData = VidaaData

type VidaaConfigEntry = ConfigEntry[VidaaData]
type HisenseVidaaConfigEntry = VidaaConfigEntry


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the VIDAA Smart TV integration services."""
    await async_setup_services(hass)
    await _async_check_and_manage_legacy_repair(hass)

    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_entries"):
        for legacy_entry in hass.config_entries.async_entries(LEGACY_DOMAIN):
            _LOGGER.info(
                "Found legacy %s config entry '%s'; migrating to %s", LEGACY_DOMAIN, legacy_entry.title, DOMAIN
            )
            await async_migrate_entry(hass, legacy_entry)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: VidaaConfigEntry) -> bool:
    """Set up VIDAA Smart TV from a config entry."""
    await _async_check_and_manage_legacy_repair(hass)

    version = getattr(entry, "version", None)
    minor_version = getattr(entry, "minor_version", 1)
    if isinstance(version, int) and (version < 2 or (version == 2 and minor_version < 3)):
        await async_migrate_entry(hass, entry)

    # Services are removed when the last entry unloads; re-assert idempotently on every setup.
    await async_setup_services(hass)

    data = entry.data
    mac = await async_ensure_entry_mac(hass, entry)
    sec_mac = entry.options.get(CONF_SECONDARY_MAC_ADDRESS) or data.get(CONF_SECONDARY_MAC_ADDRESS)
    auth_profile = entry.options.get(CONF_AUTH_PROFILE, data.get(CONF_AUTH_PROFILE, "auto"))
    use_ssl = entry.options.get(CONF_USE_SSL, data.get(CONF_USE_SSL, DEFAULT_USE_SSL))
    use_ssl, certfile, keyfile, ca_cert = await async_resolve_entry_tls(
        hass,
        entry,
        auth_profile,
        use_ssl,
        resolve_certificates_fn=resolve_certificates,
        resolve_ca_certificate_fn=resolve_ca_certificate,
    )

    brand_pref = entry.options.get(CONF_BRAND, data.get(CONF_BRAND, DEFAULT_BRAND_OPTION))
    client_brand = (
        (data.get("resolved_brand") or data.get("detected_brand") or DEFAULT_BRAND)
        if brand_pref == "auto"
        else brand_pref
    )

    client = VidaaClient(
        ip=data[CONF_IP_ADDRESS],
        mac=mac,
        secondary_mac=sec_mac,
        client_id=data.get(CONF_CLIENT_ID),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        access_token=data.get(CONF_ACCESS_TOKEN),
        access_token_time=data.get(CONF_ACCESS_TOKEN_TIME),
        access_token_duration=data.get(CONF_ACCESS_TOKEN_DURATION),
        refresh_token=data.get(CONF_REFRESH_TOKEN),
        refresh_token_time=data.get(CONF_REFRESH_TOKEN_TIME),
        refresh_token_duration=data.get(CONF_REFRESH_TOKEN_DURATION),
        auth_profile=auth_profile,
        certfile=certfile,
        keyfile=keyfile,
        ca_cert=ca_cert,
        use_ssl=use_ssl,
        brand=client_brand,
        session=async_get_clientsession(hass),
    )
    client._loop = hass.loop

    brand_changed = (brand_pref != "auto" and client.brand != data.get(CONF_BRAND)) or (
        brand_pref == "auto" and client.brand != data.get("resolved_brand")
    )
    if client.client_id != data.get(CONF_CLIENT_ID) or brand_changed:
        new_data = {
            **data,
            CONF_CLIENT_ID: client.client_id,
            CONF_USERNAME: client.username,
            CONF_PASSWORD: client.password,
            CONF_ACCESS_TOKEN: client.access_token,
            CONF_REFRESH_TOKEN: client.refresh_token,
            "resolved_brand": client.brand,
        }
        if brand_pref != "auto":
            new_data[CONF_BRAND] = client.brand
        hass.config_entries.async_update_entry(entry, data=new_data)
        data = new_data

    await async_sync_certificate_repair_issue(hass, entry, client, use_ssl=use_ssl, auth_profile=auth_profile)

    def update_entry_tokens(refreshed_client: VidaaClient) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: refreshed_client.access_token,
                CONF_ACCESS_TOKEN_TIME: refreshed_client.access_token_time,
                CONF_ACCESS_TOKEN_DURATION: refreshed_client.access_token_duration,
                CONF_REFRESH_TOKEN: refreshed_client.refresh_token,
                CONF_REFRESH_TOKEN_TIME: refreshed_client.refresh_token_time,
                CONF_REFRESH_TOKEN_DURATION: refreshed_client.refresh_token_duration,
            },
        )

    client.register_token_refreshed_callback(update_entry_tokens)

    def _handle_auth_failed(failed_client: VidaaClient) -> None:
        """Trigger native Home Assistant Core reauthentication flow."""
        # Delete any legacy custom repair card so only Core's native reauth card is shown.
        ir.async_delete_issue(hass, DOMAIN, f"auth_token_invalidated_{entry.entry_id}")
        entry.async_start_reauth(hass)

    client.register_auth_failed_callback(_handle_auth_failed)

    if not client.access_token or not client.client_id or not client.username:
        _LOGGER.warning("[%s] Missing credentials or authentication tokens; starting reauthentication", client.ip)
        client.auth_failed = True
        _handle_auth_failed(client)
    elif await client.async_check_and_refresh_token():
        update_entry_tokens(client)

    platforms_to_setup = [p for p in PLATFORMS if p != "number"]
    enable_picture = entry.options.get(CONF_ENABLE_PICTURE_CONTROLS, DEFAULT_ENABLE_PICTURE_CONTROLS)
    prune_retired_entities(hass, entry, enable_picture_controls=enable_picture)
    if enable_picture:
        platforms_to_setup.append("number")

    try:
        await client.async_connect_and_run()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to VIDAA TV at {client.ip}: {err}") from err

    artwork_tracker = ArtworkReachabilityTracker(
        enabled=entry.options.get(CONF_ENABLE_APP_ICONS, DEFAULT_ENABLE_APP_ICONS)
    )

    entry.runtime_data = VidaaData(
        client=client,
        platforms=platforms_to_setup,
        options=dict(entry.options),
        turn_on=PluggableAction(),
        artwork_tracker=artwork_tracker,
    )

    await hass.config_entries.async_forward_entry_setups(entry, platforms_to_setup)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    register_clock_sync_hooks(hass, entry, client, track_time_interval=async_track_time_interval)
    register_device_info_enrichment(hass, entry, client)
    register_artwork_reachability_probe(hass, entry, client, artwork_tracker)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: VidaaConfigEntry, device_entry: Any
) -> bool:
    """Remove a config entry from a device (stale device cleanup)."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: VidaaConfigEntry) -> None:
    """Clean up persistent Repairs issues belonging to a removed entry."""
    ir.async_delete_issue(hass, DOMAIN, f"certificate_missing_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"auth_token_invalidated_{entry.entry_id}")
    persistent_notification.async_dismiss(hass, f"vidaa_reauth_{entry.entry_id}")


async def update_listener(hass: HomeAssistant, entry: VidaaConfigEntry) -> None:
    """Handle options update."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data and runtime_data.options == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VidaaConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    platforms = runtime_data.platforms if runtime_data else PLATFORMS
    client = runtime_data.client if runtime_data else None

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        if client:
            await client.async_disconnect()
        await async_unload_services(hass, current_entry=entry)
    return unload_ok
