"""Coverage tests for protocol/certs.py, protocol/cert_extract.py, protocol/auth.py, and migration.py."""

from __future__ import annotations

import datetime
import io
import ssl
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiomqtt.exceptions import MqttConnectError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from custom_components.vidaa.const import CONF_AUTH_PROFILE, CONF_USE_SSL, DOMAIN, LEGACY_DOMAIN
from custom_components.vidaa.migration import (
    _async_check_and_manage_legacy_repair,
    _check_and_manage_legacy_repair,
    async_migrate_entry,
)
from custom_components.vidaa.protocol.auth import (
    apply_mqtt_tls,
    async_perform_token_refresh,
    async_probe_tv_auth_methods,
    build_mqtt_ssl_context,
    extract_connect_rc,
    probe_tv_auth_methods,
    test_tv_ssl_connection as run_test_tv_ssl_connection,
)
from custom_components.vidaa.protocol.cert_extract import (
    MAX_UPLOAD_SIZE,
    _extract_p12_bytes_from_archive,
    extract_and_install_certs,
    extract_pkcs12_to_pem,
)
from custom_components.vidaa.protocol.certs import check_certs_exist, validate_ssl_certs


def _generate_self_signed(tmp_path, key_type: str = "rsa"):
    if key_type == "ec":
        key = ec.generate_private_key(ec.SECP256R1())
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "VIDAA Test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    c_path = tmp_path / f"{key_type}.crt"
    k_path = tmp_path / f"{key_type}.key"
    c_path.write_bytes(cert_pem)
    k_path.write_bytes(key_pem)
    return key, cert, c_path, k_path


def test_certs_validation_and_extraction_branches(tmp_path) -> None:
    """Cover check_certs_exist, validate_ssl_certs cryptography fallbacks, and cert_extract error paths."""
    assert check_certs_exist(None, None) is False
    p12_path = tmp_path / "bundle.p12"
    p12_path.write_bytes(b"not-a-p12")
    assert check_certs_exist(str(p12_path), None) is True
    empty_crt = tmp_path / "only.crt"
    empty_crt.write_text("x")
    assert check_certs_exist(str(empty_crt), None) is False

    with patch("custom_components.vidaa.protocol.certs.extract_pkcs12_to_pem", return_value=None):
        ok, err = validate_ssl_certs(str(p12_path), None)
    assert not ok and "failed to extract" in (err or "")

    # RSA and EC cryptography fallback validation when SSLContext.load_cert_chain raises
    rsa_key, rsa_cert, rsa_c, rsa_k = _generate_self_signed(tmp_path, "rsa")
    _ec_key, _ec_cert, ec_c, ec_k = _generate_self_signed(tmp_path, "ec")

    with patch("ssl.SSLContext.load_cert_chain", side_effect=ssl.SSLError("sec level")):
        assert validate_ssl_certs(str(rsa_c), str(rsa_k)) == (True, None)
    with patch("ssl.SSLContext.load_cert_chain", side_effect=RuntimeError("unexpected")):
        assert validate_ssl_certs(str(ec_c), str(ec_k)) == (True, None)

    # Unsupported key type branch
    with (
        patch("ssl.SSLContext.load_cert_chain", side_effect=ssl.SSLError("fail")),
        patch("cryptography.hazmat.primitives.serialization.load_pem_private_key", return_value=object()),
    ):
        ok_unk, err_unk = validate_ssl_certs(str(rsa_c), str(rsa_k))
    assert not ok_unk and "Unsupported key type" in (err_unk or "")

    # extract_pkcs12_to_pem branches
    assert extract_pkcs12_to_pem(str(tmp_path / "missing.p12")) is None

    # Cache probe OSError branch + Path.read_bytes OSError
    with patch("os.path.getsize", side_effect=OSError("stat fail")):
        assert extract_pkcs12_to_pem(str(p12_path)) is None

    with patch("pathlib.Path.read_bytes", side_effect=OSError("read fail")):
        assert extract_pkcs12_to_pem(str(p12_path)) is None

    # Create a real encrypted PKCS12 with custom password
    p12_bytes = pkcs12.serialize_key_and_certificates(
        b"vidaa", rsa_key, rsa_cert, None, serialization.BestAvailableEncryption(b"custompass")
    )
    real_p12 = tmp_path / "real.p12"
    real_p12.write_bytes(p12_bytes)

    # Explicit str password + unwritable out_dir fallback
    import os

    real_makedirs = os.makedirs
    with (
        patch("tempfile.gettempdir", return_value=str(tmp_path / "temp_certs")),
        patch(
            "os.makedirs",
            side_effect=[PermissionError("ro"), real_makedirs(tmp_path / "temp_certs" / "vidaa_certs", exist_ok=True)],
        ),
    ):
        res_pem = extract_pkcs12_to_pem(str(real_p12), password="custompass", dest_dir=str(tmp_path / "ro"))
    assert res_pem is not None

    # load_key_and_certificates raises unexpected Exception
    with patch(
        "custom_components.vidaa.protocol.cert_extract.pkcs12.load_key_and_certificates",
        side_effect=RuntimeError("unexpected"),
    ):
        assert extract_pkcs12_to_pem(str(real_p12)) is None

    # Write failure saving PEMs
    fresh_p12 = tmp_path / "fresh.p12"
    fresh_p12.write_bytes(p12_bytes)
    with patch("builtins.open", side_effect=[MagicMock(), OSError("disk full")]):
        assert extract_pkcs12_to_pem(str(fresh_p12), password=b"custompass", dest_dir=str(tmp_path / "wfail")) is None

    # _extract_p12_bytes_from_archive branches
    big_zip = tmp_path / "big_member.zip"
    with zipfile.ZipFile(big_zip, "w") as zf:
        zf.writestr("custom/nested.p12", b"abc")
    with patch("zipfile.ZipInfo.file_size", 20 * 1024 * 1024, create=True):
        pass
    with zipfile.ZipFile(big_zip, "r") as zf:
        orig_getinfo = zipfile.ZipFile.getinfo
        with (
            patch.object(
                zipfile.ZipFile,
                "getinfo",
                lambda self_z, n: SimpleNamespace(file_size=20 * 1024 * 1024),
            ),
            pytest.raises(ValueError, match="exceeds size limit"),
        ):
            _extract_p12_bytes_from_archive(big_zip)
        _ = orig_getinfo

    # Non-canonical .p12 inside archive
    assert _extract_p12_bytes_from_archive(big_zip) == b"abc"

    # Nested .apk with non-canonical .p12, bad nested apk, traversal, and oversized inner apk
    nested_zip = tmp_path / "bundle.xapk"
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as izf:
        izf.writestr("other/key.pfx", b"INNER_PFX")
    with zipfile.ZipFile(nested_zip, "w") as zf:
        zf.writestr("corrupt.apk", b"not-a-zip")
        zf.writestr("inner.apk", inner_buf.getvalue())
    assert _extract_p12_bytes_from_archive(nested_zip) == b"INNER_PFX"

    # Nested apk path traversal
    trav_buf = io.BytesIO()
    with zipfile.ZipFile(trav_buf, "w") as izf:
        izf.writestr("../evil.p12", b"bad")
    trav_xapk = tmp_path / "trav.xapk"
    with zipfile.ZipFile(trav_xapk, "w") as zf:
        zf.writestr("evil.apk", trav_buf.getvalue())
    with pytest.raises(ValueError, match="Insecure file path"):
        _extract_p12_bytes_from_archive(trav_xapk)

    # Oversized nested apk skipped -> no keystore found
    with (
        patch.object(
            zipfile.ZipFile,
            "getinfo",
            lambda self_z, n: SimpleNamespace(file_size=MAX_UPLOAD_SIZE + 1),
        ),
        pytest.raises(ValueError, match="No VIDAA PKCS#12"),
    ):
        _extract_p12_bytes_from_archive(nested_zip)

    # extract_and_install_certs error classifications
    dest = tmp_path / "inst"
    with pytest.raises(ValueError, match="Uploaded file not found"):
        extract_and_install_certs(tmp_path / "nope.p12", dest)

    fake_stat = SimpleNamespace(st_size=MAX_UPLOAD_SIZE + 1)
    with patch("pathlib.Path.stat", return_value=fake_stat), pytest.raises(ValueError, match="exceeds maximum limit"):
        extract_and_install_certs(real_p12, dest)

    fake_non_zip_stat = SimpleNamespace(st_size=11 * 1024 * 1024)
    with patch("pathlib.Path.stat", return_value=fake_non_zip_stat), pytest.raises(ValueError, match="10 MB"):
        extract_and_install_certs(real_p12, dest)

    bad_key_end = tmp_path / "bad_key_end.pem"
    bad_key_end.write_text(
        "-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----\n-----BEGIN PRIVATE KEY-----\n"
    )
    with pytest.raises(ValueError, match="Malformed private key"):
        extract_and_install_certs(bad_key_end, dest)

    bad_key_parse = tmp_path / "bad_key_parse.pem"
    bad_key_parse.write_text(
        "-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----\n"
        "-----BEGIN PRIVATE KEY-----\nNOT_VALID\n-----END PRIVATE KEY-----\n"
    )
    with pytest.raises(ValueError, match="Failed parsing uploaded private key"):
        extract_and_install_certs(bad_key_parse, dest)

    bad_cert_parse = tmp_path / "bad_cert_parse.pem"
    bad_cert_parse.write_bytes(b"-----BEGIN CERTIFICATE-----\nBAD\n-----END CERTIFICATE-----\n" + rsa_k.read_bytes())
    with pytest.raises(ValueError, match="Malformed certificate"):
        extract_and_install_certs(bad_cert_parse, dest)

    # Wrong password on real P12 + str password
    with pytest.raises(ValueError, match="Failed to decrypt PKCS#12"):
        extract_and_install_certs(real_p12, dest, password="wrong")

    # Successful str password
    c_out, k_out = extract_and_install_certs(real_p12, dest, password="custompass")
    assert c_out.endswith("hisense.crt") and k_out.endswith("hisense.key")


@pytest.mark.anyio
async def test_protocol_auth_and_migration_coverage(tmp_path) -> None:
    """Cover protocol/auth.py and migration.py remaining branches."""
    # extract_connect_rc
    assert extract_connect_rc(SimpleNamespace(reason_code=SimpleNamespace(value=135))) == 135
    assert extract_connect_rc(SimpleNamespace(rc="bad")) == -1

    # build_mqtt_ssl_context & apply_mqtt_tls
    assert build_mqtt_ssl_context(use_ssl=False) is None
    _key, _cert, ca_path, key_path = _generate_self_signed(tmp_path, "rsa")
    ctx = build_mqtt_ssl_context(certfile=str(ca_path), keyfile=str(key_path), ca_cert=str(ca_path), verify_ssl=True)
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED

    with pytest.raises(FileNotFoundError, match="Certificate"):
        build_mqtt_ssl_context(certfile=str(tmp_path / "missing.crt"), keyfile=str(key_path))
    with pytest.raises(FileNotFoundError, match="Private Key"):
        build_mqtt_ssl_context(certfile=str(ca_path), keyfile=str(tmp_path / "missing.key"))

    paho_mock = MagicMock()
    apply_mqtt_tls(paho_mock, str(ca_path), str(key_path), ca_cert=str(ca_path), verify_ssl=True, use_ssl=True)
    paho_mock.tls_set.assert_called_once()

    # async_perform_token_refresh success + error paths
    async def _token_msgs():
        yield SimpleNamespace(topic="t/1", payload=b"bad-json")
        yield SimpleNamespace(topic="t/2", payload=b'{"accesstoken": "new_tok"}')

    fake_client = MagicMock()
    fake_client.messages = _token_msgs()
    fake_client.subscribe = AsyncMock()
    fake_client.publish = AsyncMock()
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    status: dict = {}
    with patch("aiomqtt.Client", return_value=fake_cm):
        res = await async_perform_token_refresh("192.168.1.100", "cid", "u", "ref", use_ssl=False, out_status=status)
    assert res == {"accesstoken": "new_tok"}
    assert status["connect_rc"] == 0

    for exc, expected_rc in (
        (MqttConnectError(5), 5),
        (TimeoutError(), None),
        (OSError("offline"), None),
        (RuntimeError("unexpected"), None),
    ):
        err_cm = MagicMock()
        err_cm.__aenter__ = AsyncMock(side_effect=exc)
        err_cm.__aexit__ = AsyncMock(return_value=False)
        st: dict = {}
        with patch("aiomqtt.Client", return_value=err_cm):
            assert (
                await async_perform_token_refresh("192.168.1.100", "cid", "u", "ref", use_ssl=False, out_status=st)
                is None
            )
        assert st["connect_rc"] == expected_rc

    # _probe_single unexpected Exception branch
    bad_probe_cm = MagicMock()
    bad_probe_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
    bad_probe_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("aiomqtt.Client", return_value=bad_probe_cm):
        probe = await async_probe_tv_auth_methods("192.168.1.100", timestamp=1700000000)
    assert probe["legacy_static"]["diagnostic"] == "no_connack"

    # Sync wrappers test_tv_ssl_connection & probe_tv_auth_methods
    with (
        patch("custom_components.vidaa.protocol.auth.asyncio.run", side_effect=[{"connected": True}, {"ok": True}]),
        patch("custom_components.vidaa.protocol.auth.async_test_tv_ssl_connection", MagicMock(return_value="C1")),
        patch("custom_components.vidaa.protocol.auth.async_probe_tv_auth_methods", MagicMock(return_value="C2")),
    ):
        assert run_test_tv_ssl_connection("192.168.1.100") == {"connected": True}
        assert probe_tv_auth_methods("192.168.1.100") == {"ok": True}

    # migration.py branches
    reg_entry = SimpleNamespace(entity_id="media_player.tv", platform=LEGACY_DOMAIN)
    ent_reg = MagicMock()
    ent_reg.async_update_entity_platform = MagicMock(side_effect=RuntimeError("immutable"))
    dev_reg = MagicMock()
    dev_reg.async_get_device.side_effect = RuntimeError("dr fail")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=MagicMock()))
    entry = SimpleNamespace(
        entry_id="m1",
        title="TV",
        domain=LEGACY_DOMAIN,
        version=1,
        minor_version=1,
        data={CONF_AUTH_PROFILE: "legacy", CONF_USE_SSL: False},
    )
    with (
        patch("custom_components.vidaa.migration.er.async_get", return_value=ent_reg),
        patch(
            "custom_components.vidaa.migration.er.async_entries_for_config_entry",
            return_value=[reg_entry],
            create=True,
        ),
        patch("custom_components.vidaa.migration.dr.async_get", return_value=dev_reg),
    ):
        assert await async_migrate_entry(hass, entry) is True
    assert reg_entry.platform == DOMAIN
    assert hass.config_entries.async_update_entry.call_args.kwargs["data"][CONF_USE_SSL] is True

    # er.async_get raising
    with (
        patch("custom_components.vidaa.migration.er.async_get", side_effect=RuntimeError("er fail")),
        patch("custom_components.vidaa.migration.dr.async_get", side_effect=RuntimeError("dr fail")),
    ):
        assert await async_migrate_entry(hass, entry) is True

    # _async_check_and_manage_legacy_repair without async_add_executor_job + exception + sync wrapper
    bare_hass = SimpleNamespace(config=SimpleNamespace(path=lambda *_p: str(tmp_path / "missing")))
    with patch("custom_components.vidaa.migration.ir.async_delete_issue") as mock_del:
        await _async_check_and_manage_legacy_repair(bare_hass)
    mock_del.assert_called_once()

    err_hass = SimpleNamespace(config=SimpleNamespace(path=MagicMock(side_effect=RuntimeError("bad path"))))
    await _async_check_and_manage_legacy_repair(err_hass)

    sync_hass = SimpleNamespace(
        loop=SimpleNamespace(is_running=lambda: True),
        async_create_background_task=MagicMock(),
    )
    with patch("custom_components.vidaa.migration._async_check_and_manage_legacy_repair", MagicMock(return_value="C")):
        _check_and_manage_legacy_repair(sync_hass)
    sync_hass.async_create_background_task.assert_called_once()
