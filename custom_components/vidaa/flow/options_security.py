"""Security and certificate options flow mixin for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries

try:
    from homeassistant.components.file_upload import process_uploaded_file
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def process_uploaded_file(hass, file_id):
        yield Path(file_id)


from homeassistant.helpers import selector

from ..const import (
    AUTH_PROFILE_SELECTOR,
    BRAND_SELECTOR,
    CONF_AUTH_PROFILE,
    CONF_BRAND,
    CONF_CERT_FILE,
    CONF_CERTFILE,
    CONF_KEYFILE,
    CONF_USE_SSL,
    DEFAULT_AUTH_PROFILE,
    DEFAULT_BRAND_OPTION,
    DEFAULT_USE_SSL,
)
from ..protocol import check_certs_exist, extract_and_install_certs, validate_ssl_certs
from .helpers import unwrap_section_data

if TYPE_CHECKING:
    from .options import VidaaOptionsFlowHandler

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "OptionsSecurityMixin",
    "check_certs_exist",
    "extract_and_install_certs",
    "validate_ssl_certs",
]


class OptionsSecurityMixin:
    """Mixin providing SSL, authentication profile, and certificate management for options flow."""

    async def async_step_security(
        self: VidaaOptionsFlowHandler, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """SSL / TLS encryption, auth profile, and client certificate paths."""
        errors: dict[str, str] = {}
        options = self.config_entry.options
        data = self.config_entry.data

        current_profile = options.get(CONF_AUTH_PROFILE, data.get(CONF_AUTH_PROFILE, DEFAULT_AUTH_PROFILE))
        current_brand = options.get(CONF_BRAND, data.get(CONF_BRAND, DEFAULT_BRAND_OPTION))
        current_use_ssl = options.get(CONF_USE_SSL, data.get(CONF_USE_SSL, DEFAULT_USE_SSL))
        current_cert = options.get(CONF_CERTFILE, data.get(CONF_CERTFILE, ""))
        current_key = options.get(CONF_KEYFILE, data.get(CONF_KEYFILE, ""))

        if user_input is not None:
            user_input = unwrap_section_data(user_input)
            uploaded_file_id = user_input.pop(CONF_CERT_FILE, None)
            if uploaded_file_id:
                try:
                    storage_dir = (
                        Path(self.hass.config.path(".storage", "vidaa", "certs"))
                        if hasattr(self, "hass") and hasattr(self.hass, "config")
                        else Path("/config/.storage/vidaa/certs")
                    )

                    def _extract(file_id: str, dest: Path) -> tuple[str, str]:
                        with process_uploaded_file(self.hass, file_id) as uploaded_path:
                            return extract_and_install_certs(uploaded_path, dest)

                    if hasattr(self, "hass") and self.hass:
                        extracted = await self.hass.async_add_executor_job(_extract, uploaded_file_id, storage_dir)
                    else:
                        loop = asyncio.get_running_loop()
                        extracted = await loop.run_in_executor(None, _extract, uploaded_file_id, storage_dir)

                    user_input[CONF_CERTFILE] = extracted[0]
                    user_input[CONF_KEYFILE] = extracted[1]
                except ValueError as ex:
                    _LOGGER.warning("Failed to extract uploaded cert in options flow: %s", ex)
                    err_msg = str(ex).lower()
                    if "size limit" in err_msg or "exceeds maximum" in err_msg:
                        errors["base"] = "file_too_large"
                    elif "decrypt" in err_msg:
                        errors["base"] = "p12_decrypt_failed"
                    elif "both a certificate and" in err_msg or "malformed" in err_msg or "failed parsing" in err_msg:
                        errors["base"] = "invalid_pem_bundle"
                    elif "no vidaa pkcs#12" in err_msg:
                        errors["base"] = "no_p12_found"
                    else:
                        errors["base"] = "invalid_cert_archive"
                except Exception as ex:
                    _LOGGER.warning("Unexpected error during certificate extraction in options flow: %s", ex)
                    errors["base"] = "invalid_cert_archive"

            new_cert = (user_input.get(CONF_CERTFILE) or "").strip()
            new_key = (user_input.get(CONF_KEYFILE) or "").strip()

            if not errors and (new_cert or new_key):
                mod_opts = sys.modules.get("custom_components.vidaa.flow.options")
                active_check_exist = getattr(mod_opts, "check_certs_exist", check_certs_exist)
                active_validate_ssl = getattr(mod_opts, "validate_ssl_certs", validate_ssl_certs)

                async def _check_exist(c: str | None, k: str | None) -> bool:
                    if hasattr(self, "hass") and self.hass:
                        return await self.hass.async_add_executor_job(active_check_exist, c, k)
                    loop = asyncio.get_running_loop()
                    return await loop.run_in_executor(None, active_check_exist, c, k)

                certs_exist = await _check_exist(new_cert, new_key)
                if not certs_exist:
                    cert_exists = await _check_exist(new_cert, new_cert) if new_cert else False
                    key_exists = await _check_exist(new_key, new_key) if new_key else False

                    if new_cert and not cert_exists:
                        errors[CONF_CERTFILE] = "certs_not_found"
                    elif new_key and not key_exists:
                        errors[CONF_KEYFILE] = "certs_not_found"
                    else:
                        errors["base"] = "certs_not_found"
                else:

                    async def _validate(c: str | None, k: str | None) -> tuple[bool, str | None]:
                        if hasattr(self, "hass") and self.hass:
                            return await self.hass.async_add_executor_job(active_validate_ssl, c, k)
                        loop = asyncio.get_running_loop()
                        return await loop.run_in_executor(None, active_validate_ssl, c, k)

                    valid, _ = await _validate(new_cert, new_key)
                    if not valid:
                        errors["base"] = "invalid_ssl_cert"

            if not errors:
                updated_options = {**self.config_entry.options, **user_input}
                new_brand = user_input.get(CONF_BRAND)
                if new_brand and new_brand != current_brand:
                    new_data = {**self.config_entry.data, CONF_BRAND: new_brand}
                    self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                return self.async_create_entry(title="", data=updated_options)

        try:
            from homeassistant.data_entry_flow import section

            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_AUTH_PROFILE,
                        default=current_profile,
                    ): AUTH_PROFILE_SELECTOR,
                    vol.Optional(
                        CONF_BRAND,
                        default=current_brand,
                    ): BRAND_SELECTOR,
                    vol.Optional(CONF_CERT_FILE): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".apk,.xapk,.p12,.pfx,.pem,.crt")
                    ),
                    vol.Optional("manual_certificates"): section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    CONF_USE_SSL,
                                    default=current_use_ssl,
                                ): bool,
                                vol.Optional(
                                    CONF_CERTFILE,
                                    default=current_cert,
                                ): str,
                                vol.Optional(
                                    CONF_KEYFILE,
                                    default=current_key,
                                ): str,
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            )
        except (ImportError, AttributeError):
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_AUTH_PROFILE,
                        default=current_profile,
                    ): AUTH_PROFILE_SELECTOR,
                    vol.Optional(
                        CONF_BRAND,
                        default=current_brand,
                    ): BRAND_SELECTOR,
                    vol.Optional(
                        CONF_USE_SSL,
                        default=current_use_ssl,
                    ): bool,
                    vol.Optional(CONF_CERT_FILE): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".apk,.xapk,.p12,.pfx,.pem,.crt")
                    ),
                    vol.Optional(
                        CONF_CERTFILE,
                        default=current_cert,
                    ): str,
                    vol.Optional(
                        CONF_KEYFILE,
                        default=current_key,
                    ): str,
                }
            )

        return self.async_show_form(
            step_id="security",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_certs(
        self: VidaaOptionsFlowHandler, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Backward-compatible alias for security."""
        return await self.async_step_security(user_input)
