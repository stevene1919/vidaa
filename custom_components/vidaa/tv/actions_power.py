"""TV power actions and initial query operations for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from typing import TYPE_CHECKING

from ..const import DEFAULT_WOL_TIMEOUT

if TYPE_CHECKING:
    from ..client import VidaaClient

_LOGGER = logging.getLogger(__name__)


def query_initial_state(client: VidaaClient, min_interval: float = 3.0) -> None:
    """Queries initial state, volume, source list, app list, and settings from TV."""
    if not (client.connected and client.mqtt_client):
        return

    now = time.time()
    with getattr(client, "_query_lock", contextlib.nullcontext()):
        last_time = getattr(client, "_last_initial_query_time", 0.0)
        if now - last_time < min_interval:
            _LOGGER.debug(
                "[%s] Suppressing duplicate query_initial_state call (%.2fs since last query)",
                client.ip,
                now - last_time,
            )
            return
        client._last_initial_query_time = now

        # The TV already broadcasts its live state automatically on
        # /remoteapp/mobile/broadcast/ui_service/state upon MQTT connect.
        # Do NOT publish actions/gettvstate: on VIDAA firmware, gettvstate
        # is the pairing challenge trigger that commands the TV to pop up a PIN.
        client.mqtt_client.publish(f"{client.topics.ui}actions/capability", "")
        time.sleep(0.05)
        client.mqtt_client.publish(f"{client.topics.platform}actions/getvolume", "")
        time.sleep(0.05)
        client.mqtt_client.publish(f"{client.topics.ui}actions/sourcelist", "")
        time.sleep(0.05)
        client.mqtt_client.publish(f"{client.topics.ui}actions/applist", "")
        time.sleep(0.05)
        client.mqtt_client.publish(f"{client.topics.platform}actions/getdeviceinfo", "")
        time.sleep(0.05)
        client.mqtt_client.publish(f"{client.topics.platform}actions/gettvinfo", "")


async def async_query_initial_state(client: VidaaClient, min_interval: float = 3.0) -> None:
    """Queries initial state, volume, source list, app list, and settings from TV asynchronously."""
    if not (client.connected and client.mqtt_client):
        return

    now = time.time()
    last_time = getattr(client, "_last_initial_query_time", 0.0)
    if now - last_time < min_interval:
        _LOGGER.debug(
            "[%s] Suppressing duplicate query_initial_state call (%.2fs since last query)",
            getattr(client, "ip", "unknown"),
            now - last_time,
        )
        return
    client._last_initial_query_time = now

    topics = [
        f"{client.topics.ui}actions/capability",
        f"{client.topics.platform}actions/getvolume",
        f"{client.topics.ui}actions/sourcelist",
        f"{client.topics.ui}actions/applist",
        f"{client.topics.platform}actions/getdeviceinfo",
        f"{client.topics.platform}actions/gettvinfo",
    ]
    for topic in topics:
        await client.async_publish(topic, "")
        await asyncio.sleep(0.05)


def turn_on_tv(
    client: VidaaClient,
    mac_targets: list[str] | None = None,
) -> None:
    """Powers on or wakes the TV safely and idempotently."""
    targets = list(mac_targets) if mac_targets else []
    if not targets:
        if getattr(client, "mac", None):
            targets.append(client.mac)
        if getattr(client, "secondary_mac", None) and client.secondary_mac not in targets:
            targets.append(client.secondary_mac)
    if targets:
        client.send_wake_on_lan(targets, ip=getattr(client, "ip", None))

    if client.connected:
        if not client.is_on and getattr(client, "has_active_signal", False) is not True:
            _LOGGER.debug(
                "[%s] TV connected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                getattr(client, "ip", "unknown"),
            )
            client.send_key("KEY_POWER")
            client.is_on = True
        else:
            client.is_on = True
            _LOGGER.debug(
                "[%s] TV already connected and running. Skipping KEY_POWER to prevent powering down",
                getattr(client, "ip", "unknown"),
            )
    else:
        _LOGGER.debug(
            "[%s] TV MQTT not connected. Attempting reconnect to check power state",
            getattr(client, "ip", "unknown"),
        )
        try:
            if client.ensure_connected():
                for _ in range(50):
                    if client.connected:
                        # Allow initial state broadcast (ui_service/state, gettvinfo) to arrive
                        # so we do not toggle off a TV that already woke via Wake-on-LAN.
                        time.sleep(1.0)
                        if not client.is_on and getattr(client, "has_active_signal", False) is not True:
                            _LOGGER.debug(
                                "[%s] TV reconnected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                                getattr(client, "ip", "unknown"),
                            )
                            client.send_key("KEY_POWER")
                        else:
                            _LOGGER.debug(
                                "[%s] TV reconnected and is already awake. Skipping KEY_POWER to prevent powering down",
                                getattr(client, "ip", "unknown"),
                            )
                        break
                    time.sleep(0.1)
        except Exception as e:
            _LOGGER.error(
                "[%s] Failed to reconnect and send KEY_POWER: %s",
                getattr(client, "ip", "unknown"),
                e,
            )

    if client.connected and client.is_on:
        return


async def async_turn_on_tv(
    client: VidaaClient,
    mac_targets: list[str] | None = None,
    timeout: float = DEFAULT_WOL_TIMEOUT,
) -> bool:
    """Powers on or wakes the TV safely and idempotently asynchronously."""
    targets = list(mac_targets) if mac_targets else []
    if not targets:
        if getattr(client, "mac", None):
            targets.append(client.mac)
        if getattr(client, "secondary_mac", None) and client.secondary_mac not in targets:
            targets.append(client.secondary_mac)
    if targets:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, functools.partial(client.send_wake_on_lan, targets, ip=getattr(client, "ip", None))
        )

    if client.connected:
        if not client.is_on and getattr(client, "has_active_signal", False) is not True:
            _LOGGER.debug(
                "[%s] TV connected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                getattr(client, "ip", "unknown"),
            )
            res = await client.async_send_key("KEY_POWER")
            if res is not False:
                client.is_on = True
                return True
            return False

        client.is_on = True
        _LOGGER.debug(
            "[%s] TV already connected and running. Skipping KEY_POWER to prevent powering down",
            getattr(client, "ip", "unknown"),
        )
        return True

    _LOGGER.debug(
        "[%s] TV MQTT not connected. Attempting reconnect to check power state",
        getattr(client, "ip", "unknown"),
    )
    if hasattr(client, "nudge_reconnect"):
        client.nudge_reconnect()
    try:
        if hasattr(client, "async_ensure_connected"):
            await client.async_ensure_connected()
    except Exception as e:
        _LOGGER.debug("[%s] Reconnect check during turn on: %s", getattr(client, "ip", "unknown"), e)

    max_wait = max(1.0, timeout)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if client.connected:
            # Wait for the TV's initial state broadcast (ui_service/state, gettvinfo)
            # before deciding whether KEY_POWER is needed, preventing a race where
            # a TV waking from deep sleep via WoL is toggled right back off.
            await asyncio.sleep(1.0)
            if not client.is_on and getattr(client, "has_active_signal", False) is not True:
                _LOGGER.debug(
                    "[%s] TV reconnected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                    getattr(client, "ip", "unknown"),
                )
                res = await client.async_send_key("KEY_POWER")
                if res is not False:
                    client.is_on = True
                    return True
            else:
                _LOGGER.debug(
                    "[%s] TV reconnected and is already awake. Skipping KEY_POWER to prevent powering down",
                    getattr(client, "ip", "unknown"),
                )
                client.is_on = True
                return True
            break
        await asyncio.sleep(0.1)

    return bool(client.connected and client.is_on)


def turn_off_tv(client: VidaaClient) -> None:
    """Powers off the TV safely."""
    if client.connected and client.is_on:
        client.send_key("KEY_POWER")
    client.is_on = False


async def async_turn_off_tv(client: VidaaClient) -> bool:
    """Powers off the TV safely asynchronously."""
    if client.connected and client.is_on:
        res = await client.async_send_key("KEY_POWER")
        if res is not False:
            client.is_on = False
            return True
        return False
    return not client.is_on


class TvPowerActionsMixin:
    """Mixin providing TV power lifecycle and state query operations."""

    def query_initial_state(self) -> None:
        """Queries initial state, volume, source list, app list, and settings from TV."""
        query_initial_state(self)  # type: ignore[arg-type]

    async def async_query_initial_state(self, min_interval: float = 3.0) -> None:
        """Queries initial state, volume, source list, app list, and settings asynchronously."""
        await async_query_initial_state(self, min_interval=min_interval)  # type: ignore[arg-type]

    def turn_on(self, mac_targets: list[str] | None = None) -> None:
        """Powers on or wakes the TV safely and idempotently."""
        turn_on_tv(self, mac_targets=mac_targets)  # type: ignore[arg-type]

    async def async_turn_on(self, mac_targets: list[str] | None = None, timeout: float = DEFAULT_WOL_TIMEOUT) -> bool:
        """Powers on or wakes the TV safely and idempotently asynchronously."""
        return await async_turn_on_tv(self, mac_targets=mac_targets, timeout=timeout)  # type: ignore[arg-type]

    def turn_off(self) -> None:
        """Powers off the TV safely."""
        turn_off_tv(self)  # type: ignore[arg-type]

    async def async_turn_off(self) -> bool:
        """Powers off the TV safely asynchronously."""
        return await async_turn_off_tv(self)  # type: ignore[arg-type]
