"""Certificate discovery, validation, and profile resolution for VIDAA TV."""

from __future__ import annotations

import contextlib
import logging
import os
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from .cert_extract import (
    KNOWN_P12_PASSWORDS,
    MAX_UPLOAD_SIZE,
    P12_CANDIDATES,
    extract_and_install_certs,
    extract_pkcs12_to_pem,
)
from .cert_profiles import (
    PROFILE_CERT_CANDIDATES,
    get_profile_default_cert_paths,
    resolve_ca_certificate,
    resolve_certificates,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "KNOWN_P12_PASSWORDS",
    "MAX_UPLOAD_SIZE",
    "P12_CANDIDATES",
    "PROFILE_CERT_CANDIDATES",
    "check_certs_exist",
    "detect_brand_from_cert_paths",
    "extract_and_install_certs",
    "extract_pkcs12_to_pem",
    "get_profile_default_cert_paths",
    "resolve_ca_certificate",
    "resolve_certificates",
    "validate_ssl_certs",
]


def detect_brand_from_cert_paths(
    certfile: str | None = None,
    keyfile: str | None = None,
    *extra_paths: str | None,
) -> str | None:
    """Detect OEM brand hint from certificate, private key, or archive filenames."""
    brand_keywords: list[tuple[tuple[str, ...], str]] = [
        (("toshiba", "regza"), "tos"),
        (("loewe",), "loe"),
        (("philips", "tpv", "aoc"), "tpv"),
        (("sharp", "aquos"), "shp"),
        (("jvc",), "jvc"),
        (("toptro",), "tpo"),
        (("schneider",), "sch"),
        (("akai",), "aka"),
        (("beko",), "bek"),
        (("telefunken",), "tel"),
        (("bush",), "bus"),
        (("vizio",), "vic"),
        (("philco",), "phi"),
        (("noblex",), "nob"),
        (("sansei",), "san"),
        (("ilo",), "ilo"),
        (("pioneer",), "pio"),
        (("seiki",), "sei"),
        (("tonomac",), "ton"),
        (("panasonic",), "psc"),
        (("rca", "rcamobile"), "rca"),
        (("sinotec",), "sin"),
        (("vestel",), "ves"),
        (("brandt",), "bra"),
        (("metz",), "met"),
        (("leica",), "lei"),
        (("hisense", "vidaa"), "his"),
    ]
    # Check extra hint paths (e.g. uploaded archive name) before extracted generic certs
    all_paths = [*extra_paths, certfile, keyfile]
    for path in all_paths:
        if not path:
            continue
        base = os.path.basename(path).lower()
        for keywords, code in brand_keywords:
            if any(token in base for token in keywords):
                return code
    return None


def validate_ssl_certs(certfile: str | None, keyfile: str | None) -> tuple[bool, str | None]:
    """Validates that certfile and keyfile exist, are valid PEM or PKCS#12, and match each other."""
    if not certfile and not keyfile:
        return True, None

    if not check_certs_exist(certfile, keyfile):
        return False, "certs_not_found"

    # If certfile is a PKCS#12 bundle, extract or validate via extract_pkcs12_to_pem
    if certfile and (certfile.lower().endswith(".p12") or certfile.lower().endswith(".pfx")):
        extracted = extract_pkcs12_to_pem(certfile)
        if not extracted:
            return False, "invalid_ssl_cert: failed to extract PKCS#12 bundle"
        certfile, keyfile = extracted

    # Try validating via Python SSLContext
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with contextlib.suppress(ssl.SSLError, AttributeError):
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        return True, None
    except ssl.SSLError as e:
        _LOGGER.debug("ssl.SSLContext failed, falling back to cryptography validation: %s", e)
    except Exception as e:
        _LOGGER.debug("Unexpected error loading cert chain via ssl context: %s", e)

    # Fallback to cryptography library validation
    try:
        cert_data = Path(certfile).read_bytes()
        key_data = Path(keyfile).read_bytes()

        cert = x509.load_pem_x509_certificate(cert_data)
        pub_key = cert.public_key()

        from cryptography.hazmat.primitives import serialization

        priv_key = serialization.load_pem_private_key(key_data, password=None)

        # Test signing with private key and verifying with certificate's public key
        test_payload = b"VIDAA_SSL_VALIDATION_PROBE"
        if isinstance(priv_key, rsa.RSAPrivateKey):
            sig = priv_key.sign(
                test_payload,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            pub_key.verify(
                sig,
                test_payload,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        elif isinstance(priv_key, ec.EllipticCurvePrivateKey):
            sig = priv_key.sign(test_payload, ec.ECDSA(hashes.SHA256()))
            pub_key.verify(sig, test_payload, ec.ECDSA(hashes.SHA256()))
        else:
            return False, "Unsupported key type; expected RSA or EC private key"

        return True, None
    except Exception as e:
        _LOGGER.warning("Certificate and key failed cryptographic validation: %s", e)
        return False, f"invalid_ssl_cert: {e}"


def check_certs_exist(certfile: str | None, keyfile: str | None) -> bool:
    """Returns True if both certificate and private key exist on disk or match valid PKCS#12 bundle."""
    if not certfile:
        return False

    if (certfile.lower().endswith(".p12") or certfile.lower().endswith(".pfx")) and os.path.isfile(certfile):
        return True

    if not keyfile:
        return False

    return os.path.isfile(certfile) and os.path.isfile(keyfile)
