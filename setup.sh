#!/usr/bin/env bash
# ===========================================
# Asterisk Phase 1 — Local SIP Setup Script
# Run on Ubuntu 22.04/24.04 or Debian 12
# Usage: sudo bash setup.sh
# ===========================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Asterisk Phase 1 Setup ==="
echo ""

# --- Check root ---
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

# --- Step 1: Install Asterisk ---
echo "[1/6] Installing Asterisk..."
apt update -qq
apt install -y asterisk sox libsox-fmt-all

# --- Step 2: Backup original configs ---
echo "[2/6] Backing up original configs..."
BACKUP_DIR="/etc/asterisk/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp /etc/asterisk/pjsip.conf "$BACKUP_DIR/" 2>/dev/null || true
cp /etc/asterisk/extensions.conf "$BACKUP_DIR/" 2>/dev/null || true
echo "  Backups saved to $BACKUP_DIR"

# --- Step 3: Deploy configuration files ---
echo "[3/6] Deploying PJSIP and dialplan configs..."
cp "$SCRIPT_DIR/pjsip.conf" /etc/asterisk/pjsip.conf
cp "$SCRIPT_DIR/extensions.conf" /etc/asterisk/extensions.conf
chown asterisk:asterisk /etc/asterisk/pjsip.conf /etc/asterisk/extensions.conf

# --- Step 4: Create custom audio file ---
echo "[4/6] Creating custom test audio..."
sox -n -r 8000 -c 1 /var/lib/asterisk/sounds/en/custom-test.wav synth 3 sine 440
chown asterisk:asterisk /var/lib/asterisk/sounds/en/custom-test.wav

# --- Step 5: Firewall ---
echo "[5/6] Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 5060/udp comment "SIP signaling"
    ufw allow 10000:20000/udp comment "RTP media"
    echo "  UFW rules added."
else
    echo "  UFW not found — skipping. Ensure ports 5060/udp and 10000-20000/udp are open."
fi

# --- Step 6: Restart Asterisk ---
echo "[6/6] Restarting Asterisk..."
systemctl enable asterisk
systemctl restart asterisk

# --- Done ---
SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "==========================================="
echo " Setup complete!"
echo "==========================================="
echo ""
echo " Server IP: $SERVER_IP"
echo ""
echo " Softphone credentials:"
echo "   Phone A — User: 100  Pass: phone100pass"
echo "   Phone B — User: 101  Pass: phone101pass"
echo "   Domain: $SERVER_IP   Port: 5060 (UDP)"
echo ""
echo " Test extensions:"
echo "   100 — Call Phone A"
echo "   101 — Call Phone B"
echo "   200 — Audio greeting"
echo "   300 — IVR menu"
echo "   400 — Echo test"
echo "   500 — Custom tone"
echo ""
echo " Debug:  sudo asterisk -rvvv"
echo " Status: sudo asterisk -rx 'pjsip show endpoints'"
echo "==========================================="
