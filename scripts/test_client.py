#!/usr/bin/env python3
"""Hisense VIDAA Integration CLI Test Script.

Allows direct testing and debugging of authentication, pairing PIN, token refreshes,
feature probing, and command execution using the exact same HisenseTvClient logic as the Home Assistant integration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

# Ensure script directory, repo root, or HA config is in Python path for package resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
COMP_DIR = os.path.join(REPO_ROOT, "custom_components", "vidaa")
HA_CONFIG_DIR = "/config"
for p in (REPO_ROOT, SCRIPT_DIR, HA_CONFIG_DIR):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

# Check required core client dependencies
missing = []
for pkg in ("aiomqtt", "cryptography"):
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)

if missing:
    print(
        f"\nERROR: Missing required dependencies: {' '.join(missing)}\n"
        f"Install them via pip:\n"
        f"    pip install {' '.join(missing)}\n",
        file=sys.stderr,
    )
    sys.exit(2)

from custom_components.vidaa.client import HisenseTvClient
from custom_components.vidaa.protocol.discovery import (
    BRAND_MAP,
    format_drift_human,
    get_arp_mac,
    get_tv_timestamp,
    probe_upnp_services,
)
from custom_components.vidaa.tv.probe import (
    create_client_from_creds,
    generate_markdown_report,
    load_credentials_file,
    probe_tv_features,
    save_credentials_file,
)

DEFAULT_CREDS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")


def do_ping(
    ip: str,
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    profile: str = "auto",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str = "his",
) -> None:
    print(f"\n[PING] Probing TV connectivity and MQTT broker at {ip}:36669 (Profile: {profile}, Brand: {brand})...")

    access_token = None
    client_id = None
    username = None
    if creds:
        access_token = creds.get("accesstoken") or creds.get("access_token")
        client_id = creds.get("client_id")
        username = creds.get("username")

    client = HisenseTvClient(
        ip=ip,
        client_id=client_id,
        username=username,
        access_token=access_token,
        certfile=certfile,
        keyfile=keyfile,
        ca_cert=ca_cert,
        auth_profile=profile,
        verify_ssl=verify_ssl,
        brand=brand,
    )

    try:
        res = client.ping()
        dev = res.get("device_info") or {}
        auth_probe = res.get("auth_probe") or {}

        print("\n📡 Connection Probe Results:")
        print(f"  • [1] TCP Port 36669:         {'✅ OPEN' if res['tcp_port_open'] else '❌ CLOSED / UNREACHABLE'}")
        print(
            f"  • [2] TLS Handshake:          {'✅ SUCCESS' if res['tls_handshake'] else '❌ FAILED'} ({res.get('tls_version') or 'N/A'}, {res.get('cipher') or 'N/A'})"
        )
        cert_pres = res.get("client_cert_presented")
        cert_path_str = f" ({res['certfile']})" if res.get("certfile") else ""
        print(
            f"  • Client Certificate:         {'✅ PRESENTED' + cert_path_str if cert_pres else '⚠️ NONE PRESENTED (Unauthenticated TLS)'}"
        )

        if res.get("mqtt_rc") is not None:
            if res["mqtt_connected"]:
                print("  • [3] Stored Credentials:     ✅ ACCEPTED (rc=0, broker is actively listening and responsive)")
            else:
                print(f"  • [3] Stored Credentials:     ⚠️ {res['mqtt_status']}")
        else:
            print(f"  • [3] Stored Credentials:     ℹ️ {res['mqtt_status']}")

        print("\n🔐 Initial Pairing Auth Compatibility:")
        std = auth_probe.get("standard_dynamic", {})
        middle = auth_probe.get("middle_dynamic", {})
        modern = auth_probe.get("modern_dynamic", {})
        legacy = auth_probe.get("legacy_static", {})

        std_p_str = "✅ ACCEPTED (rc=0)" if std.get("supported") else f"❌ REJECTED (rc={std.get('rc')})"
        mid_p_str = "✅ ACCEPTED (rc=0)" if middle.get("supported") else f"❌ REJECTED (rc={middle.get('rc')})"
        mod_p_str = "✅ ACCEPTED (rc=0)" if modern.get("supported") else f"❌ REJECTED (rc={modern.get('rc')})"
        leg_p_str = "✅ ACCEPTED (rc=0)" if legacy.get("supported") else f"❌ REJECTED (rc={legacy.get('rc')})"

        print(f"  • Standard Dynamic Auth:      {std_p_str}")
        print(f"  • Middle Dynamic Auth:        {mid_p_str}")
        print(f"  • Modern XOR Dynamic Auth:    {mod_p_str}")
        print(f"  • Legacy Static Auth:         {leg_p_str}")

        if (
            not legacy.get("supported")
            and not std.get("supported")
            and not middle.get("supported")
            and not modern.get("supported")
        ):
            if not cert_pres:
                print(
                    "\n⚠️  DIAGNOSTIC WARNING: All auth profiles were rejected with rc=5 and NO client certificate was presented!"
                )
                print(
                    "  • Many VIDAA models (especially UK/European models like 75E8QTUK, or TVs with strict broker configuration)"
                )
                print(
                    "    permit the TLS handshake without a client certificate, but actively reject all MQTT connections with rc=5"
                )
                print(
                    "    and display 'Your TV model is no longer compatible with the current version of our mobile app' on the screen."
                )
                print(
                    "  • Fix: Provide an official client certificate and private key via --cert and --key (or put hisense.crt/hisense.key in ssl/)."
                )
                print("  • If you have client_mobile_android.p12 from the official APK, convert it using OpenSSL:")
                print(
                    "    openssl pkcs12 -legacy -in client_mobile_android.p12 -passin pass:186e990688070325a1c4b0ce275d2388 -clcerts -nokeys -out hisense.crt"
                )
                print(
                    "    openssl pkcs12 -legacy -in client_mobile_android.p12 -passin pass:186e990688070325a1c4b0ce275d2388 -nocerts -nodes -out hisense.key"
                )
            else:
                print(
                    "\n⚠️  DIAGNOSTIC WARNING: All auth profiles were rejected (rc=5) despite presenting a client certificate."
                )
                print(
                    "  • Verify the certificate matches your TV's required auth profile, or your TV may use an updated credential signature."
                )

        if dev.get("model_code") or dev.get("model_name") or dev.get("friendly_name"):
            mfg = dev.get("manufacturer") or dev.get("brand") or BRAND_MAP.get(client.brand, client.brand.upper())
            model = dev.get("model_code") or dev.get("model_name") or dev.get("friendly_name")
            print(f"\n📺 Discovered TV Profile: {mfg} {model}")
            if dev.get("firmware_version"):
                print(f"  • Firmware Build:             {dev['firmware_version']}")
            if dev.get("platform"):
                print(f"  • Platform Indicator:         Platform {dev['platform']}")
        print(f"  • OEM Brand:                  {client.brand.upper()} ({BRAND_MAP.get(client.brand, client.brand)})")

        arp_mac = get_arp_mac(ip)
        if arp_mac:
            print(f"  • Discovered MAC (ARP):       {arp_mac}")
        if dev.get("mac_wifi"):
            print(f"  • Wi-Fi MAC (UPnP):           {dev['mac_wifi']}")
        if dev.get("mac_ethernet"):
            print(f"  • Ethernet MAC (UPnP):        {dev['mac_ethernet']}")

        tv_ts = get_tv_timestamp(ip, timeout=2.0)
        now_ts = int(time.time())
        if tv_ts:
            drift = tv_ts - now_ts
            tv_dt = datetime.fromtimestamp(tv_ts, tz=UTC)
            drift_str = format_drift_human(drift)
            print(
                f"  • TV Hardware Clock:          {tv_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (drift: {drift:+}s, {drift_str})"
            )
        else:
            print("  • TV Hardware Clock:          Unavailable (Port 38400 unreachable or Date header missing)")

        if res.get("auth_recommendation"):
            print("\n💡 Firmware Compatibility & Integration Recommendation:")
            print(f"  • {res['auth_recommendation']}")

        if res.get("error"):
            print(f"\n⚠️ Notice: {res['error']}")
    except FileNotFoundError as e:
        print(f"\n❌ Certificate Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Probe Failed: {e}")
        sys.exit(1)


def do_probe(
    ip: str,
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    profile: str = "auto",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str = "his",
) -> None:
    print(f"\n🔍 [PROBE] Probing TV features and menu capabilities at {ip}:36669 (Brand: {brand})...\n")
    client = (
        create_client_from_creds(
            creds,
            certfile,
            keyfile,
            ca_cert=ca_cert,
            verify_ssl=verify_ssl,
            auth_profile=profile,
            brand=brand,
        )
        if creds
        else HisenseTvClient(
            ip=ip,
            certfile=certfile,
            keyfile=keyfile,
            ca_cert=ca_cert,
            auth_profile=profile,
            verify_ssl=verify_ssl,
            brand=brand,
        )
    )

    probe_res = probe_tv_features(client, wait_time=2.5)
    if not probe_res.connected:
        print("❌ Could not connect to TV MQTT broker. Ensure TV is powered on and paired.")
        return

    print("=" * 70)
    print("📋 TV Feature Capabilities & Settings Tree:")
    print("=" * 70 + "\n")

    print("### 🖼️ Picture Settings & Modes")
    if probe_res.picture_settings:
        for item in probe_res.picture_settings:
            opts = f" (Options: {', '.join(item.options)})" if item.options else ""
            val = f" [Current: {item.menu_value}]" if item.menu_value is not None else ""
            print(f"- **{item.menu_name}** (ID: `{item.menu_id}`, Type: `{item.menu_type}`){val}{opts}")
    else:
        print("- No dynamic picture menu data returned (Static defaults active)")

    print("\n### 🔊 Sound Settings & Modes")
    if probe_res.sound_settings:
        for item in probe_res.sound_settings:
            opts = f" (Options: {', '.join(item.options)})" if item.options else ""
            val = f" [Current: {item.menu_value}]" if item.menu_value is not None else ""
            print(f"- **{item.menu_name}** (ID: `{item.menu_id}`, Type: `{item.menu_type}`){val}{opts}")
    else:
        print("- No dynamic sound menu data returned (Static defaults active)")

    print(f"\n### 🔌 Input Sources ({len(probe_res.sources)} detected)")
    for s in probe_res.sources:
        active = " [ACTIVE]" if s.get("is_signal") in ("1", 1, True) or s.get("is_active") else ""
        print(f"- `{s.get('sourceid')}`: **{s.get('sourcename', 'Unknown')}**{active}")

    print(f"\n### 📱 Installed Smart TV Applications ({len(probe_res.apps)} detected)")
    for a in probe_res.apps[:20]:
        print(f"- **{a.get('name') or a.get('appName', 'Unknown')}** (`appId`: `{a.get('appId')}`)")
    if len(probe_res.apps) > 20:
        print(f"- ... and {len(probe_res.apps) - 20} more apps")

    print("\n" + "=" * 70)


def do_report(
    ip: str,
    mac: str | None,
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    profile: str = "auto",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    probe: bool = False,
    brand: str = "his",
) -> None:
    print(f"\n🔍 [REPORT] Collecting diagnostics and generating GitHub issue report for {ip} (Brand: {brand})...\n")

    access_token = None
    client_id = None
    username = None
    if creds:
        access_token = creds.get("accesstoken") or creds.get("access_token")
        client_id = creds.get("client_id")
        username = creds.get("username")

    client = HisenseTvClient(
        ip=ip,
        mac=mac,
        client_id=client_id,
        username=username,
        access_token=access_token,
        certfile=certfile,
        keyfile=keyfile,
        ca_cert=ca_cert,
        auth_profile=profile,
        verify_ssl=verify_ssl,
        brand=brand,
    )

    try:
        ping_res = client.ping(timeout=3.0)
        version = "Unknown"
        manifest_path = os.path.join(COMP_DIR, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path) as f:
                    version = json.load(f).get("version", "Unknown")
            except Exception:
                pass

        probe_res = None
        if probe and ping_res.get("tcp_port_open") and (creds or client.auth_profile == "legacy"):
            probe_client = (
                create_client_from_creds(
                    creds,
                    certfile,
                    keyfile,
                    ca_cert=ca_cert,
                    verify_ssl=verify_ssl,
                    auth_profile=profile,
                    brand=brand,
                )
                if creds
                else client
            )
            probe_res = probe_tv_features(probe_client, wait_time=2.0)

        report_md = generate_markdown_report(
            ip=ip,
            ping_result=ping_res,
            probe_result=probe_res,
            mac=mac,
            version=version,
        )

        print("=" * 70)
        print("📋 Copy & Paste the Markdown below into your GitHub Issue report:")
        print("=" * 70 + "\n")
        print(report_md)
        print("\n" + "=" * 70)
    except FileNotFoundError as e:
        print(f"\n❌ Certificate Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Report Generation Failed: {e}")
        sys.exit(1)


def do_test_ssl(
    ip: str,
    certfile: str | None,
    keyfile: str | None,
    profile: str = "auto",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str = "his",
) -> None:
    brand_name = BRAND_MAP.get(brand, "Hisense")
    print(
        f"\n[SSL] Testing raw TLS connection to {brand_name} TV at {ip}:36669 (Profile: {profile}, Brand: {brand})..."
    )
    client = HisenseTvClient(
        ip=ip,
        certfile=certfile,
        keyfile=keyfile,
        ca_cert=ca_cert,
        auth_profile=profile,
        verify_ssl=verify_ssl,
        brand=brand,
    )
    try:
        res = client.test_ssl_connection()
        print("\n✅ TLS Connection Successful!")
        print(f"  • TV Address:         {ip}:36669")
        print(f"  • TLS Version:        {res['tls_version']}")
        print(f"  • Cipher Suite:       {res['cipher']} ({res['bits']} bits)")
        cert_pres = res.get("client_cert_presented")
        print(f"  • Client Certificate: {'✅ PRESENTED' if cert_pres else '⚠️ NONE PRESENTED (Unauthenticated TLS)'}")
        if cert_pres:
            print(f"  • Certificate File:   {res['certfile']}")
            print(f"  • Private Key File:   {res['keyfile']}")
        if res.get("ca_cert"):
            print(f"  • Root CA:            {res['ca_cert']}")
    except FileNotFoundError as e:
        print(f"\n❌ Certificate Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ TLS Connection Failed: {e}")
        sys.exit(1)


async def do_auth(
    ip: str,
    mac: str | None,
    certfile: str | None,
    keyfile: str | None,
    save_path: str,
    profile: str = "auto",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str = "his",
) -> None:
    if not mac:
        mac = get_arp_mac(ip)
        if mac:
            print(f"🔍 Auto-discovered Hardware MAC via ARP: {mac}")
    brand_name = BRAND_MAP.get(brand, "Hisense")
    print(f"\n[AUTH] Connecting to {brand_name} TV at {ip} on port 36669 (TLS, Profile: {profile}, Brand: {brand})...")
    client = HisenseTvClient(
        ip=ip,
        mac=mac,
        certfile=certfile,
        keyfile=keyfile,
        ca_cert=ca_cert,
        auth_profile=profile,
        verify_ssl=verify_ssl,
        brand=brand,
    )
    try:
        await client.async_start_auth()
        if client.brand != brand:
            print(f"ℹ️ Auto-detected TV OEM Brand: {client.brand.upper()} ({BRAND_MAP.get(client.brand, client.brand)})")

        if profile == "legacy" or client.auth_profile == "legacy":
            print("\n✅ Legacy static credentials active (no PIN required)!")
            creds = {
                "ip_address": ip,
                "mac_address": mac,
                "brand": client.brand,
                "auth_profile": "legacy",
                "client_id": client.client_id,
                "username": client.username,
                "password": client.password,
                "accesstoken": client.access_token,
                "accesstoken_time": 0,
                "accesstoken_duration_day": 0,
                "refreshtoken": None,
                "refreshtoken_time": 0,
                "refreshtoken_duration_day": 0,
            }
            save_credentials_file(save_path, creds)
            return

        print("\n✅ Initial connection established!")
        print("📺 Look at your TV screen. A 4-digit PIN should now be visible.")
        loop = asyncio.get_running_loop()
        pin = (await loop.run_in_executor(None, input, "👉 Enter the 4-digit PIN: ")).strip()

        print(f"\n[AUTH] Submitting PIN '{pin}' and requesting tokens...")
        await client.async_submit_pin(pin)

        creds = {
            "ip_address": ip,
            "mac_address": mac,
            "brand": client.brand,
            "client_id": client.client_id,
            "username": client.username,
            "password": client.password,
            "accesstoken": client.access_token,
            "accesstoken_time": client.access_token_time,
            "accesstoken_duration_day": client.access_token_duration,
            "refreshtoken": client.refresh_token,
            "refreshtoken_time": client.refresh_token_time,
            "refreshtoken_duration_day": client.refresh_token_duration,
        }

        print("\n🎉 Authentication successful!")
        print(f"  • OEM Brand:     {client.brand.upper()} ({BRAND_MAP.get(client.brand, client.brand)})")
        print(f"  • Client ID:     {client.client_id}")
        print(f"  • Username:      {client.username}")
        print(f"  • Access Token:  *** (valid {client.access_token_duration} days)")
        print(f"  • Refresh Token: *** (valid {client.refresh_token_duration} days)")

        save_credentials_file(save_path, creds)
    except FileNotFoundError as e:
        print(f"\n❌ Certificate Error: {e}")
        print(
            "  💡 Tip: Ensure your client certificate (.pem/.crt) and private key (.key) are placed in ssl/ or specified via --cert / --key."
        )
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        err_str = str(e).lower()
        if "code 5" in err_str or "not authorized" in err_str:
            print("\n💡 Diagnosis (MQTT RC 5):")
            print("  • The TV broker rejected the initial credentials during pairing.")
            if not client.certfile or not client.keyfile:
                print("  • ⚠️ NO CLIENT CERTIFICATE WAS PRESENTED!")
                print(
                    "    Many VIDAA models (especially UK/European models like 75E8QTUK, or TVs with strict broker security)"
                )
                print("    allow TLS negotiation without a client cert, but reject all pairing attempts with rc=5")
                print(
                    "    and display 'Your TV model is no longer compatible with the current version of our mobile app' on the screen."
                )
                print(
                    "    Provide client certificates via --cert and --key (or put hisense.crt and hisense.key in ssl/)."
                )
                print("    If using a .p12 archive, convert it using OpenSSL with -legacy:")
                print(
                    "    openssl pkcs12 -legacy -in client_mobile_android.p12 -passin pass:186e990688070325a1c4b0ce275d2388 -clcerts -nokeys -out hisense.crt"
                )
                print(
                    "    openssl pkcs12 -legacy -in client_mobile_android.p12 -passin pass:186e990688070325a1c4b0ce275d2388 -nocerts -nodes -out hisense.key"
                )
            else:
                print("  • If your TV is running a newer firmware build (e.g. VIDAA U7+ / Q0704+),")
                print("    it may require a newer authentication signature currently under development.")
            print("  • Run the diagnostic report to capture TV details:")
            print(f"    python3 test_client.py report --ip {ip} --probe")
        elif "timed out" in err_str:
            print("\n💡 Diagnosis (Timeout):")
            print("  • The TV did not respond to the PIN handshake request in time.")
            print("  • Ensure the TV screen is turned ON and connected to the same local network subnet.")
        sys.exit(1)


async def do_listen(
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    save_path: str,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[LISTEN] Connecting to TV at {ip} with stored credentials...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)

    def on_token_refreshed(c: HisenseTvClient) -> None:
        print(f"\n🔄 [TOKEN REFRESHED] New access token received (valid {c.access_token_duration} days)")
        creds["accesstoken"] = c.access_token
        creds["accesstoken_time"] = c.access_token_time
        creds["refreshtoken"] = c.refresh_token
        creds["refreshtoken_time"] = c.refresh_token_time
        save_credentials_file(save_path, creds)

    client.register_token_refreshed_callback(on_token_refreshed)
    client.register_state_callback(lambda data: print(f"📡 [STATE] {json.dumps(data)}"))
    client.register_volume_callback(lambda data: print(f"🔊 [VOLUME] {json.dumps(data)}"))
    client.register_picture_callback(lambda data: print(f"🖼️ [PICTURE] {json.dumps(data)}"))
    client.register_sound_callback(lambda data: print(f"🎵 [SOUND] {json.dumps(data)}"))
    client.register_sourcelist_callback(lambda data: print(f"🔌 [SOURCES] Found {len(data)} inputs"))
    client.register_applist_callback(lambda data: print(f"📱 [APPS] Found {len(data)} installed apps"))
    client.register_disconnected_callback(lambda: print("⚠️ [DISCONNECTED] TV disconnected"))

    await client.async_connect_and_run()
    print("Listening for TV events (Press Ctrl+C to stop)...")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.async_disconnect()


async def do_sniff(
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    topic: str = "/remoteapp/#",
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[SNIFF] Connecting to TV at {ip} and subscribing to topic filter '{topic}'...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)

    def on_raw(t: str, p: str) -> None:
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        try:
            parsed = json.loads(p)
            formatted = json.dumps(parsed, indent=2)
        except Exception:
            formatted = p
        print(f"\n[{now}] 📥 Topic: {t}\n{formatted}")

    if hasattr(client, "register_raw_message_callback"):
        client.register_raw_message_callback(on_raw)
    client.register_disconnected_callback(lambda: print("\n⚠️ [DISCONNECTED] TV disconnected"))

    def on_connected() -> None:
        print(f"✅ Connected! Subscribing to wildcard topic: {topic}")
        if client.mqtt_client:
            client.mqtt_client.subscribe(topic)

    client.register_connected_callback(on_connected)

    await client.async_connect_and_run()
    print(f"Sniffing MQTT broker messages on '{topic}' (Press Ctrl+C to stop)...")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await client.async_disconnect()


def do_probe_udp(ip: str, timeout: float = 2.0, port: int = 36671) -> None:
    from custom_components.vidaa.protocol.discovery import probe_udp_port

    print(f"\n[UDP PROBE] Sending discovery probe to {ip}:{port} (timeout={timeout}s)...")
    res = probe_udp_port(ip, timeout=timeout, port=port)
    if res:
        print("✅ Received UDP discovery response from TV!")
        print(f"  • Name:     {res.get('name')}")
        print(f"  • Model:    {res.get('model')}")
        print(f"  • MAC:      {res.get('mac')}")
        print(f"  • Raw JSON: {json.dumps(res.get('raw'), indent=2)}")
    else:
        print(f"❌ No response received from {ip}:{port} within {timeout}s.")
        print("   (Note: Older RemoteNow TVs listen on UDP 36671, while modern VIDAA sets use UPnP/MQTT).")


def do_refresh(
    creds: dict[str, Any],
    certfile: str | None,
    keyfile: str | None,
    save_path: str,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[REFRESH] Testing synchronous token refresh against TV at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    success = client.check_and_refresh_token(force=True)
    if success:
        print("✅ Token refreshed successfully!")
        print(f"  • New Access Token:  *** (valid {client.access_token_duration} days)")
        print(f"  • Issued At:         {time.ctime(client.access_token_time)}")
        creds["accesstoken"] = client.access_token
        creds["accesstoken_time"] = client.access_token_time
        creds["refreshtoken"] = client.refresh_token
        creds["refreshtoken_time"] = client.refresh_token_time
        save_credentials_file(save_path, creds)
    else:
        print("❌ Token refresh failed. Check TV connectivity and broker logs.")


def do_send_key(
    creds: dict[str, Any],
    key_name: str,
    certfile: str | None,
    keyfile: str | None,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[KEY] Sending key '{key_name}' to TV at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    client.connect_and_run()
    for _ in range(30):
        if client.connected:
            break
        time.sleep(0.1)

    if client.connected:
        client.send_key(key_name)
        print(f"✅ Sent '{key_name}' successfully.")
        time.sleep(0.5)
    else:
        print("❌ Could not connect to TV to send key.")

    client.disconnect()


def do_send_text(
    creds: dict[str, Any],
    text: str,
    action: str = "insert",
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[TEXT] Sending text '{text}' (action: {action}) to TV at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    client.connect_and_run()
    for _ in range(30):
        if client.connected:
            break
        time.sleep(0.1)

    if client.connected:
        client.send_text_input(text, action=action)
        print(f"✅ Sent text '{text}' successfully.")
        time.sleep(0.5)
    else:
        print("❌ Could not connect to TV to send text.")

    client.disconnect()


def do_launch_app(
    creds: dict[str, Any],
    app_name: str,
    app_id: str | None = None,
    app_url: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[APP] Launching application '{app_name or app_id}' on TV at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    client.connect_and_run()
    for _ in range(30):
        if client.connected:
            break
        time.sleep(0.1)

    if client.connected:
        client.launch_app(app_id=app_id or "", app_name=app_name or "", url=app_url or "")
        print(f"✅ Sent launch command for '{app_name or app_id}' (url: {app_url or 'default'}).")
        time.sleep(0.5)
    else:
        print("❌ Could not connect to TV to launch app.")

    client.disconnect()


def do_change_source(
    creds: dict[str, Any],
    source_target: str,
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[SOURCE] Switching to input '{source_target}' on TV at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    client.connect_and_run()
    for _ in range(30):
        if client.connected:
            break
        time.sleep(0.1)

    if client.connected:
        client.change_source(source_target)
        print(f"✅ Source change to '{source_target}' dispatched successfully.")
        time.sleep(0.5)
    else:
        print("❌ Could not connect to TV to switch input source.")

    client.disconnect()


def do_state(
    creds: dict[str, Any],
    certfile: str | None = None,
    keyfile: str | None = None,
    ca_cert: str | None = None,
    verify_ssl: bool = False,
    brand: str | None = None,
) -> None:
    ip = creds.get("ip_address")
    print(f"\n[STATE] Querying live TV snapshot at {ip}...")

    client = create_client_from_creds(creds, certfile, keyfile, ca_cert=ca_cert, verify_ssl=verify_ssl, brand=brand)
    state_cache: dict[str, Any] = {"sources": [], "apps": []}
    client.register_sourcelist_callback(lambda data: state_cache.__setitem__("sources", data))
    client.register_applist_callback(lambda data: state_cache.__setitem__("apps", data))

    client.connect_and_run()
    for _ in range(30):
        if client.connected:
            break
        time.sleep(0.1)

    if not client.connected:
        print("❌ Could not connect to TV to query state.")
        client.disconnect()
        return

    time.sleep(1.5)

    print("\n📊 TV State Snapshot:")
    print(f"  • MQTT Connected:      {client.connected}")
    print(f"  • Auth Profile:        {client.auth_profile}")
    print(f"  • OEM Brand:           {client.brand.upper()} ({BRAND_MAP.get(client.brand, client.brand)})")
    if client.access_token_time and client.access_token_duration:
        exp_dt = datetime.fromtimestamp(client.access_token_time + client.access_token_duration * 86400, tz=UTC)
        print(f"  • Access Token Expiry: {exp_dt}")
    print(f"  • Power State:         {'ON' if client.is_on else 'OFF/STANDBY'}")
    if client.volume is not None:
        print(f"  • Volume:              {client.volume}% ({'MUTED' if client.muted else 'UNMUTED'})")
    if client.active_source:
        print(f"  • Active Source:       {client.active_source}")
    if client.active_app:
        print(f"  • Active App:          {client.active_app}")

    if state_cache["sources"]:
        print(f"\n🔌 Available Sources ({len(state_cache['sources'])}):")
        for s in state_cache["sources"]:
            active = " [ACTIVE]" if s.get("is_signal") in ("1", 1, True) or s.get("is_active") else ""
            print(f"    - {s.get('sourcename', 'Unknown')} (ID: {s.get('sourceid')}){active}")

    if state_cache["apps"]:
        print(f"\n📱 Installed Apps ({len(state_cache['apps'])}):")
        app_names = [a.get("name") for a in state_cache["apps"] if a.get("name")]
        print("    " + ", ".join(sorted(app_names)[:15]) + ("..." if len(app_names) > 15 else ""))

    client.disconnect()


def do_wake(ip: str, mac: str) -> None:
    print(f"\n[WOL] Sending Wake-on-LAN magic packet to {mac} (Target IP: {ip})...")
    success = HisenseTvClient.send_wake_on_lan(mac=mac, ip=ip)
    if success:
        print(f"✅ Wake-on-LAN magic packet successfully broadcast for MAC {mac}.")
    else:
        print(f"❌ Failed to send Wake-on-LAN packet for MAC {mac}.")


def do_upnp(ip: str) -> None:
    """Probe UPnP MediaRenderer services and actions on the TV."""
    print(f"\n[UPnP] Probing UPnP MediaRenderer services on {ip}:38400...")
    probe_upnp_services(ip, verbose=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hisense VIDAA Integration CLI Test Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Generate Markdown diagnostics report for GitHub issues:
  python3 test_client.py report --ip 192.168.50.12 --probe

  # Probe picture/sound menu capabilities and dynamic options:
  python3 test_client.py probe --ip 192.168.50.12

  # Quick 3-tier connectivity & MQTT broker listening probe:
  python3 test_client.py ping --ip 192.168.50.12

  # Probe UPnP MediaRenderer services and actions:
  python3 test_client.py upnp --ip 192.168.50.12

  # Test raw SSL/TLS certificate connection to TV:
  python3 test_client.py test-ssl --ip 192.168.50.12

  # Pair with TV and save credentials:
  python3 test_client.py auth --ip 192.168.50.12

  # Listen for real-time status and state updates:
  python3 test_client.py listen

  # Send a remote key (e.g. KEY_POWER, KEY_VOLUMEUP, KEY_HOME, KEY_AUDIO):
  python3 test_client.py send-key KEY_POWER

  # Launch an app on the TV:
  python3 test_client.py launch-app "Netflix"

  # Send Wake-on-LAN magic packet:
  python3 test_client.py wake --mac E8:51:77:EC:98:1C --ip 192.168.50.12

  # Send text input to on-screen search / keyboard field:
  python3 test_client.py text "The Matrix"
  python3 test_client.py text --text-action clear
""",
    )

    parser.add_argument(
        "action",
        choices=[
            "ping",
            "report",
            "probe",
            "probe-features",
            "test-ssl",
            "auth",
            "pair",
            "listen",
            "monitor",
            "state",
            "dump-state",
            "refresh",
            "send-key",
            "launch-app",
            "source",
            "change-source",
            "text",
            "send-text",
            "wake",
            "upnp",
            "sniff",
            "probe-udp",
        ],
        help="Action to perform",
    )
    parser.add_argument(
        "key",
        nargs="?",
        help="Key name (for send-key), App name (for launch-app), Source name/ID (for source), or text string (for text)",
    )
    parser.add_argument(
        "--ip", help="IP address of the TV (required for ping/report/probe/test-ssl/auth/wake if not in config)"
    )
    parser.add_argument("--mac", help="MAC address of the TV")
    parser.add_argument(
        "--profile",
        choices=["auto", "modern", "middle", "remotenow", "legacy", "vidaa_2024", "remotenow_2018"],
        default="auto",
        help="Authentication profile and cert selector (default: auto)",
    )
    parser.add_argument(
        "--brand",
        default="his",
        help="TV OEM brand identifier for pairing salt/prefix (e.g. his, tos, loe, tpv, shp, jvc; default: his)",
    )
    parser.add_argument("--cert", help="Path to custom client certificate file (e.g. cert.pem)")
    parser.add_argument("--key", dest="key_file", help="Path to custom client private key file (e.g. key.pem)")
    parser.add_argument("--p12", help="Path to PKCS#12 certificate archive (e.g. client_mobile_android.p12)")
    parser.add_argument(
        "--ca", "--ca-cert", dest="ca_cert", help="Path to custom root CA certificate (e.g. remote_ca.pem)"
    )
    parser.add_argument("--verify-ssl", action="store_true", help="Enable strict TLS server certificate verification")
    parser.add_argument(
        "--probe", action="store_true", help="Include active feature & menu tree probing in markdown report"
    )
    parser.add_argument("--app-id", help="App ID for launch-app action")
    parser.add_argument("--url", help="Deep link URL for launch-app action (e.g. netflix://)")
    parser.add_argument("--text", help="Text string to inject (for 'text' or 'send-text' action)")
    parser.add_argument(
        "--text-action",
        choices=["insert", "replace", "clear"],
        default="insert",
        help="Action mode for text injection (default: insert)",
    )
    parser.add_argument(
        "--config", default=DEFAULT_CREDS_FILE, help=f"Path to credentials file (default: {DEFAULT_CREDS_FILE})"
    )
    parser.add_argument(
        "--topic", default="/remoteapp/#", help="MQTT topic or wildcard filter for sniff action (default: /remoteapp/#)"
    )
    parser.add_argument("-v", "--debug", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    cert_path = args.p12 or args.cert
    key_path = args.key_file

    if cert_path and (cert_path.lower().endswith(".p12") or cert_path.lower().endswith(".pfx")):
        from custom_components.vidaa.protocol import extract_pkcs12_to_pem

        extracted = extract_pkcs12_to_pem(cert_path)
        if extracted:
            cert_path, key_path = extracted
            print(
                f"ℹ️ Automatically extracted PKCS#12 bundle:\n   • Certificate: {cert_path}\n   • Private Key: {key_path}"
            )
        else:
            print(f"\n⚠️ Warning: Could not automatically extract certificates from PKCS#12 archive: {cert_path}")
            print("  If the archive uses legacy PKCS#12 encryption (standard in VIDAA mobile app bundles),")
            print("  convert it to PEM format using OpenSSL with the -legacy flag:")
            print(
                f"    openssl pkcs12 -legacy -in {cert_path} -passin pass:186e990688070325a1c4b0ce275d2388 -clcerts -nokeys -out hisense.crt"
            )
            print(
                f"    openssl pkcs12 -legacy -in {cert_path} -passin pass:186e990688070325a1c4b0ce275d2388 -nocerts -nodes -out hisense.key"
            )
            print("  Then pass: --cert hisense.crt --key hisense.key\n")
            cert_path = None
            key_path = None

    creds = load_credentials_file(args.config)
    brand = (
        creds.get("brand")
        if (args.brand == "his" and creds.get("brand"))
        else ("his" if args.brand == "auto" else args.brand)
    )

    if args.action == "ping":
        ip = args.ip or (creds.get("ip_address") if creds else None)
        if not ip:
            print("Error: --ip <IP> is required for 'ping' action (or valid credentials.json).")
            sys.exit(1)
        do_ping(
            ip,
            creds,
            cert_path,
            key_path,
            profile=args.profile,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action in ("probe", "probe-features"):
        ip = args.ip or (creds.get("ip_address") if creds else None)
        if not ip:
            print("Error: --ip <IP> is required for 'probe' action (or valid credentials.json).")
            sys.exit(1)
        do_probe(
            ip,
            creds,
            cert_path,
            key_path,
            profile=args.profile,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action == "report":
        ip = args.ip or (creds.get("ip_address") if creds else None)
        if not ip:
            print("Error: --ip <IP> is required for 'report' action (or valid credentials.json).")
            sys.exit(1)
        do_report(
            ip,
            args.mac,
            creds,
            cert_path,
            key_path,
            profile=args.profile,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            probe=args.probe,
            brand=brand,
        )

    elif args.action == "test-ssl":
        if not args.ip:
            print("Error: --ip <IP> is required for 'test-ssl' action.")
            sys.exit(1)
        do_test_ssl(
            args.ip,
            cert_path,
            key_path,
            profile=args.profile,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action in ("auth", "pair"):
        if not args.ip:
            print("Error: --ip <IP> is required for 'auth' / 'pair' action.")
            sys.exit(1)
        asyncio.run(
            do_auth(
                args.ip,
                args.mac,
                cert_path,
                key_path,
                args.config,
                profile=args.profile,
                ca_cert=args.ca_cert,
                verify_ssl=args.verify_ssl,
                brand=brand,
            )
        )

    elif args.action in ("listen", "monitor"):
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        asyncio.run(
            do_listen(
                creds, cert_path, key_path, args.config, ca_cert=args.ca_cert, verify_ssl=args.verify_ssl, brand=brand
            )
        )

    elif args.action in ("state", "dump-state"):
        ip = args.ip or creds.get("ip_address")
        if not ip:
            print("Error: --ip <IP> is required for 'state' action (or valid credentials.json).")
            sys.exit(1)
        creds["ip_address"] = ip
        do_state(creds, cert_path, args.key_file, ca_cert=args.ca_cert, verify_ssl=args.verify_ssl, brand=brand)

    elif args.action in ("source", "change-source"):
        source_target = args.key
        if not source_target:
            print("Error: Specify source name or ID to change to, e.g. python3 test_client.py source HDMI1")
            sys.exit(1)
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        do_change_source(
            creds,
            source_target,
            certfile=cert_path,
            keyfile=args.key_file,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action == "refresh":
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        do_refresh(
            creds, cert_path, args.key_file, args.config, ca_cert=args.ca_cert, verify_ssl=args.verify_ssl, brand=brand
        )

    elif args.action == "send-key":
        if not args.key:
            print("Error: Specify key name to send, e.g. python3 test_client.py send-key KEY_POWER")
            sys.exit(1)
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        do_send_key(
            creds, args.key, cert_path, args.key_file, ca_cert=args.ca_cert, verify_ssl=args.verify_ssl, brand=brand
        )

    elif args.action in ("text", "send-text"):
        text = args.text or args.key
        if not text and args.text_action != "clear":
            print(
                "Error: Specify text to send, e.g. python3 test_client.py text 'The Matrix' or python3 test_client.py text --text-action clear"
            )
            sys.exit(1)
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        do_send_text(
            creds,
            text or "",
            action=args.text_action,
            certfile=cert_path,
            keyfile=args.key_file,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action == "launch-app":
        app_name = args.key
        if not app_name and not args.app_id:
            print("Error: Specify app name or --app-id to launch, e.g. python3 test_client.py launch-app 'Netflix'")
            sys.exit(1)
        ip = args.ip or creds.get("ip_address")
        creds["ip_address"] = ip
        do_launch_app(
            creds,
            app_name,
            app_id=args.app_id,
            app_url=args.url,
            certfile=cert_path,
            keyfile=args.key_file,
            ca_cert=args.ca_cert,
            verify_ssl=args.verify_ssl,
            brand=brand,
        )

    elif args.action == "wake":
        ip = args.ip or creds.get("ip_address")
        mac = args.mac or creds.get("mac_address")
        if not mac and ip:
            mac = get_arp_mac(ip)
        if not mac:
            print("Error: --mac <MAC> (or valid IP with ARP cache entry) is required for 'wake' action.")
            sys.exit(1)
        do_wake(ip, mac)

    elif args.action == "upnp":
        ip = args.ip or (creds.get("ip_address") if creds else None)
        if not ip:
            print("Error: --ip <IP> is required for 'upnp' action (or valid credentials.json).")
            sys.exit(1)
        do_upnp(ip)

    elif args.action == "sniff":
        ip = args.ip or creds.get("ip_address")
        if not ip:
            print("Error: --ip <IP> is required for 'sniff' action (or valid credentials.json).")
            sys.exit(1)
        creds["ip_address"] = ip
        topic_target = args.key or args.topic or "/remoteapp/#"
        asyncio.run(
            do_sniff(
                creds,
                cert_path,
                args.key_file,
                topic=topic_target,
                ca_cert=args.ca_cert,
                verify_ssl=args.verify_ssl,
                brand=brand,
            )
        )

    elif args.action == "probe-udp":
        ip = args.ip or (creds.get("ip_address") if creds else None)
        if not ip:
            print("Error: --ip <IP> is required for 'probe-udp' action (or valid credentials.json).")
            sys.exit(1)
        do_probe_udp(ip)


if __name__ == "__main__":
    main()
