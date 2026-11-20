"""Unit tests for the reauthentication and reconfiguration flow handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import (
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_USE_SSL,
    DOMAIN,
)


def _reauth_flow(hass: MagicMock, entry: MagicMock, entry_id: str) -> VidaaConfigFlow:
    """Build a config flow wired up for a reauth/reconfigure of `entry`."""
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": entry_id}
    return flow


@pytest.mark.anyio
async def test_reauth_flow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauth flow prompts confirmation, triggers client auth, submits PIN, and updates entry."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_reauth"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        "auth_profile": "modern",
    }
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_entry)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "test_entry_reauth"}

    # Start reauth
    result_init = await flow.async_step_reauth(mock_entry.data)
    assert result_init["type"] == "form"
    assert result_init["step_id"] == "reauth_confirm"

    # Confirm reauth
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )
    result_confirm = await flow.async_step_reauth_confirm(user_input={})
    assert result_confirm["type"] == "form"
    assert result_confirm["step_id"] == "auth"

    # Submit PIN
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_submit_pin",
        AsyncMock(return_value=None),
    )
    flow.client.access_token = "new_access_token"
    flow.client.refresh_token = "new_refresh_token"

    result_auth = await flow.async_step_auth(user_input={"pin_code": "1234"})
    assert result_auth["type"] == "abort"
    assert result_auth["reason"] == "reauth_successful"
    assert hass.config_entries.async_update_entry.called
    assert hass.config_entries.async_reload.called


@pytest.mark.anyio
async def test_reconfigure_flow_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reconfigure flow updates IP/profile and re-pairs or updates entry."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_reconf"
    mock_entry.unique_id = "e8:51:77:aa:bb:cc"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        "auth_profile": "legacy",
    }
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_entry)
    hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "test_entry_reconf"}

    # Regression: reconfigure must skip the duplicate-entry guard against its own entry.
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()

    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )
    # Legacy/reconfigure now probes the static session for a PIN challenge;
    # return "no challenge" so the flow takes the unchanged no-PIN path.
    monkeypatch.setattr(
        "custom_components.vidaa.config_flow.async_probe_pairing_challenge",
        AsyncMock(return_value=False),
    )

    result_reconf = await flow.async_step_reconfigure(
        user_input={
            CONF_IP_ADDRESS: "192.168.1.105",
            "auth_profile": "legacy",
        }
    )
    assert result_reconf["type"] == "abort"
    assert result_reconf["reason"] == "reconfigure_successful"
    assert hass.config_entries.async_update_entry.called
    assert flow.async_set_unique_id.called is False
    assert flow._abort_if_unique_id_configured.called is False


@pytest.mark.anyio
async def test_finish_reauth_disconnects_client() -> None:
    """Test _async_finish_reauth disconnects client before reloading entry."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    flow = VidaaConfigFlow()
    flow.hass = hass
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_123"
    mock_entry.data = {CONF_IP_ADDRESS: "192.168.1.100"}
    flow._reauth_entry = mock_entry

    mock_client = MagicMock()
    mock_client.client_id = "reauth_client_id"
    mock_client.username = "hisense"
    mock_client.password = "pass"
    mock_client.access_token = "token_reauth"
    mock_client.access_token_time = 1700000000
    mock_client.access_token_duration = 3600
    mock_client.refresh_token = "reftoken_reauth"
    mock_client.refresh_token_time = 1700000000
    mock_client.refresh_token_duration = 86400
    mock_client.async_disconnect = AsyncMock()
    mock_client.disconnect = MagicMock()
    flow.client = mock_client
    flow.ip_address = "192.168.1.100"

    result = await flow._async_finish_reauth(reason="reauth_successful")
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_client.async_disconnect.called or mock_client.disconnect.called
    assert flow.client is None
    assert hass.config_entries.async_reload.called


@pytest.mark.anyio
async def test_finish_reauth_without_client() -> None:
    """Test _async_finish_reauth works when client is already None."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    flow = VidaaConfigFlow()
    flow.hass = hass
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_456"
    mock_entry.data = {CONF_IP_ADDRESS: "192.168.1.100"}
    flow._reauth_entry = mock_entry
    flow.client = None

    result = await flow._async_finish_reauth(reason="reauth_successful")
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert hass.config_entries.async_reload.called


@pytest.mark.anyio
async def test_reauth_keeps_entry_transport_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """[F3-leg2] a legacy (non-TLS) entry must stay use_ssl=False through reauth."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock()
    entry.entry_id = "legacy_entry"
    entry.unique_id = "e8:51:77:aa:bb:cc"
    entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        CONF_AUTH_PROFILE: "legacy",
        CONF_USE_SSL: False,
    }
    flow = _reauth_flow(hass, entry, "legacy_entry")
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )

    await flow.async_step_reauth(entry.data)
    assert flow.use_ssl is False
    assert flow.certfile is None

    result = await flow.async_step_reauth_confirm(user_input={})
    assert result["reason"] == "reauth_successful"

    written = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert written[CONF_USE_SSL] is False
    assert written[CONF_IP_ADDRESS] == "192.168.1.100"


@pytest.mark.anyio
async def test_reauth_seeds_certificates_from_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """[F3-leg2] reauth must reuse the entry's cert/key paths, not flow defaults."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock()
    entry.entry_id = "tls_entry"
    entry.unique_id = "e8:51:77:aa:bb:cc"
    entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        CONF_AUTH_PROFILE: "modern",
        CONF_USE_SSL: True,
        CONF_CERTFILE: "/config/ssl/hisense.crt",
        CONF_KEYFILE: "/config/ssl/hisense.key",
    }
    flow = _reauth_flow(hass, entry, "tls_entry")
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )

    await flow.async_step_reauth(entry.data)
    assert flow.use_ssl is True
    assert flow.certfile == "/config/ssl/hisense.crt"
    assert flow.keyfile == "/config/ssl/hisense.key"

    await flow.async_step_reauth_confirm(user_input={})
    flow.client.access_token = "fresh_access_token"
    await flow._async_finish_reauth(reason="reauth_successful")

    written = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert written[CONF_USE_SSL] is True
    assert written[CONF_CERTFILE] == "/config/ssl/hisense.crt"
    assert written[CONF_KEYFILE] == "/config/ssl/hisense.key"


@pytest.mark.anyio
async def test_reauth_success_deletes_auth_token_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """[F4-leg2/F5-leg6] a successful reauth must delete the persistent issue."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock()
    entry.entry_id = "issue_entry"
    entry.data = {CONF_IP_ADDRESS: "192.168.1.100"}
    flow = _reauth_flow(hass, entry, "issue_entry")
    flow._reauth_entry = entry

    deleted = []
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ir.async_delete_issue",
        lambda hass_arg, domain, issue_id: deleted.append((domain, issue_id)),
    )

    await flow._async_finish_reauth(reason="reauth_successful")

    assert deleted == [(DOMAIN, "auth_token_invalidated_issue_entry")]


@pytest.mark.anyio
async def test_reconfigure_aborts_when_new_ip_belongs_to_another_tv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[F7-leg6] reconfigure must not repoint an entry at another configured TV."""
    hass = MagicMock(spec=HomeAssistant)
    own_entry = MagicMock()
    own_entry.entry_id = "own_entry"
    own_entry.unique_id = "e8:51:77:aa:bb:cc"
    own_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        CONF_AUTH_PROFILE: "legacy",
    }
    other_entry = MagicMock()
    other_entry.entry_id = "other_entry"
    other_entry.unique_id = "e8:51:77:aa:bb:ee"

    flow = _reauth_flow(hass, own_entry, "own_entry")
    hass.config_entries.async_entries = MagicMock(return_value=[own_entry, other_entry])
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.async_resolve_mac",
        AsyncMock(return_value="e8:51:77:aa:bb:ee"),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ReauthFlowMixin._async_finish_reauth",
        AsyncMock(return_value={"type": "abort", "reason": "reconfigure_successful"}),
    )

    result = await flow.async_step_reconfigure(
        user_input={CONF_IP_ADDRESS: "192.168.1.105", CONF_AUTH_PROFILE: "legacy"}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert flow._async_finish_reauth.await_count == 0
    assert hass.config_entries.async_update_entry.called is False


@pytest.mark.anyio
async def test_reauth_confirm_disconnects_existing_running_client_before_start_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test reauth_confirm disconnects running client to prevent MQTT client ID collisions."""
    hass = MagicMock(spec=HomeAssistant)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        CONF_AUTH_PROFILE: "auto",
        CONF_USE_SSL: True,
    }

    running_client = MagicMock()
    running_client.ip = "192.168.1.100"
    running_client.mac = "e8:51:77:aa:bb:cc"
    hass.data = {DOMAIN: {"test_entry": {"client": running_client}}}
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    flow = _reauth_flow(hass, entry, "test_entry")
    flow.ip_address = "192.168.1.100"
    flow.mac_address = "e8:51:77:aa:bb:cc"
    flow.auth_profile = "auto"
    flow.use_ssl = True

    events = []
    running_client.async_disconnect = AsyncMock(side_effect=lambda: events.append("disconnect_existing"))
    running_client.disconnect = MagicMock(side_effect=lambda: events.append("disconnect_existing"))

    async def mock_start_auth(self):
        events.append("start_auth")

    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        mock_start_auth,
    )

    result = await flow.async_step_reauth_confirm(user_input={})
    assert result["type"] == "form"
    assert result["step_id"] == "auth"
    assert events == ["disconnect_existing", "start_auth"]


@pytest.mark.anyio
async def test_reauth_preserves_oem_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauth flow on an existing OEM Toshiba entry retains brand='tos'."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_toshiba"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.125",
        CONF_MAC_ADDRESS: "00:11:22:33:44:55",
        CONF_BRAND: "tos",
        CONF_AUTH_PROFILE: "modern",
    }
    flow = _reauth_flow(hass, mock_entry, "test_entry_toshiba")

    # Start reauth
    result_init = await flow.async_step_reauth(mock_entry.data)
    assert result_init["type"] == "form"
    assert result_init["step_id"] == "reauth_confirm"
    assert flow.brand == "tos"

    # Confirm reauth
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )
    result_confirm = await flow.async_step_reauth_confirm(user_input={})
    assert result_confirm["type"] == "form"
    assert result_confirm["step_id"] == "auth"
    assert flow.client is not None
    assert flow.client.brand == "tos"

    # Submit PIN and verify updated entry retains brand='tos'
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_submit_pin",
        AsyncMock(return_value=None),
    )
    flow.client.access_token = "new_tos_token"
    flow.client.refresh_token = "new_tos_refresh"

    result_auth = await flow.async_step_auth(user_input={"pin_code": "9876"})
    assert result_auth["type"] == "abort"
    assert result_auth["reason"] == "reauth_successful"

    update_call_args = hass.config_entries.async_update_entry.call_args
    updated_data = update_call_args[1]["data"]
    assert updated_data[CONF_BRAND] == "tos"


@pytest.mark.anyio
async def test_reauth_wake_tv_when_standby(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauth flow sends Wake-on-LAN when TV port 36669 is initially closed, then polls and proceeds."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_wake"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
        "secondary_mac_address": "e4:3b:c9:aa:bb:cc",
    }
    mock_entry.options = {}
    flow = _reauth_flow(hass, mock_entry, "test_entry_wake")

    await flow.async_step_reauth(mock_entry.data)

    mock_wol = MagicMock(return_value=True)
    monkeypatch.setattr("custom_components.vidaa.protocol.wol.send_wake_on_lan", mock_wol)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    # First check False (closed), second check True (opened after WoL)
    port_checks = [False, True]
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ReauthFlowMixin._async_port_open",
        AsyncMock(side_effect=lambda ip, port, timeout=1.0: port_checks.pop(0) if port_checks else True),
    )
    monkeypatch.setattr(
        "custom_components.vidaa.client.VidaaClient.async_start_auth",
        AsyncMock(return_value=None),
    )

    result_confirm = await flow.async_step_reauth_confirm(user_input={})
    assert result_confirm["type"] == "form"
    assert result_confirm["step_id"] == "auth"

    mock_wol.assert_called_once()
    called_macs = mock_wol.call_args[0][0]
    assert "e8:51:77:aa:bb:cc" in called_macs
    assert "e4:3b:c9:aa:bb:cc" in called_macs


@pytest.mark.anyio
async def test_reauth_wake_tv_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauth flow surfaces tv_not_awake error when TV port never opens."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_wake_timeout"
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "e8:51:77:aa:bb:cc",
    }
    mock_entry.options = {}
    flow = _reauth_flow(hass, mock_entry, "test_entry_wake_timeout")

    await flow.async_step_reauth(mock_entry.data)

    mock_wol = MagicMock(return_value=True)
    monkeypatch.setattr("custom_components.vidaa.protocol.wol.send_wake_on_lan", mock_wol)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ReauthFlowMixin._async_port_open",
        AsyncMock(return_value=False),
    )
    # Simulate monotonic clock passing deadline
    t = [0.0]

    def fake_monotonic():
        t[0] += 5.0
        return t[0]

    monkeypatch.setattr("time.monotonic", fake_monotonic)

    result_confirm = await flow.async_step_reauth_confirm(user_input={})
    assert result_confirm["type"] == "form"
    assert result_confirm["step_id"] == "reauth_confirm"
    assert result_confirm["errors"] == {"base": "tv_not_awake"}
    mock_wol.assert_called_once()


@pytest.mark.anyio
async def test_reauth_wake_tv_no_mac_returns_tv_not_awake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test reauth flow surfaces tv_not_awake immediately when no MAC address is configured and port is closed."""
    hass = MagicMock(spec=HomeAssistant)
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_no_mac"
    mock_entry.data = {CONF_IP_ADDRESS: "192.168.1.100"}
    mock_entry.options = {}
    flow = _reauth_flow(hass, mock_entry, "test_entry_no_mac")

    await flow.async_step_reauth(mock_entry.data)

    mock_wol = MagicMock(return_value=True)
    monkeypatch.setattr("custom_components.vidaa.protocol.wol.send_wake_on_lan", mock_wol)
    monkeypatch.setattr(
        "custom_components.vidaa.flow.reauth.ReauthFlowMixin._async_port_open",
        AsyncMock(return_value=False),
    )

    result_confirm = await flow.async_step_reauth_confirm(user_input={})
    assert result_confirm["type"] == "form"
    assert result_confirm["step_id"] == "reauth_confirm"
    assert result_confirm["errors"] == {"base": "tv_not_awake"}
    mock_wol.assert_not_called()
