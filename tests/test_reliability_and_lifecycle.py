"""Tests for wake-event sync, debounce consistency, PIN cleanup, entity HA guards, and disconnect logging."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.vidaa.binary_sensor import VidaaMqttConnectedBinarySensor
from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import CONF_IP_ADDRESS, CONF_MAC_ADDRESS
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.number import VidaaBacklightNumber
from custom_components.vidaa.protocol.pairing import async_submit_pin_code
from custom_components.vidaa.remote import VidaaRemote
from custom_components.vidaa.select import VidaaPictureModeSelect, VidaaSoundModeSelect
from custom_components.vidaa.switch import VidaaAudioOnlySwitch


@pytest.mark.anyio
async def test_state_and_device_info_updates_drive_wake_event(mock_client) -> None:
    """apply_state_update and apply_device_info_update update _wake_event without entity listeners."""
    from custom_components.vidaa.client import VidaaClient

    client = VidaaClient(ip="192.168.50.12", mac="aa:bb:cc:11:22:33", auth_profile="legacy")
    client.connected = True
    assert client._wake_event.is_set() is False

    # Waking via state broadcast sets _wake_event and unblocks async_wait_until_awake
    client._dispatch_state_update({"statetype": "fake_sleep_1"})
    assert client.is_on is True
    assert client._wake_event.is_set() is True
    assert await client.async_wait_until_awake(timeout=0.05) is True

    # Standby via state broadcast clears _wake_event
    client._dispatch_state_update({"statetype": "fake_sleep_0"})
    assert client.is_on is False
    assert client._wake_event.is_set() is False

    # Waking via gettvinfo fake_sleep_state=1 sets _wake_event too
    client._dispatch_device_info_update({"fake_sleep_state": 1})
    assert client.is_on is True
    assert client._wake_event.is_set() is True


@pytest.mark.anyio
async def test_media_player_wake_from_off_applies_immediately_despite_debounce(mock_client, mock_entry) -> None:
    """Waking from STATE_OFF with playback_debounce > 0 must not leave state=ON and is_on=False."""
    hass = MagicMock(spec=HomeAssistant)
    hass.loop = asyncio.get_running_loop()
    hass.async_create_background_task = MagicMock(side_effect=lambda coro, *a, **kw: hass.loop.create_task(coro))

    mock_client.connected = True
    mock_client.is_on = False
    mock_entry.options = {"playback_debounce": 0.5}

    mp = VidaaMediaPlayer(client=mock_client, entry=mock_entry)
    mp.hass = hass
    assert mp.state == STATE_OFF
    assert mp.is_on is False

    mp._handle_state_update({"statetype": "app", "name": "Netflix", "is_on": True})
    assert mp._debounce_handle is None
    assert mp.state == STATE_ON
    assert mp.is_on is True
    assert mp._source == "Netflix"


@pytest.mark.anyio
async def test_modern_pin_reconfigure_returns_reconfigure_successful(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modern PIN reconfigure flow preserves _reauth_reason='reconfigure_successful'."""
    assert VidaaConfigFlow.VERSION == 2
    assert VidaaConfigFlow.MINOR_VERSION == 3

    hass = MagicMock(spec=HomeAssistant)
    entry = SimpleNamespace(
        entry_id="reconf_modern",
        title="Living Room TV",
        unique_id="e8:51:77:aa:bb:cc",
        data={CONF_IP_ADDRESS: "192.168.50.11", CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc", "auth_profile": "modern"},
        options={},
    )
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "reconf_modern"}
    flow._reauth_entry = entry
    flow._reauth_reason = "reconfigure_successful"
    flow.ip_address = "192.168.50.11"
    flow.mac_address = "e8:51:77:aa:bb:cc"
    flow.client = MagicMock()
    flow.client.brand = "his"
    flow.client.client_id = "cid"
    flow.client.username = "user"
    flow.client.password = "pass"
    flow.client.access_token = "tok"
    flow.client.access_token_time = 1000
    flow.client.access_token_duration = 30
    flow.client.refresh_token = "rtok"
    flow.client.refresh_token_time = 1000
    flow.client.refresh_token_duration = 30
    flow.client.async_submit_pin = AsyncMock(return_value={"accesstoken": "tok"})
    flow.client.async_disconnect = AsyncMock()

    res = await flow.async_step_auth(user_input={"pin_code": "1234"})
    assert res["type"] == "abort"
    assert res["reason"] == "reconfigure_successful"


@pytest.mark.anyio
async def test_submit_pin_cleans_futures_rejects_bad_input_and_uses_clock_offset() -> None:
    """async_submit_pin_code validates PIN/token cleanly, cleans futures on error, and applies clock_offset."""
    from custom_components.vidaa.client import VidaaClient

    client = VidaaClient(ip="192.168.50.12", mac="aa:bb:cc:11:22:33", auth_profile="modern")
    client.clock_offset = 3600
    mqtt = MagicMock()
    mqtt.async_publish = AsyncMock(return_value=False)
    client.mqtt_client = mqtt

    # 1. Non-numeric PIN raises ValueError before touching futures
    with pytest.raises(ValueError, match="numeric"):
        await async_submit_pin_code(client, "abcd")
    assert getattr(client, "_auth_code_future", None) is None
    assert getattr(client, "_pairing_event_future", None) is None

    # 2. Failed publish clears futures inside finally
    mqtt.closed = True
    with pytest.raises(Exception, match="MQTT connection closed"):
        await async_submit_pin_code(client, "1234")
    assert client._auth_code_future is None
    assert client._pairing_event_future is None
    mqtt.closed = False

    # 3. Valid PIN + empty access token raises, while valid token applies clock_offset fallback
    async def _publish_tokens(topic: str, _payload: str = "") -> bool:
        if topic.endswith("actions/authenticationcode"):
            client._loop.call_soon_threadsafe(client._safe_set_future_result, client._auth_code_future, '{"result": 1}')
        elif topic.endswith("data/gettoken"):
            client._loop.call_soon_threadsafe(
                client._safe_set_future_result,
                client._token_future,
                '{"accesstoken": "new_tok", "refreshtoken": "new_ref"}',
            )
        return True

    mqtt.async_publish = AsyncMock(side_effect=_publish_tokens)
    with patch("custom_components.vidaa.protocol.pairing.time.time", return_value=10_000):
        await async_submit_pin_code(client, "1234")
    assert client.access_token == "new_tok"
    assert client.access_token_time == 13_600
    assert client.refresh_token_time == 13_600


def test_entity_callbacks_are_safe_when_hass_is_none(mock_client, mock_entry) -> None:
    """Callbacks across select, number, remote, binary_sensor, and switch no-op safely when hass is None."""
    entities = [
        VidaaPictureModeSelect(mock_client, mock_entry),
        VidaaSoundModeSelect(mock_client, mock_entry),
        VidaaBacklightNumber(mock_client, mock_entry),
        VidaaRemote(mock_client, mock_entry),
        VidaaMqttConnectedBinarySensor(mock_client, mock_entry),
        VidaaAudioOnlySwitch(mock_client, mock_entry),
    ]
    for ent in entities:
        ent.hass = None
        ent.schedule_update_ha_state = MagicMock(side_effect=AssertionError("Should not be called when hass is None"))

    entities[0]._handle_picture_update({})
    entities[0]._handle_connection_change()
    entities[1]._handle_sound_update({})
    entities[1]._handle_connection_change()
    entities[2]._handle_picture_update({})
    entities[2]._handle_connection_change()
    entities[3]._handle_state_update({"statetype": "fake_sleep_1"})
    entities[4]._handle_update()
    entities[5]._handle_connected()
    entities[5]._handle_disconnected()
    entities[5]._handle_state_update({"statetype": "fake_sleep_0"})


def test_connection_logs_unavailable_once_and_reconnected_once(caplog: pytest.LogCaptureFixture) -> None:
    """Disconnect logs INFO once during extended outage, then INFO once on reconnect (Silver log-when-unavailable)."""
    from custom_components.vidaa.client import VidaaClient

    client = VidaaClient(ip="192.168.50.12", mac="aa:bb:cc:11:22:33", auth_profile="legacy")
    with caplog.at_level(logging.INFO):
        client._handle_connected(standard=False)
        client._handle_disconnected(debounce=False)
        client._handle_disconnected(debounce=False)
        # Simulate another disconnect cycle while already marked unavailable
        client.connected = True
        client._handle_disconnected(debounce=False)
        client._handle_connected(standard=False)

    info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert sum("Disconnected from TV MQTT broker" in m for m in info_msgs) == 1
    assert sum("Reconnected to TV MQTT broker" in m for m in info_msgs) == 1


def test_quality_scale_yaml_is_valid() -> None:
    """quality_scale.yaml parses cleanly and tracks integration quality scale rules."""
    root = Path(__file__).resolve().parent.parent / "custom_components" / "vidaa"
    qs = yaml.safe_load((root / "quality_scale.yaml").read_text(encoding="utf-8"))
    assert isinstance(qs, dict)
    assert isinstance(qs.get("rules"), dict)
    assert qs["rules"]["log-when-unavailable"] == "done"
