"""Certificate profile candidate definitions and search path resolution for VIDAA TV."""

from __future__ import annotations

import logging
import os

from .cert_candidates import PROFILE_CERT_CANDIDATES
from .cert_extract import extract_pkcs12_to_pem

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "PROFILE_CERT_CANDIDATES",
    "get_profile_default_cert_paths",
    "resolve_ca_certificate",
    "resolve_certificates",
]


def _get_default_search_dirs(config_dir: str | None = None) -> list[str]:
    """Build list of candidate certificate search paths, scanning upwards to repo root."""
    search_dirs: list[str] = []
    if config_dir:
        for sub in (".storage/vidaa/certs", ".storage/vidaa", "ssl", "certs"):
            candidate = os.path.join(config_dir, sub)
            if candidate not in search_dirs:
                search_dirs.append(candidate)

    static_dirs = [
        "/config/.storage/vidaa/certs",
        "/config/.storage/vidaa",
        "/config/ssl",
        "/ssl",
        "/config/certs",
        "/config",
        os.path.join(os.getcwd(), ".storage", "vidaa", "certs"),
        os.path.join(os.getcwd(), "ssl"),
        os.path.join(os.getcwd(), "certs"),
    ]
    for d in static_dirs:
        if d not in search_dirs:
            search_dirs.append(d)

    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and cur != os.path.dirname(cur):
        for sub in (".storage/vidaa/certs", "ssl", "certs"):
            candidate = os.path.join(cur, sub)
            if os.path.isdir(candidate) and candidate not in search_dirs:
                search_dirs.append(candidate)
        cur = os.path.dirname(cur)
    return search_dirs


def resolve_ca_certificate(
    ca_path: str | None = None,
    search_dirs: list[str] | None = None,
    config_dir: str | None = None,
) -> str | None:
    """Resolves CA certificate path for optional server certificate validation."""
    if ca_path and os.path.isfile(ca_path):
        return os.path.abspath(ca_path)

    if search_dirs is None:
        search_dirs = _get_default_search_dirs(config_dir)

    ca_names = [
        "remote_ca.pem",
        "RemoteCA.crt",
        "RemoteCA.pem",
        "ca.pem",
        "ca.crt",
        "ca_cert.pem",
        "root_ca.pem",
    ]

    for d in search_dirs:
        for name in ca_names:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)

    return None


def resolve_certificates(
    auth_profile: str = "auto",
    certfile: str | None = None,
    keyfile: str | None = None,
    search_dirs: list[str] | None = None,
    config_dir: str | None = None,
) -> tuple[str, str]:
    """Resolves certificate and private key paths based on profile and candidate locations."""
    if search_dirs is None:
        search_dirs = _get_default_search_dirs(config_dir)

    # Handle direct PKCS#12 bundle input
    if certfile and (certfile.lower().endswith(".p12") or certfile.lower().endswith(".pfx")):
        extracted = extract_pkcs12_to_pem(certfile)
        if extracted:
            return extracted
        _LOGGER.warning(
            "Failed to extract certificates from PKCS#12 bundle '%s'. "
            "If the archive uses legacy encryption, convert it to PEM with OpenSSL: "
            "'openssl pkcs12 -legacy -in %s -passin pass:186e990688070325a1c4b0ce275d2388 -clcerts -nokeys -out hisense.crt' and "
            "'openssl pkcs12 -legacy -in %s -passin pass:186e990688070325a1c4b0ce275d2388 -nocerts -nodes -out hisense.key'",
            certfile,
            os.path.basename(certfile),
            os.path.basename(certfile),
        )
        return None, None

    profile_clean = (auth_profile or "auto").lower()
    if profile_clean in ("modern", "vidaa_2024", "vidaa"):
        profile_key = "modern"
    elif profile_clean in ("middle", "vidaa_15", "vidaa_middle"):
        profile_key = "middle"
    elif profile_clean in ("remotenow", "remotenow_2018", "standard"):
        profile_key = "remotenow"
    else:
        profile_key = "auto"

    cert_names, key_names, p12_names = PROFILE_CERT_CANDIDATES[profile_key]

    resolved_cert = None
    resolved_key = None

    if certfile and os.path.isfile(certfile):
        resolved_cert = os.path.abspath(certfile)
    else:
        for d in search_dirs:
            for name in cert_names:
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    resolved_cert = candidate
                    break
            if resolved_cert:
                break

    if keyfile and os.path.isfile(keyfile):
        resolved_key = os.path.abspath(keyfile)
    elif resolved_cert:
        cert_stem = os.path.splitext(resolved_cert)[0]
        for ext in (".key", "_key.pem", ".pem"):
            candidate = cert_stem + ext
            if candidate != resolved_cert and os.path.isfile(candidate):
                resolved_key = candidate
                break

    if not resolved_key:
        for d in search_dirs:
            for name in key_names:
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    resolved_key = candidate
                    break
            if resolved_key:
                break

    # If no separate cert/key PEM pair found, search for PKCS#12 bundles
    if not (resolved_cert and resolved_key):
        for d in search_dirs:
            for p12_name in p12_names:
                p12_candidate = os.path.join(d, p12_name)
                if os.path.isfile(p12_candidate):
                    extracted = extract_pkcs12_to_pem(p12_candidate)
                    if extracted:
                        return extracted

    if config_dir:
        fallback_dir = os.path.join(config_dir, ".storage", "vidaa", "certs")
    else:
        fallback_dir = "/config/ssl"

    default_cert = os.path.join(fallback_dir, "hisense.crt")
    default_key = os.path.join(fallback_dir, "hisense.key")

    return resolved_cert or default_cert, resolved_key or default_key


def get_profile_default_cert_paths(
    auth_profile: str,
    config_dir: str = "/config",
) -> tuple[str, str, str, str, str]:
    """Returns (default_cert_path, default_key_path, default_cert_dir, default_cert_name, default_key_name)."""
    storage_dir = os.path.join(config_dir, ".storage", "vidaa", "certs")
    default_cert_dir = storage_dir if os.path.isdir(storage_dir) else os.path.join(config_dir, "ssl")

    profile_clean = (auth_profile or "auto").lower()
    if profile_clean in ("modern", "vidaa_2024", "vidaa"):
        default_cert_name = "vidaa_2024_cert.pem"
        default_key_name = "vidaa_2024_key.pem"
    elif profile_clean in ("middle", "vidaa_15", "vidaa_middle"):
        default_cert_name = "vidaa_client_v01.pem"
        default_key_name = "vidaa_client_v01.key"
    elif profile_clean in ("remotenow", "remotenow_2018", "standard"):
        default_cert_name = "remotenow_2018_cert.pem"
        default_key_name = "remotenow_2018_key.pem"
    else:
        default_cert_name = "hisense.crt"
        default_key_name = "hisense.key"

    from .certs import check_certs_exist

    resolved_cert, resolved_key = resolve_certificates(auth_profile, config_dir=config_dir)
    if check_certs_exist(resolved_cert, resolved_key):
        default_cert_path = resolved_cert
        default_key_path = resolved_key
    else:
        default_cert_path = os.path.join(default_cert_dir, default_cert_name)
        default_key_path = os.path.join(default_cert_dir, default_key_name)

    return default_cert_path, default_key_path, default_cert_dir, default_cert_name, default_key_name
