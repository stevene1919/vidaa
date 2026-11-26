"""Coverage tests for tv/navigation.py, tv/state.py, tv/callbacks.py, tv/probe.py, and sensor/__init__.py."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.vidaa.client import VidaaClient
from custom_components.vidaa.sensor import (
    VidaaActiveAppSensor,
    VidaaActiveSourceSensor,
    VidaaMqttTrackingSensor,
    _format_input_app_label,
)
from custom_components.vidaa.tv.callbacks import CallbackRegistryMixin
from custom_components.vidaa.tv.navigation import (
    _is_hardware_source,
    cycle_tv_source,
    get_next_cycled_source,
    launch_app_by_name,
    match_app,
    resolve_canonical_app,
    resolve_source,
)
from custom_components.vidaa.tv.probe import (
    FeatureProbeResult,
    generate_markdown_report,
    load_credentials_file,
    probe_tv_features,
)
from custom_components.vidaa.tv.settings import SettingMenuItem
from custom_components.vidaa.tv.state import (
    apply_device_info_update,
    apply_picture_update,
    apply_state_update,
    apply_volume_update,
)


def test_tv_navigation_and_state_coverage() -> None:
    """Cover tv/navigation.py and tv/state.py remaining branches."""
    apps = [
        "not-a-dict",
        {"appId": "nf", "name": "Netflix", "url": "https://netflix.com"},
        {"appId": "yt_1", "name": "YouTube TV", "url": "https://yt.com"},
    ]
    assert resolve_canonical_app(None, apps, app_id="nf") == ("Netflix", "nf")  # type: ignore[arg-type]
    assert resolve_canonical_app("Custom", apps, url="https://yt.com") == ("YouTube TV", "yt_1")  # type: ignore[arg-type]
    assert resolve_canonical_app("UnknownApp", apps) == ("UnknownApp", None)  # type: ignore[arg-type]

    assert match_app(apps, "youtube-tv") is not None  # type: ignore[arg-type]
    assert match_app(apps, "tube") is not None  # type: ignore[arg-type]

    assert resolve_source([], "") == ("", None)
    assert resolve_source([{"sourceid": "dtv", "sourcename": "Antenna"}], "live tv") == ("dtv", "Antenna")
    assert resolve_source([], "live tv") == ("TV", "TV")
    assert resolve_source([], "HDMI 9") == ("HDMI 9", None)

    assert _is_hardware_source({"sourcename": "AVS"}) is True
    assert get_next_cycled_source(["bad"], "HDMI 1") is None  # type: ignore[list-item]
    assert get_next_cycled_source(
        [{"sourceid": "dtv", "sourcename": "DTV"}, {"sourceid": "hdmi1", "sourcename": "HDMI 1"}],
        "live tv",
    ) == ("hdmi1", "HDMI 1")

    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    client.launch_app = MagicMock()
    client.apps = []
    assert launch_app_by_name(client, "Plex") is True
    client.launch_app.assert_called_once_with("", "Plex", "Plex")
    client.sources = []
    assert cycle_tv_source(client) is False

    # tv/state.py
    apply_state_update(client, "not-a-dict")
    client.sources = ["bad", {"sourcename": "HDMI 1", "is_signal": "1", "is_active": True}]
    apply_state_update(client, {"statetype": "fake_sleep_0"})
    assert client.sources[1]["is_active"] is False

    apply_state_update(client, {"statetype": "screensaver"})
    assert client.state == "screensaver"

    client.current_app = None
    client.current_app_id = None
    apply_state_update(
        client,
        {
            "statetype": "playing",
            "appname": "Disney+",
            "appid": 99,
            "program_title": "Movie",
            "audio_output": "ARC",
            "hdr_mode": "HDR10",
            "audio_format": "Dolby",
            "devicename": "Living Room TV",
            "sleep_time": "30",
        },
    )
    assert client.current_app == "Disney+"
    assert client.current_app_id == "99"
    assert client.current_program == "Movie"
    assert client.audio_output_mode == "ARC"
    assert client.hdr_mode == "HDR10"
    assert client.audio_format == "Dolby"
    assert client.device_name == "Living Room TV"
    assert client.sleep_timer == 30

    apply_device_info_update(client, "bad")
    apply_device_info_update(client, {"devicename": "Updated TV"})
    assert client.device_name == "Updated TV"

    apply_volume_update(client, "bad")
    apply_volume_update(client, {"volume": 42, "is_mute": 1})
    assert client.volume == 42 and client.muted is True
    apply_volume_update(client, {"muted": False})
    assert client.muted is False
    apply_volume_update(client, {"volume_type": 2, "is_mute": 1})
    assert client.muted is True
    apply_volume_update(client, {"volume_type": 2, "muted": False})
    assert client.muted is False

    # List-backed picture_settings upsert + brightness/contrast fields
    client.picture_settings = [SettingMenuItem(menu_id=10, name="Menu_10", value=1)]  # type: ignore[assignment]
    apply_picture_update(
        client,
        {
            "menu_info": [
                {
                    "menu_id": 10,
                    "menu_name": "Brightness",
                    "menu_value": 55,
                    "menu_min": 0,
                    "menu_max": 100,
                    "menu_step": 1,
                    "menu_options": ["0", "55"],
                },
                {"menu_id": 11, "menu_name": "Contrast", "menu_value": 70},
            ]
        },
    )
    assert client.brightness == 55
    assert client.contrast == 70


def test_tv_callbacks_and_probe_coverage(tmp_path) -> None:
    """Cover tv/callbacks.py and tv/probe.py remaining branches."""

    class _Host(CallbackRegistryMixin):
        def __init__(self) -> None:
            self.is_on = True
            self.current_source = "HDMI 1"
            self.sources: list = []
            self.apps: list = []

    host = _Host()
    host._dispatch("state", {})  # before _init_callbacks
    cb = MagicMock()
    for reg, unreg in (
        (host.register_volume_callback, host.unregister_volume_callback),
        (host.register_sourcelist_callback, host.unregister_sourcelist_callback),
        (host.register_applist_callback, host.unregister_applist_callback),
        (host.register_token_refreshed_callback, host.unregister_token_refreshed_callback),
        (host.register_auth_failed_callback, host.unregister_auth_failed_callback),
        (host.register_picture_callback, host.unregister_picture_callback),
        (host.register_sound_callback, host.unregister_sound_callback),
        (host.register_hotel_mode_callback, host.unregister_hotel_mode_callback),
        (host.register_raw_message_callback, host.unregister_raw_message_callback),
        (host.register_device_info_callback, host.unregister_device_info_callback),
        (host.register_clock_drift_callback, host.unregister_clock_drift_callback),
    ):
        reg(cb)
        unreg(cb)

    # Transition is_on True -> False on device_info update
    with patch(
        "custom_components.vidaa.tv.callbacks.apply_device_info_update",
        side_effect=lambda c, _d: setattr(c, "is_on", False),
    ):
        state_cb = MagicMock()
        host.register_state_callback(state_cb)
        host._dispatch_device_info_update({})
        state_cb.assert_called_with({"statetype": "fake_sleep_0"})

    host._dispatch_sourcelist_update([{"sourcename": "HDMI 1", "hotel_mode": "1"}])
    assert host.hotel_mode is True
    host._dispatch_applist_update({"applist": [{"name": "YT", "appId": "yt"}]})
    host._dispatch_picture_update({})
    host._dispatch_sound_update({})

    # tv/probe.py
    assert load_credentials_file(str(tmp_path / "nonexistent_creds.json")) == {}
    bad_json = tmp_path / "bad_creds.json"
    bad_json.write_text("{bad")
    assert load_credentials_file(str(bad_json)) == {}

    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    client.connected = False
    client.connect_and_run = MagicMock(side_effect=lambda: setattr(client, "connected", True))
    client.query_initial_state = MagicMock()
    client.get_picture_settings = MagicMock()
    client.get_sound_settings = MagicMock()
    client.disconnect = MagicMock()

    with (
        patch("custom_components.vidaa.tv.probe.time.sleep"),
        patch(
            "custom_components.vidaa.protocol.discovery.probe_udp_port",
            return_value={"name": "TV", "model": "U7", "mac": "e8:51:77:aa:bb:cc"},
        ),
    ):
        probe_res = probe_tv_features(client, wait_time=0.0)
    assert probe_res.connected is True
    client.disconnect.assert_called_once()

    # Fire registered callbacks directly
    client._dispatch("state", {"s": 1})
    client._dispatch("volume", {"v": 10})
    client._dispatch("sourcelist", [{"sourcename": "HDMI 1"}])
    client._dispatch("applist", [{"name": "YT"}])
    client._dispatch("picture", {"p": 1})
    client._dispatch("sound", {"snd": 1})

    # Not connected early return
    dead_client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    dead_client.connected = False
    dead_client.connect_and_run = MagicMock()
    with patch("custom_components.vidaa.tv.probe.time.sleep"):
        assert probe_tv_features(dead_client).connected is False

    # generate_markdown_report branches
    now_ts = int(datetime.datetime.now(datetime.UTC).timestamp())
    report = generate_markdown_report(
        ip="192.168.1.100",
        ping_result={
            "tcp_port_open": True,
            "tls_handshake": True,
            "client_cert_presented": True,
            "mqtt_rc": 5,
            "mqtt_connected": False,
            "device_info": {
                "model_code": "55U7",
                "model_number": "U7H",
                "mac_wifi": "e8:51:77:aa:bb:cc",
                "mac_ethernet": "E8:51:77:AA:BB:DD",
                "tv_timestamp": now_ts,
            },
            "auth_probe": {
                "legacy_static": {"rc": 5, "supported": False},
                "standard_dynamic": {"rc": 5, "supported": False},
                "middle_dynamic": {"rc": 5, "supported": False},
                "modern_dynamic": {"rc": 5, "supported": False},
            },
        },
        probe_result=FeatureProbeResult(connected=True, udp_discovery=None, hotel_mode=False),
        mac="e8:51:77:aa:bb:cc",
    )
    assert "Stored Credentials Auth" in report and "Hotel Mode:** Inactive" in report


def test_sensor_init_coverage() -> None:
    """Cover sensor/__init__.py remaining branches."""
    assert _format_input_app_label("TV") == "Live TV"
    assert _format_input_app_label("Custom") == "TV Input"

    client = VidaaClient("192.168.1.100", "e8:51:77:aa:bb:cc")
    entry = SimpleNamespace(
        entry_id="s1",
        title="VIDAA TV",
        data={"mac_address": "e8:51:77:aa:bb:cc"},
        options={},
        runtime_data=SimpleNamespace(client=client, artwork_tracker=None),
    )

    client.connected = False
    client.state = "off"
    base_off = VidaaMqttTrackingSensor(client, entry, default_on="On", default_off="Off")
    assert base_off.native_value == "Off"
    base_off._register_custom_callbacks()
    base_off._unregister_custom_callbacks()
    base_off.hass = None
    base_off._handle_connected()
    assert base_off.native_value == "Standby"

    client.connected = True
    client.state = "off"
    base_stby = VidaaMqttTrackingSensor(client, entry, default_on="On", default_off="Off")
    assert base_stby.native_value == "Standby"

    app_sensor = VidaaActiveAppSensor(client, entry)
    app_sensor.hass = None
    client.connected = False
    app_sensor._sync_from_client()
    assert app_sensor.native_value == "Off"

    client.connected = True
    client.state = "on"
    client.current_app = None
    client.current_source = "TV"
    app_sensor._sync_from_client()
    assert app_sensor.native_value == "Live TV"

    app_sensor._attr_native_value = "Standby"
    app_sensor._handle_sourcelist_update([{"sourcename": "TV", "is_signal": "1"}])
    assert app_sensor.native_value == "Live TV"

    app_sensor._handle_state_update("not-a-dict")  # type: ignore[arg-type]
    client.connected = False
    app_sensor._handle_state_update({"statetype": "playing"})
    assert app_sensor.native_value == "Off"

    client.connected = True
    client.state = "on"
    app_sensor._handle_state_update({"statetype": "sourceswitch", "sourcename": "TV"})
    assert app_sensor.native_value == "Live TV"

    src_sensor = VidaaActiveSourceSensor(client, entry)
    src_sensor.hass = None
    client.connected = False
    src_sensor._sync_from_client()
    assert src_sensor.native_value == "Off"
    client.connected = True
    client.state = "off"
    src_sensor._sync_from_client()
    assert src_sensor.native_value == "Standby"
    client.connected = False
    src_sensor._handle_state_update({"statetype": "sourceswitch"})
    assert src_sensor.native_value == "Off"
