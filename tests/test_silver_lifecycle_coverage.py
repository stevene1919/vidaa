"""Silver coverage tests for tv/tokens.py, flow/helpers.py, and lifecycle.py."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.vidaa.client import VidaaClient
from custom_components.vidaa.const import (
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
)
from custom_components.vidaa.flow.helpers import (
    UploadedCertProcessingError,
    async_disconnect_existing_client,
    async_discover_device_details,
    async_probe_device_capabilities,
    async_process_uploaded_cert_file,
    async_resolve_mac,
    collect_client_auth_data,
    unwrap_section_data,
)
from custom_components.vidaa.lifecycle import (
    async_ensure_entry_mac,
    register_clock_sync_hooks,
    register_device_info_enrichment,
)
from custom_components.vidaa.tv.tokens import (
    _get_is_token_expired_fn,
    _get_perform_token_refresh_fn,
    _get_tv_timestamp_fn,
    _run_sync,
)


@pytest.mark.anyio
async def test_tv_tokens_coverage() -> None:
    """Cover tv/tokens.py helper fallbacks, delegator properties, and shims."""
    with patch.dict(
        sys.modules, {"custom_components.vidaa.client": None, "custom_components.hisense_vidaa.client": None}
    ):
        assert callable(_get_perform_token_refresh_fn())
        assert callable(_get_is_token_expired_fn())
        assert callable(_get_tv_timestamp_fn())

    async def _noop() -> None:
        return None

    with pytest.raises(RuntimeError, match="running event loop"):
        _run_sync(_noop())

    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc", refresh_token="ref")
    assert client._refresh_lock is client._token_manager.refresh_lock
    client._last_refresh_attempt = 10.0
    assert client._last_refresh_attempt == 10.0
    client._last_awake_refresh_attempt = 20.0
    assert client._last_awake_refresh_attempt == 20.0
    client._last_refresh_connect_rc = 5
    assert client._last_refresh_connect_rc == 5
    client._token_watch_closed = True
    assert client._token_watch_closed is True

    with (
        patch.object(client._token_manager, "_token_watch_tick") as mock_tick,
        patch.object(client._token_manager, "_rejected_retry_fire") as mock_fire,
        patch.object(client._token_manager, "cancel_rejected_retry") as mock_cancel,
    ):
        client._token_watch_tick()
        client._rejected_retry_fire()
        client._cancel_rejected_retry()
    mock_tick.assert_called_once()
    mock_fire.assert_called_once()
    mock_cancel.assert_called_once()

    # async_sync_clock sync & async shims + monkeypatched client.get_tv_timestamp
    client.sync_clock = lambda timeout=2.0: 5
    assert await client.async_sync_clock() == 5

    async def _async_sc(timeout=2.0):
        return -5

    client.sync_clock = _async_sc
    assert await client.async_sync_clock() == -5
    del client.__dict__["sync_clock"]

    client.upnp.async_get_tv_timestamp = AsyncMock(return_value=None)
    import custom_components.vidaa.client as client_mod

    with patch.object(client_mod, "get_tv_timestamp", AsyncMock(return_value=1700000100)):
        offset = await client.async_sync_clock(force=True)
    assert isinstance(offset, int)

    with patch.object(client_mod, "get_tv_timestamp", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await client.async_sync_clock(force=True) is None

    # async_check_and_refresh_token async shim + no refresh_token
    async def _async_chk(**_kw):
        return True

    client.check_and_refresh_token = _async_chk
    assert await client.async_check_and_refresh_token() is True
    del client.__dict__["check_and_refresh_token"]

    client.refresh_token = ""
    assert await client.async_check_and_refresh_token() is False

    # async_refresh_tokens async shim + sync wrapper
    async def _async_ref():
        return True

    client.refresh_tokens = _async_ref
    assert await client.async_refresh_tokens() is True
    del client.__dict__["refresh_tokens"]

    with patch(
        "custom_components.vidaa.tv.tokens._run_sync", side_effect=lambda coro: coro.close() or False
    ) as mock_rs:
        assert client.refresh_tokens() is False
    mock_rs.assert_called_once()


@pytest.mark.anyio
async def test_flow_helpers_coverage() -> None:
    """Cover flow/helpers.py remaining branches."""
    tuple_hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_p: "/tmp/certs"),
        async_add_executor_job=lambda _fn: ("c", "k", "his"),
    )
    assert await async_process_uploaded_cert_file(tuple_hass, "f1") == ("c", "k", "his")  # type: ignore[arg-type]

    err_hass = SimpleNamespace(
        config=SimpleNamespace(path=lambda *_p: "/tmp/certs"),
        async_add_executor_job=MagicMock(side_effect=RuntimeError("unexpected")),
    )
    with pytest.raises(UploadedCertProcessingError) as exc_info:
        await async_process_uploaded_cert_file(err_hass, "f1")  # type: ignore[arg-type]
    assert exc_info.value.error_key == "invalid_cert_archive"

    assert unwrap_section_data(None) == {}

    # async_discover_device_details branches
    no_client_details = await async_discover_device_details(MagicMock(), None, "192.168.1.100")
    assert no_client_details["title"] == "Hisense TV (192.168.1.100)"

    fp_client = MagicMock(brand="his")
    fp_client.async_get_device_fingerprint = AsyncMock(
        return_value={
            "friendly_name": "Renderer",
            "mac_wifi": "aa:bb:cc:11:22:33",
            "mac_ethernet": "dd:ee:ff:44:55:66",
            "manufacturer": "UnknownVendor",
            "brand": "zz_unknown",
        }
    )
    with patch("custom_components.vidaa.flow.helpers.async_resolve_mac", AsyncMock(return_value="aa:bb:cc:11:22:33")):
        d1 = await async_discover_device_details(MagicMock(), fp_client, "192.168.1.100")
    assert d1["mac_address"] == "aa:bb:cc:11:22:33" and d1["secondary_mac_address"] == "dd:ee:ff:44:55:66"

    with patch("custom_components.vidaa.flow.helpers.async_resolve_mac", AsyncMock(return_value=None)):
        d2 = await async_discover_device_details(MagicMock(), fp_client, "192.168.1.100")
    assert d2["mac_address"] == "aa:bb:cc:11:22:33"

    fp_client.async_get_device_fingerprint = AsyncMock(
        return_value={"mac_wifi": "aa:bb:cc:11:22:33", "manufacturer": "SmartTV", "brand": "xyz"}
    )
    d3 = await async_discover_device_details(MagicMock(), fp_client, "192.168.1.100")
    assert d3["mac_address"] == "aa:bb:cc:11:22:33" and d3["manufacturer"] == "Hisense"

    # async_probe_device_capabilities exception branch
    cap_client = MagicMock(connected=True)
    cap_client.async_get_picture_settings = AsyncMock(side_effect=RuntimeError("probe fail"))
    await async_probe_device_capabilities(MagicMock(), cap_client, "192.168.1.100")

    # async_disconnect_existing_client with entry_id filter
    c_match = MagicMock(ip="192.168.1.100", mac="e8:51:77:aa:bb:cc", async_disconnect=AsyncMock())
    c_skip = MagicMock(ip="192.168.1.100", mac="e8:51:77:aa:bb:cc", async_disconnect=AsyncMock())
    hass_disc = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda _d: [
                SimpleNamespace(entry_id="e_other", runtime_data=SimpleNamespace(client=c_skip)),
                SimpleNamespace(entry_id="e_target", runtime_data=SimpleNamespace(client=c_match)),
            ]
        )
    )
    await async_disconnect_existing_client(hass_disc, "192.168.1.100", "e8:51:77:aa:bb:cc", entry_id="e_target")  # type: ignore[arg-type]
    c_match.async_disconnect.assert_awaited_once()
    c_skip.async_disconnect.assert_not_awaited()

    assert await async_resolve_mac(MagicMock(), None) is None

    auth_data = collect_client_auth_data("192.168.1.100", "modern", True, secondary_mac_address="e8:51:77:aa:bb:dd")
    assert auth_data[CONF_SECONDARY_MAC_ADDRESS] == "e8:51:77:aa:bb:dd"


@pytest.mark.anyio
async def test_lifecycle_coverage() -> None:
    """Cover lifecycle.py remaining duplicate-MAC, clock-sync error, and device enrichment branches."""
    # async_ensure_entry_mac keeps existing unique_id if resolved MAC belongs to another entry
    other_entry = SimpleNamespace(entry_id="e_other", title="Other TV", unique_id="e8:51:77:aa:bb:cc")
    target_entry = SimpleNamespace(
        entry_id="e_target", title="TV", unique_id=None, data={"ip_address": "192.168.1.100"}
    )
    hass_mac = SimpleNamespace(
        async_add_executor_job=AsyncMock(return_value="e8:51:77:aa:bb:cc"),
        config_entries=SimpleNamespace(
            async_entries=lambda _d: [other_entry, target_entry],
            async_update_entry=MagicMock(),
        ),
    )
    res_mac = await async_ensure_entry_mac(hass_mac, target_entry)  # type: ignore[arg-type]
    assert res_mac == "e8:51:77:aa:bb:cc"
    assert hass_mac.config_entries.async_update_entry.call_args.kwargs["unique_id"] is None

    # register_clock_sync_hooks error handling inside _async_sync_tv_clock
    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    client.connected = True
    client.state = "on"
    client.async_sync_clock = AsyncMock(side_effect=RuntimeError("clock fail"))
    entry_clk = SimpleNamespace(entry_id="e1", async_on_unload=MagicMock())
    scheduled_cb = None

    def _track(_hass, cb, _interval):
        nonlocal scheduled_cb
        scheduled_cb = cb
        return lambda: None

    register_clock_sync_hooks(MagicMock(), entry_clk, client, track_time_interval=_track)  # type: ignore[arg-type]
    assert scheduled_cb is not None
    await scheduled_cb(None)

    # register_device_info_enrichment branches
    dev_cbs: list = []
    client.register_device_info_callback(lambda d: dev_cbs.append(d))
    enrich_entry = SimpleNamespace(
        entry_id="e_enr",
        data={},
        options={},
        async_on_unload=MagicMock(),
    )
    register_device_info_enrichment(MagicMock(), enrich_entry, client)  # type: ignore[arg-type]
    cb = client._callbacks["device_info"][-1]

    # 1. dev_reg without async_get_device_by_identifier -> fallback to async_get_device returning None
    hass_enr = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=MagicMock()))
    enrich_entry2 = SimpleNamespace(entry_id="e_enr2", data={}, options={}, async_on_unload=MagicMock())
    register_device_info_enrichment(hass_enr, enrich_entry2, client)  # type: ignore[arg-type]
    cb2 = client._callbacks["device_info"][-1]

    dev_reg_no_by_id = SimpleNamespace(async_get_device=MagicMock(return_value=None))
    with patch("custom_components.vidaa.lifecycle.dr.async_get", return_value=dev_reg_no_by_id):
        cb2({})
    dev_reg_no_by_id.async_get_device.assert_called_once()

    # 2. device.connections as set + dual-MAC enrichment + single-MAC variants + exception
    device = SimpleNamespace(
        id="dev1",
        model="Old",
        manufacturer="Hisense",
        sw_version="1.0",
        connections=set(),
    )
    dev_reg_full = SimpleNamespace(
        async_get_device_by_identifier=MagicMock(return_value=device),
        async_update_device=MagicMock(),
    )
    client.model_name = "NewModel"
    client.firmware_version = "2.0"
    client.mac_wifi = "e8:51:77:aa:bb:cc"
    client.mac_ethernet = "e8:51:77:aa:bb:dd"

    with patch("custom_components.vidaa.lifecycle.dr.async_get", return_value=dev_reg_full):
        cb2({})
    dev_reg_full.async_update_device.assert_called_once()
    assert CONF_MAC_ADDRESS in hass_enr.config_entries.async_update_entry.call_args.kwargs["data"]

    # primary == mac_ethernet -> secondary == mac_wifi
    enrich_entry2.data = {CONF_MAC_ADDRESS: "e8:51:77:aa:bb:dd"}
    with patch("custom_components.vidaa.lifecycle.dr.async_get", return_value=dev_reg_full):
        cb2({})
    assert (
        hass_enr.config_entries.async_update_entry.call_args.kwargs["data"][CONF_SECONDARY_MAC_ADDRESS]
        == "e8:51:77:aa:bb:cc"
    )

    # single mac_ethernet differing from primary
    client.mac_wifi = None
    client.mac_ethernet = "e8:51:77:aa:bb:ee"
    with patch("custom_components.vidaa.lifecycle.dr.async_get", return_value=dev_reg_full):
        cb2({})
    assert (
        hass_enr.config_entries.async_update_entry.call_args.kwargs["data"][CONF_SECONDARY_MAC_ADDRESS]
        == "e8:51:77:aa:bb:ee"
    )

    # single mac_wifi differing from primary
    client.mac_ethernet = None
    client.mac_wifi = "e8:51:77:aa:bb:ff"
    with patch("custom_components.vidaa.lifecycle.dr.async_get", return_value=dev_reg_full):
        cb2({})
    assert (
        hass_enr.config_entries.async_update_entry.call_args.kwargs["data"][CONF_SECONDARY_MAC_ADDRESS]
        == "e8:51:77:aa:bb:ff"
    )

    # Exception caught cleanly
    with patch("custom_components.vidaa.lifecycle.dr.async_get", side_effect=RuntimeError("dr boom")):
        cb({})
