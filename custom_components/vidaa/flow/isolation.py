"""Multi-TV isolation, MAC normalization, and duplicate-entry detection helpers."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

from ..const import (
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
    DOMAIN,
)

__all__ = [
    "cert_path_in_use_by_other_entries",
    "entry_mac_addresses",
    "find_conflicting_entry",
    "normalize_mac_str",
    "sanitize_cert_scope",
]


def normalize_mac_str(value: Any) -> str | None:
    """Normalize a MAC address to lowercase colon-separated format, or None if invalid."""
    if not isinstance(value, str):
        return None
    stripped = value.replace(":", "").replace("-", "").replace(".", "").strip().lower()
    if len(stripped) != 12 or not all(ch in "0123456789abcdef" for ch in stripped):
        return None
    return ":".join(stripped[i : i + 2] for i in range(0, 12, 2))


def sanitize_cert_scope(scope: str | None) -> str | None:
    """Sanitize a config entry ID, MAC, or IP into a safe directory component."""
    if not isinstance(scope, str):
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", scope.strip().lower()).strip("_")
    return cleaned or None


def cert_path_in_use_by_other_entries(
    hass: Any,
    path_str: str,
    *,
    exclude_entry_id: str | None = None,
) -> bool:
    """Return True if any other config entry references ``path_str``."""
    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None or not hasattr(config_entries, "async_entries"):
        return False

    try:
        entries = config_entries.async_entries(DOMAIN)
    except Exception:
        return False
    if not isinstance(entries, Iterable):
        return False

    target = os.path.abspath(path_str)
    for entry in entries:
        if exclude_entry_id and getattr(entry, "entry_id", None) == exclude_entry_id:
            continue
        for mapping in (getattr(entry, "data", None), getattr(entry, "options", None)):
            if not isinstance(mapping, dict):
                continue
            for key in (CONF_CERTFILE, CONF_KEYFILE):
                val = mapping.get(key)
                if isinstance(val, str) and val and os.path.abspath(val) == target:
                    return True
    return False


def entry_mac_addresses(entry: Any) -> set[str]:
    """Return all normalized MAC addresses associated with a config entry."""
    macs: set[str] = set()
    uid = normalize_mac_str(getattr(entry, "unique_id", None))
    if uid:
        macs.add(uid)

    data = getattr(entry, "data", None)
    if isinstance(data, dict):
        for key in (CONF_MAC_ADDRESS, CONF_SECONDARY_MAC_ADDRESS):
            if mac := normalize_mac_str(data.get(key)):
                macs.add(mac)

    options = getattr(entry, "options", None)
    if isinstance(options, dict) and (mac := normalize_mac_str(options.get(CONF_SECONDARY_MAC_ADDRESS))):
        macs.add(mac)

    rt_data = getattr(entry, "runtime_data", None)
    if isinstance(rt_data, dict):
        client = rt_data.get("client")
    elif rt_data is not None:
        client = getattr(rt_data, "client", rt_data)
    else:
        client = None
    if client is not None:
        for attr in ("mac", "secondary_mac", "mac_wifi", "mac_ethernet"):
            if mac := normalize_mac_str(getattr(client, attr, None)):
                macs.add(mac)

    return macs


def find_conflicting_entry(
    entries: Iterable[Any],
    *,
    ip_address: str | None = None,
    macs: Iterable[str | None] = (),
    exclude_entry_id: str | None = None,
) -> tuple[Any | None, str | None]:
    """Find an existing config entry matching any candidate MAC or IP address."""
    candidate_macs = {m for raw in macs if (m := normalize_mac_str(raw))}
    target_ip = ip_address.strip() if isinstance(ip_address, str) and ip_address.strip() else None

    for entry in entries:
        if exclude_entry_id and getattr(entry, "entry_id", None) == exclude_entry_id:
            continue
        if candidate_macs and candidate_macs.intersection(entry_mac_addresses(entry)):
            return entry, "mac"
        if target_ip:
            data = getattr(entry, "data", None)
            if isinstance(data, dict) and data.get(CONF_IP_ADDRESS) == target_ip:
                return entry, "ip"
    return None, None
