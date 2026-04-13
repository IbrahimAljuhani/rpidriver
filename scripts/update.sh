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
# Stash any accidental local changes so the pull doesn't fail
if ! git -C "$INSTALL_DIR" diff --quiet || ! git -C "$INSTALL_DIR" diff --cached --quiet; then
    info "Local changes detected — stashing before pull..."
    git -C "$INSTALL_DIR" stash push -m "rpidriver-update-$(date +%Y%m%d-%H%M%S)"
fi
git -C "$INSTALL_DIR" pull --ff-only || {
    echo -e "${RED}[error]${NC} git pull failed. Check your internet connection or resolve conflicts manually."
    exit 1
}

info "Updating Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

info "Compiling translation catalogs..."
"$VENV_DIR/bin/pybabel" compile -d "$INSTALL_DIR/rpidriver/translations"

info "Restarting service..."
systemctl restart "$SERVICE_NAME"

info "Update complete. $(git -C "$INSTALL_DIR" describe --tags --always)"
echo ""
echo "  Docs: https://ia.sa/rpidriver/docs"
