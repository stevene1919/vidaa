"""Pytest fixtures and configuration for VIDAA TV tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure repository root is in Python path for test execution
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Install lightweight mock stubs if running in an environment without Home Assistant
from . import stubs  # noqa: F401


@pytest.fixture
def anyio_backend():
    return "asyncio"


class MockMQTTMessage:
    """Mock paho-mqtt message object."""

    def __init__(self, topic: str, payload: bytes | str):
        self.topic = topic
        self.payload = payload.encode("utf-8") if isinstance(payload, str) else payload


@pytest.fixture
def mock_mqtt_message():
    """Factory fixture to create mock MQTT messages."""

    def _create(topic: str, payload: str | bytes):
        return MockMQTTMessage(topic, payload)

    return _create


@pytest.fixture
def mock_paho_client(monkeypatch):
    """Mocks paho.mqtt.client.Client with simulated broker responses."""
    mock_client_instance = MagicMock()
    mock_client_instance.connect_async.return_value = 0
    mock_client_instance.disconnect.return_value = 0
    mock_client_instance.publish.return_value = (0, 1)
    mock_client_instance.subscribe.return_value = (0, 1)

    mock_client_class = MagicMock(return_value=mock_client_instance)
    monkeypatch.setattr("paho.mqtt.client.Client", mock_client_class)
    return mock_client_instance


@pytest.fixture(autouse=True)
def isolate_host_network_environment(monkeypatch):
    """Ensures test suite does not query real host ARP tables or network devices by default."""
    import os

    real_exists = os.path.exists

    def mock_exists(path):
        if path == "/proc/net/arp":
            return False
        return real_exists(path)

    monkeypatch.setattr("os.path.exists", mock_exists)
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ReauthFlowMixin._async_port_open",
        AsyncMock(return_value=True),
    )


@pytest.fixture
def mock_entry(mock_client):
    from types import SimpleNamespace

    from homeassistant.config_entries import ConfigEntry

    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.title = "Living Room TV"
    entry.data = {
        "ip_address": "192.168.1.100",
        "mac_address": "e8:51:77:aa:bb:cc",
        "auth_profile": "modern",
        "model": "65U7G",
        "manufacturer": "Hisense",
        "sw_version": "V1.0",
    }
    entry.options = {"enable_remote": True, "enable_wol": True}
    entry.runtime_data = SimpleNamespace(
        client=mock_client,
        platforms=[],
        options=entry.options,
    )
    return entry


@pytest.fixture
def mock_client():
    from unittest.mock import AsyncMock

    from custom_components.vidaa.tv.actions import turn_off_tv, turn_on_tv

    client = MagicMock()
    client.ip = "192.168.1.100"
    client.connected = True
    client.is_on = True
    client.auth_profile = "modern"
    client.access_token_time = 1700000000
    client.access_token_duration = 3600
    client.refresh_token_time = 1700000000
    client.refresh_token_duration = 86400
    client.current_app = "Netflix"
    client.source = "HDMI 1"
    client.tv_state = "on"
    client.device_name = None
    client.model_name = None
    client.manufacturer = None
    client.firmware_version = None
    client.clock_offset = 0
    client.last_clock_sync = 0.0
    client.tv_timestamp = None
    client.picture_settings = []
    client.sound_settings = []
    client.has_active_signal = False
    client.auth_failed = False
    client.sync_clock = MagicMock(return_value=0)
    client.async_sync_clock = AsyncMock(return_value=0)
    client.async_connect_and_run = AsyncMock()
    client.async_disconnect = AsyncMock()
    client.async_check_and_refresh_token = AsyncMock(return_value=False)
    client.async_query_initial_state = AsyncMock()
    client.async_turn_on = AsyncMock()
    client.async_turn_off = AsyncMock()
    client.async_wait_until_awake = AsyncMock(return_value=True)
    client.async_set_volume = AsyncMock()
    client.async_send_key = AsyncMock()
    client.async_send_command = AsyncMock(return_value=True)
    client.async_set_sound_mode = AsyncMock()
    client.async_set_picture_mode = AsyncMock()
    client.async_set_backlight = AsyncMock()
    client.async_set_brightness = AsyncMock()
    client.async_set_contrast = AsyncMock()
    client.async_set_picture_setting = AsyncMock()
    client.async_set_sound_setting = AsyncMock()
    client.async_send_text_input = AsyncMock()
    client.async_launch_app = AsyncMock()
    client.async_get_picture_settings = AsyncMock()
    client.async_get_sound_settings = AsyncMock()
    client.async_get_device_fingerprint = AsyncMock(return_value={})
    client.async_turn_on.side_effect = lambda *a, **k: client.turn_on(*a, **k)
    client.async_turn_off.side_effect = lambda *a, **k: client.turn_off(*a, **k)
    client.async_set_volume.side_effect = lambda *a, **k: client.set_volume(*a, **k)
    client.async_send_key.side_effect = lambda *a, **k: client.send_key(*a, **k)
    client.async_send_command.side_effect = lambda *a, **k: client.send_command(*a, **k) or True
    client.async_set_sound_mode.side_effect = lambda *a, **k: client.set_sound_mode(*a, **k)
    client.async_set_picture_mode.side_effect = lambda *a, **k: client.set_picture_mode(*a, **k)
    client.async_set_backlight.side_effect = lambda *a, **k: client.set_backlight(*a, **k)
    client.async_set_brightness.side_effect = lambda *a, **k: client.set_brightness(*a, **k)
    client.async_set_contrast.side_effect = lambda *a, **k: client.set_contrast(*a, **k)
    client.async_set_picture_setting.side_effect = lambda *a, **k: client.set_picture_setting(*a, **k)
    client.async_set_sound_setting.side_effect = lambda *a, **k: client.set_sound_setting(*a, **k)
    client.async_send_text_input.side_effect = lambda *a, **k: client.send_text_input(*a, **k)
    client.async_launch_app.side_effect = lambda *a, **k: client.launch_app(*a, **k)
    client.async_change_source = AsyncMock(side_effect=lambda *a, **k: client.change_source(*a, **k))
    client.async_cycle_source = AsyncMock(side_effect=lambda *a, **k: client.cycle_source(*a, **k))
    client.async_disconnect.side_effect = lambda *a, **k: client.disconnect(*a, **k)
    client.async_connect_and_run.side_effect = lambda *a, **k: client.connect_and_run(*a, **k)
    client.async_sync_clock.side_effect = lambda *a, **k: client.sync_clock(*a, **k) or 0
    client.async_get_device_fingerprint.side_effect = lambda *a, **k: client.get_device_fingerprint(*a, **k) or {}
    client.async_check_and_refresh_token.side_effect = lambda *a, **k: client.check_and_refresh_token(*a, **k) or False
    client.turn_on.side_effect = lambda mac_targets=None: turn_on_tv(client, mac_targets)
    client.turn_off.side_effect = lambda: turn_off_tv(client)
    return client
