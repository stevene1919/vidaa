"""Reauthentication and reconfiguration flow mixin for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    AUTH_PROFILE_SELECTOR,
    BRAND_SELECTOR,
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_USE_SSL,
    DEFAULT_AUTH_PROFILE,
    DEFAULT_BRAND,
    DEFAULT_BRAND_OPTION,
    DEFAULT_USE_SSL,
    DOMAIN,
)
from .helpers import async_resolve_mac

if TYPE_CHECKING:
    from ..config_flow import VidaaConfigFlow

_LOGGER = logging.getLogger(__name__)

REAUTH_WAKE_TIMEOUT = 20.0
REAUTH_BROKER_SETTLE = 3.0


class ReauthFlowMixin:
    """Mixin for reauthentication and reconfiguration flow steps."""

    async def _async_finish_reauth(
        self: VidaaConfigFlow, reason: str = "reauth_successful"
    ) -> config_entries.ConfigFlowResult:
        """Update existing config entry with new credentials and reload."""
        if self._reauth_entry:
            auth_data = self._get_client_auth_data()
            if self.client:
                await self.client.async_disconnect()
                self.client = None

            # [CRITICAL-01] Synchronize entry.options so that overridden brand,
            # auth profile, or SSL settings do not diverge from the newly paired credentials.
            orig_options = (
                dict(self._reauth_entry.options)
                if isinstance(getattr(self._reauth_entry, "options", None), dict)
                else {}
            )
            new_options = dict(orig_options)
            for opt_key in (CONF_BRAND, CONF_AUTH_PROFILE, CONF_USE_SSL, CONF_CERTFILE, CONF_KEYFILE):
                if opt_key in orig_options and opt_key in auth_data:
                    new_options[opt_key] = auth_data[opt_key]

            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data={**self._reauth_entry.data, **auth_data},
                options=new_options,
            )
            # [F4-leg2/F5-leg6]: the credentials are fresh again, so the
            # persistent "reauthentication required" card must go away.
            ir.async_delete_issue(
                self.hass,
                DOMAIN,
                f"auth_token_invalidated_{self._reauth_entry.entry_id}",
            )
            persistent_notification.async_dismiss(
                self.hass,
                f"vidaa_reauth_{self._reauth_entry.entry_id}",
            )
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason=reason)

    def _async_mac_is_configured_elsewhere(
        self: VidaaConfigFlow,
    ) -> bool:
        """Check whether the resolved MAC already belongs to another entry.

        [F7-leg6]: the duplicate/unique-id guard of `_async_init_client_and_auth`
        is skipped whenever `_reauth_entry` is set, which would silently repoint
        an entry at a different TV while keeping its old unique_id.
        """
        if not self.mac_address or not self._reauth_entry:
            return False
        for other in self.hass.config_entries.async_entries(DOMAIN):
            if other.entry_id == self._reauth_entry.entry_id:
                continue
            if other.unique_id == self.mac_address:
                return True
        return False

    async def async_step_reauth(self: VidaaConfigFlow, entry_data: dict[str, Any]) -> config_entries.ConfigFlowResult:
        """Handle reauthorization initiated by Home Assistant."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        current_options = (
            dict(self._reauth_entry.options)
            if self._reauth_entry and isinstance(getattr(self._reauth_entry, "options", None), dict)
            else {}
        )
        self.ip_address = entry_data[CONF_IP_ADDRESS]
        self.mac_address = entry_data.get(CONF_MAC_ADDRESS)
        if not self.mac_address and self.ip_address:
            self.mac_address = await async_resolve_mac(self.hass, self.ip_address)
        self.auth_profile = current_options.get(
            CONF_AUTH_PROFILE, entry_data.get(CONF_AUTH_PROFILE, DEFAULT_AUTH_PROFILE)
        )
        # [F3-leg2]: reauth must keep the transport settings of the entry it is
        # re-authenticating (a legacy/non-TLS entry would otherwise be rewritten
        # as use_ssl=True by _get_client_auth_data on success).
        self.use_ssl = current_options.get(CONF_USE_SSL, entry_data.get(CONF_USE_SSL, DEFAULT_USE_SSL))
        self.brand = current_options.get(CONF_BRAND, entry_data.get(CONF_BRAND, DEFAULT_BRAND))
        self.certfile = current_options.get(CONF_CERTFILE, entry_data.get(CONF_CERTFILE))
        self.keyfile = current_options.get(CONF_KEYFILE, entry_data.get(CONF_KEYFILE))
        return await self.async_step_reauth_confirm()

    async def _async_port_open(self, ip: str, port: int, timeout: float = 1.0) -> bool:
        """Check if target TCP port is open and accepting connections."""
        try:
            conn = asyncio.open_connection(ip, port)
            _reader, writer = await asyncio.wait_for(conn, timeout=timeout)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _async_wake_tv_for_pairing(self: VidaaConfigFlow) -> bool:
        """Ensure the TV is awake enough to display a PIN. Returns True when reachable."""
        if not self.ip_address:
            return False
        if await self._async_port_open(self.ip_address, 36669, timeout=1.5):
            return True

        macs = [
            m
            for m in (
                self.mac_address,
                self._reauth_entry.options.get(CONF_SECONDARY_MAC_ADDRESS) if self._reauth_entry else None,
                self._reauth_entry.data.get(CONF_SECONDARY_MAC_ADDRESS) if self._reauth_entry else None,
            )
            if m
        ]
        if not macs:
            return False

        _LOGGER.info("[%s] TV not reachable on port 36669; sending Wake-on-LAN before reauth", self.ip_address)
        from functools import partial

        from ..protocol.wol import send_wake_on_lan

        await self.hass.async_add_executor_job(partial(send_wake_on_lan, list(dict.fromkeys(macs)), ip=self.ip_address))

        deadline = time.monotonic() + REAUTH_WAKE_TIMEOUT
        while time.monotonic() < deadline:
            if await self._async_port_open(self.ip_address, 36669, timeout=1.0):
                await asyncio.sleep(REAUTH_BROKER_SETTLE)
                return True
            await asyncio.sleep(1.0)
        return False

    async def async_step_reauth_confirm(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Dialog to confirm reauth and trigger PIN."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Disconnect any existing running client for this entry to prevent
            # duplicate MQTT Client ID collisions during the reauth flow.
            await self._async_disconnect_existing_client()

            if not await self._async_wake_tv_for_pairing():
                errors["base"] = "tv_not_awake"
                return self.async_show_form(
                    step_id="reauth_confirm",
                    description_placeholders={"ip_address": self.ip_address or ""},
                    errors=errors,
                )

            if self.use_ssl and not (self.certfile and self.keyfile):
                await self._async_resolve_ssl_certs()

            session = async_get_clientsession(self.hass) if self.hass else None
            from ..client import VidaaClient

            self.client = VidaaClient(
                self.ip_address,
                self.mac_address,
                auth_profile=self.auth_profile,
                certfile=self.certfile if self.use_ssl else None,
                keyfile=self.keyfile if self.use_ssl else None,
                use_ssl=self.use_ssl,
                brand=self.brand,
                session=session,
            )
            self.client._loop = self.hass.loop
            try:
                await self.client.async_start_auth()
                if self.client.brand and self.client.brand != self.brand:
                    self.brand = self.client.brand

                if self.auth_profile in ("legacy", "static"):
                    # The TV may demand a one-off PIN pairing.
                    return await self._async_static_pairing_step(True, "reauth_successful")
                return await self.async_step_auth()
            except AbortFlow:
                # HA flow control must never be reported as cannot_connect.
                raise
            except Exception as e:
                _LOGGER.warning("[%s] Failed to connect to TV for reauth: %s", self.ip_address, e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"ip_address": self.ip_address or ""},
            errors=errors,
        )

    async def async_step_reconfigure(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfigure initiated from 3-dots menu in HA UI."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}
        current_data = (
            dict(self._reauth_entry.data)
            if self._reauth_entry and isinstance(getattr(self._reauth_entry, "data", None), dict)
            else {}
        )
        current_options = (
            dict(self._reauth_entry.options)
            if self._reauth_entry and isinstance(getattr(self._reauth_entry, "options", None), dict)
            else {}
        )
        self.brand = current_options.get(CONF_BRAND, current_data.get(CONF_BRAND, DEFAULT_BRAND_OPTION))
        default_ip = current_data.get(CONF_IP_ADDRESS, "")
        default_profile = current_options.get(
            CONF_AUTH_PROFILE, current_data.get(CONF_AUTH_PROFILE, DEFAULT_AUTH_PROFILE)
        )
        default_brand = self.brand

        if user_input is not None:
            self.ip_address = user_input[CONF_IP_ADDRESS]
            self.auth_profile = user_input.get(CONF_AUTH_PROFILE, DEFAULT_AUTH_PROFILE)
            self.brand = user_input.get(CONF_BRAND, default_brand)
            # [F7-leg6]: the entry may be repointed at a different TV, so the MAC
            # must be resolved for the *new* IP before the target is re-paired.
            self.mac_address = await async_resolve_mac(self.hass, self.ip_address)
            if not self.mac_address:
                self.mac_address = current_data.get(CONF_MAC_ADDRESS)

            # [F7-leg6]: only the entry being reconfigured may keep this MAC.
            if self._async_mac_is_configured_elsewhere():
                return self.async_abort(reason="already_configured")

            if self.auth_profile in ("legacy", "static"):
                has_certs = await self._async_resolve_ssl_certs()
                if not has_certs:
                    self.certfile = None
                    self.keyfile = None
            elif self.auth_profile == "auto":
                if not await self._async_resolve_ssl_certs():
                    return await self.async_step_certs()
            else:
                return await self.async_step_certs()

            try:
                return await self._async_init_client_and_auth(is_reauth=True, reauth_reason="reconfigure_successful")
            except AbortFlow:
                raise
            except Exception as e:
                _LOGGER.warning("[%s] Failed to initiate reconfigure pairing: %s", self.ip_address, e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default=default_ip): str,
                    vol.Optional(CONF_AUTH_PROFILE, default=default_profile): AUTH_PROFILE_SELECTOR,
                    vol.Optional(CONF_BRAND, default=default_brand): BRAND_SELECTOR,
                }
            ),
            errors=errors,
        )
