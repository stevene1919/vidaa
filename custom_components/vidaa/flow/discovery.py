"""Auto-discovery flow mixin for VIDAA Smart TV (SSDP & Zeroconf)."""

from __future__ import annotations

import logging
import ssl
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from ..const import CONF_IP_ADDRESS
from ..protocol import DiscoveredTvInfo, parse_ssdp_discovery, parse_zeroconf_discovery
from .helpers import async_resolve_mac
from .isolation import find_conflicting_entry

if TYPE_CHECKING:
    from ..config_flow import VidaaConfigFlow

_LOGGER = logging.getLogger(__name__)


class DiscoveryFlowMixin:
    """Mixin for SSDP and Zeroconf device discovery steps."""

    async def _async_handle_discovery(
        self: VidaaConfigFlow, parsed: DiscoveredTvInfo | None
    ) -> config_entries.ConfigFlowResult:
        """Handle common SSDP and Zeroconf device resolution and flow routing."""
        if not parsed or not parsed.host:
            return self.async_abort(reason="not_vidaa_tv" if parsed is None else "cannot_connect")

        self.ip_address = parsed.host
        self.discovered_title = parsed.title
        self.manufacturer = getattr(parsed, "manufacturer", None)
        self.model = getattr(parsed, "model", None)
        self.brand = getattr(parsed, "brand", "his") or "his"
        self.mac_address = parsed.mac_address
        self.secondary_mac_address = getattr(parsed, "secondary_mac_address", None)
        if not self.mac_address and parsed.host:
            self.mac_address = await async_resolve_mac(self.hass, parsed.host)

        unique_id = self.mac_address or parsed.unique_id
        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(updates={CONF_IP_ADDRESS: self.ip_address})

        if hasattr(self, "_async_current_entries"):
            existing, match_reason = find_conflicting_entry(
                self._async_current_entries(),
                ip_address=self.ip_address,
                macs=(self.mac_address, self.secondary_mac_address),
            )
            if existing is not None:
                if (
                    match_reason == "mac"
                    and self.ip_address
                    and getattr(existing, "data", {}).get(CONF_IP_ADDRESS) != self.ip_address
                    and hasattr(getattr(self, "hass", None), "config_entries")
                ):
                    self.hass.config_entries.async_update_entry(
                        existing,
                        data={**existing.data, CONF_IP_ADDRESS: self.ip_address},
                    )
                return self.async_abort(reason="already_configured")

        return await self.async_step_discovery_confirm()

    async def async_step_ssdp(
        self: VidaaConfigFlow, discovery_info: SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle SSDP discovery."""
        parsed = await self.hass.async_add_executor_job(parse_ssdp_discovery, discovery_info)
        return await self._async_handle_discovery(parsed)

    async def async_step_zeroconf(
        self: VidaaConfigFlow, discovery_info: ZeroconfServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle Zeroconf / mDNS discovery."""
        parsed = await self.hass.async_add_executor_job(parse_zeroconf_discovery, discovery_info)
        return await self._async_handle_discovery(parsed)

    async def async_step_discovery_confirm(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm discovery setup with user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            has_certs = await self._async_resolve_ssl_certs()
            if not has_certs and self.ip_address and getattr(self, "auth_profile", "auto") == "auto":
                # Check if this TV supports legacy static auth without client certs
                try:
                    from ..client import VidaaClient

                    probe_client = VidaaClient(
                        self.ip_address,
                        self.mac_address,
                        auth_profile="legacy",
                        brand=self.brand,
                        use_ssl=True,
                    )
                    probe = await probe_client.async_probe_auth_methods(1.5)
                    if probe.get("legacy_static", {}).get("supported"):
                        self.auth_profile = "legacy"
                        self.certfile = None
                        self.keyfile = None
                        self.use_ssl = True
                        has_certs = True
                except Exception as probe_err:
                    _LOGGER.debug("[%s] Discovery auth probe exception: %s", self.ip_address, probe_err)

            if has_certs:
                try:
                    return await self._async_init_client_and_auth()
                except AbortFlow:
                    # HA flow control (e.g. already_configured) must never be
                    # turned into cannot_connect.
                    raise
                except ssl.SSLError as e:
                    _LOGGER.warning("[%s] SSL handshake failed with existing certificates: %s", self.ip_address, e)
                    self.certfile = None
                    self.keyfile = None
                    self._upload_error = "invalid_ssl_cert"
                    return await self.async_step_upload()
                except Exception as e:
                    _LOGGER.warning(
                        "[%s] Failed to connect or initiate auth with TV: %s",
                        self.ip_address,
                        e,
                    )
                    errors["base"] = "cannot_connect"
            else:
                return await self.async_step_upload()

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self.discovered_title or self.ip_address or "VIDAA TV",
                "ip_address": self.ip_address or "",
            },
            errors=errors,
        )
