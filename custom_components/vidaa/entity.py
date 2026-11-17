"""Base entity for the VIDAA Smart TV integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import VidaaClient
from .const import (
    BRAND_MAP,
    CONF_BRAND,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_SW_VERSION,
    DEFAULT_BRAND,
    DEFAULT_NAME,
    DOMAIN,
    LEGACY_DOMAIN,
)

__all__ = ["HisenseVidaaEntity", "VidaaEntity"]


class VidaaEntity(Entity):
    """Base entity representation for VIDAA Smart TV."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the base entity."""
        self._client = client
        self._entry: ConfigEntry = entry
        self._entry_id = entry.entry_id
        self._mac = entry.data.get(CONF_MAC_ADDRESS)
        self._name = entry.title or DEFAULT_NAME
        self._model = entry.data.get(CONF_MODEL, "VIDAA TV")
        client_brand = getattr(client, "brand", DEFAULT_BRAND)
        self._brand = client_brand if client_brand != "auto" else entry.data.get(CONF_BRAND, DEFAULT_BRAND)
        if self._brand == "auto":
            self._brand = DEFAULT_BRAND
        brand_default_mfg = BRAND_MAP.get(self._brand, "Hisense")
        self._manufacturer = entry.data.get(CONF_MANUFACTURER) or brand_default_mfg
        self._sw_version = entry.data.get(CONF_SW_VERSION)
        self._options = entry.options

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant DeviceInfo linking to this TV."""
        model = self._client.model_name or self._model
        brand_mfg = BRAND_MAP.get(getattr(self._client, "brand", self._brand), "Hisense")
        manufacturer = self._client.manufacturer or self._manufacturer or brand_mfg
        sw_version = self._client.firmware_version or self._sw_version
        info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id), (LEGACY_DOMAIN, self._entry_id)},
            name=self._name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version,
        )
        connections: set[tuple[str, str]] = set()
        for mac_addr in (
            self._mac,
            self._entry.options.get(CONF_SECONDARY_MAC_ADDRESS),
            self._entry.data.get(CONF_SECONDARY_MAC_ADDRESS),
            getattr(self._client, "mac_wifi", None),
            getattr(self._client, "mac_ethernet", None),
        ):
            if mac_addr:
                connections.add((CONNECTION_NETWORK_MAC, mac_addr.replace("-", ":").lower()))
        if connections:
            info["connections"] = connections
        return info

    @property
    def available(self) -> bool:
        """Return True if the TV entity is available."""
        return bool(self._entry_id and self._client)


# Backwards-compatible alias during migration
HisenseVidaaEntity = VidaaEntity
