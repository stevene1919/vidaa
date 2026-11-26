"""Targeted unit tests closing config-flow, options-flow, and isolation branch coverage."""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import AbortFlow

from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import (
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEY_REPEAT,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_USE_SSL,
    DEFAULT_KEY_REPEAT,
)
from custom_components.vidaa.flow.helpers import (
    UploadedCertProcessingError,
    async_discover_device_details,
    async_process_uploaded_cert_file,
)
from custom_components.vidaa.flow.isolation import (
    cert_path_in_use_by_other_entries,
    normalize_mac_str,
    sanitize_cert_scope,
)
from custom_components.vidaa.flow.options import VidaaOptionsFlowHandler
from custom_components.vidaa.protocol.discovery import DiscoveredTvInfo


def _make_hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.loop = asyncio.get_running_loop()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.async_create_background_task = MagicMock(side_effect=lambda coro, *a, **kw: hass.loop.create_task(coro))
    hass.config = MagicMock()
    hass.config.config_dir = "/config"
    hass.config.path = MagicMock(side_effect=lambda *parts: "/config/" + "/".join(parts))
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    return hass


@pytest.mark.anyio
async def test_config_flow_options_factory_and_auth_rehydrate(mock_entry) -> None:
    """Test async_get_options_flow and async_step_auth lazy client hydration & error branches."""
    opt_flow = VidaaConfigFlow.async_get_options_flow(mock_entry)
    assert isinstance(opt_flow, VidaaOptionsFlowHandler)

    hass = _make_hass()
    mock_entry.data = {
        CONF_IP_ADDRESS: "192.168.1.100",
        CONF_MAC_ADDRESS: "aa:bb:cc:11:22:33",
        CONF_AUTH_PROFILE: "modern",
        CONF_BRAND: "his",
        CONF_USE_SSL: True,
    }
    mock_entry.options = {}

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow._reauth_entry = mock_entry

    fake_client = MagicMock()
    fake_client.brand = "tos"
    fake_client.async_start_auth = AsyncMock()
    fake_client.async_submit_pin = AsyncMock(side_effect=RuntimeError("bad pin"))
    fake_client.async_disconnect = AsyncMock()

    with patch("custom_components.vidaa.config_flow.VidaaClient", return_value=fake_client):
        res_err = await flow.async_step_auth(user_input={"pin_code": "1234"})
    assert res_err["type"] == "form"
    assert res_err["errors"]["base"] == "invalid_auth"
    assert flow.brand == "tos"
    assert flow.manufacturer == "Toshiba"

    # When async_start_auth fails during lazy hydration -> cannot_connect
    flow2 = VidaaConfigFlow()
    flow2.hass = hass
    flow2.context = {}
    flow2._reauth_entry = mock_entry
    failing_client = MagicMock()
    failing_client.async_start_auth = AsyncMock(side_effect=OSError("offline"))
    with patch("custom_components.vidaa.config_flow.VidaaClient", return_value=failing_client):
        res_conn = await flow2.async_step_auth()
    assert res_conn["errors"]["base"] == "cannot_connect"

    # Initial setup updates default brand from client.brand before options step
    flow3 = VidaaConfigFlow()
    flow3.hass = hass
    flow3.context = {}
    flow3.ip_address = "192.168.1.100"
    flow3.client = MagicMock()
    flow3.client.brand = "loe"
    flow3.client.async_submit_pin = AsyncMock(return_value={"accesstoken": "ok"})
    with (
        patch.object(flow3, "_async_discover_device_name", AsyncMock()),
        patch.object(flow3, "_async_probe_device_capabilities", AsyncMock()),
    ):
        res_opts = await flow3.async_step_auth(user_input={"pin_code": "4321"})
    assert res_opts["step_id"] == "options"
    assert flow3.brand == "loe"


@pytest.mark.anyio
async def test_certs_flow_branches_upload_and_manual_certs(tmp_path: Path) -> None:
    """Cover _resolve_ssl_certs, upload empty/error rollback, and async_step_certs validation paths."""
    hass = _make_hass()
    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.ip_address = "192.168.1.100"

    # Sync _resolve_ssl_certs with brand hint
    with patch(
        "custom_components.vidaa.flow.certs.resolve_ssl_certs",
        return_value=(True, "/ssl/toshiba.crt", "/ssl/toshiba.key", True),
    ):
        assert flow._resolve_ssl_certs() is True
    assert flow.brand == "tos"
    assert flow.manufacturer == "Toshiba"

    with patch("custom_components.vidaa.flow.certs.resolve_ssl_certs", return_value=(False, None, None, True)):
        assert flow._resolve_ssl_certs() is False

    # Empty upload submission -> invalid_cert_archive
    res_empty = await flow.async_step_upload(user_input={})
    assert res_empty["errors"]["base"] == "invalid_cert_archive"

    # Generic connect failure after upload triggers cleanup and cannot_connect
    tmp_crt = tmp_path / ".storage" / "vidaa" / "certs" / "hisense.crt"
    tmp_key = tmp_path / ".storage" / "vidaa" / "certs" / "hisense.key"
    tmp_crt.parent.mkdir(parents=True, exist_ok=True)
    tmp_crt.write_text("c")
    tmp_key.write_text("k")
    with (
        patch(
            "custom_components.vidaa.flow.certs.async_process_uploaded_cert_file",
            AsyncMock(return_value=(str(tmp_crt), str(tmp_key), "his")),
        ),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=OSError("refused"))),
    ):
        res_fail = await flow.async_step_upload(user_input={"cert_file": "id1"})
    assert res_fail["errors"]["base"] == "cannot_connect"
    assert not tmp_crt.exists()

    # async_step_certs: p12 failure, missing certfile, missing keyfile, invalid_ssl_cert, SSLError, Exception
    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.extract_pkcs12_to_pem", return_value=None),
    ):
        res_p12 = await flow.async_step_certs(
            user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/a.p12", CONF_KEYFILE: "/k"}
        )
    assert res_p12["errors"]["base"] == "invalid_ssl_cert"

    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.check_certs_exist", side_effect=[False, False, True]),
    ):
        res_nocert = await flow.async_step_certs(
            user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/c", CONF_KEYFILE: "/k"}
        )
    assert res_nocert["errors"][CONF_CERTFILE] == "certs_not_found"

    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.check_certs_exist", side_effect=[False, True, False]),
    ):
        res_nokey = await flow.async_step_certs(
            user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/c", CONF_KEYFILE: "/k"}
        )
    assert res_nokey["errors"][CONF_KEYFILE] == "certs_not_found"

    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.check_certs_exist", return_value=True),
        patch("custom_components.vidaa.flow.certs.validate_ssl_certs", return_value=(False, "bad")),
    ):
        res_inv = await flow.async_step_certs(user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/c", CONF_KEYFILE: "/k"})
    assert res_inv["errors"]["base"] == "invalid_ssl_cert"

    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.check_certs_exist", return_value=True),
        patch("custom_components.vidaa.flow.certs.validate_ssl_certs", return_value=(True, None)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=ssl.SSLError("tls"))),
    ):
        res_ssl = await flow.async_step_certs(user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/c", CONF_KEYFILE: "/k"})
    assert res_ssl["errors"]["base"] == "invalid_ssl_cert"

    with (
        patch(
            "custom_components.vidaa.flow.certs.get_profile_default_cert_paths",
            return_value=("/c", "/k", "/d", "c", "k"),
        ),
        patch("custom_components.vidaa.flow.certs.check_certs_exist", return_value=True),
        patch("custom_components.vidaa.flow.certs.validate_ssl_certs", return_value=(True, None)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=OSError("down"))),
    ):
        res_down = await flow.async_step_certs(user_input={CONF_USE_SSL: True, CONF_CERTFILE: "/c", CONF_KEYFILE: "/k"})
    assert res_down["errors"]["base"] == "cannot_connect"


@pytest.mark.anyio
async def test_discovery_user_and_reauth_flow_branches() -> None:
    """Cover discovery confirm errors, user legacy/remove paths, and reauth/reconfigure edge cases."""
    hass = _make_hass()
    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.ip_address = "192.168.1.100"
    flow.discovered_title = "Bedroom TV"

    with (
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=True)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=ssl.SSLError("handshake"))),
    ):
        res_ssl = await flow.async_step_discovery_confirm(user_input={})
    assert res_ssl["step_id"] == "upload"
    assert res_ssl["errors"]["base"] == "invalid_ssl_cert"

    with (
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=True)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=RuntimeError("err"))),
    ):
        res_err = await flow.async_step_discovery_confirm(user_input={})
    assert res_err["errors"]["base"] == "cannot_connect"

    with (
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=True)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=AbortFlow("already_configured"))),
        pytest.raises(AbortFlow),
    ):
        await flow.async_step_discovery_confirm(user_input={})

    # User flow: legacy connect error + modern missing certs -> upload + async_remove without hass
    with (
        patch("custom_components.vidaa.flow.user.async_resolve_mac", AsyncMock(return_value="aa:bb:cc:11:22:33")),
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=False)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=OSError("offline"))),
    ):
        res_leg = await flow.async_step_user(user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_AUTH_PROFILE: "legacy"})
    assert res_leg["errors"]["base"] == "cannot_connect"

    with (
        patch("custom_components.vidaa.flow.user.async_resolve_mac", AsyncMock(return_value="aa:bb:cc:11:22:33")),
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=False)),
    ):
        res_up = await flow.async_step_user(user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_AUTH_PROFILE: "modern"})
    assert res_up["step_id"] == "upload"

    # _async_discover_device_name populates all metadata fields
    flow.client = MagicMock(brand="his")
    with patch(
        "custom_components.vidaa.flow.user.async_discover_device_details",
        AsyncMock(
            return_value={
                "title": "Living Room TV",
                "model": "65U7",
                "manufacturer": "Hisense",
                "brand": "his",
                "sw_version": "V1.0",
                "secondary_mac_address": "11:22:33:44:55:66",
                "mac_address": "aa:bb:cc:11:22:33",
            }
        ),
    ):
        await flow._async_discover_device_name()
    assert flow.model == "65U7"
    assert flow.sw_version == "V1.0"

    # async_remove with hass=None falls back to sync client.disconnect()
    sync_client = MagicMock()
    flow.hass = None
    flow.client = sync_client
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        flow.async_remove()
    sync_client.disconnect.assert_called_once()

    # Reauth helpers: async_step_reauth_confirm error + reconfigure missing certs
    flow.hass = hass
    entry = SimpleNamespace(
        entry_id="e1",
        data={CONF_IP_ADDRESS: "192.168.1.100", CONF_MAC_ADDRESS: "aa:bb:cc:11:22:33"},
        options={CONF_BRAND: "his", CONF_USE_SSL: True},
    )
    flow._reauth_entry = entry
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    reauth_client = MagicMock()
    reauth_client.brand = "his"
    reauth_client.async_start_auth = AsyncMock(side_effect=OSError("unreachable"))
    with patch("custom_components.vidaa.flow.reauth.VidaaClient", return_value=reauth_client):
        res_reauth_err = await flow.async_step_reauth_confirm(user_input={})
    assert res_reauth_err["errors"]["base"] == "cannot_connect"

    flow.context = {"entry_id": "e1"}
    with (
        patch("custom_components.vidaa.flow.reauth.async_resolve_mac", AsyncMock(return_value="aa:bb:cc:11:22:33")),
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=False)),
    ):
        res_reconf_up = await flow.async_step_reconfigure(
            user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_AUTH_PROFILE: "modern"}
        )
    assert res_reconf_up["step_id"] == "upload"

    with (
        patch("custom_components.vidaa.flow.reauth.async_resolve_mac", AsyncMock(return_value="aa:bb:cc:11:22:33")),
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=False)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=OSError("fail"))),
    ):
        res_reconf_err = await flow.async_step_reconfigure(
            user_input={CONF_IP_ADDRESS: "192.168.1.100", CONF_AUTH_PROFILE: "legacy"}
        )
    assert res_reconf_err["errors"]["base"] == "cannot_connect"


@pytest.mark.anyio
async def test_options_helpers_and_isolation_edge_cases() -> None:
    """Cover options aliases, invalid key_repeat, security upload, and helper error classifications."""
    hass = _make_hass()
    client = MagicMock(mac_wifi="aa:bb:cc:11:22:33", mac_ethernet="dd:ee:ff:44:55:66", source_dict={}, app_dict={})
    entry = SimpleNamespace(
        entry_id="opt_1",
        data={CONF_MAC_ADDRESS: "aa:bb:cc:11:22:33"},
        options={},
        runtime_data=SimpleNamespace(client=client),
    )
    opt = VidaaOptionsFlowHandler(entry)
    opt.hass = hass

    pwr_form = await opt.async_step_general()
    assert pwr_form["step_id"] == "power_network"
    pwr_clear = await opt.async_step_power_network(user_input={CONF_SECONDARY_MAC_ADDRESS: ""})
    assert pwr_clear["data"][CONF_SECONDARY_MAC_ADDRESS] == ""

    src_form = await opt.async_step_sources()
    assert src_form["step_id"] == "playback_sources"
    ps_form = await opt.async_step_picture_sound()
    assert ps_form["step_id"] == "features_remote"
    rk_submit = await opt.async_step_remote_keys(user_input={CONF_KEY_REPEAT: "not_a_num"})
    assert rk_submit["data"][CONF_KEY_REPEAT] == DEFAULT_KEY_REPEAT

    with patch(
        "custom_components.vidaa.flow.options_security.async_process_uploaded_cert_file",
        AsyncMock(side_effect=UploadedCertProcessingError("p12_decrypt_failed")),
    ):
        sec_err = await opt.async_step_certs(user_input={"cert_file": "bad_p12"})
    assert sec_err["errors"]["base"] == "p12_decrypt_failed"

    # Helper error classification branches
    for msg, expected_key in (
        ("exceeds maximum limit", "file_too_large"),
        ("Failed to decrypt PKCS#12", "p12_decrypt_failed"),
        ("Malformed certificate", "invalid_pem_bundle"),
        ("No VIDAA PKCS#12 keystore found", "no_p12_found"),
        ("unknown archive error", "invalid_cert_archive"),
    ):
        with (
            patch("custom_components.vidaa.repairs.extract_and_install_certs", side_effect=ValueError(msg)),
            patch("custom_components.vidaa.flow.helpers.extract_and_install_certs", side_effect=ValueError(msg)),
            pytest.raises(UploadedCertProcessingError) as exc_info,
        ):
            await async_process_uploaded_cert_file(hass, "/tmp/upload.bin", scope="tv1")
        assert exc_info.value.error_key == expected_key

    # async_discover_device_details dual-MAC ARP priority
    fp_client = MagicMock()
    fp_client.brand = "his"
    fp_client.async_get_device_fingerprint = AsyncMock(
        return_value={
            "friendly_name": "Renderer",
            "mac_wifi": "aa:bb:cc:11:22:33",
            "mac_ethernet": "dd:ee:ff:44:55:66",
            "manufacturer": "SmartTV",
            "brand": "his",
            "firmware_version": "V2.0",
        }
    )
    with patch("custom_components.vidaa.flow.helpers.async_resolve_mac", AsyncMock(return_value="dd:ee:ff:44:55:66")):
        details = await async_discover_device_details(hass, fp_client, "192.168.1.100")
    assert details["mac_address"] == "dd:ee:ff:44:55:66"
    assert details["secondary_mac_address"] == "aa:bb:cc:11:22:33"

    # Isolation utilities
    assert normalize_mac_str("invalid") is None
    assert sanitize_cert_scope("!!!") is None
    assert cert_path_in_use_by_other_entries(None, "/x") is False
    bad_hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=MagicMock(side_effect=RuntimeError)))
    assert cert_path_in_use_by_other_entries(bad_hass, "/x") is False
    assert DiscoveredTvInfo(host="192.168.1.100", title="TV", model="M", manufacturer="Hisense").is_vidaa is True
