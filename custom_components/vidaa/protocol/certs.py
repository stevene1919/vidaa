"""Certificate resolution and PKCS#12 bundle extraction for VIDAA Smart TV."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import zipfile
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

_LOGGER = logging.getLogger(__name__)

KNOWN_P12_PASSWORDS = [
    b"186e990688070325a1c4b0ce275d2388",
    b"multiremote",
    b"",
    None,
    b"remote",
    b"hisense",
    b"123456",
]

P12_CANDIDATES: tuple[str, ...] = (
    "res/raw/client_mobile_android.p12",
    "res/El.p12",
    "res/raw/El.p12",
    "res/raw/el.p12",
    "res/3R.p12",
    "res/raw/3R.p12",
    "assets/client_mobile_android.p12",
    "assets/El.p12",
)

MAX_UPLOAD_SIZE = 150 * 1024 * 1024  # 150 MB safety limit

__all__ = [
    "HAS_CRYPTOGRAPHY",
    "KNOWN_P12_PASSWORDS",
    "MAX_UPLOAD_SIZE",
    "P12_CANDIDATES",
    "check_certs_exist",
    "detect_brand_from_cert_paths",
    "extract_and_install_certs",
    "extract_pkcs12_to_pem",
    "get_profile_default_cert_paths",
    "resolve_ca_certificate",
    "resolve_certificates",
    "validate_ssl_certs",
]


def detect_brand_from_cert_paths(certfile: str | None, keyfile: str | None) -> str | None:
    """Detect OEM brand hint from certificate or private key filenames."""
    brand_keywords: list[tuple[tuple[str, ...], str]] = [
        (("toshiba", "regza"), "tos"),
        (("loewe",), "loe"),
        (("philips", "tpv", "aoc"), "tpv"),
        (("sharp", "aquos"), "shp"),
        (("jvc",), "jvc"),
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
        (("hisense",), "his"),
    ]
    for path in (certfile, keyfile):
        if not path:
            continue
        base = os.path.basename(path).lower()
        for keywords, code in brand_keywords:
            if any(token in base for token in keywords):
                return code
    return None


def validate_ssl_certs(certfile: str | None, keyfile: str | None) -> tuple[bool, str | None]:
    """Validate that certificate and key files exist and can be loaded into an SSLContext.

    Returns:
        tuple[is_valid, error_reason_or_None]
    """
    if not certfile and not keyfile:
        return True, None

    if not check_certs_exist(certfile, keyfile):
        return False, "certs_not_found"

    import ssl

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with contextlib.suppress(ssl.SSLError):
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        return True, None
    except ssl.SSLError as err:
        return False, f"invalid_ssl_cert: {err}"
    except Exception as err:
        return False, f"invalid_ssl_cert: {err}"


def check_certs_exist(certfile: str | None, keyfile: str | None) -> bool:
    """Check if certificate and key files exist and are readable."""
    return bool(
        certfile
        and keyfile
        and os.path.isfile(certfile)
        and os.path.isfile(keyfile)
        and os.access(certfile, os.R_OK)
        and os.access(keyfile, os.R_OK)
    )


def extract_pkcs12_to_pem(
    p12_path: str,
    password: str | bytes | None = None,
    dest_dir: str | None = None,
) -> tuple[str, str] | None:
    """Extracts client certificate and private key from a PKCS#12 (.p12/.pfx) archive.

    Returns:
        tuple[certfile_path, keyfile_path] or None if extraction fails.
    """
    if not HAS_CRYPTOGRAPHY or not p12_path or not os.path.isfile(p12_path):
        return None

    base_name = os.path.splitext(os.path.basename(p12_path))[0]
    p12_mtime = os.path.getmtime(p12_path)

    # Check if previously extracted PEM files already exist and are fresh
    candidate_dirs = []
    if dest_dir is not None:
        candidate_dirs.append(dest_dir)
    else:
        candidate_dirs.append(os.path.dirname(os.path.abspath(p12_path)))
        import tempfile

        candidate_dirs.append(os.path.join(tempfile.gettempdir(), "vidaa_certs"))
        candidate_dirs.append(os.path.join(tempfile.gettempdir(), "hisense_vidaa_certs"))

    for c_dir in candidate_dirs:
        c_cert = os.path.join(c_dir, f"{base_name}_cert.pem")
        c_key = os.path.join(c_dir, f"{base_name}_key.pem")
        try:
            if (
                os.path.isfile(c_cert)
                and os.path.isfile(c_key)
                and os.path.getsize(c_cert) > 0
                and os.path.getsize(c_key) > 0
                and os.path.getmtime(c_cert) >= p12_mtime
                and os.path.getmtime(c_key) >= p12_mtime
            ):
                return c_cert, c_key
        except OSError:
            pass

    try:
        with open(p12_path, "rb") as f:
            p12_data = f.read()
    except Exception as err:
        _LOGGER.debug("Failed to read PKCS#12 file %s: %s", p12_path, err)
        return None

    passwords_to_try: list[bytes | None] = []
    if password is not None:
        passwords_to_try.append(password.encode("utf-8") if isinstance(password, str) else password)
    passwords_to_try.extend(KNOWN_P12_PASSWORDS)

    private_key = None
    certificate = None

    last_error: Exception | None = None
    for pwd in passwords_to_try:
        try:
            key, cert, _ = pkcs12.load_key_and_certificates(p12_data, pwd)
            if key and cert:
                private_key = key
                certificate = cert
                break
        except Exception as ex:
            last_error = ex
            continue

    if not private_key or not certificate:
        _LOGGER.debug(
            "Could not extract private key and certificate from PKCS#12 file %s (last error: %s)",
            p12_path,
            last_error,
        )
        return None

    if dest_dir is None:
        dest_dir = os.path.dirname(os.path.abspath(p12_path))

    # Verify dest_dir is writable or fall back to system temp directory
    try:
        os.makedirs(dest_dir, exist_ok=True)
        test_file = os.path.join(dest_dir, ".test_write")
        with open(test_file, "wb") as f:
            f.write(b"")
        os.remove(test_file)
    except (OSError, PermissionError):
        import tempfile

        dest_dir = os.path.join(tempfile.gettempdir(), "vidaa_certs")
        os.makedirs(dest_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(p12_path))[0]
    out_cert_path = os.path.join(dest_dir, f"{base_name}_cert.pem")
    out_key_path = os.path.join(dest_dir, f"{base_name}_key.pem")

    try:
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        with open(out_cert_path, "wb") as f:
            f.write(cert_pem)
        with open(out_key_path, "wb") as f:
            f.write(key_pem)

        return out_cert_path, out_key_path
    except Exception as err:
        _LOGGER.debug("Failed to write extracted PEM files: %s", err)
        return None


def _extract_p12_bytes_from_archive(file_path: Path) -> bytes:
    """Extract PKCS#12 bytes from an APK, nested XAPK, or raw P12 archive."""
    if not zipfile.is_zipfile(file_path):
        return file_path.read_bytes()

    with zipfile.ZipFile(file_path, "r") as archive:
        for member in archive.infolist():
            name = member.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise ValueError(f"Insecure file path detected in archive: {name}")

        names = archive.namelist()
        lower_names = {n.lower(): n for n in names}

        # Check direct candidate paths
        for candidate in P12_CANDIDATES:
            if candidate.lower() in lower_names:
                actual = lower_names[candidate.lower()]
                if archive.getinfo(actual).file_size > 10 * 1024 * 1024:
                    raise ValueError("Keystore file in archive exceeds size limit")
                return archive.read(actual)

        # Check for any .p12/.pfx files in archive
        for name in names:
            if name.lower().endswith((".p12", ".pfx")) and not name.startswith("__MACOSX"):
                if archive.getinfo(name).file_size > 10 * 1024 * 1024:
                    raise ValueError("Keystore file in archive exceeds size limit")
                return archive.read(name)

        # Check nested APKs (e.g. XAPK / APKS bundle)
        for name in names:
            if name.lower().endswith(".apk") and not name.startswith("__MACOSX"):
                if archive.getinfo(name).file_size > MAX_UPLOAD_SIZE:
                    continue
                try:
                    inner_bytes = archive.read(name)
                    if zipfile.is_zipfile(io.BytesIO(inner_bytes)):
                        with zipfile.ZipFile(io.BytesIO(inner_bytes), "r") as inner_apk:
                            for inner_member in inner_apk.infolist():
                                iname = inner_member.filename
                                if iname.startswith(("/", "\\")) or ".." in Path(iname).parts:
                                    raise ValueError(f"Insecure file path detected in nested archive: {iname}")
                            inner_lower = {n.lower(): n for n in inner_apk.namelist()}
                            for candidate in P12_CANDIDATES:
                                if candidate.lower() in inner_lower:
                                    actual = inner_lower[candidate.lower()]
                                    if inner_apk.getinfo(actual).file_size > 10 * 1024 * 1024:
                                        raise ValueError("Keystore file in nested archive exceeds size limit")
                                    return inner_apk.read(actual)
                            for inner_name in inner_apk.namelist():
                                if inner_name.lower().endswith((".p12", ".pfx")) and not inner_name.startswith(
                                    "__MACOSX"
                                ):
                                    if inner_apk.getinfo(inner_name).file_size > 10 * 1024 * 1024:
                                        raise ValueError("Keystore file in nested archive exceeds size limit")
                                    return inner_apk.read(inner_name)
                except ValueError:
                    raise
                except Exception as ex:
                    _LOGGER.debug("Skipping unreadable nested APK '%s': %s", name, ex)
                    continue

    raise ValueError("No VIDAA PKCS#12 keystore found in uploaded archive")


def extract_and_install_certs(
    uploaded_path: Path | str,
    target_dir: Path | str,
    password: str | bytes | None = None,
) -> tuple[str, str]:
    """Unpack PKCS#12 or PEM certificates from uploaded file and persist PEMs to target_dir.

    Returns:
        tuple[certfile_path, keyfile_path]
    Raises:
        ValueError: If extraction, decryption, or validation fails.
    """
    if not HAS_CRYPTOGRAPHY:
        raise ValueError("Cryptography library is required for certificate extraction")

    src = Path(uploaded_path)
    dst = Path(target_dir)

    if not src.is_file():
        raise ValueError(f"Uploaded file not found: {src}")

    if src.stat().st_size > MAX_UPLOAD_SIZE:
        raise ValueError(f"Uploaded file exceeds maximum limit of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB")

    private_key = None
    certificate = None

    if zipfile.is_zipfile(src):
        p12_bytes = _extract_p12_bytes_from_archive(src)
    else:
        if src.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Uploaded non-archive keystore exceeds maximum limit of 10 MB")
        raw_data = src.read_bytes()

        if b"-----BEGIN " in raw_data:
            cert_marker = b"-----BEGIN CERTIFICATE-----"
            key_marker = None
            for km in (
                b"-----BEGIN PRIVATE KEY-----",
                b"-----BEGIN RSA PRIVATE KEY-----",
                b"-----BEGIN EC PRIVATE KEY-----",
            ):
                if km in raw_data:
                    key_marker = km
                    break
            if not (cert_marker in raw_data and key_marker):
                raise ValueError("Uploaded PEM/CRT file must contain both a certificate and an unencrypted private key")

            cert_start = raw_data.find(cert_marker)
            cert_end_marker = b"-----END CERTIFICATE-----"
            cert_end_idx = raw_data.find(cert_end_marker)
            if cert_end_idx == -1:
                raise ValueError("Malformed certificate in uploaded PEM file")
            cert_end = cert_end_idx + len(cert_end_marker)
            cert_pem = raw_data[cert_start:cert_end].strip()

            key_start = raw_data.find(key_marker)
            end_marker = key_marker.replace(b"BEGIN", b"END")
            key_end_idx = raw_data.find(end_marker)
            if key_end_idx == -1:
                raise ValueError("Malformed private key in uploaded PEM file")
            key_end = key_end_idx + len(end_marker)
            key_pem = raw_data[key_start:key_end].strip()

            try:
                certificate = x509.load_pem_x509_certificate(cert_pem)
                private_key = serialization.load_pem_private_key(key_pem, password=None)
            except Exception as e:
                raise ValueError(f"Failed parsing uploaded PEM certificate or key: {e}") from e
        else:
            p12_bytes = raw_data

    if not private_key or not certificate:
        passwords_to_try: list[bytes | None] = []
        if password is not None:
            passwords_to_try.append(password.encode("utf-8") if isinstance(password, str) else password)
        passwords_to_try.extend(KNOWN_P12_PASSWORDS)

        for pwd in passwords_to_try:
            try:
                k, c, _ = pkcs12.load_key_and_certificates(p12_bytes, pwd)
                if k and c:
                    private_key = k
                    certificate = c
                    break
            except Exception as ex:
                _LOGGER.debug("P12 candidate decryption failed: %s", ex)
                continue

    if not private_key or not certificate:
        raise ValueError("Failed to decrypt PKCS#12 keystore from uploaded file")

    dst.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(dst, 0o700)

    crt_path = dst / "hisense.crt"
    key_path = dst / "hisense.key"

    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    crt_path.write_bytes(cert_bytes)
    key_path.write_bytes(key_bytes)

    with contextlib.suppress(OSError):
        os.chmod(key_path, 0o600)

    # Validate written certificates in SSLContext
    valid, err_reason = validate_ssl_certs(str(crt_path), str(key_path))
    if not valid:
        crt_path.unlink(missing_ok=True)
        key_path.unlink(missing_ok=True)
        raise ValueError(f"Extracted certificates failed SSL validation: {err_reason}")

    return str(crt_path), str(key_path)


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
    """Resolves CA certificate path for optional server certificate validation.

    Returns:
        ca_cert_path or None
    """
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


PROFILE_CERT_CANDIDATES: dict[str, tuple[list[str], list[str], list[str]]] = {
    "modern": (
        [
            "vidaa_client_v01.pem",
            "vidaa_client_v01.crt",
            "vidaa_client_v02.pem",
            "vidaa_2024_cert.pem",
            "vidaa2024_cert.pem",
            "vidaa_client.pem",
            "hisense.crt",
            "toshiba.crt",
            "toshiba.pem",
            "loewe.crt",
            "loewe.pem",
            "philips.crt",
            "philips.pem",
            "tpv.crt",
            "tpv.pem",
            "client_cert.pem",
            "cert.pem",
        ],
        [
            "vidaa_client_v01.key",
            "vidaa_client_v02.key",
            "vidaa_2024_key.pem",
            "vidaa2024_key.pem",
            "vidaa_client.key",
            "hisense.key",
            "toshiba.key",
            "loewe.key",
            "philips.key",
            "tpv.key",
            "client_key.pem",
            "key.pem",
        ],
        [
            "vidaa_2024_client_mobile_android.p12",
            "client_mobile_android.p12",
            "El.p12",
            "el.p12",
            "3R.p12",
            "vidaa_cert.p12",
            "vidaa.p12",
            "toshiba.p12",
            "loewe.p12",
            "philips.p12",
            "tpv.p12",
        ],
    ),
    "middle": (
        [
            "vidaa_client_v01.pem",
            "vidaa_client_v01.crt",
            "vidaa_client_v02.pem",
            "vidaa_client.pem",
            "remotenow_2018_cert.pem",
            "hisense.crt",
            "toshiba.crt",
            "toshiba.pem",
            "loewe.crt",
            "loewe.pem",
            "philips.crt",
            "philips.pem",
            "tpv.crt",
            "tpv.pem",
            "client_cert.pem",
            "cert.pem",
        ],
        [
            "vidaa_client_v01.key",
            "vidaa_client_v02.key",
            "vidaa_client.key",
            "remotenow_2018_key.pem",
            "hisense.key",
            "toshiba.key",
            "loewe.key",
            "philips.key",
            "tpv.key",
            "client_key.pem",
            "key.pem",
        ],
        [
            "client_mobile_android.p12",
            "vidaa_2024_client_mobile_android.p12",
            "El.p12",
            "el.p12",
            "3R.p12",
            "rcamobile.p12",
            "hisense.p12",
            "toshiba.p12",
            "loewe.p12",
            "philips.p12",
            "tpv.p12",
        ],
    ),
    "remotenow": (
        [
            "remotenow_2018_cert.pem",
            "vidaa_client_v01.pem",
            "vidaa_client_v01.crt",
            "vidaa_client.pem",
            "hisense.crt",
            "client_cert.pem",
            "cert.pem",
        ],
        [
            "remotenow_2018_key.pem",
            "vidaa_client_v01.key",
            "vidaa_client.key",
            "hisense.key",
            "client_key.pem",
            "key.pem",
        ],
        ["rcamobile.p12", "hisense.p12", "remotenow.p12"],
    ),
    "auto": (
        [
            "vidaa_client_v01.pem",
            "vidaa_client_v01.crt",
            "vidaa_client_v02.pem",
            "vidaa_client.pem",
            "hisense.crt",
            "toshiba.crt",
            "toshiba.pem",
            "loewe.crt",
            "loewe.pem",
            "philips.crt",
            "philips.pem",
            "tpv.crt",
            "tpv.pem",
            "client_cert.pem",
            "vidaa_2024_cert.pem",
            "vidaa2024_cert.pem",
            "remotenow_2018_cert.pem",
            "cert.pem",
        ],
        [
            "vidaa_client_v01.key",
            "vidaa_client_v02.key",
            "vidaa_client.key",
            "hisense.key",
            "toshiba.key",
            "loewe.key",
            "philips.key",
            "tpv.key",
            "client_key.pem",
            "vidaa_2024_key.pem",
            "vidaa2024_key.pem",
            "remotenow_2018_key.pem",
            "key.pem",
        ],
        [
            "client_mobile_android.p12",
            "vidaa_2024_client_mobile_android.p12",
            "El.p12",
            "el.p12",
            "3R.p12",
            "vidaa_cert.p12",
            "vidaa.p12",
            "rcamobile.p12",
            "hisense.p12",
            "toshiba.p12",
            "loewe.p12",
            "philips.p12",
            "tpv.p12",
        ],
    ),
}


def resolve_certificates(
    auth_profile: str = "auto",
    certfile: str | None = None,
    keyfile: str | None = None,
    search_dirs: list[str] | None = None,
    config_dir: str | None = None,
) -> tuple[str, str]:
    """Resolves certificate and private key paths based on profile and candidate locations.

    Returns:
        tuple[certfile_path, keyfile_path]
    """
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

    resolved_cert, resolved_key = resolve_certificates(auth_profile, config_dir=config_dir)
    if check_certs_exist(resolved_cert, resolved_key):
        default_cert_path = resolved_cert
        default_key_path = resolved_key
    else:
        default_cert_path = os.path.join(default_cert_dir, default_cert_name)
        default_key_path = os.path.join(default_cert_dir, default_key_name)

    return default_cert_path, default_key_path, default_cert_dir, default_cert_name, default_key_name
