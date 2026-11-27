"""Tests verifying Bronze, Silver, and Gold Quality Scale compliance."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiomqtt.exceptions import MqttConnectError
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow

from custom_components.vidaa.binary_sensor import (
    VidaaAuthProblemBinarySensor,
    VidaaInUseBinarySensor,
    VidaaMqttConnectedBinarySensor,
)
from custom_components.vidaa.button import (
    VidaaForceReconnectButton,
    VidaaProbeCapabilitiesButton,
    VidaaSyncClockButton,
    VidaaTriggerReauthButton,
)
from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import CONF_IP_ADDRESS, CONF_SECONDARY_MAC_ADDRESS
from custom_components.vidaa.protocol.auth import async_perform_token_refresh
from custom_components.vidaa.protocol.auth_lifecycle import TokenLifecycleManager
from custom_components.vidaa.remote import VidaaRemote
from custom_components.vidaa.sensor import (
    VidaaActiveAppSensor,
    VidaaActiveSourceSensor,
    VidaaClockDriftSensor,
    VidaaReportedNameSensor,
    VidaaSessionStatusSensor,
)

INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "vidaa"


@pytest.mark.anyio
async def test_entity_unavailable_on_auth_failed_and_disconnect(mock_client, mock_entry) -> None:
    """Operational entities go unavailable when auth fails; diagnostic recovery entities stay available."""
    mock_client.connected = True
    mock_client.auth_failed = False

    app_sensor = VidaaActiveAppSensor(mock_client, mock_entry)
    source_sensor = VidaaActiveSourceSensor(mock_client, mock_entry)
    in_use = VidaaInUseBinarySensor(mock_client, mock_entry)
    reported_name = VidaaReportedNameSensor(mock_client, mock_entry)
    clock_drift = VidaaClockDriftSensor(mock_client, mock_entry)
    probe_btn = VidaaProbeCapabilitiesButton(mock_client, mock_entry)

    session_sensor = VidaaSessionStatusSensor(mock_client, mock_entry)
    auth_problem = VidaaAuthProblemBinarySensor(mock_client, mock_entry)
    mqtt_conn = VidaaMqttConnectedBinarySensor(mock_client, mock_entry)
    reconnect_btn = VidaaForceReconnectButton(mock_client, mock_entry)
    reauth_btn = VidaaTriggerReauthButton(mock_client, mock_entry)

    for entity in (
        app_sensor,
        source_sensor,
        in_use,
        reported_name,
        clock_drift,
        probe_btn,
        session_sensor,
        auth_problem,
        mqtt_conn,
        reconnect_btn,
        reauth_btn,
    ):
        assert entity.available is True

    await app_sensor.async_added_to_hass()
    await source_sensor.async_added_to_hass()
    await in_use.async_added_to_hass()
    await reported_name.async_added_to_hass()
    await clock_drift.async_added_to_hass()
    await probe_btn.async_added_to_hass()

    mock_client.auth_failed = True
    mock_client.connected = False
    probe_btn._handle_connection_change()

    for entity in (app_sensor, source_sensor, in_use, reported_name, clock_drift, probe_btn):
        assert entity.available is False

    # Diagnostic recovery tools and status sensors remain available so the user can recover
    for entity in (session_sensor, auth_problem, mqtt_conn, reconnect_btn, reauth_btn):
        assert entity.available is True

    await app_sensor.async_will_remove_from_hass()
    await source_sensor.async_will_remove_from_hass()
    await in_use.async_will_remove_from_hass()
    await reported_name.async_will_remove_from_hass()
    await clock_drift.async_will_remove_from_hass()
    await probe_btn.async_will_remove_from_hass()


@pytest.mark.anyio
async def test_log_when_unavailable_deduplicates_connect_and_refresh_warnings(caplog) -> None:
    """Repeated MQTT connect rejections and refresh retries log WARNING once, then DEBUG."""
    from custom_components.vidaa.client import VidaaClient

    client = VidaaClient(ip="192.168.1.100", mac="e8:51:77:aa:bb:cc", client_id="cid")
    client.access_token = "tok"
    client.username = "his$1"

    class _FailingClientCtx:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise MqttConnectError(5)

        async def __aexit__(self, *args):
            return False

    caplog.set_level(logging.DEBUG)
    wait_calls = 0

    async def _fake_wait_for_break(coro, timeout=None):
        nonlocal wait_calls
        coro.close()
        wait_calls += 1
        if wait_calls == 1:
            raise TimeoutError
        raise asyncio.CancelledError

    # Test non-auth rejection code loop deduplication (rc=2 -> keeps retrying)
    with (
        patch("custom_components.vidaa.protocol.connection.Client", _FailingClientCtx),
        patch("custom_components.vidaa.protocol.connection.extract_connect_rc", return_value=2),
        patch(
            "custom_components.vidaa.protocol.connection.asyncio.wait_for",
            side_effect=_fake_wait_for_break,
        ),
        contextlib.suppress(asyncio.CancelledError),
    ):
        await client._mqtt_session_loop("cid", "u", "p", None, reconnect=True, standard=True)

    connect_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "Failed to connect to TV MQTT broker" in r.message
    ]
    connect_debugs = [
        r for r in caplog.records if r.levelno == logging.DEBUG and "Failed to connect to TV MQTT broker" in r.message
    ]
    assert len(connect_warnings) == 1
    assert len(connect_debugs) >= 1

    # Reconnect resets the flag
    client._handle_connected()
    assert client._logged_connect_failure is False

    # Token refresh retry warnings are deduplicated across attempts
    caplog.clear()
    client.refresh_token = "rtok"
    client.refresh_token_time = 10**10
    client.refresh_token_duration = 30
    client.async_check_and_refresh_token = AsyncMock(return_value=False)
    client._schedule_rejected_retry = MagicMock()
    manager = TokenLifecycleManager(client)
    manager.last_refresh_connect_rc = 2

    await manager.async_refresh_token_and_update_creds()
    await manager.async_refresh_token_and_update_creds()

    retry_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "Token refresh after rejected connection failed" in r.message
    ]
    retry_debugs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "Token refresh after rejected connection failed" in r.message
    ]
    assert len(retry_warnings) == 1
    assert len(retry_debugs) == 1


@pytest.mark.anyio
async def test_async_perform_token_refresh_log_warnings_flag(caplog) -> None:
    """async_perform_token_refresh suppresses WARNING when log_warnings=False."""

    class _RejectingCtx:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise MqttConnectError(5)

        async def __aexit__(self, *args):
            return False

    caplog.set_level(logging.DEBUG)
    with patch("aiomqtt.Client", _RejectingCtx):
        res = await async_perform_token_refresh(
            "192.168.1.100",
            "cid",
            "user",
            "rtok",
            use_ssl=False,
            log_warnings=False,
        )
    assert res is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.anyio
async def test_reconfigure_aborts_on_unique_id_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconfiguring an entry to an IP belonging to a different physical TV aborts with unique_id_mismatch."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock()
    entry.entry_id = "own_entry"
    entry.unique_id = "e8:51:77:aa:bb:cc"
    entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_SECONDARY_MAC_ADDRESS: "e8:51:77:aa:bb:cd",
        "auth_profile": "legacy",
    }
    entry.options = {}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "own_entry"}

    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.async_resolve_mac",
        AsyncMock(return_value="aa:bb:cc:dd:ee:ff"),
    )

    with pytest.raises(AbortFlow) as err:
        await flow.async_step_reconfigure(user_input={CONF_IP_ADDRESS: "192.168.1.150", "auth_profile": "legacy"})
    assert err.value.reason == "unique_id_mismatch"


def test_translations_exceptions_and_icons_compliance() -> None:
    """All exceptions, session_status states, and icons match strings.json, translations, and icons.json."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == en

    translation_files = sorted((INTEGRATION_DIR / "translations").glob("*.json"))
    assert len(translation_files) == 13
    for path in translation_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "unique_id_mismatch" in data["config"]["abort"], f"{path.name} missing unique_id_mismatch"
        assert "cannot_connect" in data["exceptions"], f"{path.name} missing cannot_connect"
        assert "missing_credentials" in data["exceptions"], f"{path.name} missing missing_credentials"
        assert set(data["entity"]["sensor"]["session_status"]["state"].keys()) == {
            "active",
            "standby",
            "reauth_required",
        }, f"{path.name} missing session_status state keys"

    exceptions_defined = set(strings["exceptions"].keys())
    for py_path in sorted(INTEGRATION_DIR.rglob("*.py")):
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                fn = node.exc.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name in {
                    "HomeAssistantError",
                    "ServiceValidationError",
                    "ConfigEntryNotReady",
                    "ConfigEntryAuthFailed",
                }:
                    kws = {kw.arg: kw.value for kw in node.exc.keywords}
                    assert "translation_domain" in kws, f"{py_path.name}:{node.lineno} missing translation_domain"
                    assert "translation_key" in kws, f"{py_path.name}:{node.lineno} missing translation_key"
                    key_node = kws["translation_key"]
                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                        assert key_node.value in exceptions_defined, (
                            f"{py_path.name}:{node.lineno} unknown translation_key {key_node.value}"
                        )

    assert VidaaRemote._attr_translation_key == "remote"
    assert VidaaSessionStatusSensor._attr_device_class == SensorDeviceClass.ENUM
    for cls in (
        VidaaForceReconnectButton,
        VidaaSyncClockButton,
        VidaaProbeCapabilitiesButton,
        VidaaTriggerReauthButton,
        VidaaReportedNameSensor,
        VidaaActiveAppSensor,
        VidaaActiveSourceSensor,
    ):
        assert "_attr_icon" not in cls.__dict__
