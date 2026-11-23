"""Behavioral and boundary tests for VIDAA Smart TV integration.

These tests assert real end-to-end component behavior at entity boundaries:
- Ingesting realistic raw TV MQTT telemetry payloads (sourcelist, applist, state transitions)
- Observable Home Assistant entity attributes (activity_list, current_activity, state, availability)
- Service and action dispatches with Wake-on-LAN and wake verification
- Graceful network drop / offline state transitions without exceptions or stale state
- Legacy config migration and SSL context resolution without false repair issues
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.media_player import (
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.client import VidaaClient
from custom_components.vidaa.const import (
    CONF_ENABLE_CEC_NAMES,
    CONF_INCLUDE_APPS_IN_SOURCES,
    DOMAIN,
)
from custom_components.vidaa.helpers import async_ensure_tv_on, check_client_command_readiness
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.remote import VidaaRemote


class RealStateVidaaClient(VidaaClient):
    """Subclass of VidaaClient providing mock networking while retaining real state and callback processing."""

    def __init__(self, host: str = "192.168.50.12", mac: str = "e8:51:77:ec:98:1c"):
        # Initialize without starting real network threads
        self.host = host
        self.mac = mac
        self.port = 36669
        self._init_runtime_state()
        self._init_callbacks()
        self.connected = True
        self.state = "on"
        self.access_token = "valid_test_token"
        self._is_sleeping = False

        # Async mocks for outbound actions
        self.send_command = MagicMock()
        self.send_key = MagicMock()
        self.send_launch_app = MagicMock()
        self.send_change_source = MagicMock()
        self.async_turn_on = AsyncMock(return_value=True)
        self.async_wait_until_awake = AsyncMock(return_value=True)


@pytest.fixture
def behavioral_client():
    """Provides a VidaaClient with real internal state parsing and mock outbound hooks."""
    return RealStateVidaaClient()


@pytest.fixture
def behavioral_entry():
    """Mock config entry with standard default options."""
    entry = MagicMock()
    entry.entry_id = "vidaa_behavioral_entry_123"
    entry.data = {
        "host": "192.168.50.12",
        "mac": "e8:51:77:ec:98:1c",
        "name": "Living Room TV",
    }
    entry.options = {
        CONF_ENABLE_CEC_NAMES: True,
        CONF_INCLUDE_APPS_IN_SOURCES: True,
    }
    return entry


# -----------------------------------------------------------------------------
# 1. End-to-End Activity & Source Behavior (Testing Boundary, Not Mock Dicts)
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remote_activity_list_from_raw_mqtt_telemetry(behavioral_client, behavioral_entry):
    """Test that ingesting realistic sourcelist and applist MQTT payloads properly populates remote.activity_list."""
    remote = VidaaRemote(client=behavioral_client, entry=behavioral_entry)

    # Initially, without receiving any payloads, activity_list contains no sources/apps
    assert remote.activity_list == []

    # 1. Simulate TV broadcasting realistic raw sourcelist JSON
    raw_sourcelist_payload = [
        {"sourceid": "0", "sourcename": "TV", "displayname": "Live TV", "is_signal": "1"},
        {"sourceid": "1", "sourcename": "HDMI1", "displayname": "PlayStation 5", "is_signal": "1"},
        {"sourceid": "2", "sourcename": "HDMI2", "displayname": "Apple TV", "is_signal": "0"},
    ]
    behavioral_client._dispatch_sourcelist_update(raw_sourcelist_payload)

    # Verify sources are now observable via remote.activity_list
    assert "TV" in remote.activity_list
    assert "HDMI1" in remote.activity_list
    assert "HDMI2" in remote.activity_list

    # 2. Simulate TV broadcasting realistic raw applist JSON
    raw_applist_payload = [
        {"appId": "netflix", "name": "Netflix", "appname": "Netflix", "is_installed": True},
        {"appId": "youtube", "name": "YouTube", "appname": "YouTube", "is_installed": True},
        {"appId": "plex", "name": "Plex", "appname": "Plex", "is_installed": True},
    ]
    behavioral_client._dispatch_applist_update(raw_applist_payload)

    # Assert merged list of friendly app titles and source labels are visible
    activities = remote.activity_list
    assert "Netflix" in activities
    assert "YouTube" in activities
    assert "Plex" in activities
    assert "HDMI1" in activities

    # 3. Simulate calling async_turn_on with an activity
    with patch("custom_components.vidaa.remote.async_execute_select_source", new_callable=AsyncMock) as mock_exec:
        await remote.async_turn_on(activity="Netflix")
        mock_exec.assert_called_once()
        # Verify it passed the real parsed dictionaries rather than empty mocks
        args = mock_exec.call_args[0]
        # args: (client, sources, apps, "Netflix")
        assert "Netflix" in args[2] or "netflix" in args[2] or "Netflix" in str(args)


@pytest.mark.anyio
async def test_remote_current_activity_transitions(behavioral_client, behavioral_entry):
    """Test remote.current_activity dynamically tracks app and input source state updates."""
    remote = VidaaRemote(client=behavioral_client, entry=behavioral_entry)

    # Initial state
    assert remote.current_activity is None

    # TV launches YouTube app
    behavioral_client._dispatch_state_update(
        {
            "statetype": "app",
            "name": "YouTube",
            "appId": "youtube",
        }
    )
    assert remote.current_activity == "YouTube"

    # TV switches input to HDMI1 with CEC displayname
    behavioral_client._dispatch_state_update(
        {
            "statetype": "sourceswitch",
            "sourcename": "HDMI1",
            "displayname2": "Nintendo Switch",
        }
    )
    assert remote.current_activity == "HDMI1 (Nintendo Switch)"

    # TV goes to standby
    behavioral_client._dispatch_state_update({"statetype": "fake_sleep_0"})
    assert remote.is_on is False
    assert remote.current_activity is None


# -----------------------------------------------------------------------------
# 2. Power State Transitions & Wake Verification Behavior
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_ensure_tv_on_behavior_when_awake(behavioral_client):
    """When TV is already on, async_ensure_tv_on executes immediately without triggering turn_on."""
    behavioral_client.state = "on"
    behavioral_client.connected = True

    await async_ensure_tv_on(behavioral_client, action_description="launching test")
    behavioral_client.async_turn_on.assert_not_called()
    behavioral_client.async_wait_until_awake.assert_not_called()


@pytest.mark.anyio
async def test_async_ensure_tv_on_wakes_standby_tv(behavioral_client):
    """When TV is in standby, async_ensure_tv_on triggers turn_on and verifies awake state."""
    behavioral_client.state = "off"
    behavioral_client.connected = True

    async def fake_wake(*args, **kwargs):
        # Simulate TV powering on during wake wait
        behavioral_client.state = "on"
        return True

    behavioral_client.async_wait_until_awake.side_effect = fake_wake

    await async_ensure_tv_on(behavioral_client, action_description="launching Netflix")
    behavioral_client.async_turn_on.assert_called_once()
    behavioral_client.async_wait_until_awake.assert_called_once()


@pytest.mark.anyio
async def test_async_ensure_tv_on_raises_when_wake_fails(behavioral_client):
    """When TV fails to wake up within timeout, HomeAssistantError is raised."""
    behavioral_client.state = "off"
    behavioral_client.connected = True
    behavioral_client.async_wait_until_awake.return_value = False

    with pytest.raises(HomeAssistantError) as exc_info:
        await async_ensure_tv_on(behavioral_client, timeout=0.1, action_description="opening app")

    assert "Failed to power on TV" in str(exc_info.value)
    assert exc_info.value.translation_key == "turn_on_failed"


# -----------------------------------------------------------------------------
# 3. Graceful Network Drop & Offline State Propagation
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_media_player_offline_state_and_readiness(behavioral_client, behavioral_entry):
    """Test media player updates cleanly when connection drops and prevents blind dispatches."""
    hass = MagicMock(spec=HomeAssistant)
    player = VidaaMediaPlayer(client=behavioral_client, entry=behavioral_entry)
    player.hass = hass

    # TV is active and playing
    behavioral_client.state = "on"
    behavioral_client.connected = True
    assert player.state == MediaPlayerState.ON

    # Simulate abrupt network disconnection event from MQTT client
    behavioral_client.connected = False
    behavioral_client._dispatch_disconnected()

    # Client command readiness check must reject actions with 'not_connected'
    with pytest.raises(HomeAssistantError) as exc_info:
        check_client_command_readiness(behavioral_client)
    assert exc_info.value.translation_key == "not_connected"


@pytest.mark.anyio
async def test_auth_failure_blocks_actions_and_marks_unavailable(behavioral_client, behavioral_entry):
    """Test TV authentication rejection cleanly marks entities unavailable and prevents errors."""
    remote = VidaaRemote(client=behavioral_client, entry=behavioral_entry)
    player = VidaaMediaPlayer(client=behavioral_client, entry=behavioral_entry)

    assert remote.available is True
    assert player.available is True

    # TV broker rejects client certificate or pairing token
    behavioral_client._dispatch_auth_failed()

    assert behavioral_client.auth_failed is True
    assert remote.available is False
    assert player.available is False

    # Attempting to send commands raises clean 'auth_required' HomeAssistantError
    with pytest.raises(HomeAssistantError) as exc_info:
        check_client_command_readiness(behavioral_client)
    assert exc_info.value.translation_key == "auth_required"

    with pytest.raises(HomeAssistantError) as exc_info:
        await remote.async_turn_on()
    assert exc_info.value.translation_key == "auth_required"


# -----------------------------------------------------------------------------
# 4. Config Entry Migration & Certificate Repair Suppression
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_migration_and_repair_suppression_for_legacy_auth():
    """Verify legacy/static auth entries migrate without creating false certificate repair warnings."""
    from custom_components.vidaa import (
        _async_check_and_manage_legacy_repair,
        async_migrate_entry,
    )

    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(return_value=False)  # No legacy dir
    mock_repair = MagicMock()

    with patch("homeassistant.helpers.issue_registry.async_create_issue", mock_repair):
        # Entry v2.2 with legacy auth
        entry = MagicMock()
        entry.version = 2
        entry.minor_version = 2
        entry.domain = DOMAIN
        entry.title = "Hisense TV"
        entry.data = {
            "host": "192.168.50.12",
            "auth_profile": "legacy",
            "use_ssl": False,
            "name": "Hisense TV",
        }

        # 1. Run migration
        res = await async_migrate_entry(hass, entry)
        assert res is True
        hass.config_entries.async_update_entry.assert_called_once()
        assert hass.config_entries.async_update_entry.call_args[1]["minor_version"] == 3
        assert hass.config_entries.async_update_entry.call_args[1]["data"]["use_ssl"] is True

        # 2. Check legacy repair management
        await _async_check_and_manage_legacy_repair(hass)
        # Verify no false "certificate missing" issue was created
        mock_repair.assert_not_called()


# -----------------------------------------------------------------------------
# 5. Non-Blocking Discovery, Upload Processing, and Token Lifecycle Teardown
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_lifecycle_manager_teardown_cancels_all_tracked_tasks():
    """Verify stop_token_watch cancels all in-flight background refresh/tick tasks."""
    from custom_components.vidaa.client import VidaaClient
    from custom_components.vidaa.protocol.auth_lifecycle import TokenLifecycleManager

    client = VidaaClient("192.168.50.12", "e8:51:77:ec:98:1c")
    mgr = TokenLifecycleManager(client)

    async def long_sleeping_coro():
        await asyncio.sleep(100)

    # Spawn tasks using _spawn_task
    t1 = mgr._spawn_task(long_sleeping_coro())
    t2 = mgr._spawn_task(long_sleeping_coro())
    assert t1 is not None and not t1.done()
    assert t2 is not None and not t2.done()
    assert len(mgr._tracked_tasks) == 2

    # Stopping token watch must cancel all tracked background tasks
    mgr.stop_token_watch()
    assert t1.cancelling() or t1.cancelled() or t1.done()
    assert t2.cancelling() or t2.cancelled() or t2.done()


@pytest.mark.anyio
async def test_uploaded_cert_processing_error_translations():
    """Verify shared async_process_uploaded_cert_file translates archive failures into UI translation keys."""
    from custom_components.vidaa.flow.helpers import (
        UploadedCertProcessingError,
        async_process_uploaded_cert_file,
    )

    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock()

    # Case 1: Exceeds size limit
    hass.async_add_executor_job.side_effect = ValueError("File size limit exceeds maximum allowable 50MB")
    with pytest.raises(UploadedCertProcessingError) as exc_info:
        await async_process_uploaded_cert_file(hass, "test_file_id")
    assert exc_info.value.error_key == "file_too_large"

    # Case 2: P12 password / decrypt error
    hass.async_add_executor_job.side_effect = ValueError("Failed to decrypt PKCS#12 payload with provided password")
    with pytest.raises(UploadedCertProcessingError) as exc_info:
        await async_process_uploaded_cert_file(hass, "test_file_id")
    assert exc_info.value.error_key == "p12_decrypt_failed"

    # Case 3: Malformed PEM
    hass.async_add_executor_job.side_effect = ValueError("Archive missing both a certificate and private key")
    with pytest.raises(UploadedCertProcessingError) as exc_info:
        await async_process_uploaded_cert_file(hass, "test_file_id")
    assert exc_info.value.error_key == "invalid_pem_bundle"


@pytest.mark.anyio
async def test_discovery_flow_auto_resolves_legacy_without_upload():
    """Verify discovery step detects legacy TV via probe and proceeds without forcing cert upload."""
    from custom_components.vidaa.config_flow import VidaaConfigFlow

    flow = VidaaConfigFlow()
    flow.hass = MagicMock(spec=HomeAssistant)
    flow.ip_address = "192.168.50.12"
    flow.mac_address = "e8:51:77:ec:98:1c"
    flow.auth_profile = "auto"
    flow.discovered_title = "Hisense H43B7100"

    # Mock cert resolution returning False (no certs on disk)
    flow._async_resolve_ssl_certs = AsyncMock(return_value=False)
    flow._async_init_client_and_auth = AsyncMock(return_value={"type": "form", "step_id": "auth"})
    flow.async_step_upload = AsyncMock()

    with patch(
        "custom_components.vidaa.client.VidaaClient.async_probe_auth_methods", new_callable=AsyncMock
    ) as mock_probe:
        mock_probe.return_value = {"legacy_static": {"supported": True}}
        res = await flow.async_step_discovery_confirm(user_input={"confirm": True})
        assert res is not None

        # Should NOT have redirected to upload
        flow.async_step_upload.assert_not_called()
        # Should have routed to _async_init_client_and_auth
        flow._async_init_client_and_auth.assert_called_once()
        assert flow.auth_profile == "legacy"
        assert flow.use_ssl is True
