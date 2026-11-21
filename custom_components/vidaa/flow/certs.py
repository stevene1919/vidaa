"""Certificate handling mixin for VIDAA config flow."""

from __future__ import annotations

import asyncio
import logging
import ssl
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


from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector

from ..const import (
    BRAND_MAP,
    CONF_CERT_FILE,
    CONF_CERTFILE,
    CONF_KEYFILE,
    CONF_MANUAL_PATHS,
    CONF_USE_SSL,
    DEFAULT_BRAND,
    DEFAULT_USE_SSL,
)
from ..protocol import (
    check_certs_exist,
    detect_brand_from_cert_paths,
    extract_and_install_certs,
    extract_pkcs12_to_pem,
    get_profile_default_cert_paths,
    validate_ssl_certs,
)
from .helpers import resolve_ssl_certs

if TYPE_CHECKING:
    from ..config_flow import VidaaConfigFlow

_LOGGER = logging.getLogger(__name__)


class CertsFlowMixin:
    """Mixin for SSL certificate selection and validation in config flows."""

    async def _async_resolve_ssl_certs(self: VidaaConfigFlow) -> bool:
        """Attempts to resolve certificates from disk or profile off the event loop."""
        config_dir = self.hass.config.config_dir if hasattr(self, "hass") and hasattr(self.hass, "config") else None
        if hasattr(self, "hass") and self.hass:
            success, cert, key, use_ssl = await self.hass.async_add_executor_job(
                resolve_ssl_certs, self.auth_profile, config_dir
            )
        else:
            loop = asyncio.get_running_loop()
            success, cert, key, use_ssl = await loop.run_in_executor(
                None, resolve_ssl_certs, self.auth_profile, config_dir
            )
        if success:
            self.certfile = cert
            self.keyfile = key
            self.use_ssl = use_ssl
            brand_hint = detect_brand_from_cert_paths(cert, key)
            if brand_hint and getattr(self, "brand", DEFAULT_BRAND) == DEFAULT_BRAND:
                self.brand = brand_hint
                if brand_hint in BRAND_MAP:
                    self.manufacturer = BRAND_MAP[brand_hint]
            return True
        return False

    def _resolve_ssl_certs(self: VidaaConfigFlow) -> bool:
        """Synchronous fallback to resolve certificates from disk or profile."""
        config_dir = self.hass.config.config_dir if hasattr(self, "hass") and hasattr(self.hass, "config") else None
        success, cert, key, use_ssl = resolve_ssl_certs(self.auth_profile, config_dir)
        if success:
            self.certfile = cert
            self.keyfile = key
            self.use_ssl = use_ssl
            brand_hint = detect_brand_from_cert_paths(cert, key)
            if brand_hint and getattr(self, "brand", DEFAULT_BRAND) == DEFAULT_BRAND:
                self.brand = brand_hint
                if brand_hint in BRAND_MAP:
                    self.manufacturer = BRAND_MAP[brand_hint]
            return True
        return False

    async def async_step_upload(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle certificate file upload step."""
        errors: dict[str, str] = {}
        brand_hint: str | None = None
        if user_input is not None:
            if user_input.get(CONF_MANUAL_PATHS):
                return await self.async_step_certs()

            uploaded_file_id = user_input.get(CONF_CERT_FILE)
            if not uploaded_file_id:
                errors["base"] = "invalid_cert_archive"
            else:
                try:
                    storage_dir = (
                        Path(self.hass.config.path(".storage", "vidaa", "certs"))
                        if hasattr(self, "hass") and hasattr(self.hass, "config")
                        else Path("/config/.storage/vidaa/certs")
                    )

                    def _extract(file_id: str, dest: Path) -> tuple[str, str, str | None]:
                        with process_uploaded_file(self.hass, file_id) as uploaded_path:
                            cert_p, key_p = extract_and_install_certs(uploaded_path, dest)
                            hint = detect_brand_from_cert_paths(cert_p, key_p, str(uploaded_path), file_id)
                            return cert_p, key_p, hint

                    if hasattr(self, "hass") and self.hass:
                        extracted = await self.hass.async_add_executor_job(_extract, uploaded_file_id, storage_dir)
                    else:
                        loop = asyncio.get_running_loop()
                        extracted = await loop.run_in_executor(None, _extract, uploaded_file_id, storage_dir)

                    self.certfile, self.keyfile, upload_hint = extracted
                    self.use_ssl = True
                except ValueError as ex:
                    _LOGGER.warning("[%s] Failed to extract certificates from upload: %s", self.ip_address, ex)
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
                    _LOGGER.warning("[%s] Unexpected error during certificate extraction: %s", self.ip_address, ex)
                    errors["base"] = "invalid_cert_archive"

            if not errors:
                brand_hint = upload_hint or detect_brand_from_cert_paths(self.certfile, self.keyfile)
                if brand_hint and getattr(self, "brand", DEFAULT_BRAND) == DEFAULT_BRAND:
                    self.brand = brand_hint
                    if brand_hint in BRAND_MAP:
                        self.manufacturer = BRAND_MAP[brand_hint]
                try:
                    return await self._async_init_client_and_auth(
                        is_reauth=self._reauth_entry is not None,
                        reauth_reason=getattr(self, "_reauth_reason", "reauth_successful"),
                    )
                except AbortFlow:
                    raise
                except ssl.SSLError as e:
                    _LOGGER.warning("[%s] SSL handshake failed after cert upload: %s", self.ip_address, e)
                    errors["base"] = "invalid_ssl_cert"
                except Exception as e:
                    _LOGGER.warning("[%s] Failed to connect after cert upload: %s", self.ip_address, e)
                    errors["base"] = "cannot_connect"

        upload_schema = vol.Schema(
            {
                vol.Optional(CONF_CERT_FILE): selector.FileSelector(
                    selector.FileSelectorConfig(accept=".apk,.xapk,.p12,.pfx,.pem,.crt")
                ),
                vol.Optional(CONF_MANUAL_PATHS, default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="upload",
            data_schema=upload_schema,
            errors=errors,
        )

    async def async_step_certs(
        self: VidaaConfigFlow, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle certificate file configuration step."""
        errors: dict[str, str] = {}
        config_dir = self.hass.config.config_dir if hasattr(self.hass, "config") else "/config"
        if hasattr(self, "hass") and self.hass:
            (
                default_cert_path,
                default_key_path,
                default_cert_dir,
                default_cert_name,
                default_key_name,
            ) = await self.hass.async_add_executor_job(get_profile_default_cert_paths, self.auth_profile, config_dir)
        else:
            loop = asyncio.get_running_loop()
            (
                default_cert_path,
                default_key_path,
                default_cert_dir,
                default_cert_name,
                default_key_name,
            ) = await loop.run_in_executor(None, get_profile_default_cert_paths, self.auth_profile, config_dir)

        if user_input is not None:
            self.use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            self.certfile = user_input.get(CONF_CERTFILE) or default_cert_path
            self.keyfile = user_input.get(CONF_KEYFILE) or default_key_path

            if self.use_ssl:
                if self.certfile and (self.certfile.lower().endswith(".p12") or self.certfile.lower().endswith(".pfx")):
                    if hasattr(self, "hass") and self.hass:
                        extracted = await self.hass.async_add_executor_job(extract_pkcs12_to_pem, self.certfile)
                    else:
                        loop = asyncio.get_running_loop()
                        extracted = await loop.run_in_executor(None, extract_pkcs12_to_pem, self.certfile)
                    if extracted:
                        self.certfile, self.keyfile = extracted

                async def _check_exist(c: str | None, k: str | None) -> bool:
                    if hasattr(self, "hass") and self.hass:
                        return await self.hass.async_add_executor_job(check_certs_exist, c, k)
                    loop = asyncio.get_running_loop()
                    return await loop.run_in_executor(None, check_certs_exist, c, k)

                certs_exist = await _check_exist(self.certfile, self.keyfile)
                if not certs_exist:
                    if self.auth_profile in ("legacy", "static"):
                        self.certfile = None
                        self.keyfile = None
                    else:
                        cert_exists = await _check_exist(self.certfile, self.certfile)
                        key_exists = await _check_exist(self.keyfile, self.keyfile)
                        if not cert_exists:
                            errors[CONF_CERTFILE] = "certs_not_found"
                        elif not key_exists:
                            errors[CONF_KEYFILE] = "certs_not_found"
                        else:
                            errors["base"] = "certs_not_found"
                else:

                    async def _validate(c: str | None, k: str | None) -> tuple[bool, str | None]:
                        if hasattr(self, "hass") and self.hass:
                            return await self.hass.async_add_executor_job(validate_ssl_certs, c, k)
                        loop = asyncio.get_running_loop()
                        return await loop.run_in_executor(None, validate_ssl_certs, c, k)

                    valid, err_reason = await _validate(self.certfile, self.keyfile)
                    if not valid:
                        _LOGGER.warning("[%s] SSL certificate validation failed: %s", self.ip_address, err_reason)
                        errors["base"] = "invalid_ssl_cert"

            if not errors:
                brand_hint = detect_brand_from_cert_paths(self.certfile, self.keyfile)
                if brand_hint and getattr(self, "brand", DEFAULT_BRAND) == DEFAULT_BRAND:
                    self.brand = brand_hint
                    if brand_hint in BRAND_MAP:
                        self.manufacturer = BRAND_MAP[brand_hint]
                try:
                    return await self._async_init_client_and_auth(
                        is_reauth=self._reauth_entry is not None,
                        reauth_reason=getattr(self, "_reauth_reason", "reauth_successful"),
                    )
                except AbortFlow:
                    # HA flow control (e.g. already_configured) must never be
                    # turned into cannot_connect.
                    raise
                except ssl.SSLError as e:
                    _LOGGER.warning("[%s] SSL handshake failed: %s", self.ip_address, e)
                    errors["base"] = "invalid_ssl_cert"
                except Exception as e:
                    _LOGGER.warning("[%s] Failed to connect or initiate auth: %s", self.ip_address, e)
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="certs",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USE_SSL, default=self.use_ssl): bool,
                    vol.Optional(CONF_CERTFILE, default=self.certfile or default_cert_path): str,
                    vol.Optional(CONF_KEYFILE, default=self.keyfile or default_key_path): str,
                }
            ),
            description_placeholders={
                "cert_dir": str(default_cert_dir),
                "cert_file": default_cert_name,
                "key_file": default_key_name,
            },
            errors=errors,
        )
