"""Options flow handler for VIDAA Smart TV."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from ..const import (
    CONF_ENABLE_AUDIO_ONLY,
    CONF_ENABLE_CEC_NAMES,
    CONF_ENABLE_MEDIA_CONTROLS,
    CONF_ENABLE_PICTURE_CONTROLS,
    CONF_ENABLE_SOUND_CONTROLS,
    CONF_ENABLE_WOL,
    CONF_INCLUDE_APPS_IN_SOURCES,
    CONF_KEY_DELAY,
    CONF_KEY_REPEAT,
    CONF_MAC_ADDRESS,
    CONF_PLAYBACK_DEBOUNCE,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_SOURCES,
    DEFAULT_ENABLE_AUDIO_ONLY,
    DEFAULT_ENABLE_CEC_NAMES,
    DEFAULT_ENABLE_MEDIA_CONTROLS,
    DEFAULT_ENABLE_PICTURE_CONTROLS,
    DEFAULT_ENABLE_SOUND_CONTROLS,
    DEFAULT_ENABLE_WOL,
    DEFAULT_INCLUDE_APPS_IN_SOURCES,
    DEFAULT_KEY_DELAY,
    DEFAULT_KEY_REPEAT,
    DEFAULT_PLAYBACK_DEBOUNCE,
)
from .options_security import (
    OptionsSecurityMixin,
    check_certs_exist,
    extract_and_install_certs,
    validate_ssl_certs,
)

_LOGGER = logging.getLogger(__name__)


class VidaaOptionsFlowHandler(OptionsSecurityMixin, config_entries.OptionsFlow):
    """Handle categorized VIDAA options with intuitive menu navigation."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Present categorized options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "power_network",
                "playback_sources",
                "features_remote",
                "security",
            ],
        )

    async def async_step_power_network(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Power, Wake-on-LAN and network options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options
        data = self.config_entry.data

        primary_mac = data.get(CONF_MAC_ADDRESS) or ""

        if user_input is not None:
            raw_sec_mac = (user_input.get(CONF_SECONDARY_MAC_ADDRESS) or "").strip()
            if raw_sec_mac:
                cleaned_mac = format_mac(raw_sec_mac)
                if not re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", cleaned_mac):
                    errors[CONF_SECONDARY_MAC_ADDRESS] = "invalid_mac"
                else:
                    user_input[CONF_SECONDARY_MAC_ADDRESS] = cleaned_mac.lower()
            else:
                user_input[CONF_SECONDARY_MAC_ADDRESS] = ""

            if not errors:
                updated_options = {**self.config_entry.options, **user_input}
                return self.async_create_entry(title="", data=updated_options)

        current_sec_mac = options.get(CONF_SECONDARY_MAC_ADDRESS)
        if not current_sec_mac:
            current_sec_mac = data.get(CONF_SECONDARY_MAC_ADDRESS)

        if not current_sec_mac:
            rt_data = getattr(self.config_entry, "runtime_data", None)
            client = getattr(rt_data, "client", None) if rt_data else None
            if client:
                wifi, eth = getattr(client, "mac_wifi", None), getattr(client, "mac_ethernet", None)
                if wifi and eth and wifi != eth:
                    current_sec_mac = eth if primary_mac == wifi else wifi
                elif wifi and wifi != primary_mac:
                    current_sec_mac = wifi
                elif eth and eth != primary_mac:
                    current_sec_mac = eth

        return self.async_show_form(
            step_id="power_network",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_WOL,
                        default=options.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL),
                    ): bool,
                    vol.Optional(
                        CONF_SECONDARY_MAC_ADDRESS,
                        default=current_sec_mac or "",
                    ): str,
                }
            ),
            description_placeholders={"primary_mac": primary_mac or "Unknown"},
            errors=errors,
        )

    async def async_step_playback_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Input sources and media playback options."""
        if user_input is not None:
            updated_options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=updated_options)

        options = self.config_entry.options

        client = (
            getattr(self.config_entry.runtime_data, "client", None)
            if hasattr(self.config_entry, "runtime_data")
            else None
        )
        discovered_sources: list[str] = []
        if client:
            sources_dict = getattr(client, "source_dict", {}) or {}
            apps_dict = getattr(client, "app_dict", {}) or {}
            from ..tv.media import build_media_player_source_list

            discovered_sources = build_media_player_source_list(
                source_dict=sources_dict,
                app_dict=apps_dict,
                enable_cec=options.get(CONF_ENABLE_CEC_NAMES, DEFAULT_ENABLE_CEC_NAMES),
                include_apps=True,
            )

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_INCLUDE_APPS_IN_SOURCES,
                default=options.get(
                    CONF_INCLUDE_APPS_IN_SOURCES,
                    DEFAULT_INCLUDE_APPS_IN_SOURCES,
                ),
            ): bool,
        }

        if discovered_sources:
            selected_sources = options.get(CONF_SOURCES)
            if not selected_sources:
                selected_sources = discovered_sources
            schema_dict[
                vol.Optional(
                    CONF_SOURCES,
                    default=selected_sources,
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=discovered_sources,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )

        schema_dict.update(
            {
                vol.Optional(
                    CONF_ENABLE_MEDIA_CONTROLS,
                    default=options.get(CONF_ENABLE_MEDIA_CONTROLS, DEFAULT_ENABLE_MEDIA_CONTROLS),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_CEC_NAMES,
                    default=options.get(CONF_ENABLE_CEC_NAMES, DEFAULT_ENABLE_CEC_NAMES),
                ): bool,
                vol.Optional(
                    CONF_PLAYBACK_DEBOUNCE,
                    default=options.get(CONF_PLAYBACK_DEBOUNCE, DEFAULT_PLAYBACK_DEBOUNCE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=5.0,
                        step=0.05,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="playback_sources",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_features_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Entities, device features, and remote timing controls."""
        if user_input is not None:
            if CONF_KEY_REPEAT in user_input:
                try:
                    user_input[CONF_KEY_REPEAT] = round(float(user_input[CONF_KEY_REPEAT]))
                except (ValueError, TypeError):
                    user_input[CONF_KEY_REPEAT] = DEFAULT_KEY_REPEAT
            updated_options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=updated_options)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="features_remote",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_PICTURE_CONTROLS,
                        default=options.get(CONF_ENABLE_PICTURE_CONTROLS, DEFAULT_ENABLE_PICTURE_CONTROLS),
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_SOUND_CONTROLS,
                        default=options.get(CONF_ENABLE_SOUND_CONTROLS, DEFAULT_ENABLE_SOUND_CONTROLS),
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_AUDIO_ONLY,
                        default=options.get(CONF_ENABLE_AUDIO_ONLY, DEFAULT_ENABLE_AUDIO_ONLY),
                    ): bool,
                    vol.Optional(
                        CONF_KEY_DELAY,
                        default=options.get(CONF_KEY_DELAY, DEFAULT_KEY_DELAY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.05,
                            max=2.0,
                            step=0.05,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_KEY_REPEAT,
                        default=int(options.get(CONF_KEY_REPEAT, DEFAULT_KEY_REPEAT)),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=10,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    # --------------------------------------------------------------------------
    # Backward compatibility aliases
    # --------------------------------------------------------------------------
    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        return await self.async_step_power_network(user_input)

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        return await self.async_step_playback_sources(user_input)

    async def async_step_picture_sound(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_features_remote(user_input)

    async def async_step_remote_keys(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        return await self.async_step_features_remote(user_input)


# Backwards-compatible alias during migration
HisenseVidaaOptionsFlowHandler = VidaaOptionsFlowHandler

__all__ = [
    "HisenseVidaaOptionsFlowHandler",
    "VidaaOptionsFlowHandler",
    "check_certs_exist",
    "extract_and_install_certs",
    "validate_ssl_certs",
]
