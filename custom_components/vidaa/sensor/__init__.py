"""Operational and metadata sensors for VIDAA Smart TV."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..artwork import ArtworkReachabilityTracker, should_use_app_artwork
from ..client import VidaaClient
from ..const import DOMAIN, LEGACY_DOMAIN
from ..tv.media import parse_applist_payload, parse_sourcelist_payload
from ..tv.navigation import get_app_icon, get_source_icon, resolve_canonical_app
from .diagnostic import (
    HisenseVidaaBaseSensor,
    HisenseVidaaClockDriftSensor,
    HisenseVidaaReportedNameSensor,
    HisenseVidaaSessionStatusSensor,
    VidaaBaseSensor,
    VidaaClockDriftSensor,
    VidaaReportedNameSensor,
    VidaaSessionStatusSensor,
)

if TYPE_CHECKING:
    from .. import VidaaConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

__all__ = [
    "HisenseVidaaActiveAppSensor",
    "HisenseVidaaActiveSourceSensor",
    "HisenseVidaaBaseSensor",
    "HisenseVidaaClockDriftSensor",
    "HisenseVidaaMqttTrackingSensor",
    "HisenseVidaaReportedNameSensor",
    "HisenseVidaaSessionStatusSensor",
    "VidaaActiveAppSensor",
    "VidaaActiveSourceSensor",
    "VidaaBaseSensor",
    "VidaaClockDriftSensor",
    "VidaaMqttTrackingSensor",
    "VidaaReportedNameSensor",
    "VidaaSessionStatusSensor",
    "async_setup_entry",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIDAA sensors based on a config entry."""
    # Prune retired standalone sensors from entity registry
    entity_reg = er.async_get(hass)
    for suffix in ("audio_output", "brand_profile", "auth_profile"):
        unique_id = f"{entry.entry_id}_{suffix}"
        for domain in (DOMAIN, LEGACY_DOMAIN):
            if entity_id := entity_reg.async_get_entity_id("sensor", domain, unique_id):
                entity_reg.async_remove(entity_id)

    client: VidaaClient = entry.runtime_data.client
    async_add_entities(
        [
            VidaaSessionStatusSensor(client, entry),
            VidaaReportedNameSensor(client, entry),
            VidaaActiveAppSensor(client, entry),
            VidaaActiveSourceSensor(client, entry),
            VidaaClockDriftSensor(client, entry),
        ]
    )


class VidaaMqttTrackingSensor(VidaaBaseSensor):
    """Base class for sensors tracking live MQTT state and connection events."""

    def __init__(self, client: VidaaClient, entry: ConfigEntry, default_on: str, default_off: str = "Off") -> None:
        super().__init__(client, entry)
        self._default_on = default_on
        self._default_off = default_off
        if not client.connected:
            self._attr_native_value = default_off
        elif not client.is_on and default_on != "Standby":
            self._attr_native_value = "Standby"
        else:
            self._attr_native_value = default_on

    async def async_added_to_hass(self) -> None:
        self._client.register_connected_callback(self._handle_connected)
        self._client.register_state_callback(self._handle_state_update)
        self._client.register_disconnected_callback(self._handle_disconnected)
        self._client.register_auth_failed_callback(self._handle_auth_failed)
        self._register_custom_callbacks()
        self._sync_from_client()

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_connected_callback(self._handle_connected)
        self._client.unregister_state_callback(self._handle_state_update)
        self._client.unregister_disconnected_callback(self._handle_disconnected)
        self._client.unregister_auth_failed_callback(self._handle_auth_failed)
        self._unregister_custom_callbacks()

    @property
    def available(self) -> bool:
        """Return True if the TV entity is available."""
        return super().available and getattr(self._client, "auth_failed", False) is not True

    def _handle_auth_failed(self, *args: Any) -> None:
        self._schedule_state_update()

    def _sync_from_client(self) -> None:
        """Hydrate cached client telemetry when entity initializes or attaches."""

    def _register_custom_callbacks(self) -> None:
        pass

    def _unregister_custom_callbacks(self) -> None:
        pass

    def _handle_connected(self) -> None:
        if self._attr_native_value == self._default_off:
            if not self._client.is_on and self._default_on != "Standby":
                self._attr_native_value = "Standby"
            else:
                self._attr_native_value = self._default_on
        self._schedule_state_update()

    def _handle_disconnected(self) -> None:
        self._attr_native_value = self._default_off
        self._schedule_state_update()

    def _handle_state_update(self, state: dict[str, Any]) -> None:
        raise NotImplementedError


def _format_input_app_label(source: str | None) -> str:
    """Return a user-friendly active_app label for a physical input source."""
    low = (source or "").strip().lower()
    if low == "tv":
        return "Live TV"
    if "hdmi" in low:
        return "HDMI Input"
    if "av" in low or "component" in low or "composite" in low:
        return "AV Input"
    return "TV Input"


class VidaaActiveAppSensor(VidaaMqttTrackingSensor):
    """Sensor reporting the foreground active application."""

    _attr_translation_key = "active_app"

    def __init__(self, client: VidaaClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry, default_on="Standby", default_off="Off")
        self._attr_unique_id = f"{self._entry_id}_active_app"
        self._app_dict: dict[str, str] = {}
        self._app_icons: dict[str, str] = {}
        self._favorite_apps: list[str] = []
        self._last_known_app: str | None = None
        self._sync_from_client()

    def _sync_from_client(self) -> None:
        """Hydrate app catalog and foreground app state from already-received client telemetry."""
        apps = getattr(self._client, "apps", None)
        if isinstance(apps, list) and apps:
            self._app_dict, self._app_icons, self._favorite_apps = parse_applist_payload(apps)

        active_src: str | None = None
        sources = getattr(self._client, "sources", None)
        if isinstance(sources, list) and sources:
            _, _, _, active_src = parse_sourcelist_payload(sources)

        if getattr(self._client, "connected", False) is not True:
            self._attr_native_value = self._default_off
            return
        if getattr(self._client, "is_on", False) is not True:
            self._attr_native_value = "Standby"
            return

        current_app = getattr(self._client, "current_app", None)
        if isinstance(current_app, str) and current_app:
            self._attr_native_value = current_app
            self._last_known_app = current_app
            return

        current_src = getattr(self._client, "current_source", None)
        resolved_src = current_src if isinstance(current_src, str) and current_src else active_src
        if resolved_src:
            label = _format_input_app_label(resolved_src)
            self._attr_native_value = label
            if label == "Live TV":
                self._last_known_app = "Live TV"

    def _register_custom_callbacks(self) -> None:
        self._client.register_applist_callback(self._handle_applist_update)
        self._client.register_sourcelist_callback(self._handle_sourcelist_update)
        tracker = getattr(getattr(self._entry, "runtime_data", None), "artwork_tracker", None)
        if isinstance(tracker, ArtworkReachabilityTracker):
            tracker.register_listener(self._schedule_state_update)

    def _unregister_custom_callbacks(self) -> None:
        self._client.unregister_applist_callback(self._handle_applist_update)
        self._client.unregister_sourcelist_callback(self._handle_sourcelist_update)
        tracker = getattr(getattr(self._entry, "runtime_data", None), "artwork_tracker", None)
        if isinstance(tracker, ArtworkReachabilityTracker):
            tracker.unregister_listener(self._schedule_state_update)

    def _handle_applist_update(self, apps: list[dict[str, Any]]) -> None:
        if apps:
            self._app_dict, self._app_icons, self._favorite_apps = parse_applist_payload(apps)
            self._schedule_state_update()

    def _handle_sourcelist_update(self, sources: list[dict[str, Any]]) -> None:
        if sources and self._client.connected and self._client.is_on:
            _, _, _, active_src = parse_sourcelist_payload(sources)
            if active_src and self._attr_native_value in ("Off", "Standby"):
                label = _format_input_app_label(active_src)
                self._attr_native_value = label
                if label == "Live TV":
                    self._last_known_app = "Live TV"
                self._schedule_state_update()

    def _handle_state_update(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict):
            return
        statetype = state.get("statetype")
        if not self._client.connected:
            self._attr_native_value = "Off"
        elif statetype == "fake_sleep_0" or not self._client.is_on:
            self._attr_native_value = "Standby"
        elif statetype == "app":
            raw_name = state.get("name") or state.get("appName") or state.get("appname")
            app_id = str(state.get("appId") or state.get("activeAppId") or state.get("appid") or "")
            canonical_name, canonical_id = resolve_canonical_app(
                str(raw_name) if raw_name else None,
                getattr(self._client, "apps", None),
                app_id or None,
                state.get("url"),
            )
            resolved_id = canonical_id or app_id
            self._attr_native_value = canonical_name or self._app_dict.get(resolved_id, "App")
            self._last_known_app = self._attr_native_value
        elif statetype == "livetv":
            self._attr_native_value = "Live TV"
            self._last_known_app = "Live TV"
        elif statetype == "sourceswitch":
            src = (
                state.get("sourcename")
                or state.get("sourceName")
                or state.get("displayname")
                or state.get("sourceid")
                or getattr(self._client, "current_source", None)
            )
            label = _format_input_app_label(src if isinstance(src, str) else None)
            self._attr_native_value = label
            if label == "Live TV":
                self._last_known_app = "Live TV"
        elif statetype in ("launcher", "remote_launcher"):
            self._attr_native_value = "Home Launcher"
            self._last_known_app = "Home Launcher"
        else:
            app_id = str(state.get("appId") or state.get("activeAppId") or state.get("appid") or "")
            if app_id:
                self._attr_native_value = self._app_dict.get(app_id, app_id)
                self._last_known_app = self._attr_native_value
        self._schedule_state_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs: dict[str, Any] = {"total_installed_apps": len(self._app_dict)}
        if self._last_known_app:
            attrs["last_known_app"] = self._last_known_app
        return attrs

    @property
    def entity_picture(self) -> str | None:
        """Return dynamic app icon artwork."""
        if not should_use_app_artwork(self._entry):
            return None
        return self._app_icons.get(self._attr_native_value) if self._attr_native_value else None

    @property
    def icon(self) -> str:
        """Return dynamic MDI icon for the active app or state."""
        return get_app_icon(self._attr_native_value)


class VidaaActiveSourceSensor(VidaaMqttTrackingSensor):
    """Sensor reporting current physical input source."""

    _attr_translation_key = "active_source"

    def __init__(self, client: VidaaClient, entry: ConfigEntry) -> None:
        super().__init__(client, entry, default_on="Standby", default_off="Off")
        self._attr_unique_id = f"{self._entry_id}_active_source"
        self._available_sources: list[str] = []
        self._connected_inputs: list[str] = []
        self._custom_labels: dict[str, str] = {}
        self._connected_device: str | None = None
        self._last_known_source: str | None = None
        self._sync_from_client()

    def _sync_from_client(self) -> None:
        """Hydrate source catalog and active physical input from cached client telemetry."""
        active_src: str | None = None
        sources = getattr(self._client, "sources", None)
        if isinstance(sources, list) and sources:
            self._available_sources, self._connected_inputs, self._custom_labels, active_src = parse_sourcelist_payload(
                sources
            )
            if active_src:
                self._last_known_source = active_src

        if getattr(self._client, "connected", False) is not True:
            self._attr_native_value = self._default_off
            self._connected_device = None
            return
        if getattr(self._client, "is_on", False) is not True:
            self._attr_native_value = "Standby"
            self._connected_device = None
            return

        current_app = getattr(self._client, "current_app", None)
        if isinstance(current_app, str) and current_app:
            self._attr_native_value = "Home Launcher" if current_app == "Home Launcher" else "App"
            self._connected_device = None
            return

        current_src = getattr(self._client, "current_source", None)
        resolved_src = current_src if isinstance(current_src, str) and current_src else active_src
        if resolved_src:
            self._attr_native_value = resolved_src
            self._last_known_source = resolved_src
            conn_dev = getattr(self._client, "connected_device", None)
            self._connected_device = (
                conn_dev if isinstance(conn_dev, str) and conn_dev else self._custom_labels.get(resolved_src)
            )

    def _register_custom_callbacks(self) -> None:
        self._client.register_sourcelist_callback(self._handle_sourcelist_update)

    def _unregister_custom_callbacks(self) -> None:
        self._client.unregister_sourcelist_callback(self._handle_sourcelist_update)

    def _handle_state_update(self, state: dict[str, Any]) -> None:
        statetype = state.get("statetype")
        if not self._client.connected:
            self._attr_native_value = "Off"
            self._connected_device = None
        elif statetype == "fake_sleep_0" or not self._client.is_on:
            self._attr_native_value = "Standby"
            self._connected_device = None
        elif statetype == "sourceswitch":
            resolved = state.get("sourcename") or state.get("sourceName") or state.get("displayname")
            if not resolved and "sourceid" in state:
                client_src = getattr(self._client, "current_source", None)
                resolved = client_src if isinstance(client_src, str) and client_src else str(state["sourceid"])
            self._attr_native_value = resolved or "HDMI"
            self._last_known_source = self._attr_native_value
            self._connected_device = (
                state.get("displayname2")
                or state.get("source_detail")
                or self._custom_labels.get(self._attr_native_value)
            )
        elif statetype == "livetv":
            self._attr_native_value = "TV"
            self._last_known_source = "TV"
            self._connected_device = None
        elif statetype == "app":
            self._attr_native_value = "App"
            self._connected_device = None
        elif statetype in ("launcher", "remote_launcher"):
            self._attr_native_value = "Home Launcher"
            self._connected_device = None
        elif state.get("sourcename") or state.get("sourceName"):
            self._attr_native_value = state.get("sourcename") or state.get("sourceName")
            self._last_known_source = self._attr_native_value
            self._connected_device = (
                state.get("displayname2")
                or state.get("source_detail")
                or self._custom_labels.get(self._attr_native_value)
            )
        self._schedule_state_update()

    def _handle_sourcelist_update(self, sources: list[dict[str, Any]]) -> None:
        if sources:
            self._available_sources, self._connected_inputs, self._custom_labels, active_src = parse_sourcelist_payload(
                sources
            )
            if active_src:
                self._last_known_source = active_src
                if self._client.connected and self._client.is_on:
                    self._attr_native_value = active_src
            if (
                self._attr_native_value
                and self._attr_native_value in self._custom_labels
                and not self._connected_device
            ):
                self._connected_device = self._custom_labels[self._attr_native_value]
            self._schedule_state_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return physical input source attributes."""
        attrs: dict[str, Any] = {}
        if (
            self._attr_native_value
            and self._attr_native_value not in ("Off", "Standby", "App", "Home Launcher")
            and self._connected_device
            and "hdmi" in str(self._attr_native_value).lower()
        ):
            attrs["display_name"] = f"{self._attr_native_value} ({self._connected_device})"
        if self._last_known_source:
            attrs["last_known_source"] = self._last_known_source
        attrs.update(
            {
                key: val
                for key, val in (
                    ("available_sources", self._available_sources),
                    ("connected_inputs", self._connected_inputs),
                    ("connected_device", self._connected_device),
                )
                if val
            }
        )
        return attrs

    @property
    def icon(self) -> str:
        """Return dynamic MDI icon based on active input source."""
        return get_source_icon(self._attr_native_value)


# Backwards-compatible aliases during migration
HisenseVidaaMqttTrackingSensor = VidaaMqttTrackingSensor
HisenseVidaaActiveAppSensor = VidaaActiveAppSensor
HisenseVidaaActiveSourceSensor = VidaaActiveSourceSensor
