"""Unit tests for multi-TV isolation, service dispatch, deduplication, and UX placeholders."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import socket
import ssl
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa import async_setup
from custom_components.vidaa.config_flow import VidaaConfigFlow
from custom_components.vidaa.const import (
    ATTR_APP,
    ATTR_KEY,
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
    DOMAIN,
    SERVICE_LAUNCH_APP,
    SERVICE_SEND_KEY,
)
from custom_components.vidaa.lifecycle import async_ensure_entry_mac, async_sync_certificate_repair_issue
from custom_components.vidaa.repairs import AuthTokenInvalidatedRepairFlow, CertificateMissingRepairFlow
from custom_components.vidaa.services import _get_target_clients
from custom_components.vidaa.switch import VidaaDebugLoggingSwitch
from custom_components.vidaa.tv.fingerprint import query_mdns_fingerprint


def _create_p12_bytes(cn: str) -> bytes:
    """Create a minimal PKCS#12 bundle for testing."""
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"test", key, cert, None, serialization.NoEncryption())


@pytest.mark.anyio
async def test_multi_tv_scoped_cert_uploads_do_not_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploading certificates for a second TV stores them in a separate scoped directory."""
    certs_root = tmp_path / ".storage" / "vidaa" / "certs"
    apk1 = tmp_path / "tv1.apk"
    apk2 = tmp_path / "tv2.apk"
    with zipfile.ZipFile(apk1, "w") as z1:
        z1.writestr("res/raw/client_mobile_android.p12", _create_p12_bytes("TV1"))
    with zipfile.ZipFile(apk2, "w") as z2:
        z2.writestr("res/raw/client_mobile_android.p12", _create_p12_bytes("TV2"))

    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.config = MagicMock()
    hass.config.path = MagicMock(return_value=str(certs_root))

    monkeypatch.setattr(
        "custom_components.vidaa.config_flow.VidaaConfigFlow._async_init_client_and_auth",
        AsyncMock(return_value={"type": "form", "step_id": "auth"}),
    )

    flow1 = VidaaConfigFlow()
    flow1.hass = hass
    flow1.context = {}
    flow1.ip_address = "192.168.50.11"
    flow1.mac_address = "aa:bb:cc:11:22:33"
    await flow1.async_step_upload(user_input={"cert_file": str(apk1)})

    flow2 = VidaaConfigFlow()
    flow2.hass = hass
    flow2.context = {}
    flow2.ip_address = "192.168.50.12"
    flow2.mac_address = "dd:ee:ff:44:55:66"
    await flow2.async_step_upload(user_input={"cert_file": str(apk2)})

    assert flow1.certfile != flow2.certfile
    assert flow1.keyfile != flow2.keyfile
    assert Path(flow1.certfile).read_bytes() != Path(flow2.certfile).read_bytes()
    assert Path(flow1.certfile).exists()
    assert Path(flow2.certfile).exists()


@pytest.mark.anyio
async def test_cleanup_installed_certs_preserves_other_tv_cert(tmp_path: Path) -> None:
    """Failed TLS on TV #2 must never unlink a certificate actively used by TV #1."""
    shared_cert = tmp_path / ".storage" / "vidaa" / "certs" / "hisense.crt"
    shared_key = tmp_path / ".storage" / "vidaa" / "certs" / "hisense.key"
    shared_cert.parent.mkdir(parents=True, exist_ok=True)
    shared_cert.write_text("TV1 CERT")
    shared_key.write_text("TV1 KEY")

    entry1 = SimpleNamespace(
        entry_id="entry_1",
        data={CONF_CERTFILE: str(shared_cert), CONF_KEYFILE: str(shared_key)},
        options={},
    )
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry1])

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.ip_address = "192.168.50.12"
    flow.certfile = str(shared_cert)
    flow.keyfile = str(shared_key)
    flow._cleanup_installed_certs()

    assert shared_cert.exists()
    assert shared_key.exists()


@pytest.mark.anyio
async def test_second_tv_ssl_error_routes_to_upload_instead_of_cannot_connect() -> None:
    """If existing TV #1 certs fail SSL handshake for TV #2, route to upload step."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    flow = VidaaConfigFlow()
    flow.hass = hass
    flow.context = {}

    with (
        patch.object(flow, "_async_resolve_ssl_certs", AsyncMock(return_value=True)),
        patch.object(flow, "_async_init_client_and_auth", AsyncMock(side_effect=ssl.SSLError("bad cert"))),
        patch("custom_components.vidaa.flow.user.async_resolve_mac", AsyncMock(return_value="dd:ee:ff:44:55:66")),
    ):
        res = await flow.async_step_user(user_input={CONF_IP_ADDRESS: "192.168.50.12"})

    assert res["type"] == "form"
    assert res["step_id"] == "upload"
    assert res["errors"]["base"] == "invalid_ssl_cert"


@pytest.mark.anyio
async def test_multi_tv_service_dispatch_continues_when_one_tv_off_and_runs_concurrently() -> None:
    """Multi-TV service calls run concurrently and succeed for awake TVs even if one TV is off."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    handlers = {}
    hass.services.async_register = MagicMock(side_effect=lambda _d, s, h, schema=None, **kw: handlers.setdefault(s, h))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    call_order: list[str] = []

    async def _slow_cmd_1(_key: str) -> bool:
        call_order.append("tv1_start")
        await asyncio.sleep(0.03)
        call_order.append("tv1_end")
        return True

    async def _slow_cmd_2(_key: str) -> bool:
        call_order.append("tv2_start")
        await asyncio.sleep(0.03)
        call_order.append("tv2_end")
        return True

    client_off = MagicMock()
    client_off.ip = "192.168.50.11"
    client_off.mac = "aa:bb:cc:11:22:33"
    client_off.connected = True
    client_off.is_on = False
    client_off.auth_failed = False
    client_off.async_send_command = AsyncMock(return_value=True)

    client_on = MagicMock()
    client_on.ip = "192.168.50.12"
    client_on.mac = "dd:ee:ff:44:55:66"
    client_on.connected = True
    client_on.is_on = True
    client_on.auth_failed = False
    client_on.async_send_command = AsyncMock(side_effect=_slow_cmd_2)

    entry1 = SimpleNamespace(entry_id="e1", data={}, options={}, runtime_data=SimpleNamespace(client=client_off))
    entry2 = SimpleNamespace(entry_id="e2", data={}, options={}, runtime_data=SimpleNamespace(client=client_on))
    hass.config_entries = MagicMock()
    hass.config_entries.async_loaded_entries = MagicMock(return_value=[entry1, entry2])

    await async_setup(hass, {})

    # 1. Partial failure: TV1 is off, TV2 is on -> TV2 still receives KEY_HOME
    res = await handlers[SERVICE_SEND_KEY](
        ServiceCall(domain=DOMAIN, service=SERVICE_SEND_KEY, data={"entity_id": "all", ATTR_KEY: "KEY_HOME"})
    )
    assert res["targets"] == ["192.168.50.12"]
    assert res["count"] == 1
    assert len(res["failed"]) == 1
    assert res["failed"][0]["ip"] == "192.168.50.11"
    client_on.async_send_command.assert_awaited_once_with("KEY_HOME")

    # 2. All targets fail -> raises HomeAssistantError
    client_on.is_on = False
    with pytest.raises(HomeAssistantError):
        await handlers[SERVICE_SEND_KEY](
            ServiceCall(domain=DOMAIN, service=SERVICE_SEND_KEY, data={"entity_id": "all", ATTR_KEY: "KEY_HOME"})
        )

    # 3. Both TVs on -> concurrent execution (both start before either finishes)
    call_order.clear()
    client_off.is_on = True
    client_on.is_on = True
    client_off.async_send_command = AsyncMock(side_effect=_slow_cmd_1)
    client_on.async_send_command = AsyncMock(side_effect=_slow_cmd_2)
    res_both = await handlers[SERVICE_SEND_KEY](
        ServiceCall(domain=DOMAIN, service=SERVICE_SEND_KEY, data={"entity_id": "all", ATTR_KEY: "KEY_HOME"})
    )
    assert res_both["count"] == 2
    assert "failed" not in res_both
    assert set(call_order[:2]) == {"tv1_start", "tv2_start"}

    # 4. launch_app partial failure skips sleeping TV that fails to wake without blocking awake TV
    client_off.is_on = False
    client_off.async_turn_on = AsyncMock(return_value=False)
    client_off.apps = []
    client_on.apps = [{"name": "Netflix", "appId": "1", "url": "netflix"}]
    client_on.async_launch_app = AsyncMock(return_value=True)
    res_launch = await handlers[SERVICE_LAUNCH_APP](
        ServiceCall(domain=DOMAIN, service=SERVICE_LAUNCH_APP, data={"entity_id": "all", ATTR_APP: "Netflix"})
    )
    assert res_launch["count"] == 1
    assert res_launch["targets"][0]["ip"] == "192.168.50.12"
    assert len(res_launch["failed"]) == 1


def test_service_targeting_normalizes_mac_and_matches_secondary_mac() -> None:
    """Service MAC targeting matches uppercase/hyphenated formats and secondary MACs."""
    hass = MagicMock(spec=HomeAssistant)
    client1 = MagicMock(ip="192.168.50.11", mac="aa:bb:cc:11:22:33", secondary_mac="aa:bb:cc:11:22:34")
    client2 = MagicMock(ip="192.168.50.12", mac="dd:ee:ff:44:55:66", secondary_mac=None)
    entry1 = SimpleNamespace(
        entry_id="e1",
        unique_id="aa:bb:cc:11:22:33",
        data={CONF_MAC_ADDRESS: "aa:bb:cc:11:22:33", CONF_SECONDARY_MAC_ADDRESS: "aa:bb:cc:11:22:34"},
        options={},
        runtime_data=SimpleNamespace(client=client1),
    )
    entry2 = SimpleNamespace(
        entry_id="e2",
        unique_id="dd:ee:ff:44:55:66",
        data={CONF_MAC_ADDRESS: "dd:ee:ff:44:55:66"},
        options={},
        runtime_data=SimpleNamespace(client=client2),
    )
    hass.config_entries = MagicMock()
    hass.config_entries.async_loaded_entries = MagicMock(return_value=[entry1, entry2])

    call_upper = ServiceCall(domain=DOMAIN, service=SERVICE_SEND_KEY, data={"mac": "DD-EE-FF-44-55-66"})
    assert _get_target_clients(hass, call_upper) == [client2]

    call_sec = ServiceCall(domain=DOMAIN, service=SERVICE_SEND_KEY, data={"mac_address": "AA:BB:CC:11:22:34"})
    assert _get_target_clients(hass, call_sec) == [client1]


@pytest.mark.anyio
async def test_duplicate_tv_guards_for_secondary_mac_no_arp_ip_and_reconfigure() -> None:
    """Duplicate guards block dual-MAC re-discovery, VLAN no-ARP IP duplicates, and reconfigure collisions."""
    entry1 = SimpleNamespace(
        entry_id="e1",
        title="Living Room TV",
        unique_id="aa:bb:cc:11:22:33",
        data={
            CONF_IP_ADDRESS: "192.168.50.11",
            CONF_MAC_ADDRESS: "aa:bb:cc:11:22:33",
            CONF_SECONDARY_MAC_ADDRESS: "aa:bb:cc:11:22:34",
        },
        options={},
    )
    entry2 = SimpleNamespace(
        entry_id="e2",
        title="Bedroom TV",
        unique_id="dd:ee:ff:44:55:66",
        data={CONF_IP_ADDRESS: "192.168.50.12", CONF_MAC_ADDRESS: "dd:ee:ff:44:55:66"},
        options={},
    )
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry1, entry2])
    hass.config_entries.async_get_entry = MagicMock(side_effect=lambda eid: entry2 if eid == "e2" else entry1)

    # 1. Discovery with TV1's secondary MAC on a new IP aborts and updates IP
    disc_flow = VidaaConfigFlow()
    disc_flow.hass = hass
    disc_flow.context = {}
    disc_flow._async_current_entries = MagicMock(return_value=[entry1, entry2])
    disc_flow.async_set_unique_id = AsyncMock()
    disc_flow._abort_if_unique_id_configured = MagicMock()

    parsed = SimpleNamespace(
        host="192.168.50.99",
        title="Living Room TV",
        manufacturer="Hisense",
        model="65U7",
        brand="his",
        mac_address="aa:bb:cc:11:22:34",
        secondary_mac_address=None,
        unique_id="aa:bb:cc:11:22:34",
    )
    res_disc = await disc_flow._async_handle_discovery(parsed)
    assert res_disc["type"] == "abort"
    assert res_disc["reason"] == "already_configured"
    hass.config_entries.async_update_entry.assert_called_once()

    # 2. Manual setup with ARP returning None and existing IP aborts already_configured
    user_flow = VidaaConfigFlow()
    user_flow.hass = hass
    user_flow.context = {}
    user_flow.ip_address = "192.168.50.11"
    user_flow.mac_address = None
    user_flow._async_current_entries = MagicMock(return_value=[entry1, entry2])
    with patch("custom_components.vidaa.flow.user.async_resolve_mac", AsyncMock(return_value=None)):
        res_user = await user_flow._async_init_client_and_auth()
    assert res_user["type"] == "abort"
    assert res_user["reason"] == "already_configured"

    # 3. Reconfigure TV2 to TV1's IP when ARP fails aborts already_configured
    reconf_flow = VidaaConfigFlow()
    reconf_flow.hass = hass
    reconf_flow.context = {"entry_id": "e2"}
    with patch("custom_components.vidaa.flow.reauth.async_resolve_mac", AsyncMock(return_value=None)):
        res_reconf = await reconf_flow.async_step_reconfigure(user_input={CONF_IP_ADDRESS: "192.168.50.11"})
    assert res_reconf["type"] == "abort"
    assert res_reconf["reason"] == "already_configured"

    # 4. Startup MAC enrichment does not steal another entry's unique_id
    hass.config_entries.async_update_entry.reset_mock()
    hass.async_add_executor_job = AsyncMock(return_value="aa:bb:cc:11:22:33")
    entry_no_mac = SimpleNamespace(
        entry_id="e3",
        title="Third TV",
        unique_id="third_uid",
        data={CONF_IP_ADDRESS: "192.168.50.13"},
        options={},
    )
    hass.config_entries.async_entries = MagicMock(return_value=[entry1, entry_no_mac])
    await async_ensure_entry_mac(hass, entry_no_mac)
    assert hass.config_entries.async_update_entry.call_args.kwargs["unique_id"] == "third_uid"


@pytest.mark.anyio
async def test_repairs_and_pin_prompt_include_tv_placeholders_and_valid_translations() -> None:
    """Repairs issues/dialogs and PIN prompts identify the target TV across all 14 translation files."""
    entry = SimpleNamespace(
        entry_id="entry_bed",
        title="Bedroom TV",
        data={CONF_IP_ADDRESS: "192.168.50.12"},
        options={},
    )
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.async_add_executor_job = AsyncMock(return_value=False)
    client = SimpleNamespace(certfile=None, keyfile=None)

    with patch("custom_components.vidaa.lifecycle.ir.async_create_issue") as mock_create_issue:
        await async_sync_certificate_repair_issue(hass, entry, client, use_ssl=True, auth_profile="modern")
        mock_create_issue.assert_called_once()
        assert mock_create_issue.call_args.kwargs["translation_placeholders"] == {
            "name": "Bedroom TV",
            "ip_address": "192.168.50.12",
        }

    cert_flow = CertificateMissingRepairFlow(entry_id="entry_bed")
    cert_flow.hass = hass
    cert_form = await cert_flow.async_step_confirm()
    assert cert_form["description_placeholders"] == {"name": "Bedroom TV", "ip_address": "192.168.50.12"}

    auth_issue_flow = AuthTokenInvalidatedRepairFlow(entry_id="entry_bed")
    auth_issue_flow.hass = hass
    auth_issue_form = await auth_issue_flow.async_step_confirm()
    assert auth_issue_form["description_placeholders"] == {"name": "Bedroom TV", "ip_address": "192.168.50.12"}

    pin_flow = VidaaConfigFlow()
    pin_flow.hass = hass
    pin_flow.ip_address = "192.168.50.12"
    pin_flow.discovered_title = "Bedroom TV"
    pin_flow.client = MagicMock()
    pin_form = await pin_flow.async_step_auth()
    assert pin_form["description_placeholders"] == {"name": "Bedroom TV", "ip_address": "192.168.50.12"}

    base = Path(__file__).resolve().parent.parent / "custom_components" / "vidaa"
    files = [str(base / "strings.json"), *sorted(glob.glob(str(base / "translations" / "*.json")))]
    assert len(files) == 14
    for path in files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert "{name}" in data["config"]["step"]["auth"]["description"]
        assert "{ip_address}" in data["config"]["step"]["auth"]["description"]
        assert "{name}" in data["issues"]["certificate_missing"]["title"]
        assert "{name}" in data["issues"]["certificate_missing"]["fix_flow"]["step"]["confirm"]["description"]
        assert "{ip_address}" in data["issues"]["certificate_missing"]["fix_flow"]["step"]["confirm"]["description"]


@pytest.mark.anyio
async def test_debug_logging_switch_syncs_across_multiple_tvs() -> None:
    """Toggling debug logging on one TV updates the switch state on every configured TV."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    client1 = MagicMock(ip="192.168.50.11")
    client2 = MagicMock(ip="192.168.50.12")
    entry1 = SimpleNamespace(entry_id="e1", title="TV 1", data={}, options={})
    entry2 = SimpleNamespace(entry_id="e2", title="TV 2", data={}, options={})

    sw1 = VidaaDebugLoggingSwitch(client1, entry1)
    sw2 = VidaaDebugLoggingSwitch(client2, entry2)
    sw1.hass = hass
    sw2.hass = hass
    sw1.async_write_ha_state = MagicMock()
    sw2.async_write_ha_state = MagicMock()

    await sw1.async_added_to_hass()
    await sw2.async_added_to_hass()

    try:
        await sw1.async_turn_on()
        assert sw1.is_on is True
        assert sw2.is_on is True
        sw1.async_write_ha_state.assert_called_once()
        sw2.async_write_ha_state.assert_called_once()

        sw1.async_write_ha_state.reset_mock()
        sw2.async_write_ha_state.reset_mock()

        await sw2.async_turn_off()
        assert sw1.is_on is False
        assert sw2.is_on is False
        sw1.async_write_ha_state.assert_called_once()
        sw2.async_write_ha_state.assert_called_once()
    finally:
        logging.getLogger("custom_components.vidaa").setLevel(logging.NOTSET)
        await sw1.async_will_remove_from_hass()
        await sw2.async_will_remove_from_hass()


def test_query_mdns_fingerprint_ignores_other_smart_tvs() -> None:
    """mDNS fingerprinting only accepts records whose IP matches target_ip."""
    mock_zc = MagicMock()
    other_tv = MagicMock()
    other_tv.addresses = [socket.inet_aton("192.168.50.99")]
    other_tv.properties = {b"model": b"Wrong_TV", b"fv": b"V9.9", b"serialNumber": b"WRONG"}
    mock_zc.get_service_info.return_value = other_tv

    class MockBrowser:
        def __init__(self, zc, types, listener):
            for t in types:
                listener.add_service(zc, t, "Other Smart TV")

        def cancel(self):
            pass

    with (
        patch("zeroconf.ServiceBrowser", MockBrowser),
        patch("time.sleep"),
    ):
        info = query_mdns_fingerprint("192.168.50.12", zc=mock_zc)

    assert info["model_code"] is None
    assert info["firmware_version"] is None
    assert info["serial_number"] is None
