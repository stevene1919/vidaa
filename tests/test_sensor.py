"""Tests for VIDAA Smart TV sensor platform."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.vidaa.sensor import (
    HisenseVidaaActiveAppSensor,
    HisenseVidaaActiveSourceSensor,
    HisenseVidaaClockDriftSensor,
    HisenseVidaaReportedNameSensor,
    HisenseVidaaSessionStatusSensor,
    VidaaActiveAppSensor,
    VidaaActiveSourceSensor,
    VidaaClockDriftSensor,
    VidaaReportedNameSensor,
    VidaaSessionStatusSensor,
    async_setup_entry as async_setup_sensors,
)


def test_sensor_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* sensor classes are aliases for Vidaa* sensor classes."""
    assert HisenseVidaaSessionStatusSensor is VidaaSessionStatusSensor
    assert HisenseVidaaActiveAppSensor is VidaaActiveAppSensor
    assert HisenseVidaaActiveSourceSensor is VidaaActiveSourceSensor
    assert HisenseVidaaReportedNameSensor is VidaaReportedNameSensor
    assert HisenseVidaaClockDriftSensor is VidaaClockDriftSensor


@pytest.mark.anyio
async def test_sensor_entities(mock_client, mock_entry):
    """Test operational and diagnostic sensor entities."""
    s_status = VidaaSessionStatusSensor(mock_client, mock_entry)
    s_status._update_state()
    assert s_status.native_value == "Active"
    assert s_status.extra_state_attributes["encryption"] == "TLSv1.2 (Port 36669)"
    assert s_status.extra_state_attributes["local_only"] is True
    assert "paired_at" in s_status.extra_state_attributes
    assert "access_token_expires_at" in s_status.extra_state_attributes
    assert "refresh_token_expires_at" in s_status.extra_state_attributes

    mock_client.connected = False
    s_status._update_state()
    assert s_status.native_value == "Standby"

    s_status._handle_auth_failed(mock_client)
    assert s_status.native_value == "Reauth Required"

    mock_client.connected = True
    assert s_status.extra_state_attributes["configured_auth_profile"] == "VIDAA 2.0 (Newer Firmware / 2024+)"

    s_app = VidaaActiveAppSensor(mock_client, mock_entry)
    s_app._handle_applist_update([{"appId": "123", "appName": "Netflix"}])
    s_app._handle_state_update({"appId": "123"})
    assert s_app.native_value == "Netflix"

    s_source = VidaaActiveSourceSensor(mock_client, mock_entry)
    s_source._handle_sourcelist_update(
        [
            {"sourceName": "TV", "has_signal": 0, "is_active": False},
            {"sourceName": "VIDAA tv", "has_signal": 1, "is_active": False},
            {"sourceName": "HDMI 1", "displayname2": "Chromecast", "has_signal": 1, "is_active": True},
            {"sourceName": "HDMI 2", "has_signal": 1, "is_active": False},
        ]
    )
    assert s_source.native_value == "HDMI 1"
    assert "raw_source" not in s_source.extra_state_attributes
    assert "custom_labels" not in s_source.extra_state_attributes
    assert s_source.extra_state_attributes["connected_device"] == "Chromecast"
    assert s_source.extra_state_attributes["display_name"] == "HDMI 1 (Chromecast)"
    assert s_source.extra_state_attributes["available_sources"] == ["TV", "HDMI 1", "HDMI 2"]
    assert s_source.extra_state_attributes["connected_inputs"] == ["HDMI 1", "HDMI 2"]
    assert "VIDAA tv" not in s_source.extra_state_attributes["available_sources"]
    assert "VIDAA tv" not in s_source.extra_state_attributes["connected_inputs"]

    s_source._handle_state_update(
        {
            "statetype": "sourceswitch",
            "sourcename": "HDMI 1",
            "displayname2": "PlayStation 5",
        }
    )
    assert s_source.native_value == "HDMI 1"
    assert s_source.extra_state_attributes["connected_device"] == "PlayStation 5"
    assert s_source.extra_state_attributes["display_name"] == "HDMI 1 (PlayStation 5)"

    s_source._handle_state_update(
        {
            "statetype": "livetv",
            "channel_name": "ABC HD",
            "channel_num": "20",
        }
    )
    assert s_source.native_value == "TV"
    assert "channel_name" not in s_source.extra_state_attributes
    assert "channel_num" not in s_source.extra_state_attributes

    s_name = VidaaReportedNameSensor(mock_client, mock_entry)
    assert s_name.native_value == "Living Room TV"
    mock_client.device_name = "Bedroom VIDAA TV"
    s_name._handle_device_info({"friendly_name": "Bedroom VIDAA TV"})
    assert s_name.native_value == "Bedroom VIDAA TV"
    assert s_name.extra_state_attributes["ip_address"] == "192.168.1.100"
    assert s_name.extra_state_attributes["mac_address"] == "e8:51:77:aa:bb:cc"

    # Test Clock Drift Sensor
    s_drift = VidaaClockDriftSensor(mock_client, mock_entry)
    assert s_drift.native_value == 0
    assert s_drift._attr_icon == "mdi:clock-check-outline"
    assert s_drift.extra_state_attributes["synchronized"] is True
    assert s_drift.extra_state_attributes["drift_human"] == "0s"

    # Negative drift (e.g. TV clock behind host by ~6 days)
    mock_client.clock_offset = -516360
    s_drift._update_state()
    assert s_drift.native_value == -516360
    assert s_drift._attr_icon == "mdi:clock-alert-outline"
    assert s_drift.extra_state_attributes["synchronized"] is False
    assert "-5d" in s_drift.extra_state_attributes["drift_human"]

    # Positive drift (e.g. TV clock ahead of host by > 1 hour)
    mock_client.clock_offset = 3665
    s_drift._update_state()
    assert s_drift.native_value == 3665
    assert s_drift._attr_icon == "mdi:clock-alert-outline"
    assert s_drift.extra_state_attributes["synchronized"] is False
    assert "+1h" in s_drift.extra_state_attributes["drift_human"]

    # Small drift within tolerance (+45 seconds)
    mock_client.clock_offset = 45
    s_drift._update_state()
    assert s_drift.native_value == 45
    assert s_drift._attr_icon == "mdi:clock-check-outline"
    assert s_drift.extra_state_attributes["synchronized"] is True
    assert "+45s" in s_drift.extra_state_attributes["drift_human"]

    # None / unknown clock offset
    mock_client.clock_offset = None
    s_drift._update_state()
    assert s_drift.native_value is None
    assert s_drift._attr_icon == "mdi:clock-outline"
    assert s_drift.extra_state_attributes["synchronized"] is False
    assert s_drift.extra_state_attributes["drift_human"] == "Unknown"


def test_session_status_auth_and_brand_profile_attributes(mock_client, mock_entry):
    """Test SessionStatusSensor exposes configured_auth_profile, brand_profile, and active_brand."""
    from custom_components.vidaa.const import AUTH_PROFILES, BRAND_PROFILES

    mock_entry.data = {**mock_entry.data, "auth_profile": "modern", "brand": "his", "brand_profile": "auto"}
    mock_entry.options = {**mock_entry.options, "auth_profile": "legacy"}
    mock_client.brand = "his"

    sensor = VidaaSessionStatusSensor(mock_client, mock_entry)
    attrs = sensor.extra_state_attributes
    assert attrs["configured_auth_profile"] == AUTH_PROFILES["legacy"]
    assert attrs["brand_profile"] == BRAND_PROFILES["auto"]
    assert attrs["active_brand"] == "Hisense"

    # Falls back to entry.data when options don't override the profile, and respects explicit brand override
    mock_entry.options = {"brand": "tpo"}
    mock_client.brand = "tpo"
    sensor_tpo = VidaaSessionStatusSensor(mock_client, mock_entry)
    attrs_tpo = sensor_tpo.extra_state_attributes
    assert attrs_tpo["configured_auth_profile"] == AUTH_PROFILES["modern"]
    assert attrs_tpo["brand_profile"] == BRAND_PROFILES["tpo"]
    assert attrs_tpo["active_brand"] == "TOPTRO"


def test_session_status_latches_reauth_required(mock_client, mock_entry):
    """[F8-leg4] "Reauth Required" survives a disconnect until a successful connect."""
    mock_client.connected = True
    sensor = VidaaSessionStatusSensor(mock_client, mock_entry)
    assert sensor.native_value == "Active"

    sensor._handle_auth_failed(mock_client)
    assert sensor.native_value == "Reauth Required"

    # A subsequent disconnect must NOT overwrite the latch.
    mock_client.connected = False
    sensor._handle_disconnected()
    assert sensor.native_value == "Reauth Required"

    # A successful reconnect clears the latch.
    mock_client.connected = True
    sensor._handle_connected()
    assert sensor.native_value == "Active"


def test_session_status_sensor_masks_client_id_and_applies_offset():
    """SessionStatusSensor masks client_id and applies clock_offset."""
    client = MagicMock()
    client.connected = True
    client.use_ssl = True
    client.auth_profile = "modern"
    client.client_id = "E85177AABBCC$his$123456_vidaacommon_001"
    client.clock_offset = 3600
    client.access_token_time = 1700000000
    client.access_token_duration = 2
    client.refresh_token_time = 1700000000
    client.refresh_token_duration = 60

    entry = MagicMock()
    entry.entry_id = "test_entry"

    sensor = VidaaSessionStatusSensor(client, entry)
    attrs = sensor.extra_state_attributes

    # client_id is masked
    assert attrs["client_id"] == "E85177AA..._001"
    assert "paired_at" in attrs
    assert "access_token_expires_at" in attrs


@pytest.mark.anyio
async def test_sensor_setup_entry_excludes_retired_sensors(mock_client, mock_entry):
    """Verify async_setup_entry for sensor platform does not add retired diagnostic entities."""
    hass = MagicMock(spec=HomeAssistant)
    added_sensors = []
    await async_setup_sensors(hass, mock_entry, lambda entities: added_sensors.extend(entities))

    assert len(added_sensors) == 5
    unique_ids = [s.unique_id for s in added_sensors]
    assert f"{mock_entry.entry_id}_audio_output" not in unique_ids
    assert f"{mock_entry.entry_id}_brand_profile" not in unique_ids
    assert f"{mock_entry.entry_id}_auth_profile" not in unique_ids
    assert any(isinstance(s, VidaaActiveSourceSensor) for s in added_sensors)
    assert any(isinstance(s, VidaaActiveAppSensor) for s in added_sensors)


def test_active_source_standby_and_last_known_source(mock_client, mock_entry):
    """Test active source transitions to Standby when asleep and preserves last_known_source."""
    mock_client.connected = True
    mock_client.is_on = True
    sensor = VidaaActiveSourceSensor(mock_client, mock_entry)

    # Active HDMI input while on
    sensor._handle_sourcelist_update([{"sourceName": "HDMI 2", "is_active": True}])
    assert sensor.native_value == "HDMI 2"
    assert sensor.extra_state_attributes["last_known_source"] == "HDMI 2"

    # TV enters standby (fake_sleep_0 or is_on=False)
    mock_client.is_on = False
    sensor._handle_state_update({"statetype": "fake_sleep_0"})
    assert sensor.native_value == "Standby"
    assert sensor.extra_state_attributes["last_known_source"] == "HDMI 2"

    # Sourcelist arrives while in standby: updates last_known_source but does NOT wake sensor
    sensor._handle_sourcelist_update([{"sourceName": "HDMI 1", "is_active": True}])
    assert sensor.native_value == "Standby"
    assert sensor.extra_state_attributes["last_known_source"] == "HDMI 1"

    # Disconnected
    mock_client.connected = False
    sensor._handle_disconnected()
    assert sensor.native_value == "Off"
    assert sensor.extra_state_attributes["last_known_source"] == "HDMI 1"


def test_active_app_standby_and_last_known_app(mock_client, mock_entry):
    """Test active app transitions to Standby/Off and preserves last_known_app."""
    mock_client.connected = True
    mock_client.is_on = True
    sensor = VidaaActiveAppSensor(mock_client, mock_entry)

    sensor._handle_applist_update([{"appId": "netflix_app", "appName": "Netflix"}])
    sensor._handle_state_update({"statetype": "app", "appId": "netflix_app"})
    assert sensor.native_value == "Netflix"
    assert sensor.extra_state_attributes["last_known_app"] == "Netflix"

    # Standby
    mock_client.is_on = False
    sensor._handle_state_update({"statetype": "fake_sleep_0"})
    assert sensor.native_value == "Standby"
    assert sensor.extra_state_attributes["last_known_app"] == "Netflix"

    # Disconnected
    mock_client.connected = False
    sensor._handle_disconnected()
    assert sensor.native_value == "Off"
    assert sensor.extra_state_attributes["last_known_app"] == "Netflix"


def test_active_app_and_source_remote_launcher_transition(mock_client, mock_entry):
    """Test Active App and Source sensors correctly handle remote_launcher broadcast (Issue #58)."""
    mock_client.connected = True
    mock_client.is_on = True
    app_sensor = VidaaActiveAppSensor(mock_client, mock_entry)
    source_sensor = VidaaActiveSourceSensor(mock_client, mock_entry)

    app_sensor._handle_applist_update(
        [
            {"appId": "1", "appName": "netflix"},
            {"appId": "3", "appName": "youtube"},
        ]
    )
    # Enter Netflix
    app_sensor._handle_state_update({"statetype": "app", "name": "netflix", "url": "netflix", "appId": "1"})
    assert app_sensor.native_value == "netflix"

    # Return to Home Screen via remote_launcher
    app_sensor._handle_state_update({"statetype": "remote_launcher"})
    assert app_sensor.native_value == "Home Launcher"
    assert app_sensor.extra_state_attributes["last_known_app"] == "Home Launcher"

    # Active source sensor on remote_launcher and app transitions
    source_sensor._handle_state_update({"statetype": "remote_launcher"})
    assert source_sensor.native_value == "Home Launcher"
    assert source_sensor.icon == "mdi:view-dashboard"

    source_sensor._handle_state_update({"statetype": "app", "name": "youtube", "appId": "3"})
    assert source_sensor.native_value == "App"
    assert source_sensor.icon == "mdi:application"

    # Enter YouTube
    app_sensor._handle_state_update({"statetype": "app", "name": "youtube", "url": "youtube", "appId": "3"})
    assert app_sensor.native_value == "youtube"


def test_sensor_disabled_by_default(mock_client, mock_entry):
    """Verify specialized diagnostic sensors are disabled by default."""
    s_drift = VidaaClockDriftSensor(mock_client, mock_entry)
    assert s_drift.entity_registry_enabled_default is False

    s_name = VidaaReportedNameSensor(mock_client, mock_entry)
    assert s_name.entity_registry_enabled_default is False


@pytest.mark.anyio
async def test_sensors_hydrate_from_cached_client_state_on_startup(mock_entry):
    """Active App, Active Source, and Session Status hydrate from telemetry received before platform setup."""
    from custom_components.vidaa.client import VidaaClient

    client = VidaaClient(ip="192.168.50.12", mac="e8:51:77:ec:98:1c", client_id="cid")
    client.connected = True
    client.is_on = True
    client._dispatch_applist_update(
        [
            {"appId": "1", "name": "Netflix", "isFav": True, "httpIcon": "iconDownloadhttps://example.com/nf.png"},
            {"appId": "3", "name": "YouTube", "isFav": False},
        ]
    )
    client._dispatch_sourcelist_update(
        [
            {"sourceid": "TV", "sourcename": "TV", "is_signal": "0", "has_signal": "0"},
            {
                "sourceid": "HDMI1",
                "sourcename": "HDMI1",
                "displayname2": "Chromecast",
                "is_signal": "0",
                "has_signal": "1",
            },
            {"sourceid": "HDMI2", "sourcename": "HDMI2", "is_signal": "1", "has_signal": "1"},
        ]
    )

    # Sensors instantiated AFTER MQTT telemetry already arrived
    app_sensor = VidaaActiveAppSensor(client, mock_entry)
    source_sensor = VidaaActiveSourceSensor(client, mock_entry)

    assert app_sensor.native_value == "HDMI Input"
    assert app_sensor.icon == "mdi:video-input-hdmi"
    assert app_sensor.extra_state_attributes["total_installed_apps"] == 2

    assert source_sensor.native_value == "HDMI2"
    assert source_sensor.extra_state_attributes["available_sources"] == ["TV", "HDMI1", "HDMI2"]
    assert source_sensor.extra_state_attributes["connected_inputs"] == ["HDMI1", "HDMI2"]
    assert source_sensor.extra_state_attributes["last_known_source"] == "HDMI2"

    # Also verify app-state with lowercase TV broadcast ("netflix", no appId) resolves to canonical "Netflix" + artwork
    client._dispatch_state_update({"statetype": "app", "name": "netflix", "url": "netflix"})
    await app_sensor.async_added_to_hass()
    await source_sensor.async_added_to_hass()
    assert client.current_app == "Netflix"
    assert client.current_app_id == "1"
    assert app_sensor.native_value == "Netflix"
    assert app_sensor.entity_picture == "https://example.com/nf.png"
    assert source_sensor.native_value == "App"

    # Verify sourceswitch with sourceid-only payload resolves friendly name and input label
    client._dispatch_state_update({"statetype": "sourceswitch", "sourceid": "HDMI1"})
    assert source_sensor.native_value == "HDMI1"
    assert source_sensor.extra_state_attributes["connected_device"] == "Chromecast"
    assert app_sensor.native_value == "HDMI Input"

    # Verify AV physical input reports AV Input with component icon
    client._dispatch_state_update({"statetype": "sourceswitch", "sourceid": "AVS", "sourcename": "AV"})
    assert app_sensor.native_value == "AV Input"
    assert app_sensor.icon == "mdi:video-input-component"

    # Verify SessionStatusSensor hydrates pre-existing auth_failed=True on init
    client.connected = False
    client.auth_failed = True
    status_sensor = VidaaSessionStatusSensor(client, mock_entry)
    assert status_sensor.native_value == "Reauth Required"
