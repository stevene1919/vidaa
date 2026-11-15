# 🧪 Standalone CLI Testing & Diagnostic Tools

The integration includes two standalone Python CLI utilities that share 100% of the backend logic with the Home Assistant integration (`client.py`, `crypto.py`, `discovery.py`). These tools communicate directly with real TVs for diagnostic reporting, capability probing, and live monitoring.

---

## ⚡ 30-Second Quick Start

Choose the method that matches your environment:

### Method 1: Inside Home Assistant (Terminal / SSH Add-on — Easiest & Fastest)

Home Assistant already has all required Python libraries pre-installed. Run this single copy-paste command in your HA Terminal:

```bash
curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/test_client.py -o /config/test_client.py && python3 /config/test_client.py report --ip <TV_IP>
```

*(Replace `<TV_IP>` with your TV's local IP address, e.g. `192.168.1.50`).*

> [!NOTE]
> **Prerequisite**: Requires the VIDAA integration to already be installed in Home Assistant (e.g. via HACS in `/config/custom_components/vidaa`). If you haven't installed the integration yet, use **Method 2** on your computer.

---

### Method 2: On Any PC, Mac, or Linux Computer (Standalone)

Run these 3 commands in your terminal:

```bash
# 1. Clone the repository and enter the directory
git clone https://github.com/stevene1919/vidaa.git
cd vidaa

# 2. Install the lightweight client dependencies
pip3 install aiomqtt defusedxml cryptography pytest

# 3. Run the diagnostic report (from the root of the vidaa folder)
python3 scripts/test_client.py report --ip <TV_IP>
```

> [!NOTE]
> **Important Path Note**: When running standalone from your computer, always run commands from the **`vidaa/` root directory** using the `scripts/` prefix:
> ```bash
> python3 scripts/test_client.py report --ip <TV_IP>
> ```
> `pytest` is required when running outside of Home Assistant so that the tool can load the bundled Home Assistant stubs (`tests/conftest.py`).

---

## 🔬 `test_client.py` — Auth Probe & Pairing Tool

[`scripts/test_client.py`](../scripts/test_client.py) focuses on **initial discovery, SSL validation, authentication, and diagnostic reporting**.

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
python3 scripts/test_client.py wake --mac E8:51:77:EC:98:1C
```

### 12. Probe UPnP MediaRenderer Services (`upnp`)

Probes UPnP MediaRenderer SOAP services (`RenderingControl:1`, `AVTransport:1`, and `LanControlInfo:1`) on port `38400` / `18400`:

```bash
python3 scripts/test_client.py upnp --ip <TV_IP>
```

---

## 🛠️ `debug_tv.py` — Live Runtime Debugger

[`scripts/debug_tv.py`](../scripts/debug_tv.py) focuses on **live state inspection, real-time event monitoring, and manual command dispatching**. It automatically loads existing credentials from `credentials.json`.

```bash
# Dump current state, sources, apps, and volume:
python3 scripts/debug_tv.py --dump-state

# Continuously stream live MQTT events from the TV:
python3 scripts/debug_tv.py --monitor

# Send a remote keypress:
python3 scripts/debug_tv.py --send-key KEY_HOME
python3 scripts/debug_tv.py --send-key KEY_VOLUMEUP

# Launch an app by name or App ID:
python3 scripts/debug_tv.py --launch-app Netflix
python3 scripts/debug_tv.py --launch-app "Disney+"

# Switch input source:
python3 scripts/debug_tv.py --change-source HDMI1
python3 scripts/debug_tv.py --change-source TV

# Send virtual keyboard text input to an active on-screen field:
python3 scripts/debug_tv.py --text "Inception"
python3 scripts/debug_tv.py --text "Dune" --text-action replace
python3 scripts/debug_tv.py --text-action clear

# Probe UPnP MediaRenderer services and actions (volume, mute, transport info):
python3 scripts/debug_tv.py --probe-upnp

# Inspect UPnP Date header and calculate TV clock drift:
python3 scripts/debug_tv.py --sync-clock

# Override TV IP and test OEM partner brand:
python3 scripts/debug_tv.py --ip 192.168.50.12 --brand toshiba --monitor

# Verbose debug logging:
python3 scripts/debug_tv.py --dump-state -v
```

> [!TIP]
> Running `python3 scripts/debug_tv.py` with no arguments produces a complete state dump (`--dump-state`).
