"""Service call execution handlers for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..const import (
    ATTR_ACTION,
    ATTR_APP,
    ATTR_APP_ID,
    ATTR_APP_NAME,
    ATTR_CHANNEL,
    ATTR_CONFIRM,
    ATTR_DELAY,
    ATTR_KEY,
    ATTR_MENU_ID,
    ATTR_MENU_VALUE,
    ATTR_REPEAT,
    ATTR_SEQUENCE,
    ATTR_TEXT,
    ATTR_URL,
    DEFAULT_WOL_TIMEOUT,
    DOMAIN,
    POWER_KEYS,
)
from .target import _resolve_service_targets, parse_key_sequence

_LOGGER = logging.getLogger(__name__)


async def handle_send_key(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle send_key service call."""
    key = call.data.get(ATTR_KEY)
    repeat = call.data.get(ATTR_REPEAT, 1)
    delay = call.data.get(ATTR_DELAY, 0.2)
    target_clients = _resolve_service_targets(hass, call)
    is_power_key = str(key).strip().lower() in POWER_KEYS

    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                f"Failed to send key {key}: TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="send_key_failed",
                translation_placeholders={"key": str(key), "error": "TV is disconnected"},
            )
        if not is_power_key and getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        for i in range(repeat):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            try:
                res = await client.async_send_command(key)
                if res is False:
                    raise ConnectionError(f"Command execution failed for {key}")
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to send key {key}: {err}",
                    translation_domain=DOMAIN,
                    translation_key="send_key_failed",
                    translation_placeholders={"key": str(key), "error": str(err)},
                ) from err

    return {
        "key": key,
        "repeat": repeat,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }


async def handle_send_key_sequence(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle send_key_sequence service call."""
    raw_sequence = call.data.get(ATTR_SEQUENCE)
    delay = float(call.data.get(ATTR_DELAY, 0.3))
    target_clients = _resolve_service_targets(hass, call)
    sequence = parse_key_sequence(raw_sequence)

    if not sequence:
        raise ServiceValidationError(
            "No valid keys provided in sequence.",
            translation_domain=DOMAIN,
            translation_key="empty_key_sequence",
        )

    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                "Failed to execute key sequence: TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="send_key_sequence_failed",
                translation_placeholders={"key": str(sequence[0]), "error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        for i, key in enumerate(sequence):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            try:
                res = await client.async_send_command(key)
                if res is False:
                    raise ConnectionError(f"Command execution failed for {key}")
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to execute key sequence at step {key}: {err}",
                    translation_domain=DOMAIN,
                    translation_key="send_key_sequence_failed",
                    translation_placeholders={"key": str(key), "error": str(err)},
                ) from err

    return {
        "sequence": sequence,
        "delay": delay,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }


async def handle_change_channel(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle change_channel service call by dispatching numeric digits."""
    raw_channel = str(call.data.get(ATTR_CHANNEL, "")).strip()
    confirm = bool(call.data.get(ATTR_CONFIRM, True))
    delay = float(call.data.get(ATTR_DELAY, 0.25))
    target_clients = _resolve_service_targets(hass, call)

    digits = [ch for ch in raw_channel if ch.isdigit()]
    if not digits:
        raise ServiceValidationError(
            f"Channel {raw_channel} contains no valid digits.",
            translation_domain=DOMAIN,
            translation_key="invalid_channel_digits",
            translation_placeholders={"channel": raw_channel},
        )

    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                "Failed to change channel: TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="change_channel_digit_failed",
                translation_placeholders={"digit": str(digits[0]), "error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        for i, digit in enumerate(digits):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            key = f"KEY_{digit}"
            try:
                res = await client.async_send_command(key)
                if res is False:
                    raise ConnectionError(f"Command execution failed for {key}")
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to send channel digit {digit}: {err}",
                    translation_domain=DOMAIN,
                    translation_key="change_channel_digit_failed",
                    translation_placeholders={"digit": str(digit), "error": str(err)},
                ) from err

        if confirm:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                res = await client.async_send_command("KEY_OK")
                if res is False:
                    raise ConnectionError("Command execution failed for KEY_OK")
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to send channel confirm command: {err}",
                    translation_domain=DOMAIN,
                    translation_key="change_channel_confirm_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    return {
        "channel": raw_channel,
        "digits": digits,
        "confirmed": confirm,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }


async def handle_launch_app(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle launch_app service call."""
    app = str(call.data.get(ATTR_APP) or "")
    requested_app_id = str(call.data.get(ATTR_APP_ID) or "")
    target_clients = _resolve_service_targets(hass, call)
    launched: list[dict[str, Any]] = []
    lookup_ids = {value.lower() for value in (app, requested_app_id) if value}

    for client in target_clients:
        matched_app = None
        for a in getattr(client, "apps", []):
            if isinstance(a, dict) and (
                (app and str(a.get("name") or a.get("appName") or "").lower() == app.lower())
                or str(a.get("appId") or a.get("app_id") or "").lower() in lookup_ids
            ):
                matched_app = a
                break

        if matched_app:
            app_id = str(matched_app.get("appId") or matched_app.get("app_id") or "")
            app_name = str(matched_app.get("name") or matched_app.get("appName") or "")
            app_url = str(matched_app.get("url") or matched_app.get("appUrl") or "")
        else:
            app_id = ""
            app_name = app or requested_app_id
            app_url = app

        app_id = requested_app_id or app_id
        app_name = str(call.data.get(ATTR_APP_NAME, app_name))
        app_url = str(call.data.get(ATTR_URL, app_url))

        if getattr(client, "is_on", True) is False:
            _LOGGER.debug(
                "[%s] TV is off; powering on before launching app '%s'",
                getattr(client, "ip", "unknown"),
                app_name,
            )
            await client.async_turn_on()
            wait_fn = getattr(client, "async_wait_until_awake", None)
            if wait_fn is not None and callable(wait_fn):
                res = wait_fn(timeout=DEFAULT_WOL_TIMEOUT)
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    awake = await res
                else:
                    awake = bool(res)
                if not awake:
                    raise HomeAssistantError(
                        f"Failed to launch app {app_name}: TV did not wake up",
                        translation_domain=DOMAIN,
                        translation_key="turn_on_failed",
                    )
            await asyncio.sleep(0.5)

        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                f"Failed to launch app {app_name}: TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="launch_app_failed",
                translation_placeholders={"app_name": str(app_name), "error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )

        try:
            res = await client.async_launch_app(
                app_id,
                app_name,
                app_url,
            )
            if res is False:
                raise ConnectionError(f"App launch command failed for {app_name}")
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to launch app {app_name}: {err}",
                translation_domain=DOMAIN,
                translation_key="launch_app_failed",
                translation_placeholders={"app_name": str(app_name), "error": str(err)},
            ) from err

        launched.append(
            {
                "ip": getattr(client, "ip", "unknown"),
                "app_name": app_name,
                "app_id": app_id,
                "app_url": app_url,
            }
        )

    return {
        "app": app or requested_app_id,
        "targets": launched,
        "count": len(launched),
    }


async def handle_set_picture_setting(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle set_picture_setting service call."""
    menu_id = call.data.get(ATTR_MENU_ID)
    menu_val = call.data.get(ATTR_MENU_VALUE)
    target_clients = _resolve_service_targets(hass, call)
    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                f"Failed to set picture setting (menu_id={menu_id}): TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="set_picture_setting_failed",
                translation_placeholders={"menu_id": str(menu_id), "error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        try:
            res = await client.async_set_picture_setting(menu_id, menu_val)
            if res is False:
                raise ConnectionError(f"Picture setting update failed for menu_id {menu_id}")
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to set picture setting (menu_id={menu_id}): {err}",
                translation_domain=DOMAIN,
                translation_key="set_picture_setting_failed",
                translation_placeholders={"menu_id": str(menu_id), "error": str(err)},
            ) from err
    return {
        "menu_id": menu_id,
        "menu_value": menu_val,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }


async def handle_set_sound_setting(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle set_sound_setting service call."""
    menu_id = call.data.get(ATTR_MENU_ID)
    menu_val = call.data.get(ATTR_MENU_VALUE)
    target_clients = _resolve_service_targets(hass, call)
    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                f"Failed to set sound setting (menu_id={menu_id}): TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="set_sound_setting_failed",
                translation_placeholders={"menu_id": str(menu_id), "error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        try:
            res = await client.async_set_sound_setting(menu_id, menu_val)
            if res is False:
                raise ConnectionError(f"Sound setting update failed for menu_id {menu_id}")
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to set sound setting (menu_id={menu_id}): {err}",
                translation_domain=DOMAIN,
                translation_key="set_sound_setting_failed",
                translation_placeholders={"menu_id": str(menu_id), "error": str(err)},
            ) from err
    return {
        "menu_id": menu_id,
        "menu_value": menu_val,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }


async def handle_send_text_input(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Handle send_text_input service call."""
    text = call.data.get(ATTR_TEXT, "")
    action = call.data.get(ATTR_ACTION, "insert")
    target_clients = _resolve_service_targets(hass, call)
    for client in target_clients:
        if getattr(client, "auth_failed", False) is True:
            raise HomeAssistantError(
                "Authentication required: Re-pair TV in Settings > Integrations.",
                translation_domain=DOMAIN,
                translation_key="auth_required",
            )
        if getattr(client, "connected", True) is False:
            raise HomeAssistantError(
                "Failed to send text input: TV is disconnected",
                translation_domain=DOMAIN,
                translation_key="send_text_input_failed",
                translation_placeholders={"error": "TV is disconnected"},
            )
        if getattr(client, "is_on", True) is False:
            raise HomeAssistantError(
                "Cannot perform action: TV is currently turned off.",
                translation_domain=DOMAIN,
                translation_key="device_off",
            )
        try:
            res = await client.async_send_text_input(text, action)
            if res is False:
                raise ConnectionError("Text input delivery failed")
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to send text input: {err}",
                translation_domain=DOMAIN,
                translation_key="send_text_input_failed",
                translation_placeholders={"error": str(err)},
            ) from err
    return {
        "text": text,
        "action": action,
        "targets": [getattr(c, "ip", "unknown") for c in target_clients],
        "count": len(target_clients),
    }
