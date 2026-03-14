#!/usr/bin/env bash
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
# TRITIUM-SC Quick Deploy Script
# Sets up everything needed to run Tritium on a fresh Ubuntu/Debian machine.
#
# Usage:
#   sudo ./scripts/deploy.sh              # Full install
#   sudo ./scripts/deploy.sh --no-systemd  # Skip systemd service creation
#   sudo ./scripts/deploy.sh --check       # Check what's installed, don't change anything
#
# What this does:
#   1. Installs system dependencies (mosquitto, python3, etc.)
#   2. Creates Python venv and installs pip dependencies
#   3. Installs tritium-lib in editable mode
#   4. Starts mosquitto broker
#   5. Optionally creates a systemd service for SC server

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TRITIUM_DIR="$(cd "$SC_DIR/.." && pwd)"
LIB_DIR="$TRITIUM_DIR/tritium-lib"

NO_SYSTEMD=false
CHECK_ONLY=false
SC_PORT=${TRITIUM_PORT:-8000}

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
MAGENTA='\033[0;35m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

for arg in "$@"; do
    case "$arg" in
        --no-systemd) NO_SYSTEMD=true ;;
        --check) CHECK_ONLY=true ;;
        --help|-h)
            echo "Usage: sudo $0 [--no-systemd] [--check]"
            echo "  --no-systemd  Skip systemd service creation"
            echo "  --check       Check what's installed without changing anything"
            exit 0
            ;;
    esac
done

log() { echo -e "${CYAN}[TRITIUM]${NC} $1"; }
ok()  { echo -e "${GREEN}  [OK]${NC} $1"; }
warn(){ echo -e "${YELLOW}  [WARN]${NC} $1"; }
fail(){ echo -e "${MAGENTA}  [FAIL]${NC} $1"; }

# --- Check mode ---
if [ "$CHECK_ONLY" = true ]; then
    log "Checking Tritium deployment readiness..."
    echo ""

    # Python
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 --version 2>&1)
        ok "Python: $PY_VER"
    else
        fail "Python3 not found"
    fi

    # System packages
    for pkg in mosquitto git ffmpeg; do
        if command -v "$pkg" &>/dev/null; then
            ok "$pkg installed"
        else
            warn "$pkg not installed"
        fi
    done

    # Mosquitto running
    if systemctl is-active --quiet mosquitto 2>/dev/null; then
        ok "Mosquitto running"
    elif pgrep -x mosquitto >/dev/null 2>&1; then
        ok "Mosquitto running (not systemd)"
    else
        warn "Mosquitto not running"
    fi

    # Venv
    if [ -f "$SC_DIR/.venv/bin/python3" ]; then
        ok "Python venv exists"
    else
        warn "Python venv not found at $SC_DIR/.venv"
    fi

    # tritium-lib
    if [ -d "$LIB_DIR" ]; then
        ok "tritium-lib found at $LIB_DIR"
    else
        warn "tritium-lib not found"
    fi

    # Ports
    for port in 8000 1883 8080; do
        if ss -tlnp 2>/dev/null | grep -q ":$port "; then
            ok "Port $port in use"
        else
            warn "Port $port available"
        fi
    done

    # Optional
    for pkg in ollama platformio; do
        if command -v "$pkg" &>/dev/null; then
            ok "$pkg installed (optional)"
        else
            echo -e "  [--] $pkg not installed (optional)"
        fi
    done

    echo ""
    log "Check complete."
    exit 0
fi

# --- Full install ---
log "Starting Tritium deployment..."
echo ""

# Must run as root for apt and systemd
if [ "$EUID" -ne 0 ] && [ "$NO_SYSTEMD" = false ]; then
    fail "Please run with sudo for system package installation"
    echo "  Or use: $0 --no-systemd  (skip system-level changes)"
    exit 1
fi

# 1. System packages
log "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    mosquitto mosquitto-clients \
    git curl wget \
    build-essential libffi-dev libssl-dev \
    ffmpeg \
    2>/dev/null
ok "System packages installed"

# 2. Start mosquitto
log "Configuring MQTT broker..."
if systemctl is-enabled mosquitto 2>/dev/null; then
    systemctl start mosquitto 2>/dev/null || true
    systemctl enable mosquitto 2>/dev/null || true
    ok "Mosquitto enabled and started"
else
    # Start directly if systemctl not available
    if ! pgrep -x mosquitto >/dev/null 2>&1; then
        mosquitto -d 2>/dev/null || true
    fi
    ok "Mosquitto started"
fi

# 3. Python venv
log "Setting up Python virtual environment..."
if [ ! -f "$SC_DIR/.venv/bin/python3" ]; then
    python3 -m venv "$SC_DIR/.venv"
    ok "Created venv at $SC_DIR/.venv"
else
    ok "Venv already exists"
fi

# Upgrade pip
"$SC_DIR/.venv/bin/pip" install --upgrade pip -q

# 4. Install tritium-lib
if [ -d "$LIB_DIR" ]; then
    log "Installing tritium-lib..."
    "$SC_DIR/.venv/bin/pip" install -e "$LIB_DIR" -q
    ok "tritium-lib installed (editable)"
fi

# 5. Install SC requirements
log "Installing tritium-sc dependencies..."
if [ -f "$SC_DIR/requirements.txt" ]; then
    "$SC_DIR/.venv/bin/pip" install -r "$SC_DIR/requirements.txt" -q
    ok "SC dependencies installed"
fi

# 6. Create data directories
log "Creating data directories..."
mkdir -p "$SC_DIR/data/amy" "$SC_DIR/data/synthetic" "$SC_DIR/conf"
ok "Data directories ready"

# 7. Systemd service
if [ "$NO_SYSTEMD" = false ]; then
    log "Creating systemd service..."

    ACTUAL_USER="${SUDO_USER:-$(whoami)}"
    ACTUAL_GROUP=$(id -gn "$ACTUAL_USER" 2>/dev/null || echo "$ACTUAL_USER")

    cat > /etc/systemd/system/tritium-sc.service << SVCEOF
[Unit]
Description=Tritium Command Center
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=$ACTUAL_USER
Group=$ACTUAL_GROUP
WorkingDirectory=$SC_DIR
Environment=PYTHONPATH=$SC_DIR/src
Environment=CUDA_VISIBLE_DEVICES=
ExecStart=$SC_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $SC_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable tritium-sc.service
    ok "Systemd service created and enabled"
    echo ""
    log "To start now:  sudo systemctl start tritium-sc"
    log "To view logs:  journalctl -u tritium-sc -f"
else
    echo ""
    log "To start manually:  cd $SC_DIR && ./start.sh"
fi

echo ""
log "Deployment complete!"
log "Command Center will be at: http://localhost:$SC_PORT"
log "Run '$0 --check' to verify the installation"
