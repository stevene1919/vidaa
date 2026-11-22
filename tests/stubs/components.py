"""Mock stubs for Home Assistant component modules."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

import voluptuous as vol

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha
else:
    ha = sys.modules["homeassistant"]

components = types.ModuleType("homeassistant.components")

# media_player
media_player = types.ModuleType("homeassistant.components.media_player")


class MediaPlayerDeviceClass:
    TV = "tv"
    RECEIVER = "receiver"
    SPEAKER = "speaker"


class MediaPlayerEntity:
    _attr_device_class = None

    @property
    def device_class(self):
        return getattr(self, "_attr_device_class", None)

    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass


class MediaPlayerEntityFeature:
    PAUSE = 1
    SEEK = 2
    VOLUME_SET = 4
    VOLUME_MUTE = 8
    PREVIOUS_TRACK = 16
    NEXT_TRACK = 32
    TURN_ON = 128
    TURN_OFF = 256
    PLAY_MEDIA = 512
    VOLUME_STEP = 1024
    SELECT_SOURCE = 2048
    STOP = 4096
    PLAY = 16384
    SELECT_SOUND_MODE = 65536
    BROWSE_MEDIA = 131072


class MediaClass:
    APP = "app"
    DIRECTORY = "directory"
    CHANNEL = "channel"
    TV_SHOW = "tv_show"


class BrowseMedia:
    def __init__(
        self,
        *,
        media_class: str,
        media_content_id: str,
        media_content_type: str,
        title: str,
        can_play: bool,
        can_expand: bool,
        children: list[BrowseMedia] | None = None,
        children_media_class: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        self.media_class = media_class
        self.media_content_id = media_content_id
        self.media_content_type = media_content_type
        self.title = title
        self.can_play = can_play
        self.can_expand = can_expand
        self.children = children or []
        self.children_media_class = children_media_class
        self.thumbnail = thumbnail


class MediaType:
    CHANNEL = "channel"
    APP = "app"
    URL = "url"
    MUSIC = "music"
    VIDEO = "video"
    TVSHOW = "tvshow"


class MediaPlayerState:
    OFF = "off"
    ON = "on"
    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    STANDBY = "standby"


media_player.MediaPlayerState = MediaPlayerState
media_player.MediaType = MediaType
media_player.MediaClass = MediaClass
media_player.BrowseMedia = BrowseMedia
media_player.MediaPlayerEntity = MediaPlayerEntity
media_player.MediaPlayerDeviceClass = MediaPlayerDeviceClass
media_player.MediaPlayerEntityFeature = MediaPlayerEntityFeature
components.media_player = media_player
sys.modules["homeassistant.components.media_player"] = media_player

# remote
remote = types.ModuleType("homeassistant.components.remote")


class RemoteEntity:
    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass


class RemoteEntityFeature:
    ACTIVITY = 1


remote.RemoteEntity = RemoteEntity
remote.RemoteEntityFeature = RemoteEntityFeature
components.remote = remote
sys.modules["homeassistant.components.remote"] = remote

# sensor
sensor = types.ModuleType("homeassistant.components.sensor")


class SensorEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def async_write_ha_state(self):
        pass

    @property
    def native_value(self):
        return getattr(self, "_attr_native_value", None)

    @property
    def extra_state_attributes(self):
        return getattr(self, "_attr_extra_state_attributes", {})


class SensorDeviceClass:
    TIMESTAMP = "timestamp"
    ENUM = "enum"
    DURATION = "duration"


sensor.SensorEntity = SensorEntity
sensor.SensorDeviceClass = SensorDeviceClass
components.sensor = sensor
sys.modules["homeassistant.components.sensor"] = sensor

# binary_sensor
binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")


class BinarySensorEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def async_write_ha_state(self):
        pass

    @property
    def is_on(self):
        return getattr(self, "_attr_is_on", None)


class BinarySensorDeviceClass:
    CONNECTIVITY = "connectivity"
    RUNNING = "running"
    POWER = "power"
    PROBLEM = "problem"


binary_sensor.BinarySensorEntity = BinarySensorEntity
binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
components.binary_sensor = binary_sensor
sys.modules["homeassistant.components.binary_sensor"] = binary_sensor

# button
button = types.ModuleType("homeassistant.components.button")


class ButtonEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def async_write_ha_state(self):
        pass


class ButtonDeviceClass:
    RESTART = "restart"
    UPDATE = "update"


button.ButtonEntity = ButtonEntity
button.ButtonDeviceClass = ButtonDeviceClass
components.button = button
sys.modules["homeassistant.components.button"] = button

# repairs
repairs = types.ModuleType("homeassistant.components.repairs")


class RepairsFlow:
    def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
            "description_placeholders": description_placeholders,
        }

    def async_create_entry(self, *, data=None):
        return {"type": "create_entry", "data": data or {}}


repairs.RepairsFlow = RepairsFlow
components.repairs = repairs
sys.modules["homeassistant.components.repairs"] = repairs

# diagnostics
diagnostics = types.ModuleType("homeassistant.components.diagnostics")


def async_redact_data(data, to_redact):
    if isinstance(data, dict):
        return {k: ("**REDACTED**" if k in to_redact else async_redact_data(v, to_redact)) for k, v in data.items()}
    return data


diagnostics.async_redact_data = async_redact_data
components.diagnostics = diagnostics
sys.modules["homeassistant.components.diagnostics"] = diagnostics

# persistent_notification
persistent_notification = types.ModuleType("homeassistant.components.persistent_notification")


def _pn_async_create(hass, message, title=None, notification_id=None):
    if hasattr(hass, "data") and isinstance(hass.data, dict):
        notifications = hass.data.setdefault("persistent_notification", {})
        notifications[notification_id or "default"] = {
            "message": message,
            "title": title,
            "notification_id": notification_id,
        }


def _pn_async_dismiss(hass, notification_id):
    if hasattr(hass, "data") and isinstance(hass.data, dict):
        hass.data.get("persistent_notification", {}).pop(notification_id, None)


persistent_notification.async_create = _pn_async_create
persistent_notification.async_dismiss = _pn_async_dismiss
components.persistent_notification = persistent_notification
sys.modules["homeassistant.components.persistent_notification"] = persistent_notification

# notify
notify = types.ModuleType("homeassistant.components.notify")


class NotifyEntity:
    _attr_has_entity_name = True

    def async_write_ha_state(self):
        pass


notify.NotifyEntity = NotifyEntity
components.notify = notify
sys.modules["homeassistant.components.notify"] = notify

# switch
switch = types.ModuleType("homeassistant.components.switch")


class SwitchEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass

    @property
    def is_on(self):
        return getattr(self, "_attr_is_on", False)


class SwitchDeviceClass:
    SWITCH = "switch"


switch.SwitchEntity = SwitchEntity
switch.SwitchDeviceClass = SwitchDeviceClass
components.switch = switch
sys.modules["homeassistant.components.switch"] = switch

# select
select = types.ModuleType("homeassistant.components.select")


class SelectEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass

    @property
    def current_option(self):
        return getattr(self, "_attr_current_option", None)

    @property
    def options(self):
        return getattr(self, "_attr_options", [])


select.SelectEntity = SelectEntity
components.select = select
sys.modules["homeassistant.components.select"] = select

# number
number = types.ModuleType("homeassistant.components.number")


class NumberMode:
    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class NumberEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def schedule_update_ha_state(self):
        pass

    def async_write_ha_state(self):
        pass

    @property
    def native_value(self):
        return getattr(self, "_attr_native_value", None)

    @property
    def native_min_value(self):
        return getattr(self, "_attr_native_min_value", 0.0)

    @property
    def native_max_value(self):
        return getattr(self, "_attr_native_max_value", 100.0)

    @property
    def native_step(self):
        return getattr(self, "_attr_native_step", 1.0)

    @property
    def mode(self):
        return getattr(self, "_attr_mode", NumberMode.AUTO)


number.NumberEntity = NumberEntity
number.NumberMode = NumberMode
components.number = number
sys.modules["homeassistant.components.number"] = number

# device_automation
device_automation = types.ModuleType("homeassistant.components.device_automation")


class InvalidDeviceAutomationConfig(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.kwargs = kwargs


DEVICE_TRIGGER_BASE_SCHEMA = vol.Schema(
    {
        vol.Required("platform"): "device",
        vol.Required("domain"): str,
        vol.Required("device_id"): str,
    }
)
device_automation.InvalidDeviceAutomationConfig = InvalidDeviceAutomationConfig
device_automation.DEVICE_TRIGGER_BASE_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA
components.device_automation = device_automation
sys.modules["homeassistant.components.device_automation"] = device_automation

# file_upload
file_upload = types.ModuleType("homeassistant.components.file_upload")


@contextmanager
def process_uploaded_file(hass, file_id):
    yield Path(file_id)


file_upload.process_uploaded_file = process_uploaded_file
components.file_upload = file_upload
sys.modules["homeassistant.components.file_upload"] = file_upload

components.__path__ = []
ha.components = components
sys.modules["homeassistant.components"] = components
