"""Tests for TV power actions and query initial state in tv/actions_power.py."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.vidaa.tv.actions_power import (
    TvPowerActionsMixin,
    async_query_initial_state,
    async_turn_off_tv,
    async_turn_on_tv,
    query_initial_state,
    turn_off_tv,
    turn_on_tv,
)


class DummyPowerClient(TvPowerActionsMixin):
    def __init__(self):
        self.connected = True
        self.is_on = False
        self.ip = "192.168.1.100"
        self.mac = "e8:51:77:aa:bb:cc"
        self.secondary_mac = "e8:51:77:aa:bb:cd"
        self.mqtt_client = MagicMock()
        self.async_publish = AsyncMock(return_value=True)
        self.async_send_key = AsyncMock(return_value=True)
        self.send_key = MagicMock()
        self.send_wake_on_lan = MagicMock()
        self.topics = MagicMock()
        self.topics.ui = "/remoteapp/tv/ui_service/test/"
        self.topics.platform = "/remoteapp/tv/platform_service/test/"
        self._last_initial_query_time = 0.0
        self._last_wake_time = 0.0
        self._last_power_toggle_time = 0.0
        self._connected_time = 0.0
        self._last_standby_time = 0.0


def test_query_initial_state():
    client = DummyPowerClient()

    # Disconnected -> early return
    client.connected = False
    query_initial_state(client)
    client.mqtt_client.publish.assert_not_called()

    # Connected -> publishes 6 topics
    client.connected = True
    query_initial_state(client)
    assert client.mqtt_client.publish.call_count == 6

    # Duplicate call within min_interval suppressed
    client.mqtt_client.publish.reset_mock()
    query_initial_state(client, min_interval=10.0)
    client.mqtt_client.publish.assert_not_called()


@pytest.mark.anyio
async def test_async_query_initial_state():
    client = DummyPowerClient()

    # Disconnected -> early return
    client.connected = False
    await async_query_initial_state(client)
    assert client.async_publish.await_count == 0

    # Connected -> publishes 6 topics
    client.connected = True
    await async_query_initial_state(client)
    assert client.async_publish.await_count == 6

    # Duplicate suppressed
    client.async_publish.reset_mock()
    await async_query_initial_state(client, min_interval=10.0)
    assert client.async_publish.await_count == 0


def test_turn_on_tv_sync():
    client = DummyPowerClient()

    # 1. Connected and already on -> skips KEY_POWER
    client.connected = True
    client.is_on = True
    turn_on_tv(client, settle_delay=0)
    client.send_key.assert_not_called()

    # 2. Connected, standby, recent wake (< 3s) -> skips KEY_POWER
    client.is_on = False
    client._last_wake_time = time.time()
    turn_on_tv(client, settle_delay=0)
    client.send_key.assert_not_called()
    assert client.is_on is True

    # 3. Connected, standby, recent toggle cooldown (< 2s) -> skips KEY_POWER
    client.is_on = False
    client._last_wake_time = 0.0
    client._last_power_toggle_time = time.time()
    turn_on_tv(client, settle_delay=0)
    client.send_key.assert_not_called()
    assert client.is_on is True

    # 4. Connected, standby, no recent wake/toggle -> sends KEY_POWER
    client.is_on = False
    client._last_power_toggle_time = 0.0
    turn_on_tv(client, settle_delay=0)
    client.send_key.assert_called_once_with("KEY_POWER")
    assert client.is_on is True

    # 5. Disconnected -> reconnects
    client.connected = False
    client.is_on = False
    client.send_key.reset_mock()
    client.ensure_connected = MagicMock(return_value=True)

    def _side_effect():
        client.connected = True

    # After first loop step, make connected True with confirmed standby
    now = time.time()
    client._connected_time = now
    client._last_standby_time = now + 1
    with patch("time.sleep", side_effect=lambda s: _side_effect()):
        turn_on_tv(client, settle_delay=0)
    client.send_key.assert_called_with("KEY_POWER")


@pytest.mark.anyio
async def test_async_turn_on_tv():
    client = DummyPowerClient()

    # 1. Connected and on -> skips
    client.connected = True
    client.is_on = True
    assert await async_turn_on_tv(client, settle_delay=0) is True
    client.async_send_key.assert_not_awaited()

    # 2. Connected, standby, recent wake (< 3s)
    client.is_on = False
    client._last_wake_time = time.time()
    assert await async_turn_on_tv(client, settle_delay=0) is True
    client.async_send_key.assert_not_awaited()
    assert client.is_on is True

    # 3. Connected, standby, recent toggle cooldown
    client.is_on = False
    client._last_wake_time = 0.0
    client._last_power_toggle_time = time.time()
    assert await async_turn_on_tv(client, settle_delay=0) is True
    client.async_send_key.assert_not_awaited()

    # 4. Connected, standby, waking during settle window
    client.is_on = False
    client._last_power_toggle_time = 0.0

    async def _mock_sleep(delay):
        client._last_wake_time = time.time()

    with patch("asyncio.sleep", side_effect=_mock_sleep):
        assert await async_turn_on_tv(client, settle_delay=0.1) is True
    client.async_send_key.assert_not_awaited()

    # 5. Connected in standby -> sends KEY_POWER
    client.is_on = False
    client._last_wake_time = 0.0
    assert await async_turn_on_tv(client, settle_delay=0) is True
    client.async_send_key.assert_awaited_with("KEY_POWER")
    assert client.is_on is True

    # 6. Disconnected reconnect with confirmed standby
    client.connected = False
    client.is_on = False
    client._last_wake_time = 0.0
    client._last_power_toggle_time = 0.0
    client.async_send_key.reset_mock()
    client.nudge_reconnect = MagicMock()
    client.async_ensure_connected = AsyncMock()

    now = time.time()
    client._connected_time = now
    client._last_standby_time = now + 10

    async def _make_connected(*args, **kwargs):
        client.connected = True

    with patch("asyncio.sleep", side_effect=_make_connected):
        assert await async_turn_on_tv(client, timeout=0.5, settle_delay=0) is True
    client.async_send_key.assert_awaited_with("KEY_POWER")


def test_turn_off_tv_sync():
    client = DummyPowerClient()

    # Connected and on -> sends KEY_POWER and sets is_on=False
    client.connected = True
    client.is_on = True
    turn_off_tv(client)
    client.send_key.assert_called_once_with("KEY_POWER")
    assert client.is_on is False

    # Already off -> no send_key
    client.send_key.reset_mock()
    turn_off_tv(client)
    client.send_key.assert_not_called()


@pytest.mark.anyio
async def test_async_turn_off_tv():
    client = DummyPowerClient()

    # Connected and on
    client.connected = True
    client.is_on = True
    assert await async_turn_off_tv(client) is True
    client.async_send_key.assert_awaited_once_with("KEY_POWER")
    assert client.is_on is False

    # Delivery failure
    client.is_on = True
    client.async_send_key = AsyncMock(return_value=False)
    assert await async_turn_off_tv(client) is False

    # Already off
    client.is_on = False
    assert await async_turn_off_tv(client) is True


@pytest.mark.anyio
async def test_tv_power_actions_mixin():
    client = DummyPowerClient()
    client.query_initial_state()
    await client.async_query_initial_state()
    client.turn_on(settle_delay=0)
    assert await client.async_turn_on(settle_delay=0) is True
    client.turn_off()
    assert await client.async_turn_off() is True


def test_turn_on_tv_skips_wol_when_empty_targets_or_already_on():
    """Explicit mac_targets=[] or an already-awake TV must not emit Wake-on-LAN broadcasts."""
    client = DummyPowerClient()

    # 1. Standby with explicit empty mac_targets=[] -> sends KEY_POWER without WoL
    client.connected = True
    client.is_on = False
    turn_on_tv(client, mac_targets=[], settle_delay=0)
    client.send_wake_on_lan.assert_not_called()
    client.send_key.assert_called_once_with("KEY_POWER")

    # 2. Already connected and awake with mac_targets=None -> skips both WoL and KEY_POWER
    client.send_wake_on_lan.reset_mock()
    client.send_key.reset_mock()
    client.connected = True
    client.is_on = True
    turn_on_tv(client, mac_targets=None, settle_delay=0)
    client.send_wake_on_lan.assert_not_called()
    client.send_key.assert_not_called()


@pytest.mark.anyio
async def test_async_turn_on_tv_skips_wol_when_empty_targets_or_already_on():
    """Async turn_on skips Wake-on-LAN when mac_targets=[] or TV is already awake."""
    client = DummyPowerClient()

    # 1. Standby with explicit empty mac_targets=[] -> sends KEY_POWER without WoL
    client.connected = True
    client.is_on = False
    assert await async_turn_on_tv(client, mac_targets=[], settle_delay=0) is True
    client.send_wake_on_lan.assert_not_called()
    client.async_send_key.assert_awaited_once_with("KEY_POWER")

    # 2. Already connected and awake with mac_targets=None -> skips both WoL and KEY_POWER
    client.send_wake_on_lan.reset_mock()
    client.async_send_key.reset_mock()
    client.connected = True
    client.is_on = True
    assert await async_turn_on_tv(client, mac_targets=None, settle_delay=0) is True
    client.send_wake_on_lan.assert_not_called()
    client.async_send_key.assert_not_awaited()
