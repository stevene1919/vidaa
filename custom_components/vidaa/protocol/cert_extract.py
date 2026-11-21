"""Certificate extraction, PKCS#12 decoding, and archive installation for VIDAA TV."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

_LOGGER = logging.getLogger(__name__)

# Known hardcoded keystore passwords across VIDAA and RemoteNOW Android applications
KNOWN_P12_PASSWORDS: tuple[bytes, ...] = (
    b"186e990688070325a1c4b0ce275d2388",  # VIDAA 2024 / standard multi-remote app
    b"multiremote",  # RemoteNOW / legacy app
    b"",  # Empty password fallback
)

# Canonical asset paths inside official APK / XAPK distributions
P12_CANDIDATES: tuple[str, ...] = (
    "res/raw/client_mobile_android.p12",
    "res/El.p12",
    "res/el.p12",
    "res/3R.p12",
    "assets/client_mobile_android.p12",
    "assets/El.p12",
)

# Maximum allowed size for uploaded archive (150 MB safety limit against zip bombs)
MAX_UPLOAD_SIZE = 150 * 1024 * 1024

__all__ = [
    "KNOWN_P12_PASSWORDS",
    "MAX_UPLOAD_SIZE",
    "P12_CANDIDATES",
    "extract_and_install_certs",
    "extract_pkcs12_to_pem",
]


def extract_pkcs12_to_pem(
    p12_path: str,
    password: bytes | str | None = None,
    dest_dir: str | None = None,
    target_dir: str | None = None,
) -> tuple[str, str] | None:
    """Extracts client certificate and private key PEM files from a PKCS#12 bundle."""
    if not p12_path or not os.path.isfile(p12_path):
        return None

    out_dir = dest_dir or target_dir
    base_name = os.path.splitext(os.path.basename(p12_path))[0]
    p12_mtime = os.path.getmtime(p12_path)

    candidate_dirs: list[str] = (
        [out_dir]
        if out_dir is not None
        else [
            os.path.dirname(os.path.abspath(p12_path)),
            os.path.join(tempfile.gettempdir(), "vidaa_certs"),
            os.path.join(tempfile.gettempdir(), "hisense_vidaa_certs"),
        ]
    )

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
        p12_data = Path(p12_path).read_bytes()
    except Exception as ex:
        _LOGGER.debug("Could not read PKCS#12 file '%s': %s", p12_path, ex)
        return None

    passwords_to_try: list[bytes | None] = []
    if password is not None:
        passwords_to_try.append(password.encode("utf-8") if isinstance(password, str) else password)
    passwords_to_try.extend(KNOWN_P12_PASSWORDS)

    private_key = None
    certificate = None

    for pwd in passwords_to_try:
        try:
            private_key, certificate, _additional_certs = pkcs12.load_key_and_certificates(p12_data, pwd)
            if private_key is not None and certificate is not None:
                break
        except (ValueError, TypeError):
            continue
        except Exception as ex:
            _LOGGER.debug("Unexpected error loading PKCS#12 with password candidate: %s", ex)
            continue

    if not private_key or not certificate:
        return None

    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(p12_path))

    # Verify out_dir is writable or fall back to system temp directory
    try:
        os.makedirs(out_dir, exist_ok=True)
        test_file = os.path.join(out_dir, ".test_write")
        with open(test_file, "wb") as f:
            f.write(b"")
        os.remove(test_file)
    except (OSError, PermissionError):
        out_dir = os.path.join(tempfile.gettempdir(), "vidaa_certs")
        os.makedirs(out_dir, exist_ok=True)

    out_cert_path = os.path.join(out_dir, f"{base_name}_cert.pem")
    out_key_path = os.path.join(out_dir, f"{base_name}_key.pem")

    try:
        with open(out_cert_path, "wb") as f_cert:
            f_cert.write(certificate.public_bytes(serialization.Encoding.PEM))

        with open(out_key_path, "wb") as f_key:
            f_key.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with contextlib.suppress(OSError):
            os.chmod(out_key_path, 0o600)

        return out_cert_path, out_key_path
    except Exception as ex:
        _LOGGER.warning("Failed saving extracted PEM certificates to '%s': %s", out_dir, ex)
        return None


def _extract_p12_bytes_from_archive(file_path: Path) -> bytes:
    """Extract raw PKCS#12 bytes from an APK or nested XAPK archive safely."""

    def _read_keystore(z: zipfile.ZipFile, name: str, nested: bool = False) -> bytes:
        if z.getinfo(name).file_size > 10 * 1024 * 1024:
            scope = "nested " if nested else ""
            raise ValueError(f"Keystore file in {scope}archive exceeds size limit")
        return z.read(name)

    with zipfile.ZipFile(file_path, "r") as archive:
        for member in archive.infolist():
            name = member.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise ValueError(f"Insecure file path detected in archive: {name}")

        names = archive.namelist()
        lower_names = {n.lower(): n for n in names}

        for candidate in P12_CANDIDATES:
            if candidate.lower() in lower_names:
                return _read_keystore(archive, lower_names[candidate.lower()])

        for name in names:
            if name.lower().endswith((".p12", ".pfx")) and not name.startswith("__MACOSX"):
                return _read_keystore(archive, name)

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
                                    return _read_keystore(inner_apk, inner_lower[candidate.lower()], nested=True)
                            for inner_name in inner_apk.namelist():
                                if inner_name.lower().endswith((".p12", ".pfx")) and not inner_name.startswith(
                                    "__MACOSX"
                                ):
                                    return _read_keystore(inner_apk, inner_name, nested=True)
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
    """Extract and install certificates from an uploaded APK, XAPK, P12, or PEM file."""
    src = Path(uploaded_path)
    dest = Path(target_dir)

    if not src.exists():
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
                private_key, certificate, _ = pkcs12.load_key_and_certificates(p12_bytes, pwd)
                if private_key and certificate:
                    break
            except (ValueError, TypeError):
                continue
            except Exception as ex:
                _LOGGER.debug("Failed testing candidate password: %s", ex)
                continue

    if not private_key or not certificate:
        raise ValueError("Failed to decrypt PKCS#12 keystore from uploaded file")

    dest.mkdir(parents=True, exist_ok=True)
    crt_path = dest / "hisense.crt"
    key_path = dest / "hisense.key"

    crt_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    with contextlib.suppress(OSError):
        key_path.chmod(0o600)

    return str(crt_path), str(key_path)
