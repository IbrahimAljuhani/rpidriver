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
            --groups lp,plugdev,dialout "$RUN_USER"
fi

# Add to systemd-journal group so the dashboard can stream live logs
if getent group systemd-journal &>/dev/null; then
    usermod -aG systemd-journal "$RUN_USER"
    info "Added $RUN_USER to systemd-journal group (live log streaming)."
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

# websocket-client is required by neoleap_driver (NeoLeap Mada terminal).
# Installed separately so a missing package doesn't fail the core install.
info "Installing websocket-client (required for NeoLeap Mada terminal)..."
"$VENV_DIR/bin/pip" install "websocket-client>=1.6" || \
    warning "websocket-client install failed — NeoLeap driver will not work. Run manually: pip install websocket-client"

"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

# ── Compile translation catalogs ───────────────────────────────────────────
info "Compiling translation catalogs..."
"$VENV_DIR/bin/pybabel" compile -d "$INSTALL_DIR/rpidriver/translations"

# ── Config file ────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.ini" ]]; then
    info "Installing default config..."
    cp "$INSTALL_DIR/config/config.ini.tmpl" "$CONFIG_DIR/config.ini"
else
    info "Existing config found — skipping."
fi
chown -R "$RUN_USER:$RUN_USER" "$CONFIG_DIR"

# ── SSL certificate ────────────────────────────────────────────────────────
info "Setting up SSL certificate..."
SSL_DIR="$CONFIG_DIR/ssl"
mkdir -p "$SSL_DIR"

if [[ ! -f "$SSL_DIR/cert.pem" ]]; then
    info "Generating self-signed SSL certificate (valid 10 years)..."
    PI_IP=$(hostname -I | awk '{print $1}')
    openssl req -x509 \
        -newkey rsa:2048 \
        -keyout "$SSL_DIR/key.pem" \
        -out    "$SSL_DIR/cert.pem" \
        -days   3650 \
        -nodes \
        -subj   "/C=SA/O=RPiDriver/CN=rpidriver" \
        -addext "subjectAltName=IP:${PI_IP},DNS:rpidriver.local" \
        2>/dev/null
    chmod 600 "$SSL_DIR/key.pem"
    chmod 644 "$SSL_DIR/cert.pem"
    chown -R "$RUN_USER:$RUN_USER" "$SSL_DIR"
    info "Certificate generated: $SSL_DIR/cert.pem (IP: $PI_IP)"
else
    info "Existing SSL certificate found — skipping generation."
fi

# ── udev rules ─────────────────────────────────────────────────────────────
info "Installing udev rules..."
cat > /etc/udev/rules.d/99-rpidriver.rules << 'EOF'
# ESC/POS printers — Epson
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0666", GROUP="plugdev"
# ESC/POS printers — Star Micronics
SUBSYSTEM=="usb", ATTRS{idVendor}=="0519", MODE="0666", GROUP="plugdev"
# Generic USB-CDC (customer displays, /dev/ttyACM*)
SUBSYSTEM=="tty", SUBSYSTEMS=="usb", KERNEL=="ttyACM*", MODE="0666", GROUP="plugdev"
# Serial scales and adapters (/dev/ttyUSB*)
SUBSYSTEM=="tty", KERNEL=="ttyUSB*", MODE="0666", GROUP="plugdev"
EOF
udevadm control --reload-rules
udevadm trigger

# ── systemd service ────────────────────────────────────────────────────────
info "Installing systemd service..."
# ── Generate secret key ────────────────────────────────────────────────────
SECRETS_FILE="$CONFIG_DIR/secrets"
if [[ ! -f "$SECRETS_FILE" ]]; then
    info "Generating Flask secret key..."
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "$SECRETS_FILE" << SECRETS_EOF
# RPiDriver secrets — keep this file private (chmod 600)
RPIDRIVER_SECRET=$SECRET_KEY
SECRETS_EOF
    chmod 600 "$SECRETS_FILE"
    chown "$RUN_USER:$RUN_USER" "$SECRETS_FILE"
    info "Secret key saved to $SECRETS_FILE"
else
    info "Existing secrets file found — skipping key generation."
fi

cat > /etc/systemd/system/rpidriver.service << EOF
[Unit]
Description=RPiDriver — Odoo POS Hardware Proxy
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
Environment=RPIDRIVER_CONFIG=$CONFIG_DIR/config.ini
EnvironmentFile=$CONFIG_DIR/secrets
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

# ── sudoers — allow rpidriver to restart its own service without a password ──
SUDOERS_FILE="/etc/sudoers.d/rpidriver"
info "Installing sudoers entry for passwordless service restart..."
cat > "$SUDOERS_FILE" << 'SUDOERS_EOF'
# Allow the rpidriver service user to restart itself via the dashboard
rpidriver ALL=(ALL) NOPASSWD: /bin/systemctl restart rpidriver
SUDOERS_EOF
chmod 440 "$SUDOERS_FILE"
# Validate the file — remove it if visudo finds a syntax error
visudo -c -f "$SUDOERS_FILE" || { warning "sudoers syntax error — removing file."; rm -f "$SUDOERS_FILE"; }

# ── Done ────────────────────────────────────────────────────────────────────
info "Installation complete!"
echo ""
echo "  ┌─────────────────────────────────────────────────────────────────┐"
echo "  │  NEXT STEPS                                                     │"
echo "  │                                                                 │"
echo "  │  1. Start the service:                                          │"
echo "  │     sudo systemctl start rpidriver                              │"
echo "  │                                                                 │"
echo "  │  2. Open the dashboard:                                         │"
echo "  │     https://$(hostname -I | awk '{print $1}'):8069              │"
echo "  │                                                                 │"
echo "  │  3. Configure drivers in-browser:                               │"
echo "  │     https://$(hostname -I | awk '{print $1}'):8069/config       │"
echo "  │     (no more sudo nano — everything editable in the browser)    │"
echo "  │                                                                 │"
echo "  │  4. View live logs:                                             │"
echo "  │     https://$(hostname -I | awk '{print $1}'):8069/logs         │"
echo "  └─────────────────────────────────────────────────────────────────┘"
echo ""
echo "  Useful commands:"
echo "    systemctl status rpidriver"
echo "    journalctl -u rpidriver -f"
echo ""
echo "  Docs: https://ia.sa/rpidriver/docs"
