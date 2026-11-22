"""Tests for UPnP, DLNA, and ARP device fingerprinting in tv/fingerprint.py."""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

from custom_components.vidaa.tv.fingerprint import (
    format_drift_human,
    get_arp_mac,
    get_tv_timestamp,
    probe_upnp_services,
)


def test_format_drift_human():
    assert format_drift_human(0) == "0s"
    assert format_drift_human(5) == "+5s"
    assert format_drift_human(-10) == "-10s"
    assert format_drift_human(90061) == "+1d 1h 1m 1s"
    assert format_drift_human(-3661) == "-1h 1m 1s"


def test_get_tv_timestamp():
    # Success via Date header
    mock_resp = MagicMock()
    mock_resp.headers = {"Date": "Sun, 06 Nov 1994 08:49:37 GMT"}
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        ts = get_tv_timestamp("192.168.1.50")
        assert ts == 784111777

    # Failure / no responding port
    with patch("urllib.request.urlopen", side_effect=Exception("Timeout")):
        assert get_tv_timestamp("192.168.1.50") is None


def test_get_arp_mac():
    import sys

    # 1. getmac success
    mock_getmac = MagicMock()
    mock_getmac.get_mac_address.return_value = "AA:BB:CC:DD:EE:FF"
    with patch.dict(sys.modules, {"getmac": mock_getmac}):
        assert get_arp_mac("192.168.1.50") == "aa:bb:cc:dd:ee:ff"

    # 2. /proc/net/arp fallback
    proc_arp_content = (
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.50     0x1         0x2         11:22:33:44:55:66     *        eth0\n"
    )
    with (
        patch.dict(sys.modules, {"getmac": None}),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=proc_arp_content)),
    ):
        assert get_arp_mac("192.168.1.50") == "11:22:33:44:55:66"


def test_probe_upnp_services_not_responding():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res = probe_upnp_services("192.168.1.50", verbose=False)
        assert res["active_port"] is None


def test_probe_upnp_services_responding():
    desc_xml = (
        '<?xml version="1.0"?>'
        '<root xmlns="urn:schemas-upnp-org:device-1-0">'
        "<device>"
        "<friendlyName>Hisense 65U7G</friendlyName>"
        "</device>"
        "</root>"
    )
    get_vol_resp = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        "<s:Body>"
        "<u:GetVolumeResponse><CurrentVolume>25</CurrentVolume></u:GetVolumeResponse>"
        "</s:Body></s:Envelope>"
    )
    get_mute_resp = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        "<s:Body>"
        "<u:GetMuteResponse><CurrentMute>0</CurrentMute></u:GetMuteResponse>"
        "</s:Body></s:Envelope>"
    )
    get_trans_resp = (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
        "<s:Body>"
        "<u:GetTransportInfoResponse><CurrentTransportState>PLAYING</CurrentTransportState><CurrentTransportStatus>OK</CurrentTransportStatus></u:GetTransportInfoResponse>"
        "</s:Body></s:Envelope>"
    )

    def mock_urlopen(req, *args, **kwargs):
        resp = MagicMock()
        resp.status = 200
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "rendererdevicedesc.xml" in url:
            resp.read.return_value = desc_xml.encode("utf-8")
        elif "mingusrcr" in url:
            data = req.data.decode("utf-8")
            if "GetVolume" in data:
                resp.read.return_value = get_vol_resp.encode("utf-8")
            else:
                resp.read.return_value = get_mute_resp.encode("utf-8")
        elif "mingusavtr" in url:
            resp.read.return_value = get_trans_resp.encode("utf-8")
        elif "hisense_lan_control" in url:
            resp.read.return_value = b"<LanControlResponse>OK</LanControlResponse>"
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = probe_upnp_services("192.168.1.50", verbose=False)
        assert res["active_port"] in (38400, 18400)
        assert res["friendly_name"] == "Hisense 65U7G"
        assert res["volume"] == 25
        assert res["muted"] is False
        assert res["transport_state"] == "PLAYING"


def test_query_upnp_descriptor():
    from custom_components.vidaa.tv.fingerprint import query_upnp_descriptor

    desc_xml = (
        '<?xml version="1.0"?>'
        '<root xmlns="urn:schemas-upnp-org:device-1-0">'
        "<device>"
        "<friendlyName>Hisense 65U7G</friendlyName>"
        "<modelName>65U7G</modelName>"
        "<modelNumber>HE65U7G</modelNumber>"
        "<manufacturer>Hisense</manufacturer>"
        "</device>"
        "</root>"
    )

    mock_resp = MagicMock()
    mock_resp.headers = {"Date": "Sun, 06 Nov 1994 08:49:37 GMT"}
    mock_resp.read.return_value = desc_xml.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = query_upnp_descriptor("192.168.1.50")
        assert info["friendly_name"] == "Hisense 65U7G"
        assert info["model_name"] == "65U7G"
        assert info["tv_timestamp"] == 784111777

    # Failure handling
    with patch("urllib.request.urlopen", side_effect=Exception("Failed")):
        info_fail = query_upnp_descriptor("192.168.1.50")
        assert info_fail["model_name"] is None


def test_query_mdns_fingerprint():
    from custom_components.vidaa.tv.fingerprint import query_mdns_fingerprint

    # 1. zc is None
    res = query_mdns_fingerprint("192.168.1.50", zc=None)
    assert res["model_code"] is None

    # 2. zc with mock service browser
    mock_zc = MagicMock()
    s_info = MagicMock()
    import socket

    s_info.addresses = [socket.inet_aton("192.168.1.50")]
    s_info.properties = {
        b"model": b"Hisense_65U7G",
        b"fv": b"V1.0",
        b"serialNumber": b"123456",
        b"company": b"Hisense",
    }
    mock_zc.get_service_info.return_value = s_info

    class MockBrowser:
        def __init__(self, zc, types, listener):
            for t in types:
                listener.add_service(zc, t, "Hisense Smart TV")

        def cancel(self):
            pass

    with (
        patch("zeroconf.ServiceBrowser", MockBrowser),
        patch("time.sleep"),
    ):
        info = query_mdns_fingerprint("192.168.1.50", zc=mock_zc)
        assert info["model_code"] == "Hisense_65U7G"
        assert info["firmware_version"] == "V1.0"
        assert info["serial_number"] == "123456"
        assert info["manufacturer"] == "Hisense"


def test_get_device_fingerprint():
    from custom_components.vidaa.tv.fingerprint import get_device_fingerprint

    upnp_res = {"friendly_name": "Hisense TV", "model_name": "65U7G"}
    mdns_res = {"model_code": "65U7G", "firmware_version": "V2.0", "serial_number": "SN123", "manufacturer": "Hisense"}

    with (
        patch("custom_components.vidaa.tv.fingerprint.query_upnp_descriptor", return_value=upnp_res),
        patch("custom_components.vidaa.tv.fingerprint.query_mdns_fingerprint", return_value=mdns_res),
    ):
        fp = get_device_fingerprint("192.168.1.50")
        assert fp["friendly_name"] == "Hisense TV"
        assert fp["model_name"] == "65U7G"
        assert fp["model_code"] == "65U7G"
        assert fp["firmware_version"] == "V2.0"
        assert fp["serial_number"] == "SN123"
        assert fp["manufacturer"] == "Hisense"
