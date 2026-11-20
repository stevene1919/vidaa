# 🧪 Standalone CLI Testing & Diagnostic Tools

The integration includes a unified standalone Python CLI utility (`scripts/test_client.py`) and a zero-setup one-liner runner (`scripts/diag.sh`) that share 100% of the backend protocol logic with the Home Assistant integration (`client.py`, `crypto.py`, `discovery.py`). These tools communicate directly with real TVs for diagnostic reporting, capability probing, pairing, and live monitoring.

---

## ⚡ 30-Second Quick Start

Choose the method that matches your environment:

### Method 1: Zero-Setup One-Liner (Easiest — Works Everywhere)

Works directly in Home Assistant Terminal, or on any Linux / macOS computer without needing git or manual cloning:

```bash
curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/diag.sh | bash -s -- --ip <TV_IP>
```

*(Replace `<TV_IP>` with your TV's local IP address, e.g. `192.168.1.50`).*

To include dynamic picture and sound menu tree probing in the diagnostic report:
```bash
curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/diag.sh | bash -s -- --ip <TV_IP> --probe
```

---

### Method 2: On Any PC, Mac, or Linux Computer (Standalone Clone)

If you have cloned the repository locally:

```bash
# 1. Install the lightweight client dependencies
pip3 install aiomqtt cryptography defusedxml aiohttp

# 2. Run the diagnostic report (from the root of the vidaa folder)
python3 scripts/test_client.py report --ip <TV_IP>
```

---

## 🔬 `test_client.py` — Unified CLI & Diagnostic Tool

[`scripts/test_client.py`](../scripts/test_client.py) is the central command-line interface for **discovery, SSL validation, authentication, diagnostic reporting, and live TV control**.

*(All commands below are shown from the `vidaa/` root directory. If running inside Home Assistant `/config`, drop the `scripts/` prefix).*

### 1. Generate GitHub Issue Diagnostic Report (`report`)

Generates a sanitized Markdown diagnostics block detailing hardware info, firmware version, multi-tier authentication support, and optionally probed picture/sound menu capabilities ready to paste into GitHub issues:

```bash
# Generate basic diagnostics report:
python3 scripts/test_client.py report --ip <TV_IP>

# Generate report for a specific OEM partner brand (e.g. loewe, toshiba, toptro):
python3 scripts/test_client.py report --ip <TV_IP> --brand loe
python3 scripts/test_client.py report --ip <TV_IP> --brand tos

# Generate full diagnostics report with dynamic picture/sound menu probing:
python3 scripts/test_client.py report --ip <TV_IP> --probe
```

### 2. Feature & Menu Capability Probing (`probe` / `probe-features`)

Connects to the TV broker and probes dynamic picture settings, sound equalizer options, device descriptors, and app/source capabilities:

```bash
python3 scripts/test_client.py probe --ip <TV_IP>
```

### 3. Diagnostic Probe & Firmware Detection (`ping`)

Tests TCP port reachability, TLS handshake, broker response, and multi-tier auth capabilities:

```bash
python3 scripts/test_client.py ping --ip <TV_IP>

# Test specific authentication profile (modern / middle / remotenow / legacy):
python3 scripts/test_client.py ping --ip <TV_IP> --profile modern
python3 scripts/test_client.py ping --ip <TV_IP> --profile middle

# Test specific OEM partner brand (his / tos / loe / tpv / tpo / etc.):
python3 scripts/test_client.py ping --ip <TV_IP> --brand toshiba
python3 scripts/test_client.py ping --ip <TV_IP> --brand loewe
python3 scripts/test_client.py ping --ip <TV_IP> --brand toptro
```

> [!NOTE]
> `ping` and `test-ssl` display whether client certificates were loaded and presented. On modern VIDAA firmware, connecting without client certificates causes all authentication methods to fail with `rc=5` (Not Authorized) and displays an on-screen compatibility warning on the TV.

### 4. Test Raw SSL/TLS Connection (`test-ssl`)

Verifies TLS cipher negotiation and certificate validity without pairing:

```bash
python3 scripts/test_client.py test-ssl --ip <TV_IP>
python3 scripts/test_client.py test-ssl --ip <TV_IP> --profile modern
python3 scripts/test_client.py test-ssl --ip <TV_IP> --profile middle
python3 scripts/test_client.py test-ssl --ip <TV_IP> --cert /path/to/cert.pem --key /path/to/key.pem
```

### 5. Interactive PIN Pairing (`auth`)

Initiates the challenge handshake, displays the on-screen 4-digit PIN on the TV, and saves the issued tokens to `credentials.json`:

```bash
python3 scripts/test_client.py auth --ip <TV_IP>
python3 scripts/test_client.py auth --ip <TV_IP> --profile modern
python3 scripts/test_client.py auth --ip <TV_IP> --brand toshiba
python3 scripts/test_client.py auth --ip <TV_IP> --brand toptro
```

### 6. Test Token Renewal (`refresh`)

Tests renewal of the 2-day access token using the 30-day refresh token:

```bash
python3 scripts/test_client.py refresh
```

### 7. Listen to Real-Time TV Events (`listen`)

Subscribes to live state changes, volume updates, source list, and app list:

```bash
python3 scripts/test_client.py listen
```

### 8. Send Remote Key Command (`send-key`)

Dispatches a single key command:

```bash
python3 scripts/test_client.py send-key KEY_VOLUMEUP
python3 scripts/test_client.py send-key KEY_POWER
```

### 9. Launch App by Name (`launch-app`)

Launches an installed Smart TV application by name:

```bash
python3 scripts/test_client.py launch-app "YouTube"
python3 scripts/test_client.py launch-app "Netflix"
```

### 10. Virtual Keyboard & Text Input (`text`)

Sends virtual keyboard input to an active on-screen search bar or text input field:

```bash
python3 scripts/test_client.py text "The Matrix"
python3 scripts/test_client.py text --text-action replace "Bluey"
python3 scripts/test_client.py text --text-action clear
```

### 11. Wake-on-LAN Broadcast (`wake`)

Broadcasts a subnet-directed magic packet:

```bash
python3 scripts/test_client.py wake --mac E8:51:77:AA:BB:CC
```

### 12. Probe UPnP MediaRenderer Services (`upnp`)

Probes UPnP MediaRenderer SOAP services (`RenderingControl:1`, `AVTransport:1`, and `LanControlInfo:1`) on port `38400` / `18400`:

```bash
python3 scripts/test_client.py upnp --ip <TV_IP>
```

---

### 13. Query Live TV State Snapshot (`state`)

Connects to the TV, dumps power state, volume/mute levels, active source, active app, and queries installed input sources and applications:

```bash
python3 scripts/test_client.py state
python3 scripts/test_client.py state --ip <TV_IP>
```

### 14. Switch Input Source (`source`)

Switches the TV to a specific input source by name or source ID:

```bash
python3 scripts/test_client.py source HDMI1
python3 scripts/test_client.py source TV
```

### 15. Stream Live MQTT Events (`monitor` / `listen`)

Continuously streams and pretty-prints live status, volume, and state updates from the TV broker (press `Ctrl+C` to stop):

```bash
python3 scripts/test_client.py monitor
python3 scripts/test_client.py monitor --ip <TV_IP>
```
