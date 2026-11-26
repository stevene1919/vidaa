"""Silver coverage tests for tv/fingerprint.py, protocol/pairing.py, protocol/upnp.py, and protocol/discovery.py."""

from __future__ import annotations

import email.utils
import io
import urllib.error
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.vidaa.client import VidaaClient
from custom_components.vidaa.protocol.discovery import (
    async_probe_udp_port,
    normalize_brand_code,
    parse_ssdp_discovery,
    parse_zeroconf_discovery,
    probe_udp_port,
)
from custom_components.vidaa.protocol.pairing import (
    _async_execute_pairing_attempt,
    async_probe_pairing_challenge,
    async_start_pairing_handshake,
    async_submit_pin_code,
)
from custom_components.vidaa.protocol.upnp import VidaaUpnpClient
from custom_components.vidaa.tv.fingerprint import (
    probe_upnp_services,
    query_mdns_fingerprint,
)


def test_tv_fingerprint_upnp_and_mdns_coverage() -> None:
    """Cover probe_upnp_services (verbose, HTTP 200/404/500/error) and query_mdns_fingerprint."""
    with patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
        empty_res = probe_upnp_services("192.168.1.100", verbose=True)
    assert empty_res["active_port"] is None

    def _make_resp(body: str, status: int = 200):
        cm = MagicMock()
        resp = MagicMock()
        resp.status = status
        resp.read.return_value = body.encode("utf-8")
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        return cm

    # Success on port 38400 + all 4 SOAP actions 200 OK
    ok_responses = [
        _make_resp("<root><device><friendlyName>Bedroom TV</friendlyName></device></root>"),
        _make_resp("<CurrentVolume>25</CurrentVolume>"),
        _make_resp("<CurrentMute>1</CurrentMute>"),
        _make_resp(
            "<CurrentTransportState>PLAYING</CurrentTransportState><CurrentTransportStatus>OK</CurrentTransportStatus>"
        ),
        _make_resp("<Response>OK</Response>"),
    ]
    with patch("urllib.request.urlopen", side_effect=ok_responses):
        ok_res = probe_upnp_services("192.168.1.100", verbose=True)
    assert ok_res["active_port"] == 38400
    assert ok_res["lan_control_status"] == 200

    # SOAP failures: HTTPError 404, HTTPError 500, and generic RuntimeError
    http_404 = urllib.error.HTTPError("http://192.168.1.100:38400", 404, "Not Found", {}, io.BytesIO(b"nope"))
    http_500 = urllib.error.HTTPError("http://192.168.1.100:38400", 500, "Server Err", {}, io.BytesIO(b"err"))
    err_responses = [
        _make_resp("<root><device><friendlyName>Bedroom TV</friendlyName></device></root>"),
        http_500,
        RuntimeError("net reset"),
        http_404,
        urllib.error.HTTPError("http://192.168.1.100:38400", 404, "Not Found", {}, io.BytesIO(b"lan404")),
    ]
    with patch("urllib.request.urlopen", side_effect=err_responses):
        err_res = probe_upnp_services("192.168.1.100", verbose=True)
    assert err_res["lan_control_status"] == 404

    # query_mdns_fingerprint update_service / remove_service & exception path
    def _fake_browser(_zc, _types, listener):
        listener.update_service(_zc, "_airplay._tcp.local.", "TV")
        listener.remove_service(_zc, "_airplay._tcp.local.", "TV")
        return MagicMock()

    with (
        patch("zeroconf.ServiceBrowser", side_effect=_fake_browser),
        patch("custom_components.vidaa.tv.fingerprint.time.sleep"),
    ):
        mdns_ok = query_mdns_fingerprint("192.168.1.100", zc=MagicMock())
    assert mdns_ok["model_code"] is None

    with patch("zeroconf.ServiceBrowser", side_effect=RuntimeError("zc fail")):
        mdns_err = query_mdns_fingerprint("192.168.1.100", zc=MagicMock())
    assert mdns_err["manufacturer"] is None


@pytest.mark.anyio
async def test_protocol_pairing_coverage() -> None:
    """Cover protocol/pairing.py remaining cascade, timeout, and PIN submission branches."""
    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    client.async_disconnect = AsyncMock()
    client.async_subscribe = AsyncMock()
    client.async_publish = AsyncMock(return_value=True)

    # async_probe_pairing_challenge resets pre-resolved _auth_future
    async def _open_pre_resolved(*_args, **_kwargs):
        if client._auth_future and not client._auth_future.done():
            client._auth_future.set_result("stale")

    client.async_open_pairing_session = AsyncMock(side_effect=_open_pre_resolved)
    with patch("custom_components.vidaa.protocol.pairing.asyncio.sleep", AsyncMock()):
        assert await async_probe_pairing_challenge(client, timeout=0.05) is False

    # async_start_pairing_handshake explicit middle & remotenow profiles
    client._async_start_auth_internal = AsyncMock()
    client.auth_profile = "middle"
    await async_start_pairing_handshake(client)
    client._async_start_auth_internal.assert_awaited_with(profile="middle")

    client.auth_profile = "remotenow"
    await async_start_pairing_handshake(client)
    client._async_start_auth_internal.assert_awaited_with(profile="remotenow")

    # auto profile fingerprint brand + transport_protocol branches (3290, 3100, 2500, exception)
    for proto, expected_first in (("3290", "modern"), ("3100", "middle"), ("2500", "remotenow")):
        c = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc", auth_profile="auto", brand="his")
        c.async_get_device_fingerprint = AsyncMock(return_value={"brand": "toshiba", "transport_protocol": proto})
        c._async_start_auth_internal = AsyncMock()
        await async_start_pairing_handshake(c)
        assert c.brand == "tos"
        assert c.auth_profile == expected_first

    c_fp_err = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc", auth_profile="auto", brand="his")
    c_fp_err.async_get_device_fingerprint = AsyncMock(side_effect=RuntimeError("fp fail"))
    c_fp_err._async_start_auth_internal = AsyncMock(side_effect=OSError("network down"))
    with pytest.raises(OSError, match="network down"):
        await async_start_pairing_handshake(c_fp_err)

    # OEM brand probe breaks inner loop on non-auth error
    c_oem = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc", auth_profile="auto", brand="his")
    c_oem.async_get_device_fingerprint = AsyncMock(return_value={})
    c_oem._async_start_auth_internal = AsyncMock(
        side_effect=[
            Exception("code 5"),
            Exception("code 5"),
            Exception("code 5"),
            ConnectionResetError("socket drop"),
            ConnectionResetError("socket drop"),
            ConnectionResetError("socket drop"),
            ConnectionResetError("socket drop"),
            ConnectionResetError("socket drop"),
            ConnectionResetError("socket drop"),
        ]
    )
    with pytest.raises(Exception, match="pairing brand=his"):
        await async_start_pairing_handshake(c_oem)

    # _async_execute_pairing_attempt: immediate success & 3-timeout failure
    c_exec = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    c_exec.async_disconnect = AsyncMock()
    c_exec.upnp.async_get_tv_timestamp = AsyncMock(return_value=1700000000)
    c_exec.derive_pairing_credentials = MagicMock()
    c_exec.async_open_pairing_session = AsyncMock()
    c_exec.async_subscribe = AsyncMock()
    c_exec.async_publish = AsyncMock()

    async def _fast_wait_ok(coro, timeout=None):
        if hasattr(coro, "close"):
            coro.close()
        return ""

    with (
        patch("custom_components.vidaa.protocol.pairing.asyncio.sleep", AsyncMock()),
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait_for", side_effect=_fast_wait_ok),
    ):
        await _async_execute_pairing_attempt(c_exec, profile="modern")

    async def _fast_wait_timeout(coro, timeout=None):
        if hasattr(coro, "close"):
            coro.close()
        raise TimeoutError()

    with (
        patch("custom_components.vidaa.protocol.pairing.asyncio.sleep", AsyncMock()),
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait_for", side_effect=_fast_wait_timeout),
        pytest.raises(Exception, match="TV did not show PIN"),
    ):
        await _async_execute_pairing_attempt(c_exec, profile="modern")

    # async_submit_pin_code error paths
    c_pin = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    c_pin.mqtt_client = None
    with pytest.raises(Exception, match="MQTT client not initialized"):
        await async_submit_pin_code(c_pin, "1234")

    c_pin.mqtt_client = MagicMock()
    c_pin.async_publish = AsyncMock(return_value=True)
    with (
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait", AsyncMock(return_value=(set(), set()))),
        pytest.raises(Exception, match="Timeout waiting for PIN validation"),
    ):
        await async_submit_pin_code(c_pin, "1234")

    async def _pin_ok_wait(fs, **_kw):
        for f in fs:
            if f is c_pin._auth_code_future:
                f.set_result('{"result": 1}')
                return ({f}, set())
        return (set(), set())

    async def _token_empty_wait_for(fut, timeout=None):
        return '{"accesstoken": ""}'

    with (
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait", side_effect=_pin_ok_wait),
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait_for", side_effect=_token_empty_wait_for),
        pytest.raises(Exception, match="empty access token"),
    ):
        await async_submit_pin_code(c_pin, "1234")

    with (
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait", side_effect=_pin_ok_wait),
        patch("custom_components.vidaa.protocol.pairing.asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
        pytest.raises(Exception, match="Timeout waiting for token issuance"),
    ):
        await async_submit_pin_code(c_pin, "1234")


@pytest.mark.anyio
async def test_upnp_and_discovery_coverage() -> None:
    """Cover protocol/upnp.py and protocol/discovery.py remaining branches."""
    # UPnP
    xml_desc = (
        '<?xml version="1.0"?>'
        '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
        "<friendlyName>TV</friendlyName>"
        "<modelDescription>model=55U7\nvoice=1</modelDescription>"
        "</device></root>"
    )
    get_resp = MagicMock()
    get_resp.status = 200
    get_resp.headers = {"Date": email.utils.formatdate(1700000000, usegmt=True)}
    get_resp.read = AsyncMock(return_value=xml_desc.encode("utf-8"))
    get_cm = MagicMock()
    get_cm.__aenter__ = AsyncMock(return_value=get_resp)
    get_cm.__exit__ = AsyncMock(return_value=False)

    bad_xml_post = MagicMock()
    bad_xml_post.status = 200
    bad_xml_post.text = AsyncMock(return_value="<not-closed")
    post_cm = MagicMock()
    post_cm.__aenter__ = AsyncMock(return_value=bad_xml_post)
    post_cm.__exit__ = AsyncMock(return_value=False)

    session = MagicMock(closed=False)
    session.get.return_value = get_cm
    session.post.return_value = post_cm
    upnp = VidaaUpnpClient("192.168.1.100", session=session)

    ts = await upnp.async_get_tv_timestamp()
    assert ts == 1700000000
    fp = await upnp.async_get_device_fingerprint()
    assert fp["model"] == "55U7" and fp["voice"] == "1"

    assert await upnp.async_get_volume() is None
    assert await upnp.async_get_mute() is None
    assert await upnp.async_get_transport_info() is None

    session.post.side_effect = aiohttp.ClientError("conn err")
    st, msg = await upnp.async_send_soap("/p", "s", "a")
    assert st == 0 and "conn err" in msg

    session.post.side_effect = RuntimeError("unexpected")
    st2, msg2 = await upnp.async_send_soap("/p", "s", "a")
    assert st2 == 0 and "unexpected" in msg2

    # Discovery
    assert normalize_brand_code("my-toshiba-tv") == "tos"
    assert normalize_brand_code("superhisensetv") == "his"

    assert (
        parse_ssdp_discovery(SimpleNamespace(upnp={"manufacturer": "Hisense"}, ssdp_headers={}, ssdp_location=None))
        is None
    )

    ssdp_info = SimpleNamespace(
        upnp={
            "manufacturer": "Hisense",
            "modelDescription": "macWifi=\nmacWifi=e8:51:77:aa:bb:cc\nmacEthernet=e8:51:77:aa:bb:cc\nnetwork_device=e8:51:77:aa:bb:cc",
        },
        ssdp_headers={},
        ssdp_location="http://192.168.1.100:38400/desc.xml",
    )
    with patch("custom_components.vidaa.protocol.discovery.get_arp_mac", return_value=None):
        parsed = parse_ssdp_discovery(ssdp_info)
    assert parsed is not None
    assert parsed.host == "192.168.1.100"
    assert parsed.secondary_mac_address is None

    assert parse_zeroconf_discovery(SimpleNamespace(host=None)) is None
    zc_non_map = parse_zeroconf_discovery(
        SimpleNamespace(host="192.168.1.100", properties=["invalid"], name="TV._airplay._tcp.local.")
    )
    assert zc_non_map is not None
    zc_str_prop = parse_zeroconf_discovery(
        SimpleNamespace(host="192.168.1.100", properties={"md": "U7H"}, name="Bedroom TV._airplay._tcp.local.")
    )
    assert zc_str_prop is not None and zc_str_prop.model == "U7H"

    # probe_udp_port + async_probe_udp_port
    fake_sock = MagicMock()
    fake_sock.sendto.side_effect = [OSError("send fail"), None, None]
    fake_sock.recvfrom.side_effect = [
        (b"{}", ("192.168.1.101", 36671)),
        (b"HI_RAW", ("192.168.1.100", 36671)),
    ]
    with patch("socket.socket", return_value=fake_sock):
        udp = probe_udp_port("192.168.1.100", timeout=1.0)
    assert udp is not None and udp["raw"] == {"raw": "HI_RAW"}

    fake_sock2 = MagicMock()
    fake_sock2.recvfrom.side_effect = RuntimeError("recv fail")
    with patch("socket.socket", return_value=fake_sock2):
        assert probe_udp_port("192.168.1.100", timeout=1.0) is None

    with patch("custom_components.vidaa.protocol.discovery.probe_udp_port", return_value={"ip": "192.168.1.100"}):
        assert await async_probe_udp_port("192.168.1.100") == {"ip": "192.168.1.100"}
