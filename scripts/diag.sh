#!/bin/sh
# -----------------------------------------------------------------------------
# VIDAA Smart TV Integration — Zero-Setup Diagnostics Runner
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/diag.sh | bash -s -- --ip <TV_IP>
#
# Examples:
#   curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/diag.sh | bash -s -- --ip 192.168.1.50
#   curl -sSL https://raw.githubusercontent.com/stevene1919/vidaa/main/scripts/diag.sh | bash -s -- --ip 192.168.1.50 --probe
# -----------------------------------------------------------------------------
set -e

TMP_DIR=$(mktemp -d /tmp/vidaa-diag-XXXXXX 2>/dev/null || mktemp -d -t 'vidaa-diag')
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

# Check python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required but not installed." >&2
    exit 1
fi

# Download archive from GitHub
TAR_URL="https://codeload.github.com/stevene1919/vidaa/tar.gz/refs/heads/main"

echo "==> 📦 Fetching diagnostic tools from stevene1919/vidaa..."
if command -v curl >/dev/null 2>&1; then
    curl -sSL "$TAR_URL" | tar -xz -C "$TMP_DIR" --strip-components=1
elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$TAR_URL" | tar -xz -C "$TMP_DIR" --strip-components=1
else
    echo "ERROR: Neither curl nor wget is available." >&2
    exit 1
fi

cd "$TMP_DIR"

# Check / install minimal dependencies if needed
python3 -c "import aiomqtt, cryptography" >/dev/null 2>&1 || {
    echo "==> ⚡ Installing lightweight client dependencies (aiomqtt, cryptography)..."
    pip3 install --quiet --upgrade aiomqtt cryptography defusedxml aiohttp >/dev/null 2>&1 || pip install --quiet --upgrade aiomqtt cryptography defusedxml aiohttp >/dev/null 2>&1 || true
}

ACTION="report"
if [ "$1" = "sniff" ] || [ "$1" = "probe-udp" ] || [ "$1" = "ping" ] || [ "$1" = "upnp" ] || [ "$1" = "listen" ]; then
    ACTION="$1"
    shift
fi

echo "==> 🔬 Running TV diagnostics ($ACTION)..."
python3 scripts/test_client.py "$ACTION" "$@"
