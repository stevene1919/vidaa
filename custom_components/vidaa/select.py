"""Select platform for VIDAA Smart TV integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaClient
from .const import (
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_SOUND_CONTROLS,
    DEFAULT_ENABLE_PICTURE_CONTROLS,
    DEFAULT_ENABLE_SOUND_CONTROLS,
    DOMAIN,
    LEGACY_DOMAIN,
)
from .entity import VidaaEntity
from .helpers import check_client_command_readiness

if TYPE_CHECKING:
    from . import VidaaConfigEntry
from .tv.settings import (
    DEFAULT_MENU_ID_PICTURE_MODE,
    DEFAULT_MENU_ID_SOUND_MODE,
    STANDARD_PICTURE_MODES,
    STANDARD_SOUND_MODES,
    find_menu_item_by_name,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


class VidaaPictureModeSelect(VidaaEntity, SelectEntity):
    """VIDAA Picture Mode selector."""

    _attr_translation_key = "picture_mode"

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_picture_mode"
        self._current_mode = "Standard"

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and bool(self._client and self._client.connected)

    async def async_added_to_hass(self) -> None:
        self._client.register_picture_callback(self._handle_picture_update)
        self._client.register_connected_callback(self._handle_connection_change)
        self._client.register_disconnected_callback(self._handle_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_picture_callback(self._handle_picture_update)
        self._client.unregister_connected_callback(self._handle_connection_change)
        self._client.unregister_disconnected_callback(self._handle_connection_change)

    def _handle_connection_change(self, *args: Any) -> None:
        self.schedule_update_ha_state()

    @property
    def options(self) -> list[str]:
        pm_item = find_menu_item_by_name(self._client.picture_settings, "Picture Mode", DEFAULT_MENU_ID_PICTURE_MODE)
        if pm_item and pm_item.options:
            return pm_item.options
        return STANDARD_PICTURE_MODES

    @property
    def current_option(self) -> str | None:
        if self._client.picture_mode:
            return self._client.picture_mode
        return self._current_mode

    def _handle_picture_update(self, data: dict[str, Any]) -> None:
        if self._client.picture_mode:
            self._current_mode = self._client.picture_mode
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change picture mode option."""
        check_client_command_readiness(self._client, require_on=True)
        res = await self._client.async_set_picture_mode(option)
        if res is False:
            raise HomeAssistantError(
                f"Failed to set picture mode to {option}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="set_picture_setting_failed",
                translation_placeholders={"menu_id": "picture_mode", "error": "command delivery failed"},
            )
        self._current_mode = option
        self.async_write_ha_state()


class VidaaSoundModeSelect(VidaaEntity, SelectEntity):
    """VIDAA Sound Mode selector."""

    _attr_translation_key = "sound_mode"

    def __init__(
        self,
        client: VidaaClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(client=client, entry=entry)
        self._attr_unique_id = f"{self._entry_id}_sound_mode"
        self._current_mode = "Standard"

    @property
    def unique_id(self) -> str:
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and bool(self._client and self._client.connected)

    async def async_added_to_hass(self) -> None:
        self._client.register_sound_callback(self._handle_sound_update)
        self._client.register_connected_callback(self._handle_connection_change)
        self._client.register_disconnected_callback(self._handle_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        self._client.unregister_sound_callback(self._handle_sound_update)
        self._client.unregister_connected_callback(self._handle_connection_change)
        self._client.unregister_disconnected_callback(self._handle_connection_change)

    def _handle_connection_change(self, *args: Any) -> None:
        self.schedule_update_ha_state()

    @property
    def options(self) -> list[str]:
        sm_item = find_menu_item_by_name(self._client.sound_settings, "Sound Mode", DEFAULT_MENU_ID_SOUND_MODE)
        if sm_item and sm_item.options:
            return sm_item.options
        return STANDARD_SOUND_MODES

    @property
    def current_option(self) -> str | None:
        if self._client.sound_mode:
            return self._client.sound_mode
        return self._current_mode

    def _handle_sound_update(self, data: dict[str, Any]) -> None:
        if self._client.sound_mode:
            self._current_mode = self._client.sound_mode
        self.schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change sound mode option."""
        check_client_command_readiness(self._client, require_on=True)
        res = await self._client.async_set_sound_mode(option)
        if res is False:
            raise HomeAssistantError(
                f"Failed to set sound mode to {option}: command delivery failed",
                translation_domain=DOMAIN,
                translation_key="set_sound_setting_failed",
                translation_placeholders={"menu_id": "sound_mode", "error": "command delivery failed"},
            )
        self._current_mode = option
        self.async_write_ha_state()


# Backwards-compatible aliases during migration
HisenseVidaaPictureModeSelect = VidaaPictureModeSelect
HisenseVidaaSoundModeSelect = VidaaSoundModeSelect


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VidaaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the VIDAA select platform."""
    client: VidaaClient = config_entry.runtime_data.client

    enable_picture = config_entry.options.get(CONF_ENABLE_PICTURE_CONTROLS, DEFAULT_ENABLE_PICTURE_CONTROLS)
    enable_sound = config_entry.options.get(CONF_ENABLE_SOUND_CONTROLS, DEFAULT_ENABLE_SOUND_CONTROLS)

    # Clean up disabled/unsupported entities from entity registry
    entity_reg = er.async_get(hass)
    for domain in (DOMAIN, LEGACY_DOMAIN):
        unique_id = f"{config_entry.entry_id}_audio_output_select"
        if entity_id := entity_reg.async_get_entity_id("select", domain, unique_id):
            entity_reg.async_remove(entity_id)

    if not enable_picture:
        for domain in (DOMAIN, LEGACY_DOMAIN):
            unique_id = f"{config_entry.entry_id}_picture_mode"
            if entity_id := entity_reg.async_get_entity_id("select", domain, unique_id):
                entity_reg.async_remove(entity_id)

    if not enable_sound:
        for domain in (DOMAIN, LEGACY_DOMAIN):
            unique_id = f"{config_entry.entry_id}_sound_mode"
            if entity_id := entity_reg.async_get_entity_id("select", domain, unique_id):
                entity_reg.async_remove(entity_id)

    entities: list[SelectEntity] = []
    if enable_picture:
        entities.append(VidaaPictureModeSelect(client=client, entry=config_entry))
    if enable_sound:
        entities.append(VidaaSoundModeSelect(client=client, entry=config_entry))

    if entities:
        async_add_entities(entities)
