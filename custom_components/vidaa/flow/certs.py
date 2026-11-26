"""Certificate handling mixin for VIDAA config flow."""

from __future__ import annotations

import asyncio
import contextlib
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
    extract_pkcs12_to_pem,
    get_profile_default_cert_paths,
    validate_ssl_certs,
)
from .helpers import (
    UploadedCertProcessingError,
    async_process_uploaded_cert_file,
    resolve_ssl_certs,
)
from .isolation import cert_path_in_use_by_other_entries

if TYPE_CHECKING:
    from ..config_flow import VidaaConfigFlow

_LOGGER = logging.getLogger(__name__)


class CertsFlowMixin:
    """Mixin for SSL certificate selection and validation in config flows."""

    def _cleanup_installed_certs(self: VidaaConfigFlow) -> None:
        """Removes installed certificates from storage if client auth fails after upload."""
        entry_id = self._reauth_entry.entry_id if getattr(self, "_reauth_entry", None) else None
        candidates = getattr(self, "_uploaded_cert_paths", None) or (
            getattr(self, "certfile", None),
            getattr(self, "keyfile", None),
        )
        for path_str in candidates:
            if path_str:
                path = Path(path_str)
                if (
                    ".storage" in path.parts
                    and "vidaa" in path.parts
                    and path.is_file()
                    and not cert_path_in_use_by_other_entries(
                        getattr(self, "hass", None), path_str, exclude_entry_id=entry_id
                    )
                ):
                    with contextlib.suppress(OSError):
                        path.unlink()
        self._uploaded_cert_paths = None
        self.certfile = None
        self.keyfile = None

    async def _run_executor(self: VidaaConfigFlow, func: Any, *args: Any) -> Any:
        """Run a function in the executor, handling both live HA and MagicMock."""
        if (
            hasattr(self, "hass")
            and hasattr(self.hass, "async_add_executor_job")
            and callable(self.hass.async_add_executor_job)
        ):
            res = self.hass.async_add_executor_job(func, *args)
            if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                return await res
            if type(self.hass.async_add_executor_job).__name__ == "MagicMock":
                return func(*args)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    async def _async_resolve_ssl_certs(self: VidaaConfigFlow) -> bool:
        """Attempts to resolve certificates from disk or profile off the event loop."""
        config_dir = self.hass.config.config_dir if hasattr(self, "hass") and hasattr(self.hass, "config") else None
        success, cert, key, use_ssl = await self._run_executor(resolve_ssl_certs, self.auth_profile, config_dir)
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
        if getattr(self, "_upload_error", None):
            errors["base"] = self._upload_error
            self._upload_error = None
        if user_input is not None:
            if user_input.get(CONF_MANUAL_PATHS):
                return await self.async_step_certs()

            uploaded_file_id = user_input.get(CONF_CERT_FILE)
            if not uploaded_file_id:
                errors["base"] = "invalid_cert_archive"
            else:
                try:
                    reauth_entry = getattr(self, "_reauth_entry", None)
                    cert_scope = (
                        (reauth_entry.entry_id if reauth_entry else None)
                        or getattr(self, "mac_address", None)
                        or getattr(self, "ip_address", None)
                    )
                    self.certfile, self.keyfile, upload_hint = await async_process_uploaded_cert_file(
                        self.hass, uploaded_file_id, scope=cert_scope
                    )
                    self._uploaded_cert_paths = (self.certfile, self.keyfile)
                    self.use_ssl = True
                except UploadedCertProcessingError as ex:
                    errors["base"] = ex.error_key

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
                    self._cleanup_installed_certs()
                    errors["base"] = "invalid_ssl_cert"
                except Exception as e:
                    _LOGGER.warning("[%s] Failed to connect after cert upload: %s", self.ip_address, e)
                    self._cleanup_installed_certs()
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
        (
            default_cert_path,
            default_key_path,
            default_cert_dir,
            default_cert_name,
            default_key_name,
        ) = await self._run_executor(get_profile_default_cert_paths, self.auth_profile, config_dir)

        if user_input is not None:
            self.use_ssl = user_input.get(CONF_USE_SSL, DEFAULT_USE_SSL)
            self.certfile = user_input.get(CONF_CERTFILE) or default_cert_path
            self.keyfile = user_input.get(CONF_KEYFILE) or default_key_path

            if self.use_ssl:
                if self.certfile and (self.certfile.lower().endswith(".p12") or self.certfile.lower().endswith(".pfx")):
                    extracted = await self._run_executor(extract_pkcs12_to_pem, self.certfile)
                    if extracted:
                        self.certfile, self.keyfile = extracted
                    else:
                        errors["base"] = "invalid_ssl_cert"

                if not errors:
                    certs_exist = await self._run_executor(check_certs_exist, self.certfile, self.keyfile)
                    if not certs_exist:
                        if self.auth_profile in ("legacy", "static"):
                            self.certfile = None
                            self.keyfile = None
                        else:
                            cert_exists = await self._run_executor(check_certs_exist, self.certfile, self.certfile)
                            key_exists = await self._run_executor(check_certs_exist, self.keyfile, self.keyfile)
                            if not cert_exists:
                                errors[CONF_CERTFILE] = "certs_not_found"
                            elif not key_exists:
                                errors[CONF_KEYFILE] = "certs_not_found"
                            else:
                                errors["base"] = "certs_not_found"
                    else:
                        valid, err_reason = await self._run_executor(validate_ssl_certs, self.certfile, self.keyfile)
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
