"""Repairs implementation for VIDAA Smart TV."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

try:
    from homeassistant.components.file_upload import process_uploaded_file
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def process_uploaded_file(hass, file_id):
        yield Path(file_id)


from .const import CONF_AUTH_PROFILE, CONF_CERT_FILE, CONF_CERTFILE, CONF_KEYFILE
from .protocol import check_certs_exist, extract_and_install_certs, resolve_certificates

_LOGGER = logging.getLogger(__name__)


class CertificateMissingRepairFlow(RepairsFlow):
    """Handler for certificate missing repair flow."""

    def __init__(self, entry_id: str | None = None) -> None:
        """Initialize with config entry id."""
        super().__init__()
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Handle the confirmation step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id) if self._entry_id else None
            uploaded_file_id = user_input.get(CONF_CERT_FILE)
            if uploaded_file_id:
                try:
                    storage_dir = (
                        Path(self.hass.config.path(".storage", "vidaa", "certs"))
                        if hasattr(self.hass, "config")
                        else Path("/config/.storage/vidaa/certs")
                    )

                    def _extract(file_id: str, dest: Path) -> tuple[str, str]:
                        with process_uploaded_file(self.hass, file_id) as uploaded_path:
                            return extract_and_install_certs(uploaded_path, dest)

                    if hasattr(self, "hass") and self.hass and hasattr(self.hass, "async_add_executor_job"):
                        res = self.hass.async_add_executor_job(_extract, uploaded_file_id, storage_dir)
                        if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                            extracted = await res
                        else:
                            extracted = _extract(uploaded_file_id, storage_dir)
                    else:
                        loop = asyncio.get_running_loop()
                        extracted = await loop.run_in_executor(None, _extract, uploaded_file_id, storage_dir)

                    if entry is not None:
                        new_opts = dict(entry.options)
                        new_opts[CONF_CERTFILE] = extracted[0]
                        new_opts[CONF_KEYFILE] = extracted[1]
                        self.hass.config_entries.async_update_entry(entry, options=new_opts)
                        reload_res = self.hass.config_entries.async_reload(entry.entry_id)
                        if asyncio.iscoroutine(reload_res) or isinstance(reload_res, asyncio.Future):
                            await reload_res
                    return self.async_create_entry(data={})
                except ValueError as ex:
                    _LOGGER.warning("Failed to extract uploaded cert in repair flow: %s", ex)
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
                    _LOGGER.warning("Unexpected error during cert extraction in repair flow: %s", ex)
                    errors["base"] = "invalid_cert_archive"

            if not errors:
                auth_profile = "auto"
                custom_cert = None
                custom_key = None
                if entry:
                    opts = entry.options
                    d = entry.data
                    auth_profile = opts.get(CONF_AUTH_PROFILE, d.get(CONF_AUTH_PROFILE, "auto"))
                    custom_cert = opts.get(CONF_CERTFILE, d.get(CONF_CERTFILE))
                    custom_key = opts.get(CONF_KEYFILE, d.get(CONF_KEYFILE))

                try:

                    def _verify_resolved_certs() -> bool:
                        try:
                            config_dir = self.hass.config.config_dir if hasattr(self.hass, "config") else None
                            cert, key = resolve_certificates(
                                auth_profile=auth_profile,
                                certfile=custom_cert,
                                keyfile=custom_key,
                                config_dir=config_dir,
                            )
                        except TypeError:
                            cert, key = resolve_certificates()
                        return bool(cert and key and check_certs_exist(cert, key))

                    if await self.hass.async_add_executor_job(_verify_resolved_certs):
                        if entry is not None:
                            reload_res = self.hass.config_entries.async_reload(entry.entry_id)
                            if asyncio.iscoroutine(reload_res) or isinstance(reload_res, asyncio.Future):
                                await reload_res
                        return self.async_create_entry(data={})
                except Exception as err:
                    _LOGGER.debug("Certificate verification failed during repair: %s", err)
                errors["base"] = "certificates_still_missing"

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_CERT_FILE): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".apk,.xapk,.p12,.pfx,.pem,.crt")
                    ),
                }
            ),
            errors=errors,
        )


class AuthTokenInvalidatedRepairFlow(RepairsFlow):
    """Repair flow shown when the TV broker has rejected all stored tokens.

    This happens when the TV invalidates its token store out-of-band, e.g.
    after a firmware update or a hard mains power-cycle.  The only recovery
    path is to re-run the pairing flow to obtain a fresh credential set.
    """

    def __init__(self, entry_id: str | None = None) -> None:
        """Initialize the flow with the config entry that needs re-pairing."""
        super().__init__()
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Handle the first step."""
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Prompt the user to reconfigure the integration."""
        if user_input is not None:
            # [F5-leg2/F6-leg6]: dismissing the card alone hides a still-broken
            # TV (the client stops dispatching auth_failed after the rejection),
            # so the advertised re-pairing must actually be started.
            entry = self.hass.config_entries.async_get_entry(self._entry_id) if self._entry_id else None
            if entry is not None:
                entry.async_start_reauth(self.hass)
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )


def _entry_id_for_issue(issue_id: str, data: dict[str, Any] | None) -> str | None:
    """Return the config entry id a persistent issue belongs to."""
    if isinstance(data, dict) and data.get("entry_id"):
        return str(data["entry_id"])
    for prefix in ("auth_token_invalidated_", "certificate_missing_"):
        if issue_id.startswith(prefix):
            return issue_id[len(prefix) :] or None
    return None


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create a repair fix flow for the issue."""
    if issue_id.startswith("certificate_missing"):
        return CertificateMissingRepairFlow(entry_id=_entry_id_for_issue(issue_id, data))
    if issue_id.startswith("auth_token_invalidated"):
        return AuthTokenInvalidatedRepairFlow(entry_id=_entry_id_for_issue(issue_id, data))
    return CertificateMissingRepairFlow(entry_id=_entry_id_for_issue(issue_id, data))
