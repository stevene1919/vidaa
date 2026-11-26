"""TV power actions and initial query operations for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from typing import TYPE_CHECKING

from ..const import DEFAULT_WOL_TIMEOUT

POWER_TOGGLE_COOLDOWN: float = 2.0
STANDBY_WAKE_SETTLE_DELAY: float = 0.3

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


def _resolve_mac_targets(client: VidaaClient, mac_targets: list[str] | None) -> list[str]:
    """Return Wake-on-LAN MAC targets from explicit override or client defaults."""
    if mac_targets is not None:
        return [m for m in mac_targets if m]
    targets: list[str] = []
    if getattr(client, "mac", None):
        targets.append(client.mac)
    if getattr(client, "secondary_mac", None) and client.secondary_mac not in targets:
        targets.append(client.secondary_mac)
    return targets


def _is_confirmed_standby(client: VidaaClient) -> bool:
    """Return True if a standby telemetry packet arrived during the current MQTT session."""
    conn_time = getattr(client, "_connected_time", 0.0)
    last_standby = getattr(client, "_last_standby_time", 0.0)
    return (
        isinstance(last_standby, (int, float)) and isinstance(conn_time, (int, float)) and last_standby >= conn_time > 0
    )


def turn_on_tv(
    client: VidaaClient,
    mac_targets: list[str] | None = None,
    settle_delay: float = STANDBY_WAKE_SETTLE_DELAY,
) -> None:
    """Powers on or wakes the TV safely and idempotently."""
    if client.connected and client.is_on:
        client.is_on = True
        _LOGGER.debug(
            "[%s] TV already connected and running. Skipping KEY_POWER to prevent powering down",
            getattr(client, "ip", "unknown"),
        )
        return

    targets = _resolve_mac_targets(client, mac_targets)

    if targets:
        client.send_wake_on_lan(targets, ip=getattr(client, "ip", None))

    if client.connected:
        now = time.time()
        last_wake = getattr(client, "_last_wake_time", 0.0)
        if isinstance(last_wake, (int, float)) and now - last_wake < 3.0:
            client.is_on = True
            _LOGGER.debug(
                "[%s] TV waking broadcast arrived recently (%.2fs ago). Skipping KEY_POWER to prevent inverting power",
                getattr(client, "ip", "unknown"),
                now - last_wake,
            )
            return

        last_toggle = getattr(client, "_last_power_toggle_time", 0.0)
        if isinstance(last_toggle, (int, float)) and now - last_toggle < POWER_TOGGLE_COOLDOWN:
            client.is_on = True
            _LOGGER.debug(
                "[%s] Suppressing duplicate KEY_POWER toggle within %.1fs cooldown",
                getattr(client, "ip", "unknown"),
                POWER_TOGGLE_COOLDOWN,
            )
            return

        if settle_delay > 0:
            time.sleep(settle_delay)

        lw_check = getattr(client, "_last_wake_time", 0.0)
        recent_wake = isinstance(lw_check, (int, float)) and (time.time() - lw_check < 3.0)
        if client.is_on or recent_wake:
            client.is_on = True
            _LOGGER.debug(
                "[%s] TV waking broadcast arrived during settle window. Skipping KEY_POWER",
                getattr(client, "ip", "unknown"),
            )
            return

        _LOGGER.debug(
            "[%s] TV connected in standby/fake_sleep. Sending KEY_POWER to wake screen",
            getattr(client, "ip", "unknown"),
        )
        client._last_power_toggle_time = time.time()
        client.send_key("KEY_POWER")
        client.is_on = True
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
                        if _is_confirmed_standby(client):
                            _LOGGER.debug(
                                "[%s] TV reconnected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                                getattr(client, "ip", "unknown"),
                            )
                            client.send_key("KEY_POWER")
                        else:
                            _LOGGER.debug(
                                "[%s] TV reconnected and is booting/awake. Skipping KEY_POWER to prevent powering down",
                                getattr(client, "ip", "unknown"),
                            )
                        client.is_on = True
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
    settle_delay: float = STANDBY_WAKE_SETTLE_DELAY,
) -> bool:
    """Powers on or wakes the TV safely and idempotently asynchronously."""
    if client.connected and client.is_on:
        client.is_on = True
        _LOGGER.debug(
            "[%s] TV already connected and running. Skipping KEY_POWER to prevent powering down",
            getattr(client, "ip", "unknown"),
        )
        return True

    targets = _resolve_mac_targets(client, mac_targets)

    if targets:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, functools.partial(client.send_wake_on_lan, targets, ip=getattr(client, "ip", None))
        )

    if client.connected:
        now = time.time()
        last_wake = getattr(client, "_last_wake_time", 0.0)
        if isinstance(last_wake, (int, float)) and now - last_wake < 3.0:
            client.is_on = True
            _LOGGER.debug(
                "[%s] TV waking broadcast arrived recently (%.2fs ago). Skipping KEY_POWER to prevent inverting power",
                getattr(client, "ip", "unknown"),
                now - last_wake,
            )
            return True

        last_toggle = getattr(client, "_last_power_toggle_time", 0.0)
        if isinstance(last_toggle, (int, float)) and now - last_toggle < POWER_TOGGLE_COOLDOWN:
            client.is_on = True
            _LOGGER.debug(
                "[%s] Suppressing duplicate KEY_POWER toggle within %.1fs cooldown",
                getattr(client, "ip", "unknown"),
                POWER_TOGGLE_COOLDOWN,
            )
            return True

        if settle_delay > 0:
            await asyncio.sleep(settle_delay)

        lw_check = getattr(client, "_last_wake_time", 0.0)
        recent_wake = isinstance(lw_check, (int, float)) and (time.time() - lw_check < 3.0)
        if client.is_on or recent_wake:
            client.is_on = True
            _LOGGER.debug(
                "[%s] TV waking broadcast arrived during settle window. Skipping KEY_POWER",
                getattr(client, "ip", "unknown"),
            )
            return True

        _LOGGER.debug(
            "[%s] TV connected in standby/fake_sleep. Sending KEY_POWER to wake screen",
            getattr(client, "ip", "unknown"),
        )
        client._last_power_toggle_time = time.time()
        res = await client.async_send_key("KEY_POWER")
        if res is not False:
            client.is_on = True
            return True
        return False

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
            now = time.time()
            lw_check = getattr(client, "_last_wake_time", 0.0)
            recent_wake = isinstance(lw_check, (int, float)) and (now - lw_check < 3.0)
            if client.is_on or recent_wake:
                _LOGGER.debug(
                    "[%s] TV reconnected and is already awake. Skipping KEY_POWER to prevent powering down",
                    getattr(client, "ip", "unknown"),
                )
                client.is_on = True
                return True

            last_toggle = getattr(client, "_last_power_toggle_time", 0.0)
            if isinstance(last_toggle, (int, float)) and now - last_toggle < POWER_TOGGLE_COOLDOWN:
                _LOGGER.debug(
                    "[%s] Suppressing duplicate KEY_POWER toggle within %.1fs cooldown",
                    getattr(client, "ip", "unknown"),
                    POWER_TOGGLE_COOLDOWN,
                )
                client.is_on = True
                return True

            if _is_confirmed_standby(client):
                _LOGGER.debug(
                    "[%s] TV reconnected in standby/fake_sleep. Sending KEY_POWER to wake screen",
                    getattr(client, "ip", "unknown"),
                )
                client._last_power_toggle_time = time.time()
                res = await client.async_send_key("KEY_POWER")
                if res is not False:
                    client.is_on = True
                    return True
                break

            _LOGGER.debug(
                "[%s] TV reconnected after WoL/cold-boot. No standby signal received; skipping KEY_POWER to allow boot to complete",
                getattr(client, "ip", "unknown"),
            )
            client.is_on = True
            return True
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
    client.is_on = False
    return True


class TvPowerActionsMixin:
    """Mixin providing TV power lifecycle and state query operations."""

    def query_initial_state(self) -> None:
        """Queries initial state, volume, source list, app list, and settings from TV."""
        query_initial_state(self)  # type: ignore[arg-type]

    async def async_query_initial_state(self, min_interval: float = 3.0) -> None:
        """Queries initial state, volume, source list, app list, and settings asynchronously."""
        await async_query_initial_state(self, min_interval=min_interval)  # type: ignore[arg-type]

    def turn_on(self, mac_targets: list[str] | None = None, settle_delay: float = STANDBY_WAKE_SETTLE_DELAY) -> None:
        """Powers on or wakes the TV safely and idempotently."""
        turn_on_tv(self, mac_targets=mac_targets, settle_delay=settle_delay)  # type: ignore[arg-type]

    async def async_turn_on(
        self,
        mac_targets: list[str] | None = None,
        timeout: float = DEFAULT_WOL_TIMEOUT,
        settle_delay: float = STANDBY_WAKE_SETTLE_DELAY,
    ) -> bool:
        """Powers on or wakes the TV safely and idempotently asynchronously."""
        return await async_turn_on_tv(
            self,  # type: ignore[arg-type]
            mac_targets=mac_targets,
            timeout=timeout,
            settle_delay=settle_delay,
        )

    def turn_off(self) -> None:
        """Powers off the TV safely."""
        turn_off_tv(self)  # type: ignore[arg-type]

    async def async_turn_off(self) -> bool:
        """Powers off the TV safely asynchronously."""
        return await async_turn_off_tv(self)  # type: ignore[arg-type]
