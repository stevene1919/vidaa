"""TV remote input, app launch, and input source actions for VIDAA Smart TV."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .navigation import (
    get_next_cycled_source,
    match_app,
    resolve_command_key,
    resolve_source,
)

if TYPE_CHECKING:
    from ..client import VidaaClient

_LOGGER = logging.getLogger(__name__)


def send_key(client: VidaaClient, key: str) -> None:
    """Publishes a raw keypress event to the TV."""
    if client.connected and client.mqtt_client:
        client.mqtt_client.publish(f"{client.topics.remote}actions/sendkey", key)


async def async_send_key(client: VidaaClient, key: str) -> bool:
    """Publishes a raw keypress event to the TV asynchronously."""
    if client.connected and client.mqtt_client:
        return await client.async_publish(f"{client.topics.remote}actions/sendkey", key)
    return False


def send_command(client: VidaaClient, command: str) -> bool:
    """Sends a key command to the TV, automatically resolving known key aliases."""
    if not command:
        return False
    normalized_command = command.strip().lower()
    if normalized_command.startswith(("text:", "type:")):
        raw_val = command.split(":", 1)[1]
        action = "insert"
        if raw_val.lower().startswith("replace:"):
            action = "replace"
            raw_val = raw_val.split(":", 1)[1]
        elif raw_val.lower().startswith("clear:"):
            action = "clear"
            raw_val = raw_val.split(":", 1)[1]
        elif raw_val.lower() == "clear":
            action = "clear"
            raw_val = ""
        client.send_text_input(raw_val, action=action)
        return True
    if normalized_command in ("clear_text", "text_clear"):
        client.send_text_input("", action="clear")
        return True
    if normalized_command.startswith("app:"):
        app_target = command.split(":", 1)[1].strip()
        return client._launch_app_by_name(app_target)
    if normalized_command.startswith("source:"):
        source_target = command.split(":", 1)[1].strip()
        return client._change_source_by_name_or_id(source_target)
    if normalized_command in (
        "input",
        "source",
        "cycle_source",
        "input_cycle",
        "source_cycle",
        "key_input",
        "key_source",
    ):
        return client.cycle_source()
    if normalized_command in ("input_menu", "source_menu", "key_input_menu", "key_source_menu"):
        client.send_key("KEY_MENU")
        return True

    key_to_send = resolve_command_key(command)
    client.send_key(key_to_send)
    return True


async def async_send_command(client: VidaaClient, command: str) -> bool:
    """Sends a key command to the TV asynchronously, resolving known key aliases."""
    if not command:
        return False
    normalized_command = command.strip().lower()
    if normalized_command.startswith(("text:", "type:")):
        raw_val = command.split(":", 1)[1]
        action = "insert"
        if raw_val.lower().startswith("replace:"):
            action = "replace"
            raw_val = raw_val.split(":", 1)[1]
        elif raw_val.lower().startswith("clear:"):
            action = "clear"
            raw_val = raw_val.split(":", 1)[1]
        elif raw_val.lower() == "clear":
            action = "clear"
            raw_val = ""
        return bool(await client.async_send_text_input(raw_val, action=action))
    if normalized_command in ("clear_text", "text_clear"):
        return bool(await client.async_send_text_input("", action="clear"))
    if normalized_command.startswith("app:"):
        app_target = command.split(":", 1)[1].strip()
        return bool(await client.async_launch_app_by_name(app_target))
    if normalized_command.startswith("source:"):
        source_target = command.split(":", 1)[1].strip()
        return bool(await client.async_change_source_by_name_or_id(source_target))
    if normalized_command in (
        "input",
        "source",
        "cycle_source",
        "input_cycle",
        "source_cycle",
        "key_input",
        "key_source",
    ):
        return bool(await client.async_cycle_source())
    if normalized_command in ("input_menu", "source_menu", "key_input_menu", "key_source_menu"):
        return bool(await client.async_send_key("KEY_MENU"))

    key_to_send = resolve_command_key(command)
    return bool(await client.async_send_key(key_to_send))


def cycle_source(client: VidaaClient) -> bool:
    """Cycles to the next available input source."""
    next_source = get_next_cycled_source(client.sources, client.current_source)
    if not next_source:
        client.send_key("KEY_MENU")
        return True

    next_source_id, next_source_name = next_source
    client.change_source(next_source_id, next_source_name)
    return True


async def async_cycle_source(client: VidaaClient) -> bool:
    """Cycles to the next available input source asynchronously."""
    next_source = get_next_cycled_source(client.sources, client.current_source)
    if not next_source:
        return bool(await client.async_send_key("KEY_MENU"))

    next_source_id, next_source_name = next_source
    return bool(await client.async_change_source(next_source_id, next_source_name))


def launch_app_by_name(client: VidaaClient, name_or_id: str) -> bool:
    """Launches an app by name or app ID from cached applist."""
    matched = match_app(client.apps, name_or_id)
    if matched:
        client.launch_app(matched["appId"], matched["name"], matched["url"])
        return True

    target_clean = name_or_id.strip().lower()
    if target_clean in ("netflix", "app_netflix"):
        client.send_key("KEY_NETFLIX")
        return True
    if target_clean in ("youtube", "app_youtube"):
        client.send_key("KEY_YOUTUBE")
        return True
    if target_clean in ("prime", "prime video", "app_prime"):
        client.send_key("KEY_PRIME")
        return True

    return False


async def async_launch_app_by_name(client: VidaaClient, name_or_id: str) -> bool:
    """Launches an app by name or app ID from cached applist asynchronously."""
    matched = match_app(client.apps, name_or_id)
    if matched:
        return bool(await client.async_launch_app(matched["appId"], matched["name"], matched["url"]))

    target_clean = name_or_id.strip().lower()
    if target_clean in ("netflix", "app_netflix"):
        return bool(await client.async_send_key("KEY_NETFLIX"))
    if target_clean in ("youtube", "app_youtube"):
        return bool(await client.async_send_key("KEY_YOUTUBE"))
    if target_clean in ("prime", "prime video", "app_prime"):
        return bool(await client.async_send_key("KEY_PRIME"))

    return False


def change_source_by_name_or_id(client: VidaaClient, target: str) -> bool:
    """Switches to source by name (e.g. HDMI1, TV) or numeric sourceid."""
    resolved_source_id, resolved_source_name = resolve_source(client.sources, target)
    client.change_source(resolved_source_id or target.strip(), resolved_source_name)
    return True


async def async_change_source_by_name_or_id(client: VidaaClient, target: str) -> bool:
    """Switches to source by name or numeric sourceid asynchronously."""
    resolved_source_id, resolved_source_name = resolve_source(client.sources, target)
    return bool(await client.async_change_source(resolved_source_id or target.strip(), resolved_source_name))


def change_source(client: VidaaClient, source_id: str, source_name: str | None = None) -> None:
    """Switches the active input source on the TV."""
    if not client.connected or not client.mqtt_client:
        return

    clean_source_id = str(source_id).strip()
    clean_source_name = source_name.strip() if source_name else None

    if not clean_source_name:
        resolved_id, resolved_name = resolve_source(getattr(client, "sources", []), clean_source_id)
        if resolved_name:
            clean_source_name = resolved_name
        if resolved_id:
            clean_source_id = resolved_id

    payload_dict: dict[str, Any] = {}
    if clean_source_id:
        payload_dict["sourceid"] = clean_source_id
    if clean_source_name:
        payload_dict["sourcename"] = clean_source_name
    if not payload_dict:
        payload_dict = {"sourceid": source_id}

    payload = json.dumps(payload_dict)
    client.mqtt_client.publish(f"{client.topics.ui}actions/changesource", payload)

    # Dual publish for newer VIDAA firmware expecting source name
    if clean_source_name and clean_source_id != clean_source_name and str(clean_source_id).isdigit():
        _LOGGER.debug(
            "[%s] changesource: also attempting name-as-id publish (sourceid=%s) for firmware expecting the display name",
            getattr(client, "ip", "unknown"),
            clean_source_name,
        )
        payload_modern = json.dumps({"sourceid": clean_source_name, "sourcename": clean_source_name})
        client.mqtt_client.publish(f"{client.topics.ui}actions/changesource", payload_modern)

    if (
        str(clean_source_id).upper() == "TV"
        or (clean_source_name and str(clean_source_name).upper() == "TV")
        or str(source_id).lower() == "tv"
    ):
        client.send_key("KEY_LIVETV")


async def async_change_source(client: VidaaClient, source_id: str, source_name: str | None = None) -> bool:
    """Switches the active input source on the TV asynchronously."""
    if not client.connected or not client.mqtt_client:
        return False

    if getattr(client, "hotel_mode", False):
        _LOGGER.warning(
            "[%s] Source change to '%s' requested, but TV is currently in Hotel Mode (TV OS ignores source switching while Hotel Mode is active)",
            getattr(client, "ip", "unknown"),
            source_name or source_id,
        )

    clean_source_id = str(source_id).strip()
    clean_source_name = source_name.strip() if source_name else None
    if not clean_source_name:
        resolved_id, resolved_name = resolve_source(getattr(client, "sources", []), clean_source_id)
        if resolved_name:
            clean_source_name = resolved_name
        if resolved_id:
            clean_source_id = resolved_id

    payload_dict: dict[str, Any] = {}
    if clean_source_id:
        payload_dict["sourceid"] = clean_source_id
    if clean_source_name:
        payload_dict["sourcename"] = clean_source_name
    if not payload_dict:
        payload_dict = {"sourceid": source_id}

    payload = json.dumps(payload_dict)
    res = await client.async_publish(f"{client.topics.ui}actions/changesource", payload)

    # Dual publish for newer VIDAA firmware expecting source name
    if clean_source_name and clean_source_id != clean_source_name and str(clean_source_id).isdigit():
        _LOGGER.debug(
            "[%s] changesource: also attempting name-as-id publish (sourceid=%s) for firmware expecting the display name",
            getattr(client, "ip", "unknown"),
            clean_source_name,
        )
        payload_modern = json.dumps({"sourceid": clean_source_name, "sourcename": clean_source_name})
        await client.async_publish(f"{client.topics.ui}actions/changesource", payload_modern)

    if (
        str(clean_source_id).upper() == "TV"
        or (clean_source_name and str(clean_source_name).upper() == "TV")
        or str(source_id).lower() == "tv"
    ):
        await client.async_send_key("KEY_LIVETV")

    return res


def launch_app(client: VidaaClient, app_id: str, app_name: str, url: str) -> None:
    """Launches an installed Smart TV application."""
    if client.connected and client.mqtt_client:
        payload = json.dumps(
            {
                "appId": app_id,
                "name": app_name,
                "url": url,
                "urlType": 37,
                "appName": app_name,
                "appUrl": url,
            }
        )
        client.mqtt_client.publish(f"{client.topics.ui}actions/launchapp", payload)


async def async_launch_app(client: VidaaClient, app_id: str, app_name: str, url: str) -> bool:
    """Launches an installed Smart TV application asynchronously."""
    if client.connected and client.mqtt_client:
        if getattr(client, "hotel_mode", False):
            _LOGGER.warning(
                "[%s] App launch for '%s' requested, but TV is currently in Hotel Mode (TV OS ignores app launching while Hotel Mode is active)",
                getattr(client, "ip", "unknown"),
                app_name or app_id,
            )
        payload = json.dumps(
            {
                "appId": app_id,
                "name": app_name,
                "url": url,
                "urlType": 37,
                "appName": app_name,
                "appUrl": url,
            }
        )
        return await client.async_publish(f"{client.topics.ui}actions/launchapp", payload)
    return False


def send_text_input(client: VidaaClient, text: str, action: str = "insert") -> None:
    """Sends virtual keyboard string input to active on-screen input/search field."""
    if client.connected and client.mqtt_client:
        payload = json.dumps({"text": text, "action": action})
        client.mqtt_client.publish(f"{client.topics.platform}actions/txtinputdata", payload)
        client.mqtt_client.publish(f"{client.topics.platform}actions/bwsinputdata", payload)


async def async_send_text_input(client: VidaaClient, text: str, action: str = "insert") -> bool:
    """Sends virtual keyboard string input asynchronously."""
    if client.connected and client.mqtt_client:
        payload = json.dumps({"text": text, "action": action})
        res1 = await client.async_publish(f"{client.topics.platform}actions/txtinputdata", payload)
        res2 = await client.async_publish(f"{client.topics.platform}actions/bwsinputdata", payload)
        return bool(res1 or res2)
    return False


class TvInputActionsMixin:
    """Mixin providing remote key dispatch, input source cycling, and app launching."""

    def send_key(self, key: str) -> None:
        """Publishes a raw keypress event to the TV."""
        send_key(self, key=key)  # type: ignore[arg-type]

    async def async_send_key(self, key: str) -> bool:
        """Publishes a raw keypress event to the TV asynchronously."""
        return await async_send_key(self, key=key)  # type: ignore[arg-type]

    def send_command(self, command: str) -> bool:
        """Sends a key command to the TV, automatically resolving known key aliases."""
        return send_command(self, command=command)  # type: ignore[arg-type]

    async def async_send_command(self, command: str) -> bool:
        """Sends a key command to the TV asynchronously, resolving known key aliases."""
        return await async_send_command(self, command=command)  # type: ignore[arg-type]

    def cycle_source(self) -> bool:
        """Cycles to the next available input source."""
        return cycle_source(self)  # type: ignore[arg-type]

    async def async_cycle_source(self) -> bool:
        """Cycles to the next available input source asynchronously."""
        return await async_cycle_source(self)  # type: ignore[arg-type]

    def _launch_app_by_name(self, name_or_id: str) -> bool:
        """Launches an app by name or app ID from cached applist."""
        return launch_app_by_name(self, name_or_id=name_or_id)  # type: ignore[arg-type]

    async def async_launch_app_by_name(self, name_or_id: str) -> bool:
        """Launches an app by name or app ID from cached applist asynchronously."""
        return await async_launch_app_by_name(self, name_or_id=name_or_id)  # type: ignore[arg-type]

    def _change_source_by_name_or_id(self, target: str) -> bool:
        """Switches to source by name (e.g. HDMI1, TV) or numeric sourceid."""
        return change_source_by_name_or_id(self, target=target)  # type: ignore[arg-type]

    async def async_change_source_by_name_or_id(self, target: str) -> bool:
        """Switches to source by name or numeric sourceid asynchronously."""
        return await async_change_source_by_name_or_id(self, target=target)  # type: ignore[arg-type]

    def change_source(self, source_id: str, source_name: str | None = None) -> None:
        """Switches the active input source on the TV."""
        change_source(self, source_id=source_id, source_name=source_name)  # type: ignore[arg-type]

    async def async_change_source(self, source_id: str, source_name: str | None = None) -> bool:
        """Switches the active input source on the TV asynchronously."""
        return await async_change_source(self, source_id=source_id, source_name=source_name)  # type: ignore[arg-type]

    def launch_app(self, app_id: str, app_name: str, url: str) -> None:
        """Launches an installed Smart TV application."""
        launch_app(self, app_id=app_id, app_name=app_name, url=url)  # type: ignore[arg-type]

    async def async_launch_app(self, app_id: str, app_name: str, url: str) -> bool:
        """Launches an installed Smart TV application asynchronously."""
        return await async_launch_app(self, app_id=app_id, app_name=app_name, url=url)  # type: ignore[arg-type]

    def send_text_input(self, text: str, action: str = "insert") -> None:
        """Sends virtual keyboard string input to active on-screen input/search field."""
        send_text_input(self, text=text, action=action)  # type: ignore[arg-type]

    async def async_send_text_input(self, text: str, action: str = "insert") -> bool:
        """Sends virtual keyboard string input asynchronously."""
        return await async_send_text_input(self, text=text, action=action)  # type: ignore[arg-type]
