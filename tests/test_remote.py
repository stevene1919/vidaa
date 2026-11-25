"""Tests for VIDAA Smart TV remote control entity."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.vidaa.const import (
    DOMAIN,
    LEGACY_DOMAIN,
)
from custom_components.vidaa.remote import (
    HisenseVidaaRemote,
    VidaaRemote,
    async_setup_entry as async_setup_remote,
)


def test_remote_backwards_compatibility_alias():
    """Verify HisenseVidaaRemote is an alias for VidaaRemote for backwards compatibility."""
    assert HisenseVidaaRemote is VidaaRemote


def test_remote_device_info(mock_client, mock_entry):
    """Test device info registration for remote entity."""
    rem = VidaaRemote(
        client=mock_client,
        entry=mock_entry,
    )
    rem_info = rem.device_info
    assert rem_info["identifiers"] == {(DOMAIN, "test_entry_id"), (LEGACY_DOMAIN, "test_entry_id")}
    assert rem_info["model"] == "65U7G"
    assert rem_info["manufacturer"] == "Hisense"
    assert ("mac", "e8:51:77:aa:bb:cc") in rem_info["connections"]


def test_remote_availability_on_auth_failure(mock_client, mock_entry):
    """Test remote reports unavailable when client.auth_failed is True."""
    mock_client.auth_failed = False
    mock_client.connected = False
    mock_client.is_on = False
    rem = VidaaRemote(client=mock_client, entry=mock_entry)

    assert rem.available is True

    # When TV broker rejects credentials, entity becomes unavailable
    mock_client.auth_failed = True
    assert rem.available is False


@pytest.mark.anyio
async def test_remote_send_command(mock_client, mock_entry):
    """Test remote entity send command handling and burst/hold timings."""
    rem = VidaaRemote(
        client=mock_client,
        entry=mock_entry,
    )
    # Standard command
    await rem.async_send_command(["home", "ok"], delay_secs=0.01)
    assert mock_client.send_command.call_count == 2

    # Hold secs for OK long press
    await rem.async_send_command(["ok"], hold_secs=0.5)
    mock_client.send_key.assert_called_with("KEY_OK_LONG_PRESS")

    # Hold secs for arbitrary key burst
    mock_client.send_command.reset_mock()
    await rem.async_send_command(["up"], hold_secs=0.3)
    assert mock_client.send_command.call_count == 3


@pytest.mark.anyio
async def test_remote_idempotent_power_control(mock_client, mock_entry):
    """Test idempotent power control on remote entity."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

    def _mock_bg_task(coro, *a, **kw):
        return asyncio.get_running_loop().create_task(coro)

    hass.async_create_background_task = MagicMock(side_effect=_mock_bg_task)

    rem = VidaaRemote(
        client=mock_client,
        entry=mock_entry,
    )
    rem.hass = hass
    rem.entity_id = "remote.living_room_tv"

    # Mock client connected: initial state should be ON
    mock_client.connected = True
    assert rem.is_on is True

    # Calling async_turn_on when already connected & ON must NOT send KEY_POWER
    mock_client.send_key.reset_mock()
    await rem.async_turn_on()
    mock_client.send_key.assert_not_called()
    assert rem.is_on is True

    # Simulate TV entering fake sleep (screen off)
    rem._handle_state_update({"statetype": "fake_sleep_0"})
    assert rem.is_on is False

    # Calling async_turn_on while in fake_sleep_0 MUST send KEY_POWER to wake screen
    await rem.async_turn_on()
    mock_client.send_key.assert_called_once_with("KEY_POWER")
    assert rem.is_on is True


@pytest.mark.anyio
async def test_remote_send_command_num_repeats_option(mock_client, mock_entry):
    """[F1-leg4] The key_repeat option applies when HA sends the service default."""
    mock_entry.options = {"enable_remote": True, "key_repeat": 5}
    rem = VidaaRemote(client=mock_client, entry=mock_entry)

    # HA's remote.send_command schema always sends num_repeats (default 1): with the
    # service default the key_repeat option must be honoured.
    await rem.async_send_command(["up"], num_repeats=1, delay_secs=0)
    assert mock_client.send_command.call_count == 5

    # An explicit caller-supplied value still wins.
    mock_client.send_command.reset_mock()
    await rem.async_send_command(["up"], num_repeats=3, delay_secs=0)
    assert mock_client.send_command.call_count == 3

    # Float values from options (e.g. from HA NumberSelector serialization) or kwargs do not crash range().
    mock_entry.options = {"enable_remote": True, "key_repeat": 2.0}
    rem_float = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.send_command.reset_mock()
    await rem_float.async_send_command(["up"], num_repeats=1, delay_secs=0)
    assert mock_client.send_command.call_count == 2

    mock_client.send_command.reset_mock()
    await rem_float.async_send_command(["up"], num_repeats=4.0, delay_secs=0)
    assert mock_client.send_command.call_count == 4


def test_remote_off_ish_statetypes_stay_off(mock_client, mock_entry):
    """[F3-leg4 residual] remote statetype handling agrees with tv/state.py."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem.entity_id = "remote.living_room_tv"
    mock_client.connected = True

    # (a) an off-ish statetype after a remote callback must keep is_on False
    rem._handle_state_update({"statetype": "poweroff"})
    assert mock_client.is_on is False
    assert rem.is_on is False

    # (b) fake_sleep_1 means the TV is waking up → ON
    rem._handle_state_update({"statetype": "fake_sleep_1"})
    assert mock_client.is_on is True
    assert rem.is_on is True

    # (c) fake_sleep_0 (exact) → OFF
    rem._handle_state_update({"statetype": "fake_sleep_0"})
    assert mock_client.is_on is False
    assert rem.is_on is False


@pytest.mark.anyio
async def test_remote_platform_always_sets_up_entity(mock_client, mock_entry):
    """Remote platform always registers entity regardless of options."""
    hass = MagicMock(spec=HomeAssistant)
    mock_entry.runtime_data = MagicMock(client=mock_client)
    entities = []
    await async_setup_remote(hass, mock_entry, lambda e: entities.extend(e))
    assert len(entities) == 1
    assert entities[0].unique_id == f"{mock_entry.entry_id}_remote"


@pytest.mark.anyio
async def test_remote_action_exceptions(mock_client, mock_entry):
    """Test remote entity actions raise HomeAssistantError when disconnected or command fails."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)

    # 1. Disconnected: send_command raises not_connected
    mock_client.connected = False
    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_send_command(["KEY_POWER"])
    assert exc_info.value.translation_key == "not_connected"

    # 2. Connected but command delivery fails: raises send_key_failed
    mock_client.connected = True
    mock_client.async_send_command = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_send_command(["KEY_MENU"])
    assert exc_info.value.translation_key == "send_key_failed"

    # 3. Disconnected turn_off when TV on raises not_connected
    mock_client.connected = False
    mock_client.is_on = True
    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_off()
    assert exc_info.value.translation_key == "not_connected"


@pytest.mark.anyio
async def test_remote_action_exceptions_on_auth_failed(mock_client, mock_entry):
    """Test remote raises auth_required when client.auth_failed is True."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.auth_failed = True
    mock_client.connected = False

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_on()
    assert exc_info.value.translation_key == "auth_required"

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_off()
    assert exc_info.value.translation_key == "auth_required"

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_send_command(["KEY_POWER"])
    assert exc_info.value.translation_key == "auth_required"


@pytest.mark.anyio
async def test_remote_turn_on_failed_wol(mock_client, mock_entry):
    """Test remote raises turn_on_failed when client.async_turn_on returns False."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.auth_failed = False
    mock_client.async_turn_on = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_on()
    assert exc_info.value.translation_key == "turn_on_failed"


@pytest.mark.anyio
async def test_remote_action_exceptions_when_tv_off(mock_client, mock_entry):
    """Test remote raises device_off for non-power keys when TV is off, allows power keys, and turn_off no-ops."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem._options = {"enable_cec_names": True}
    mock_client.connected = True
    mock_client.is_on = False
    mock_client.async_send_command = AsyncMock(return_value=True)

    # 1. Turn off is a safe no-op when already off
    await rem.async_turn_off()
    mock_client.async_send_key.assert_not_called()

    # 2. Non-power command raises device_off
    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_send_command(["KEY_VOLUMEUP"])
    assert exc_info.value.translation_key == "device_off"

    # 3. Power command is permitted even when off
    await rem.async_send_command(["KEY_POWER"])
    mock_client.async_send_command.assert_called_with("KEY_POWER")


def test_remote_current_activity_transitions(mock_client, mock_entry):
    """Test current_activity transitions cleanly between app, launcher, and HDMI without sticking."""
    from custom_components.vidaa.tv.state import apply_state_update

    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem._options = {"enable_cec_names": True}
    mock_client.connected = True
    mock_client.is_on = True

    # 1. TV launches Home Launcher
    apply_state_update(mock_client, {"statetype": "remote_launcher"})
    rem._handle_state_update({"statetype": "remote_launcher"})
    assert rem.current_activity == "Home Launcher"

    # 2. TV switches to HDMI2 with connected device
    apply_state_update(
        mock_client,
        {"statetype": "sourceswitch", "sourcename": "HDMI2", "displayname2": "Chromecast"},
    )
    rem._handle_state_update({"statetype": "sourceswitch"})
    # current_activity must reflect HDMI source (and CEC name), NOT stick on Home Launcher
    assert rem.current_activity == "HDMI2 (Chromecast)"

    # 3. TV launches Netflix
    apply_state_update(mock_client, {"statetype": "app", "name": "Netflix", "appId": "1"})
    rem._handle_state_update({"statetype": "app"})
    assert rem.current_activity == "Netflix"


@pytest.mark.anyio
async def test_remote_lifecycle_callbacks(mock_client, mock_entry):
    """Test remote entity registration and removal of client callbacks."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem.schedule_update_ha_state = MagicMock()

    await rem.async_added_to_hass()
    mock_client.register_connected_callback.assert_called_with(rem._handle_connected)
    mock_client.register_state_callback.assert_called_with(rem._handle_state_update)

    rem._handle_connected()
    rem._handle_disconnected()
    assert rem.schedule_update_ha_state.call_count == 2

    await rem.async_will_remove_from_hass()
    mock_client.unregister_connected_callback.assert_called_with(rem._handle_connected)
    mock_client.unregister_state_callback.assert_called_with(rem._handle_state_update)


@pytest.mark.anyio
async def test_remote_async_exec_helper(mock_client, mock_entry):
    """Test _async_exec helper with sync and async functions."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    assert await rem._async_exec(lambda: 42) == 42

    async def _coro(val):
        return val * 2

    assert await rem._async_exec(_coro, 21) == 42


@pytest.mark.anyio
async def test_remote_current_activity_when_off(mock_client, mock_entry):
    """Test current_activity returns None when TV is off."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.is_on = False
    assert rem.current_activity is None


@pytest.mark.anyio
async def test_remote_turn_on_with_activity_and_secondary_mac(mock_client, mock_entry):
    """Test turn_on targets secondary MAC and launches activity."""
    mock_entry.options = {
        "enable_wol": True,
        "secondary_mac_address": "e8:51:77:00:11:22",
    }
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem.async_write_ha_state = MagicMock()
    mock_client.connected = True
    mock_client.is_on = True
    mock_client.async_turn_on = AsyncMock(return_value=True)

    with patch("custom_components.vidaa.remote.async_execute_select_source", AsyncMock()) as mock_sel:
        await rem.async_turn_on(activity="Netflix")
        mock_client.async_turn_on.assert_awaited_once()
        woken_macs = mock_client.async_turn_on.await_args[0][0]
        assert "e8:51:77:00:11:22" in woken_macs
        mock_sel.assert_awaited_once()


@pytest.mark.anyio
async def test_remote_turn_on_with_activity_fails_to_wake(mock_client, mock_entry):
    """Test turn_on with activity raises if TV does not wake up in time."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.connected = True
    mock_client.is_on = False
    mock_client.async_turn_on = AsyncMock(return_value=True)
    mock_client.async_wait_until_awake = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_on(activity="HDMI 1")
    assert exc_info.value.translation_key == "turn_on_failed"


@pytest.mark.anyio
async def test_remote_turn_off_failure_raises(mock_client, mock_entry):
    """Test turn_off raises when async_turn_off returns False."""
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.connected = True
    mock_client.is_on = True
    mock_client.async_turn_off = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_turn_off()
    assert exc_info.value.translation_key == "send_key_failed"


@pytest.mark.anyio
async def test_remote_send_command_edge_options_and_hold(mock_client, mock_entry):
    """Test send_command with invalid delay/repeat types and mute hold."""
    mock_entry.options = {
        "key_delay": "invalid_delay",
        "key_repeat": "invalid_repeat",
    }
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    mock_client.connected = True
    mock_client.is_on = True

    # 1. Invalid option types gracefully fall back without exception
    await rem.async_send_command(["up"], num_repeats="bad_num", delay_secs="bad_delay", hold_secs="bad_hold")
    assert mock_client.send_command.call_count == 1

    # 2. Hold secs on mute sends KEY_MUTE_LONG_PRESS
    mock_client.async_send_key.reset_mock()
    await rem.async_send_command(["mute"], hold_secs=0.5)
    mock_client.async_send_key.assert_awaited_with("KEY_MUTE_LONG_PRESS")

    # 3. Hold secs step failure raises send_key_failed
    mock_client.async_send_command = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError) as exc_info:
        await rem.async_send_command(["left"], hold_secs=0.2)
    assert exc_info.value.translation_key == "send_key_failed"


@pytest.mark.anyio
async def test_remote_turn_on_skips_wol_when_disabled(mock_client, mock_entry):
    """Remote turn_on passes an empty MAC list when enable_wol is False."""
    mock_entry.data = {"mac_address": "e8:51:77:aa:bb:cc"}
    mock_entry.options = {"enable_wol": False}
    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem.async_write_ha_state = MagicMock()
    mock_client.async_turn_on = AsyncMock(return_value=True)

    await rem.async_turn_on()

    mock_client.async_turn_on.assert_awaited_once_with([])


@pytest.mark.anyio
async def test_remote_turn_on_delegates_to_pluggable_action_and_selects_activity(mock_client, mock_entry):
    """Remote turn_on honors attached PluggableAction Turn On trigger and still launches activity."""
    from homeassistant.helpers.trigger import PluggableAction

    from custom_components.vidaa import VidaaData
    from custom_components.vidaa.triggers.turn_on import async_get_turn_on_trigger

    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    pluggable = PluggableAction()
    action_ran: list[bool] = []

    def _custom_action(variables, description, context=None):
        action_ran.append(True)
        mock_client.connected = True
        mock_client.is_on = True

    PluggableAction.async_attach_trigger(hass, async_get_turn_on_trigger("device_tv"), _custom_action, {})
    pluggable.async_register(hass, async_get_turn_on_trigger("device_tv"))

    mock_entry.runtime_data = VidaaData(
        client=mock_client,
        platforms=["remote"],
        options={},
        turn_on=pluggable,
    )
    mock_client.connected = True
    mock_client.is_on = False
    mock_client.async_turn_on = AsyncMock(return_value=True)

    rem = VidaaRemote(client=mock_client, entry=mock_entry)
    rem.hass = hass
    rem.async_write_ha_state = MagicMock()

    with (
        patch("custom_components.vidaa.remote.async_execute_select_source", AsyncMock()) as mock_sel,
        patch("custom_components.vidaa.helpers.asyncio.sleep", AsyncMock()),
    ):
        await rem.async_turn_on(activity="Netflix")

    assert action_ran == [True]
    mock_client.async_turn_on.assert_not_awaited()
    mock_sel.assert_awaited_once()
