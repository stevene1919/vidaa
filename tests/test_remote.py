"""Tests for VIDAA Smart TV remote control entity."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
