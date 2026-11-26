"""PIN authentication and static pairing mixin for VIDAA config flow."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..client import VidaaClient
from ..const import (
    BRAND_MAP,
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CERTFILE,
    CONF_IP_ADDRESS,
    CONF_KEYFILE,
    CONF_MAC_ADDRESS,
    CONF_USE_SSL,
    DEFAULT_AUTH_PROFILE,
    DEFAULT_BRAND,
    DEFAULT_USE_SSL,
)
from ..protocol.pairing import PairingStatusError, async_probe_pairing_challenge

if TYPE_CHECKING:
    from ..config_flow import VidaaConfigFlow

_LOGGER = logging.getLogger(__name__)

__all__ = ["AuthFlowMixin"]


def _get_client_class() -> type[VidaaClient]:
    cf = sys.modules.get("custom_components.vidaa.config_flow") or sys.modules.get(
        "custom_components.hisense_vidaa.config_flow"
    )
    if cf and hasattr(cf, "VidaaClient"):
        return cf.VidaaClient
    return VidaaClient


def _get_probe_challenge_fn() -> Any:
    cf = sys.modules.get("custom_components.vidaa.config_flow") or sys.modules.get(
        "custom_components.hisense_vidaa.config_flow"
    )
    if cf and hasattr(cf, "async_probe_pairing_challenge"):
        return cf.async_probe_pairing_challenge
    return async_probe_pairing_challenge


class AuthFlowMixin:
    """Mixin for TV PIN challenge authentication and static pairing steps."""

    async def _async_static_pairing_step(
        self: VidaaConfigFlow, is_reauth: bool, reauth_reason: str
    ) -> config_entries.ConfigFlowResult:
        """Probe a static session for a PIN challenge before continuing as before."""
        probe_fn = _get_probe_challenge_fn()
        try:
            challenged = await probe_fn(self.client)
        except PairingStatusError as e:
            _LOGGER.warning("[%s] TV pairing dialog %s during challenge probe", self.ip_address, e.status)
            self._pairing_error = "invalid_auth"
            return await self.async_step_auth()

        if challenged:
            return await self.async_step_auth()

        await self.client.async_disconnect()
        if is_reauth and self._reauth_entry:
            return await self._async_finish_reauth(reason=reauth_reason)
        await self._async_discover_device_name()
        await self._async_probe_device_capabilities()
        return await self.async_step_options()

    async def async_step_auth(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle PIN code entry step."""
        errors: dict[str, str] = {}
        if self._pairing_error:
            errors["base"] = self._pairing_error
            self._pairing_error = None

        if not self.client:
            if not self.ip_address and self._reauth_entry:
                opts = (
                    dict(self._reauth_entry.options)
                    if isinstance(getattr(self._reauth_entry, "options", None), dict)
                    else {}
                )
                data = (
                    dict(self._reauth_entry.data) if isinstance(getattr(self._reauth_entry, "data", None), dict) else {}
                )
                self.ip_address = data.get(CONF_IP_ADDRESS)
                self.mac_address = data.get(CONF_MAC_ADDRESS)
                self.auth_profile = opts.get(CONF_AUTH_PROFILE, data.get(CONF_AUTH_PROFILE, DEFAULT_AUTH_PROFILE))
                self.brand = opts.get(CONF_BRAND, data.get(CONF_BRAND, DEFAULT_BRAND))
                self.use_ssl = opts.get(CONF_USE_SSL, data.get(CONF_USE_SSL, DEFAULT_USE_SSL))
                self.certfile = opts.get(CONF_CERTFILE, data.get(CONF_CERTFILE))
                self.keyfile = opts.get(CONF_KEYFILE, data.get(CONF_KEYFILE))

            if self.ip_address:
                session = async_get_clientsession(self.hass) if self.hass else None
                client_cls = _get_client_class()
                self.client = client_cls(
                    self.ip_address,
                    self.mac_address,
                    auth_profile=self.auth_profile,
                    brand=self.brand,
                    session=session,
                    certfile=self.certfile,
                    keyfile=self.keyfile,
                    use_ssl=self.use_ssl,
                )
                self.client._loop = self.hass.loop
                try:
                    await self.client.async_start_auth()
                    if self.client.brand and self.client.brand != self.brand:
                        self.brand = self.client.brand
                        if self.brand in BRAND_MAP:
                            self.manufacturer = BRAND_MAP[self.brand]
                except Exception as e:
                    _LOGGER.warning("[%s] Failed to connect to TV to show PIN: %s", self.ip_address, e)
                    errors["base"] = "cannot_connect"

        if user_input is not None and self.client:
            pin_code = str(user_input["pin_code"]).strip().replace(" ", "").replace("-", "")
            try:
                await self.client.async_submit_pin(pin_code)
            except PairingStatusError as e:
                _LOGGER.warning("[%s] TV pairing dialog %s while submitting PIN", self.ip_address, e.status)
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.warning("[%s] Failed to validate PIN or retrieve tokens from TV: %s", self.ip_address, e)
                errors["base"] = "invalid_auth"
            else:
                if self._reauth_entry:
                    return await self._async_finish_reauth(reason=getattr(self, "_reauth_reason", "reauth_successful"))

                await self._async_discover_device_name()
                await self._async_probe_device_capabilities()
                if (
                    self.client
                    and self.client.brand
                    and self.client.brand != DEFAULT_BRAND
                    and self.brand == DEFAULT_BRAND
                ):
                    self.brand = self.client.brand
                return await self.async_step_options()

        reauth_entry = getattr(self, "_reauth_entry", None)
        entry_title = getattr(reauth_entry, "title", None) if reauth_entry else None
        tv_name = (
            getattr(self, "discovered_title", None)
            or (entry_title if isinstance(entry_title, str) and entry_title else None)
            or self.ip_address
            or "VIDAA TV"
        )
        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema(
                {
                    vol.Required("pin_code"): str,
                }
            ),
            description_placeholders={
                "name": str(tv_name),
                "ip_address": str(self.ip_address or ""),
            },
            errors=errors,
        )
