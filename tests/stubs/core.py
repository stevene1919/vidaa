"""Mock stubs for Home Assistant core modules (core, const, config_entries, data_entry_flow, exceptions)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha
else:
    ha = sys.modules["homeassistant"]

# core
if "homeassistant.core" not in sys.modules:
    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        config_entries = None
        services = None
        data = None
        loop = None

        def async_create_background_task(self, target, name=None):
            if hasattr(target, "close"):
                target.close()
            return None

        def async_create_task(self, target, name=None):
            return None

        def async_add_executor_job(self, target, *args):
            return None

        def __init__(self):
            self.config_entries = MagicMock()
            self.services = MagicMock()
            self.data = {}

    class ServiceCall:
        def __init__(self, domain=None, service=None, data=None, context=None):
            self.domain = domain
            self.service = service
            self.data = data or {}
            self.context = context

    class SupportsResponse:
        NONE = "none"
        ONLY = "only"
        OPTIONAL = "optional"

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall
    core.SupportsResponse = SupportsResponse
    core.callback = callback
    core.CALLBACK_TYPE = MagicMock
    core.Context = MagicMock
    ha.core = core
    sys.modules["homeassistant.core"] = core

# const
if "homeassistant.const" not in sys.modules:
    const = types.ModuleType("homeassistant.const")
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    const.STATE_PAUSED = "paused"
    const.STATE_PLAYING = "playing"
    const.STATE_IDLE = "idle"
    const.ATTR_DEVICE_ID = "device_id"
    const.ATTR_ENTITY_ID = "entity_id"
    const.CONF_DEVICE_ID = "device_id"
    const.CONF_DOMAIN = "domain"
    const.CONF_OPTIONS = "options"
    const.CONF_PLATFORM = "platform"
    const.CONF_TYPE = "type"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"

    const.EntityCategory = EntityCategory

    class UnitOfTime:
        SECONDS = "s"
        MINUTES = "min"
        HOURS = "h"
        DAYS = "d"

    const.UnitOfTime = UnitOfTime
    ha.const = const
    sys.modules["homeassistant.const"] = const

# config_entries
if "homeassistant.config_entries" not in sys.modules:
    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntryState:
        LOADED = "loaded"
        SETUP_ERROR = "setup_error"
        NOT_LOADED = "not_loaded"

    class ConfigEntry:
        def async_on_unload(self, func):
            pass

        def add_update_listener(self, listener):
            return lambda: None

        def async_start_reauth(self, hass):
            pass

    class ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls._domain = domain

        async def async_set_unique_id(self, unique_id, raise_on_progress=True):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self, updates=None, error="already_configured"):
            pass

        def _get_reauth_entry(self):
            return self.hass.config_entries.async_get_entry(self.context["entry_id"])

        def _get_reconfigure_entry(self):
            return self.hass.config_entries.async_get_entry(self.context["entry_id"])

        def _abort_if_unique_id_mismatch(self, *, reason="unique_id_mismatch", description_placeholders=None):
            entry = None
            if isinstance(getattr(self, "context", None), dict) and "entry_id" in self.context:
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            if entry is None:
                entry = getattr(self, "_reauth_entry", None)
            flow_uid = getattr(self, "unique_id", None)
            entry_uid = getattr(entry, "unique_id", None) if entry is not None else None
            if flow_uid and entry_uid and str(flow_uid).lower() != str(entry_uid).lower():
                raise data_entry_flow.AbortFlow(reason)

        def async_update_reload_and_abort(
            self,
            entry,
            *,
            unique_id=None,
            title=None,
            data=None,
            data_updates=None,
            options=None,
            reason="reconfigure_successful",
            reload_even_if_entry_is_unchanged=True,
        ):
            update_kwargs = {}
            if data is not None:
                update_kwargs["data"] = data
            elif data_updates is not None:
                update_kwargs["data"] = {**getattr(entry, "data", {}), **data_updates}
            if options is not None:
                update_kwargs["options"] = options
            if title is not None:
                update_kwargs["title"] = title
            if unique_id is not None:
                update_kwargs["unique_id"] = unique_id
            self.hass.config_entries.async_update_entry(entry, **update_kwargs)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason=reason)

        def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                "description_placeholders": description_placeholders,
            }

        def async_create_entry(self, *, title, data, options=None):
            return {"type": "create_entry", "title": title, "data": data, "options": options}

        def async_abort(self, *, reason, description_placeholders=None):
            return {"type": "abort", "reason": reason, "description_placeholders": description_placeholders}

        async def async_step_user(self, user_input=None):
            return self.async_abort(reason="not_implemented")

        async def async_step_reconfigure(self, user_input=None):
            return self.async_abort(reason="not_implemented")

    class OptionsFlow:
        def async_show_menu(self, *, step_id, menu_options):
            return {"type": "menu", "step_id": step_id, "menu_options": menu_options}

        def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
                "description_placeholders": description_placeholders,
            }

        def async_create_entry(self, *, title="", data=None):
            return {"type": "create_entry", "title": title, "data": data or {}}

    ConfigFlowResult = dict
    config_entries.ConfigEntryState = ConfigEntryState
    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigFlowResult = ConfigFlowResult
    ha.config_entries = config_entries
    sys.modules["homeassistant.config_entries"] = config_entries

# data_entry_flow
if "homeassistant.data_entry_flow" not in sys.modules:
    data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
    FlowResult = dict

    class AbortFlow(Exception):
        """HA flow-control exception raised by _abort_if_unique_id_configured etc."""

        def __init__(self, reason: str) -> None:
            super().__init__(reason)
            self.reason = reason

    def section(schema, options=None):
        """HA data_entry_flow.section helper stub."""
        return schema

    data_entry_flow.FlowResult = FlowResult
    data_entry_flow.AbortFlow = AbortFlow
    data_entry_flow.section = section
    ha.data_entry_flow = data_entry_flow
    sys.modules["homeassistant.data_entry_flow"] = data_entry_flow

# exceptions
if "homeassistant.exceptions" not in sys.modules:
    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        def __init__(
            self, message=None, *, translation_domain=None, translation_key=None, translation_placeholders=None
        ):
            super().__init__(message)
            self.message = message
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders

    class ConfigEntryNotReady(HomeAssistantError):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    class ServiceValidationError(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.ServiceValidationError = ServiceValidationError
    ha.exceptions = exceptions
    sys.modules["homeassistant.exceptions"] = exceptions
