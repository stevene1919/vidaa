"""Mock stubs for Home Assistant helper modules."""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import MagicMock

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha
else:
    ha = sys.modules["homeassistant"]

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []

# helpers.service
service_module = types.ModuleType("homeassistant.helpers.service")
service_module.async_set_service_schema = MagicMock()
helpers.service = service_module
sys.modules["homeassistant.helpers.service"] = service_module

# helpers.entity
entity_module = types.ModuleType("homeassistant.helpers.entity")


class Entity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass

    def async_on_remove(self, func):
        pass

    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)

    @property
    def entity_registry_enabled_default(self):
        return getattr(self, "_attr_entity_registry_enabled_default", True)


entity_module.Entity = Entity
helpers.entity = entity_module
sys.modules["homeassistant.helpers.entity"] = entity_module

# helpers.selector
selector = types.ModuleType("homeassistant.helpers.selector")


class NumberSelector:
    def __init__(self, config):
        self.config = config

    def __call__(self, data):
        return data


class NumberSelectorConfig:
    def __init__(self, **kwargs):
        self.config = kwargs


class NumberSelectorMode:
    SLIDER = "slider"
    BOX = "box"


class SelectSelector:
    def __init__(self, config):
        self.config = config

    def __call__(self, data):
        return data


class SelectSelectorConfig:
    def __init__(self, **kwargs):
        self.config = kwargs


class SelectSelectorMode:
    DROPDOWN = "dropdown"


class SelectOptionDict(dict):
    def __init__(self, value, label):
        super().__init__(value=value, label=label)


class FileSelector:
    def __init__(self, config=None):
        self.config = config

    def __call__(self, data):
        return data


class FileSelectorConfig:
    def __init__(self, **kwargs):
        self.config = kwargs


selector.NumberSelector = NumberSelector
selector.NumberSelectorConfig = NumberSelectorConfig
selector.NumberSelectorMode = NumberSelectorMode
selector.SelectSelector = SelectSelector
selector.SelectSelectorConfig = SelectSelectorConfig
selector.SelectSelectorMode = SelectSelectorMode
selector.SelectOptionDict = SelectOptionDict
selector.FileSelector = FileSelector
selector.FileSelectorConfig = FileSelectorConfig
helpers.selector = selector
sys.modules["homeassistant.helpers.selector"] = selector

# helpers.device_registry
device_registry = types.ModuleType("homeassistant.helpers.device_registry")


class DeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


def format_mac(mac: str) -> str:
    clean = mac.replace("-", ":").lower()
    parts = clean.split(":")
    return ":".join(f"{p:>02}" for p in parts)


class DeviceEntry:
    def __init__(self, id="test_device_id", name="Hisense TV", name_by_user=None, config_entries=None):
        self.id = id
        self.name = name
        self.name_by_user = name_by_user
        self.config_entries = config_entries or []


device_registry.DeviceEntry = DeviceEntry
device_registry.DeviceInfo = DeviceInfo
device_registry.CONNECTION_NETWORK_MAC = "mac"
device_registry.format_mac = format_mac
device_registry.async_get = MagicMock()
helpers.device_registry = device_registry
sys.modules["homeassistant.helpers.device_registry"] = device_registry

# helpers.entity_platform
entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
AddEntitiesCallback = MagicMock
entity_platform.AddEntitiesCallback = AddEntitiesCallback
helpers.entity_platform = entity_platform
sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

# helpers.entity_registry
entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")


def async_get(hass):
    return MagicMock()


entity_registry.async_get = async_get
helpers.entity_registry = entity_registry
sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

# helpers.area_registry
area_registry = types.ModuleType("homeassistant.helpers.area_registry")
area_registry.async_get = MagicMock()
helpers.area_registry = area_registry
sys.modules["homeassistant.helpers.area_registry"] = area_registry

# helpers.issue_registry
issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")


class IssueSeverity:
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"


def async_create_issue(*args, **kwargs):
    pass


def async_delete_issue(*args, **kwargs):
    pass


issue_registry.IssueSeverity = IssueSeverity
issue_registry.async_create_issue = async_create_issue
issue_registry.async_delete_issue = async_delete_issue
helpers.issue_registry = issue_registry
sys.modules["homeassistant.helpers.issue_registry"] = issue_registry

# helpers.config_validation
cv = types.ModuleType("homeassistant.helpers.config_validation")


def config_entry_only_config_schema(domain):
    return lambda val: val


def empty_config_schema(domain):
    return lambda val: val


def ensure_list(val):
    return val if isinstance(val, list) else [val]


cv.config_entry_only_config_schema = config_entry_only_config_schema
cv.empty_config_schema = empty_config_schema
cv.ensure_list = ensure_list
cv.entity_ids = lambda val: val
cv.string = lambda val: str(val)
helpers.config_validation = cv
sys.modules["homeassistant.helpers.config_validation"] = cv

# helpers.typing
typing_mod = types.ModuleType("homeassistant.helpers.typing")
typing_mod.ConfigType = dict
helpers.typing = typing_mod
sys.modules["homeassistant.helpers.typing"] = typing_mod

# helpers.automation
automation_mod = types.ModuleType("homeassistant.helpers.automation")


def move_top_level_schema_fields_to_options(complete_config, schema_dict):
    return complete_config


automation_mod.move_top_level_schema_fields_to_options = move_top_level_schema_fields_to_options
helpers.automation = automation_mod
sys.modules["homeassistant.helpers.automation"] = automation_mod

# helpers.trigger
trigger_mod = types.ModuleType("homeassistant.helpers.trigger")
DATA_PLUGGABLE_ACTIONS = "pluggable_actions"


class Trigger:
    def __init__(self, hass, config):
        self._hass = hass
        self._config = config

    @classmethod
    async def async_validate_complete_config(cls, hass, config):
        return config

    @classmethod
    async def async_validate_config(cls, hass, config):
        return config

    async def async_attach_runner(self, run_action, did_not_trigger=None):
        return lambda: None


class TriggerConfig:
    def __init__(self, options=None):
        self.options = options or {}


class PluggableAction:
    def __init__(self, update=None):
        self._update = update
        self._registered_key = None
        self._hass = None

    def __bool__(self):
        if not self._hass or not self._registered_key:
            return False
        reg = self._hass.data.get(DATA_PLUGGABLE_ACTIONS, {})
        entry = reg.get(self._registered_key)
        return bool(entry and entry.get("actions"))

    def async_run_update(self):
        if self._update:
            self._update()

    @staticmethod
    def async_attach_trigger(hass, trigger, action, variables):
        reg = hass.data.setdefault(DATA_PLUGGABLE_ACTIONS, {})
        key = tuple(sorted(trigger.items()))
        entry = reg.setdefault(key, {"actions": []})
        action_item = (action, variables)
        entry["actions"].append(action_item)

        def _remove():
            if action_item in entry["actions"]:
                entry["actions"].remove(action_item)

        return _remove

    def async_register(self, hass, trigger):
        self._hass = hass
        self._registered_key = tuple(sorted(trigger.items()))
        reg = hass.data.setdefault(DATA_PLUGGABLE_ACTIONS, {})
        reg.setdefault(self._registered_key, {"actions": []})

        def _remove():
            self._registered_key = None

        return _remove

    async def async_run(self, hass, context=None):
        if not self._registered_key:
            return
        reg = hass.data.get(DATA_PLUGGABLE_ACTIONS, {})
        entry = reg.get(self._registered_key)
        if entry and entry.get("actions"):
            for action, variables in list(entry["actions"]):
                try:
                    res = action(variables, context)
                except TypeError:
                    res = action(variables)
                if asyncio.iscoroutine(res):
                    await res


trigger_mod.Trigger = Trigger
trigger_mod.TriggerConfig = TriggerConfig
trigger_mod.TriggerActionRunner = MagicMock
trigger_mod.TriggerNotTriggeredReporter = MagicMock
trigger_mod.TriggerActionType = MagicMock
trigger_mod.TriggerInfo = MagicMock
trigger_mod.PluggableAction = PluggableAction
helpers.trigger = trigger_mod
sys.modules["homeassistant.helpers.trigger"] = trigger_mod

# helpers.service_info.ssdp
service_info = types.ModuleType("homeassistant.helpers.service_info")
ssdp = types.ModuleType("homeassistant.helpers.service_info.ssdp")


class SsdpServiceInfo:
    def __init__(self, ssdp_usn=None, ssdp_st=None, ssdp_location=None, ssdp_headers=None, upnp=None, ssdp_udn=None):
        self.ssdp_usn = ssdp_usn
        self.ssdp_st = ssdp_st
        self.ssdp_location = ssdp_location
        self.ssdp_headers = ssdp_headers or {}
        self.upnp = upnp or {}
        self.ssdp_udn = ssdp_udn


ssdp.SsdpServiceInfo = SsdpServiceInfo
service_info.ssdp = ssdp
sys.modules["homeassistant.helpers.service_info.ssdp"] = ssdp

# helpers.service_info.zeroconf
zeroconf_info = types.ModuleType("homeassistant.helpers.service_info.zeroconf")


class ZeroconfServiceInfo:
    def __init__(
        self,
        host=None,
        port=None,
        hostname=None,
        type=None,
        name=None,
        properties=None,
        ip_address=None,
        ip_addresses=None,
    ):
        self.host = host or ip_address
        self.port = port
        self.hostname = hostname
        self.type = type
        self.name = name
        self.properties = properties or {}
        self.ip_address = ip_address or host
        self.ip_addresses = ip_addresses or ([self.ip_address] if self.ip_address else [])


zeroconf_info.ZeroconfServiceInfo = ZeroconfServiceInfo
service_info.zeroconf = zeroconf_info
sys.modules["homeassistant.helpers.service_info.zeroconf"] = zeroconf_info

helpers.service_info = service_info
sys.modules["homeassistant.helpers.service_info"] = service_info

# helpers.event
event = types.ModuleType("homeassistant.helpers.event")


def async_track_time_interval(hass, action, interval):
    return lambda: None


event.async_track_time_interval = async_track_time_interval
helpers.event = event
sys.modules["homeassistant.helpers.event"] = event

# helpers.aiohttp_client
aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")


def async_get_clientsession(hass=None, verify_ssl=True):
    return MagicMock()


aiohttp_client.async_get_clientsession = async_get_clientsession
helpers.aiohttp_client = aiohttp_client
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

ha.helpers = helpers
sys.modules["homeassistant.helpers"] = helpers
