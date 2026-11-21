# 🔒 Advanced SSL Certificate Setup & Architecture Guide

> [!TIP]
> ### 🔰 Looking for a Simple 2-Minute Setup?
> If you are a first-time user or beginner, **you do not need to read this technical reference!**  
> Jump straight to the **[Beginner's Quick Start Guide](quick_start_beginners.md)** for a simple 3-step browser walk-through (zero OpenSSL, zero terminal commands, zero Samba shares).
>
> *This document is an advanced technical reference for power users needing custom PEM keypairs, OpenSSL conversion commands, Root CA validation, or architectural details on mutual TLS in VIDAA OS.*

VIDAA OS smart TVs enforce mutual TLS (mTLS) or client certificate authentication on MQTT port `36669`. To establish a secure connection, Home Assistant must present a valid client certificate and private key.

> [!IMPORTANT]
> ### 📱 No Android Device or Running Mobile App Required!
> A common misconception is that this integration requires an Android smartphone, tablet, or running mobile app. **It does not.**
> - **Direct Local Control**: Home Assistant communicates directly across your local network to the TV's hardware MQTT broker. No mobile device is involved at runtime.
> - **VIDAA OS is Embedded Linux**: VIDAA OS is a proprietary embedded Linux operating system (not Android TV).
> - **Why is the Android APK Mentioned?**: Hisense/VIDAA distributes the pre-signed client mutual TLS certificate bundled inside their official companion app package (`.apk` / `.xapk`). An APK file is simply a standard ZIP archive. Home Assistant can unpack and decrypt it entirely in memory during setup, or you can extract it on any PC or Mac. You never need an Android device or emulator.

---

## 🌐 Universal Certificate Architecture

### One Universal Keypair for All Brands
A key architectural principle of VIDAA OS is that **there are no separate certificates for different television brands**:

```mermaid
flowchart TD
    VendorApp["Vendor APK / XAPK Archive<br/>(com.universal.remote.multi)"] --> P12["PKCS#12 Keystore<br/>(client_mobile_android.p12 / El.p12)"]
    P12 --> Cert["Client Certificate<br/>(CN=VidaaAppAndroidV01)"]
    Cert --> Broker1["Hisense TV<br/>(RemoteCA)"]
    Cert --> Broker2["Toshiba / REGZA TV<br/>(RemoteCA)"]
    Cert --> Broker3["Loewe TV<br/>(RemoteCA)"]
    Cert --> Broker4["Philips / TPV / AOC TV<br/>(RemoteCA)"]
    Cert --> Broker5["Sharp / JVC / TOPTRO<br/>(RemoteCA)"]
```

- **Shared Root Authority**: All VIDAA OS television brokers share the exact same root Certificate Authority (`RemoteCA`).
- **Universal Subject Identity**: The client certificate (`CN=VidaaAppAndroidV01`) is accepted by all VIDAA OS devices worldwide, regardless of manufacturer branding.
- **Brand Salts vs Certificates**: Dynamic OEM authentication salts (e.g., Hisense, Toshiba, Loewe) are distinct from TLS transport security. They are derived from TV model identification, UPnP descriptors, or optional filename hints, while the underlying TLS certificate remains 100% universal.

---

## 📂 Storage Locations & Discovery Hierarchy

The integration automatically scans for certificates in the following priority order:

1. **`/config/.storage/vidaa/certs/`** *(Recommended & Default)*:
   - Component-managed internal storage used by the native UI file uploader.
   - Preserved in Home Assistant backups and survives all HACS integration updates.
2. **`/config/ssl/`** *(Standard HA SSL directory)*:
   - Ideal for users managing SSL certificates manually or sharing certificates across multiple integrations.
3. **`/ssl/`** *(Legacy / Core root)*
4. **`/config/certs/`**
5. **`/config/`**

Newly uploaded or extracted certificates are written as PEM files (`hisense.crt` and `hisense.key`) inside `/config/.storage/vidaa/certs/` (or `/config/ssl/` if already present), with restrictive file permissions (`0o600`).

---

## 🚀 Setup Methods

### Method A: Native Browser Upload in Config Flow (Recommended)

Starting in version **3.6.1**, the configuration flow includes a native file upload selector (`FileSelector`):

1. Go to **Settings → Devices & Services → Add Integration → VIDAA Smart TV**.
2. If no certificates exist on disk, Home Assistant presents the **Upload VIDAA App or Certificate Archive** form.
3. Select or drag & drop any supported archive:
   - Android APK: `com.universal.remote.multi.apk`
   - Android XAPK bundle: `VIDAA Smart TV.xapk`
   - PKCS#12 keystore: `client_mobile_android.p12`, `El.p12`, `3R.p12`, or `toshiba.p12`
   - Combined PEM bundle: `hisense_bundle.pem` (a single `.pem` containing both `-----BEGIN CERTIFICATE-----` and `-----BEGIN PRIVATE KEY-----`)
4. **In-Memory Extraction Pipeline**:
   - The archive is inspected in memory with zero-footprint temporary disk buffering.
   - Archive members are checked against known PKCS#12 candidate paths:
     - `res/raw/client_mobile_android.p12`
     - `res/El.p12` (modern primary obfuscated name)
     - `res/3R.p12` (modern secondary obfuscated name)
     - Any wildcard `.p12` / `.pfx` archive found inside the APK
     - `assets/` / nested `.apk` containers (for `.xapk` bundles)
   - Decryption is attempted against known vendor passwords (`186e990688070325a1c4b0ce275d2388`, `multiremote`, and empty `""`).
   - The resulting PEM keypair is written to `/config/.storage/vidaa/certs/` and the temporary archive is instantly purged.

---

### Method B: Manual Placement in `/config/ssl/`

If you prefer managing files directly via File Editor, Studio Code Server, or Samba:

1. Place your keypair or `.p12` bundle into `/config/ssl/`.
2. Supported file formats:
   - **PKCS#12 Archive**: `client_mobile_android.p12`, `El.p12`, or `3R.p12` *(auto-decrypted on startup)*.
   - **Split PEM Keypair**: `hisense.crt` and `hisense.key` (or `vidaa_2024_cert.pem` and `vidaa_2024_key.pem`).
3. Set appropriate permissions on the private key:
   ```bash
   chmod 600 /config/ssl/hisense.key
   ```
4. When you click **Add Integration → VIDAA Smart TV**, Home Assistant auto-discovers these files and proceeds directly to IP address entry!

---

### Method C: Manual Path Entry in Config Flow (Advanced)

On the initial file upload screen, you can check:
☑️ **`Configure manual certificate paths instead`**

Clicking **Submit** opens the manual certificate configuration dialog, allowing you to specify custom filesystem paths:
- **Certificate file path:** e.g. `/config/ssl/hisense.crt` (or `/config/ssl/vidaa_2024_cert.pem`)
- **Private key file path:** e.g. `/config/ssl/hisense.key` (or `/config/ssl/vidaa_2024_key.pem`)
- **Use SSL:** Enabled (mTLS)

> [!NOTE]
> **Container vs Host Paths**:
> If running Home Assistant in Docker or Home Assistant OS, ensure paths are entered from the perspective of the Home Assistant container (e.g. `/config/ssl/hisense.crt`), rather than the external host OS path (such as `/opt/homeassistant/ssl/...` or `/opt/usb/...`).

Home Assistant verifies that the files exist, validates that the private key matches the certificate public key, and pairs with the TV.

---

## 🏷️ Optional OEM Brand Hinting via Filenames

While the certificate is universal, naming your certificate or upload file can optionally provide a manufacturer hint to pre-select your TV brand:

| Filename Keyword | Detected Brand Code | Manufacturer |
| :--- | :--- | :--- |
| `toshiba`, `regza` | `tos` | Toshiba / REGZA |
| `loewe` | `loe` | Loewe |
| `philips`, `tpv`, `aoc` | `tpv` | Philips / TPV / AOC |
| `sharp`, `aquos` | `shp` | Sharp |
| `jvc` | `jvc` | JVC |
| `toptro` | `tpo` | TOPTRO |
| `schneider` | `sch` | Schneider |
| `akai` | `aka` | Akai |
| `beko` | `bek` | Beko |
| `telefunken` | `tel` | Telefunken |
| `bush` | `bus` | Bush |
| `vizio` | `vic` | VIZIO |
| `hisense`, `vidaa` *(Default)* | `his` | Hisense |

*(Example: Uploading or placing `toshiba.p12` or `loewe.crt` automatically sets the brand selector to Toshiba or Loewe).*

---

## 🛠️ Manual OpenSSL CLI Commands (Power Users)

If you wish to extract and inspect the PEM files manually using OpenSSL:

### Extracting from `.p12` using OpenSSL 3.x (with Legacy Provider)
Modern distributions (Debian 12+, Ubuntu 22.04+) default to OpenSSL 3.x, which requires the `-legacy` provider flag to decrypt RC2/3DES legacy keystores:

```bash
# 1. Extract Certificate (Public Key):
openssl pkcs12 -legacy -in client_mobile_android.p12 \
  -passin pass:186e990688070325a1c4b0ce275d2388 \
  -clcerts -nokeys -out /config/ssl/hisense.crt

# 2. Extract Private Key (Unencrypted):
openssl pkcs12 -legacy -in client_mobile_android.p12 \
  -passin pass:186e990688070325a1c4b0ce275d2388 \
  -nocerts -nodes -out /config/ssl/hisense.key

# 3. Secure Private Key Permissions:
chmod 600 /config/ssl/hisense.key
```

### Verifying Certificate & Key Matching
Ensure that the certificate modulus matches the private key modulus:

```bash
# Verify Certificate Details:
openssl x509 -in /config/ssl/hisense.crt -noout -subject -dates

# Verify Modulus Match:
CERT_MD5=$(openssl x509 -noout -modulus -in /config/ssl/hisense.crt | openssl md5)
KEY_MD5=$(openssl rsa -noout -modulus -in /config/ssl/hisense.key | openssl md5)

if [ "$CERT_MD5" = "$KEY_MD5" ]; then
    echo "✅ Keypair matches!"
else
    echo "❌ Keypair mismatch!"
fi
```

---

## 🛡️ Root CA Verification

By default, the integration connects with `CERT_NONE` verification for the TV broker's self-signed server certificate, matching official VIDAA companion app behavior.

If your network security policy requires strict Root CA verification:
1. Place the root certificate (`remote_ca.pem` or `RemoteCA.crt`) into `/config/ssl/` or `/config/.storage/vidaa/certs/`.
2. The integration will automatically load the CA and validate the TV's TLS handshake against the authority.

---

## 🧪 Testing SSL Connectivity via CLI

You can verify your certificates and test the mutual TLS handshake with your TV directly from the command line using [`scripts/test_client.py`](../scripts/test_client.py):

```bash
# Test SSL handshake using auto-discovered certs:
python3 scripts/test_client.py test-ssl --ip <TV_IP>

# Test with explicit certificate paths:
python3 scripts/test_client.py test-ssl --ip <TV_IP> \
  --cert /config/ssl/hisense.crt \
  --key /config/ssl/hisense.key
```

> For setup prerequisites and full testing syntax, see the **[Standalone CLI Testing & Diagnostic Tools Guide](cli_tools.md)**.
