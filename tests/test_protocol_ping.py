"""Tests for protocol/ping.py connectivity probes and error conditions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.vidaa.protocol.ping import async_ping_tv, ping_tv


@pytest.mark.anyio
async def test_async_ping_tv_tcp_failure():
    """Test ping returns gracefully when TCP connection fails."""
    with patch("asyncio.open_connection", side_effect=OSError("Host unreachable")):
        res = await async_ping_tv("192.168.1.50", timeout=0.1)
        assert res["tcp_port_open"] is False
        assert "TCP connection failed" in res["error"]


@pytest.mark.anyio
async def test_async_ping_tv_tls_failure():
    """Test ping when TCP is open but TLS handshake fails."""
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with (
        patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)),
        patch(
            "custom_components.vidaa.protocol.ping.async_test_tv_ssl_connection",
            side_effect=Exception("SSL handshake error"),
        ),
    ):
        res = await async_ping_tv("192.168.1.50", timeout=0.1)
        assert res["tcp_port_open"] is True
        assert res["tls_handshake"] is False
        assert "TLS handshake failed" in res["error"]


@pytest.mark.anyio
async def test_async_ping_tv_mqtt_success_and_failures():
    """Test ping MQTT connection outcomes: success, auth rejection, and general error."""
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    ssl_info = {
        "connected": True,
        "tls_version": "TLSv1.2",
        "cipher": "ECDHE-RSA-AES128-GCM-SHA256",
        "client_cert_presented": True,
        "certfile": "/fake/cert.pem",
        "keyfile": "/fake/key.pem",
    }

    # 1. Success (rc=0)
    class MockClientSuccess:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    with (
        patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)),
        patch("custom_components.vidaa.protocol.ping.async_test_tv_ssl_connection", return_value=ssl_info),
        patch("custom_components.vidaa.protocol.ping.build_mqtt_ssl_context"),
        patch("aiomqtt.Client", MockClientSuccess),
        patch("custom_components.vidaa.protocol.ping.async_probe_tv_auth_methods", return_value={}),
        patch("custom_components.vidaa.protocol.upnp.VidaaUpnpClient.async_get_device_fingerprint", return_value={}),
        patch("custom_components.vidaa.protocol.upnp.VidaaUpnpClient.close", AsyncMock()),
    ):
        res = await async_ping_tv(
            "192.168.1.50",
            client_id="cid",
            username="user",
            password="pwd",
            certfile="/fake/cert.pem",
            keyfile="/fake/key.pem",
        )
        assert res["tcp_port_open"] is True
        assert res["tls_handshake"] is True
        assert res["mqtt_connected"] is True
        assert res["mqtt_status"] == "Connected successfully"

    # 2. Auth rejection (rc=5 / 134)
    from aiomqtt.exceptions import MqttConnectError

    class MockClientReject:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise MqttConnectError(5)

        async def __aexit__(self, *args):
            pass

    with (
        patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)),
        patch("custom_components.vidaa.protocol.ping.async_test_tv_ssl_connection", return_value=ssl_info),
        patch("custom_components.vidaa.protocol.ping.build_mqtt_ssl_context"),
        patch("aiomqtt.Client", MockClientReject),
        patch("custom_components.vidaa.protocol.ping.extract_connect_rc", return_value=5),
    ):
        res = await async_ping_tv("192.168.1.50", client_id="cid", username="user", password="pwd")
        assert res["mqtt_connected"] is False
        assert "Rejected: Bad username or password" in res["mqtt_status"]

    # 3. Custom upnp client passed in
    mock_upnp = MagicMock()
    mock_upnp.async_get_device_fingerprint = AsyncMock(return_value={"model": "TestTV"})
    mock_upnp.close = AsyncMock()

    with (
        patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)),
        patch("custom_components.vidaa.protocol.ping.async_test_tv_ssl_connection", return_value=ssl_info),
    ):
        res = await async_ping_tv("192.168.1.50", upnp=mock_upnp)
        assert res["device_info"] == {"model": "TestTV"}
        mock_upnp.close.assert_awaited_once()


def test_ping_tv_sync_wrapper():
    """Test synchronous ping_tv wrapper."""
    with patch("custom_components.vidaa.protocol.ping.async_ping_tv", AsyncMock(return_value={"tcp_port_open": True})):
        res = ping_tv("192.168.1.50")
        assert res["tcp_port_open"] is True
