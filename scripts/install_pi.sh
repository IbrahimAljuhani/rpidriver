#!/usr/bin/env bash
# RPiDriver — One-command installer for Raspberry Pi OS (Bookworm / Bullseye)
# Usage: curl -fsSL https://ia.sa/rpidriver/install | sudo bash

set -euo pipefail

REPO_URL="https://github.com/ibrahimaljuhani/rpidriver.git"
INSTALL_DIR="/opt/rpidriver"
CONFIG_DIR="/etc/rpidriver"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_NAME="rpidriver"
RUN_USER="rpidriver"
MIN_PYTHON_MINOR=10

# ── Colour helpers ─────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[rpidriver]${NC} $*"; }
warning() { echo -e "${YELLOW}[warning]${NC} $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ── Root check ─────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Run this script as root: sudo bash install_pi.sh"

# ── Python version check ───────────────────────────────────────────────────
info "Checking Python version..."
PYTHON_BIN=$(command -v python3 || true)
[[ -n "$PYTHON_BIN" ]] || error "python3 not found. Install it first."

PYTHON_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major)")

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt "$MIN_PYTHON_MINOR" ]]; then
    error "Python 3.${MIN_PYTHON_MINOR}+ required. Found: $("$PYTHON_BIN" --version)"
fi
info "Python $("$PYTHON_BIN" --version) — OK"

# ── System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    libusb-1.0-0 \
    cups cups-client \
    fonts-noto-core fonts-noto-extra \
    git curl ca-certificates

# ── Create system user ─────────────────────────────────────────────────────
if ! id "$RUN_USER" &>/dev/null; then
    info "Creating system user: $RUN_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin \
            --groups lp,plugdev "$RUN_USER"
fi

# ── Clone / update source ──────────────────────────────────────────────────
# Full clone (not --depth=1) so that `update.sh` can git pull cleanly
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning rpidriver from $REPO_URL..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── Python virtualenv ──────────────────────────────────────────────────────
info "Creating Python virtualenv..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip wheel
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

# ── Config file ────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.ini" ]]; then
    info "Installing default config..."
    cp "$INSTALL_DIR/config/config.ini.tmpl" "$CONFIG_DIR/config.ini"
else
    info "Existing config found — skipping."
fi
chown -R "$RUN_USER:$RUN_USER" "$CONFIG_DIR"

# ── udev rules ─────────────────────────────────────────────────────────────
info "Installing udev rules..."
cat > /etc/udev/rules.d/99-rpidriver.rules << 'EOF'
# ESC/POS printers — Epson
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0666", GROUP="plugdev"
# ESC/POS printers — Star Micronics
SUBSYSTEM=="usb", ATTRS{idVendor}=="0519", MODE="0666", GROUP="plugdev"
# Generic USB-CDC (customer displays)
SUBSYSTEM=="tty", SUBSYSTEMS=="usb", MODE="0666", GROUP="plugdev"
EOF
udevadm control --reload-rules
udevadm trigger

# ── systemd service ────────────────────────────────────────────────────────
info "Installing systemd service..."
cat > /etc/systemd/system/rpidriver.service << EOF
[Unit]
Description=RPiDriver — Odoo POS Hardware Proxy
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
Environment=RPIDRIVER_CONFIG=$CONFIG_DIR/config.ini
ExecStart=$VENV_DIR/bin/rpidriver
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=rpidriver

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
# Service is NOT started automatically — edit config.ini first

# ── Done ────────────────────────────────────────────────────────────────────
info "Installation complete!"
echo ""
echo "  ┌─────────────────────────────────────────────────────────────────┐"
echo "  │  NEXT STEPS                                                     │"
echo "  │                                                                 │"
echo "  │  1. Edit the config:                                            │"
echo "  │     sudo nano $CONFIG_DIR/config.ini                            │"
echo "  │                                                                 │"
echo "  │  2. Start the service:                                          │"
echo "  │     sudo systemctl start rpidriver                              │"
echo "  │                                                                 │"
echo "  │  3. Open the dashboard:                                         │"
echo "  │     http://$(hostname -I | awk '{print $1}'):8069               │"
echo "  └─────────────────────────────────────────────────────────────────┘"
echo ""
echo "  Useful commands:"
echo "    systemctl status rpidriver"
echo "    journalctl -u rpidriver -f"
echo ""
echo "  Docs: https://ia.sa/rpidriver/docs"
