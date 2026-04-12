#!/usr/bin/env bash
# RPiDriver — Uninstaller
# Usage: sudo bash /opt/rpidriver/scripts/uninstall.sh

set -euo pipefail

SERVICE_NAME="rpidriver"
INSTALL_DIR="/opt/rpidriver"
CONFIG_DIR="/etc/rpidriver"
RUN_USER="rpidriver"

YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "\033[0;32m[rpidriver]${NC} $*"; }
warning() { echo -e "${YELLOW}[warning]${NC} $*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }

read -rp "This will remove RPiDriver completely. Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

info "Stopping and disabling service..."
systemctl stop "$SERVICE_NAME"    || true
systemctl disable "$SERVICE_NAME" || true
rm -f "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload

info "Removing udev rules..."
rm -f /etc/udev/rules.d/99-rpidriver.rules
udevadm control --reload-rules

info "Removing installation directory..."
rm -rf "$INSTALL_DIR"

warning "Config directory $CONFIG_DIR was NOT removed (preserve your settings)."
warning "To remove it manually: sudo rm -rf $CONFIG_DIR"

info "Removing system user..."
userdel "$RUN_USER" 2>/dev/null || true

info "Uninstall complete."
