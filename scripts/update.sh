#!/usr/bin/env bash
# RPiDriver — In-place updater
# Usage: sudo bash /opt/rpidriver/scripts/update.sh

set -euo pipefail

INSTALL_DIR="/opt/rpidriver"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_NAME="rpidriver"

GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${GREEN}[rpidriver]${NC} $*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }

info "Pulling latest source..."
git -C "$INSTALL_DIR" pull --ff-only

info "Updating Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

info "Restarting service..."
systemctl restart "$SERVICE_NAME"

info "Update complete. $(git -C "$INSTALL_DIR" describe --tags --always)"
echo ""
echo "  Docs: https://ia.sa/rpidriver/docs"
