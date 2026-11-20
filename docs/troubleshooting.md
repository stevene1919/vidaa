# 🛠️ VIDAA Smart TV Troubleshooting Guide

This guide helps you identify, diagnose, and resolve common issues encountered when using the **VIDAA Smart TV** integration in Home Assistant, including service call errors, standby behavior, pairing recovery, and network connectivity.

---

## 🧭 Quick Diagnostic Flow

When something isn't working as expected, follow these first steps:

1. **Check TV Power & Network State**: Can the TV be pinged, or is it in deep sleep? (VIDAA TVs shut down their network cards in deep standby unless Wake-on-LAN/Mobile Turn-On is enabled in TV settings).
2. **Check Home Assistant Repairs**: If the TV wiped its pairing session tokens, Home Assistant will create an alert under **Settings** → **Repairs**.
3. **Inspect Entity State & Diagnostics**: Open `media_player.<tv_name>` in Developer Tools or download diagnostics from the integration device card (**Settings** → **Devices & Services** → **VIDAA Smart TV** → **⋮** → **Download diagnostics**).
4. **Enable Debug Logging**: Toggle `switch.<tv_name>_debug_logging` to capture live communication in **Settings** → **System** → **Logs**.

---

## ⚠️ Service Action & Automation Error Reference

When an automation or manual service call fails, Home Assistant displays an error banner or logs an exception. Use this table to understand the cause and resolution:

| Error Message / Translation Key | Cause | How to Fix |
| :--- | :--- | :--- |
| **`Failed to send key {key}: {error}`**<br>(`send_key_failed`) | The TV's MQTT broker rejected the key command, the TV is disconnected, or an invalid key name was supplied. | 1. Ensure the TV is awake (send a Wake-on-LAN command if asleep).<br>2. Verify the key name matches supported keys (e.g., `KEY_POWER`, `KEY_VOLUMEUP`, `KEY_HOME`). See [`services_and_automations.md`](services_and_automations.md#21-supported-key-names--aliases). |
| **`Key sequence cannot be empty`**<br>(`empty_key_sequence`) | The `send_key_sequence` action was triggered with an empty `sequence` list. | Ensure your automation or script passes at least one key name in the `sequence` list parameter. |
| **`Failed to send key sequence at step {index} ({key}): {error}`**<br>(`send_key_sequence_failed`) | The sequence was interrupted (e.g. TV disconnected, command timed out, or unmapped key at step *N*). | Check the error details for the specific key step that failed. Increase `delay` between keys (e.g., to `0.5`s or `1.0`s) to give the TV OS time to process each keypress. |
| **`Channel digits must contain numbers only: {channel}`**<br>(`invalid_channel_digits`) | The `change_channel` action received non-numeric characters (e.g., letters or spaces). | Provide only numeric digits or dot-separated channel numbers (e.g. `10`, `70`, `7.1`). |
| **`Failed to send channel digit {digit}: {error}`**<br>(`change_channel_digit_failed`) | Communication with the TV failed while sending one of the numeric channel keys (`KEY_0` - `KEY_9`). | Ensure the TV is currently in Live TV / Antenna tuner mode before changing channels. If the TV is in an HDMI input or streaming app, tune to Live TV first. |
| **`Failed to send channel confirmation key {key}: {error}`**<br>(`change_channel_confirm_failed`) | The TV failed to receive the trailing confirmation key (`KEY_OK` / `KEY_ENTER`). | Increase `digit_delay` in the service call (e.g., `digit_delay: 0.5`) to allow slower TV tuners to register digits before confirmation. |
| **`Failed to launch app {app_name}: {error}`**<br>(`launch_app_failed`) | The app name or app ID is not installed on this TV, or the TV OS rejected the launch payload. | Verify that the app is installed and visible in the TV's native app launcher. Check `media_player.<tv_name>` attributes for the list of available sources/apps. |
| **`Failed to set picture setting {setting} to {value}: {error}`**<br>(`set_picture_setting_failed`) | The requested picture preset or numeric value is out of range or not supported on this TV model. | Use the built-in UI select/number entities (e.g., `select.<tv_name>_picture_mode`) or check supported modes in the TV settings menu. |
| **`Failed to set sound setting {setting} to {value}: {error}`**<br>(`set_sound_setting_failed`) | The requested sound mode is unsupported or ARC/eARC soundbar control is overriding TV internal sound modes. | If an external soundbar or AV receiver is connected via eARC, sound modes may be locked by the external audio device. |
| **`Failed to send text input: {error}`**<br>(`send_text_input_failed`) | The TV refused the text string because an on-screen keyboard dialog is not currently open. | Ensure the TV screen is currently displaying an active text input search box or keyboard before calling `send_text_input`. |

---

## 🔌 Connection & Network Issues

### 1. TV Shows "Unavailable" When Powered Off
* **Explanation:** VIDAA OS operates in two tiers of standby:
  1. **Light Standby (Screen Off)**: MQTT broker stays active for ~5-15 minutes after power-off.
  2. **Deep Standby (Cold Sleep)**: The TV powers down its main system board and Wi-Fi chip to comply with EU/international eco-power regulations (<0.5W). In this state, the TV cannot maintain a TCP/MQTT socket connection and will appear **unavailable** in Home Assistant.
* **Solution:**
  * Go to TV **Settings** → **Network** / **System** → **Advanced Settings** and enable:
    * **Wake on LAN / Network Standby** (or **Mobile App Turn On / TV Auto Action**)
    * **Fast Start / Fast Boot** (if available)
  * Configure Wake-on-LAN in the integration's Options Flow (burst count 3-5 packets) so Home Assistant can wake the TV over the network when you press Power On.
  * See [`power_and_standby_settings.md`](power_and_standby_settings.md) for TV firmware setting guides.

### 2. Connection Refused on Port 36669
* **Explanation:** The integration communicates with the TV's local MQTT broker over port `36669` (TCP/TLS).
* **Troubleshooting Steps:**
  * Confirm the TV and Home Assistant are on the same subnet, or that routing/firewall rules permit traffic from Home Assistant to TV port `36669`.
  * Verify reachability from Home Assistant terminal:
    ```bash
    nc -zv <tv_ip> 36669
    ```
  * Note: Hisense and VIDAA devices often drop ICMP ping requests by default. Reachability must be verified via TCP port `36669` or UPnP HTTP port `38400` (e.g. `curl -I http://<tv_ip>:38400/MediaServer/rendererdevicedesc.xml`), not standard `ping`.
  * See [`network_requirements.md`](network_requirements.md) for complete port and firewall specifications.

### 3. Wake-on-LAN Does Nothing When Tested Immediately After Powering Off
* **Explanation**: You cannot test Wake-on-LAN immediately after turning off the TV. For the first ~15 minutes after power-off, the TV remains in transitional Fast Boot standby (~7.5W). In this state, the network card is not in low-power L2 sleep mode and **completely ignores Wake-on-LAN magic packets**. During this 15-minute window, the TV only wakes via software MQTT (`KEY_POWER`) or the remote.
* **Solution**: Wait **15 to 20 minutes** after turning the TV off. Once the TV drops into true regulatory deep sleep (0.0W on a smart plug), the network chip enters low-power listening mode and will respond to Wake-on-LAN magic packets.

---

## 🔐 Pairing & Authentication Issues

### 1. Pairing Fails or PIN Does Not Appear on Screen
* **Smart / Connected Services Disabled (Terms of Use Not Accepted):** VIDAA OS suppresses the on-screen 4-digit pairing PIN popup if **Smart Services** (Connected Services, Terms of Use, and Privacy Policy) are turned off or skipped in TV settings (`Settings → Support / System → Terms & Conditions / Smart Services`). Enable them on the TV and try pairing again. If you wish to isolate the TV from the internet, you can safely block its IP address from WAN/internet access at your router once pairing is completed.
* **TV Hardware Clock Drift (Firewall-Blocked / Isolated IoT LANs):** VIDAA OS lacks a battery-backed Real-Time Clock (RTC). If the TV is completely cut off from the internet by a router firewall or DNS sinkhole (e.g. AdGuard / Pi-hole) without an NTP redirect rule, its internal clock will drift or reset after reboots/power cycles. The TV's MQTT broker rejects modern timestamped authentication challenges if the TV's internal clock differs from real time by more than ±60–120 seconds, resulting in a silent connection failure (`rc: 5 / 135`) without ever displaying the 4-digit PIN. Temporarily allow outbound internet access (or check TV Settings → System → Time/Date, verify the time, and power-cycle the TV). See [Section 6 of Network Requirements](network_requirements.md#6-tv-hardware-clock-ntp-sync--isolated-iot-lans-wan-blocked) for long-term UDP 123 NAT redirection.
* **Mobile App Conflict:** VIDAA TVs typically allow only one active remote control session at a time. If the official **RemoteNOW** or **VIDAA** mobile app is currently running on a phone or tablet, close the mobile app completely before starting pairing in Home Assistant.
* **Keystore Bundle Filename:** Verify that `client_mobile_android.p12` or `El.p12` is in `/config/ssl/`.
* **Stale Pairing Cache:** In Home Assistant, restart the config flow or trigger re-pairing via the **Start re-authentication** button (`button.<tv_name>_start_re_authentication` or `button.<tv_name>_trigger_re_pairing`).
* **Expired PIN:** PIN codes displayed on the TV screen expire after 60 seconds. Enter the 4-digit code promptly.

### 2. Frequent Token Loss or Prompts to Re-Authenticate
* **Cause: Volatile Memory Wipes on Standby:**
  * Some VIDAA TV models clear their RAM when entering deep sleep if external HDMI streaming sticks (Fire TV, Roku, Chromecast) draw power from the TV's USB port. When the TV goes into standby, the USB port cuts power abruptly, causing an ungraceful shutdown that wipes volatile authentication tokens.
* **Fix:**
  * Power streaming sticks from a wall AC adapter rather than the TV's USB ports.
  * In TV Settings, disable **Auto Standby with No Signal**.
  * Keep Home Assistant's client certificates properly configured in `/config/ssl/` as documented in [`certificates.md`](certificates.md) to enable automatic mutual TLS authentication.

* **Automated Alerts via Authentication Problem Sensor:**
  * When stored tokens are wiped or invalidated by the TV broker, the diagnostic entity `binary_sensor.<tv_name>_authentication_problem` turns `on` and Home Assistant displays a persistent Repairs notification. You can automate instant notifications using:
    ```yaml
    alias: "Notify when VIDAA TV requires re-authentication"
    trigger:
      - trigger: state
        entity_id: binary_sensor.hisense_tv_authentication_problem
        to: "on"
        for: "00:01:00"
    action:
      - action: notify.notify
        data:
          title: "Hisense TV Needs Re-Pairing"
          message: "The TV broker invalidated stored tokens. Open Home Assistant Repairs to re-pair."
    ```

### 3. Broker Rejection or "Not Authorized" Error (`rc: 5` / `rc: 135`)
An MQTT return code of `rc: 5` (MQTT 3.1.1) or `rc: 135` (MQTT 5.0) indicates that the mutual TLS handshake completed successfully, but the TV's internal broker explicitly rejected the generated client credentials. This is caused by one of two issues:

* **Cause A: TV Hardware Clock Drift / Missing NTP (WAN-Blocked Sets):**
  * Modern VIDAA firmware validates the HMAC-SHA256 / MD5 password signature against the TV's internal real-time clock. If the TV's system clock is skewed by more than ~60–120 seconds relative to real UTC time, authentication fails with `rc: 5 / 135`.
  * While the integration automatically queries the TV's HTTP `Date:` header on port `38400` to calculate drift offset, **some partner chassis (such as Loewe) do not serve HTTP responses on port 38400**, leaving Home Assistant with no choice but to fall back to host local time.
  * **Fix:**
    1. Check **Settings → System → Time/Date** on the TV. Ensure the on-screen time, date, and timezone match real time.
    2. If the TV is isolated from the internet by a firewall, temporarily allow WAN access and reboot the TV so its internal NTP client can sync.
    3. For permanent network isolation, configure a router firewall DNAT redirection rule capturing `UDP 123` (NTP) from the TV and redirecting to your local gateway/NTP server. See [Section 6 of Network Requirements](network_requirements.md#6-tv-hardware-clock-ntp-sync--isolated-iot-lans-wan-blocked).

* **Cause B: OEM Brand Code Mismatch:**
  * When communicating with licensed partner brands (Toshiba, Loewe, TPV/Philips, Sharp, JVC, TOPTRO, etc.), the TV/projector broker validates client credentials against an OEM brand prefix salt. If generic Hisense credentials (`his`) are sent to a partner device, the broker rejects authentication with `rc: 5` (MQTT 3.1.1) or `rc: 135` (MQTT 5.0).
  * **Fix:**
    * Keep **Brand Profile** set to **Auto Detect (Recommended)**. When enabled, the integration queries UPnP port `38400` / `18400` to extract `brand=` from `<modelDescription>` or cascades through supported candidate OEM brands (`tos`, `loe`, `tpv`, `shp`, `jvc`, `tpo`).
    * If adding a device across an isolated VLAN where UPnP is blocked and cascade is exhausted, open **Settings → Devices & Services → VIDAA Smart TV → Configure → Security** and manually select your device's brand from the dropdown.
    * Inspect `sensor.<tv_name>_session_status` attributes (`brand_profile`, `active_brand`, `auth_profile`) to view the currently configured brand profile and active OEM brand in real time.

### 4. Baseline Verification: Testing with the Official VIDAA App (iOS & Android)
* If Home Assistant fails to discover your TV or the 4-digit pairing PIN never appears on your TV screen, testing with the official companion mobile app is the fastest way to confirm whether your TV hardware and network are ready:
  1. **Download the Official App:**
     - **iOS:** Install **VIDAA** from the [Apple App Store](https://apps.apple.com/us/app/vidaa/id1526408639) (published by *V America Operations Inc.*).
     - **Android:** Install **VIDAA** from the [Google Play Store](https://play.google.com/store/apps/details?id=com.universal.remote.multi).
  2. **Attempt Pairing:**
     - Connect your phone to the same local Wi-Fi / subnet as the TV.
     - Open the app and attempt to pair with the TV.
     - **If the official mobile app ALSO cannot connect or no PIN appears:** The TV's remote service is disabled on the device. Ensure the TV is awake, connected to Wi-Fi, and that all **Smart / Connected Services** terms are accepted under `Settings → Support / System → Terms & Conditions / Smart Services`.
     - **If the mobile app pairs successfully:** This confirms the TV's internal broker is healthy. Check the app's *Device Info* screen to confirm your TV's advertised brand, model code, and firmware build.
  3. ⚠️ **Important — Force Close the Mobile App:**
     Once verified, **force-close / swipe away the mobile app completely** on your phone. VIDAA TVs typically allow only one active remote control session at a time; leaving the mobile app open in the background will cause Home Assistant's pairing attempts to be rejected or time out.

### 5. Do I Need an Android Phone or Android TV to Use This?
* **No.** VIDAA OS is a Linux-based operating system, not Android TV.
* **No Android Hardware/OS Required:** You do not need an Android phone, tablet, or emulator to set up or run this integration. Home Assistant connects directly to the TV over your local network.
* **What if my TV runs Android TV or Google TV?**
  * If your TV runs Android TV or Google TV (including North American Hisense Android models, Sony, TCL, Chromecast, or NVIDIA Shield), this integration will not connect because port `36669` is not present.
  * For standard D-pad navigation and volume control, use Home Assistant's built-in [Android TV Remote](https://www.home-assistant.io/integrations/androidtv_remote/) integration.
  * For advanced features (direct OS shell access, dynamic HDMI-CEC input discovery, real-time on-screen keyboard detection, and SoC hardware health sensors over native TLS 1.3 Wireless Debugging), use [**ADB mDNS**](https://github.com/stevene1919/adb_mdns/).
* **Why the APK is Mentioned:** The vendor pre-signs its client mutual TLS certificate (`.p12` bundle) inside the publicly available VIDAA remote app package (`.apk`). Because an `.apk` is simply an unencrypted ZIP archive, you can open and extract it on any computer (Windows, macOS, Linux) with standard tools like `unzip` or 7-Zip without ever owning an Android device.

---

## 🔊 Audio, Volume & External Amplifier (ARC/eARC) Behavior

### 1. Volume Slider Does Nothing When Connected to an External Amp or Soundbar
* **Cause: Absolute Volume vs. CEC Step Control:**
  * When you drag the volume slider in Home Assistant, the integration sends an absolute volume command (`0–100` via `actions/changevolume`).
  * On VIDAA OS, the TV firmware **only applies absolute percentage volume changes to the TV's internal speakers**.
  * When an external AV receiver or soundbar is connected via **HDMI ARC/eARC (CEC)**, the TV firmware ignores absolute network volume commands and delegates volume control to the external amplifier over HDMI-CEC. The CEC protocol requires incremental step commands.
* **Solution:**
  * Use the **Volume Up** and **Volume Down** buttons (`media_player.volume_up` / `media_player.volume_down`, or send key `KEY_VOLUMEUP` / `KEY_VOLUMEDOWN`). The TV forwards these step keypresses directly across the HDMI ARC/eARC bus to adjust your amplifier volume.
  * In Lovelace dashboards, use pill rockers or button cards mapped to `volume_up` and `volume_down` rather than the continuous slider when outputting to an external amplifier.

### 2. Missing `sensor.<tv>_audio_output` Entity
* **Explanation:**
  * In earlier integration versions, standalone `sensor.<tv>_audio_output` and `select.<tv>_audio_output` entities were exposed.
  * These were intentionally retired in favor of the **`audio_output` state attribute** directly on the main `media_player.<tv_name>` entity (`TV Speakers` or `ARC / eARC`).
  * This eliminates entity registry clutter while keeping audio output state readily accessible in automations and templates (e.g. `state_attr('media_player.living_room_tv', 'audio_output')`). Note that VIDAA firmware only distinguishes `ARC / eARC` from internal speakers over MQTT; Optical/SPDIF and Bluetooth appear as `TV Speakers`.

---

---

## 📊 Diagnostic Logs & Bug Reporting

If you continue to experience problems:

1. Enable the integration's diagnostic switch: `switch.<tv_name>_debug_logging`.
2. Reproduce the problem (e.g. attempt to turn on, send a key, or change inputs).
3. Download the sanitized diagnostic file from **Settings** → **Devices & Services** → **VIDAA Smart TV** → **⋮** → **Download diagnostics**.
4. Open an issue on GitHub: [`https://github.com/stevene1919/vidaa/issues`](https://github.com/stevene1919/vidaa/issues) and attach the sanitized diagnostics JSON file along with relevant log excerpts.
