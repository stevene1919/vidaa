"""Binary sensors for VIDAA Smart TV."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaClient
from .const import DOMAIN
from .entity import VidaaEntity

if TYPE_CHECKING:
    from . import VidaaConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIDAA binary sensors."""
    client: VidaaClient = entry.runtime_data.client

    # Clean up deprecated hotel_mode binary sensor from registry if present
    ent_reg = er.async_get(hass)
    hotel_mode_uid = f"{entry.entry_id}_hotel_mode"
    if entity_id := ent_reg.async_get_entity_id("binary_sensor", DOMAIN, hotel_mode_uid):
        ent_reg.async_remove(entity_id)

    async_add_entities(
        [
            VidaaMqttConnectedBinarySensor(client, entry),
            VidaaInUseBinarySensor(client, entry),
            VidaaAuthProblemBinarySensor(client, entry),
        ]
    )


class VidaaMqttConnectedBinarySensor(VidaaEntity, BinarySensorEntity):
    """Binary sensor indicating if TV MQTT broker connection is active."""

    _attr_translation_key = "mqtt_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_mqtt_connected"

    @property
    def is_on(self) -> bool:
        """Return true if MQTT connection is active."""
        return self._client.connected

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added."""
        self._client.register_connected_callback(self._handle_update)
        self._client.register_state_callback(self._handle_update)
        self._client.register_disconnected_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self._client.unregister_connected_callback(self._handle_update)
        self._client.unregister_state_callback(self._handle_update)
        self._client.unregister_disconnected_callback(self._handle_update)

    def _handle_update(self, *args: Any) -> None:
        if getattr(self, "hass", None) is not None:
            self.schedule_update_ha_state()


class VidaaInUseBinarySensor(VidaaEntity, BinarySensorEntity):
    """Binary sensor indicating whether the TV is genuinely awake and displaying content."""

    _attr_translation_key = "in_use"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the in-use binary sensor."""
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_in_use"

    @property
    def is_on(self) -> bool:
        """Return True when TV display is actively in use and not dormant/standby."""
        if not (self._client and self._client.connected and self._client.is_on):
            return False
        if self._client.state in ("off", "standby", ""):
            return False
        app = (self._client.current_app or "").strip().lower()
        return app not in ("off", "standby", "sleep")

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added."""
        self._client.register_connected_callback(self._handle_update)
        self._client.register_state_callback(self._handle_update)
        self._client.register_volume_callback(self._handle_update)
        self._client.register_disconnected_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self._client.unregister_connected_callback(self._handle_update)
        self._client.unregister_state_callback(self._handle_update)
        self._client.unregister_volume_callback(self._handle_update)
        self._client.unregister_disconnected_callback(self._handle_update)

    def _handle_update(self, *args: Any) -> None:
        if getattr(self, "hass", None) is not None:
            self.schedule_update_ha_state()


class VidaaAuthProblemBinarySensor(VidaaEntity, BinarySensorEntity):
    """Binary sensor indicating whether the TV has rejected stored credentials and re-pairing is required."""

    _attr_translation_key = "auth_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the auth problem binary sensor."""
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_auth_problem"

    @property
    def is_on(self) -> bool:
        """Return True when TV has rejected authentication and reauth is required."""
        return getattr(self._client, "auth_failed", False) is True

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added."""
        self._client.register_auth_failed_callback(self._handle_update)
        self._client.register_connected_callback(self._handle_update)
        self._client.register_disconnected_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self._client.unregister_auth_failed_callback(self._handle_update)
        self._client.unregister_connected_callback(self._handle_update)
        self._client.unregister_disconnected_callback(self._handle_update)

    def _handle_update(self, *args: Any) -> None:
        if getattr(self, "hass", None) is not None:
            self.schedule_update_ha_state()


# Backwards-compatible aliases during migration
HisenseVidaaMqttConnectedBinarySensor = VidaaMqttConnectedBinarySensor
HisenseVidaaInUseBinarySensor = VidaaInUseBinarySensor
HisenseVidaaAuthProblemBinarySensor = VidaaAuthProblemBinarySensor
