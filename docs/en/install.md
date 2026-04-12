# RPiDriver — Installation Guide

## Requirements

- Raspberry Pi 3B+ or newer (Raspberry Pi OS Bookworm / Bullseye recommended)
- Python 3.10 or newer
- Internet connection during installation

## One-Command Install

```bash
curl -fsSL https://ia.sa/rpidriver/install | sudo bash
```

This script will:
1. Verify Python 3.10+ is available
2. Install system packages (`libusb`, `cups`, Noto fonts, etc.)
3. Clone the repository to `/opt/rpidriver`
4. Create a Python virtualenv and install all dependencies
5. Write a default config to `/etc/rpidriver/config.ini`
6. Install a `systemd` service that starts on boot
7. Configure `udev` rules so USB printers work without `root`

---

## Manual Installation

### 1. Clone the repository

```bash
git clone https://github.com/ibrahimaljuhani/rpidriver.git /opt/rpidriver
cd /opt/rpidriver
```

### 2. Create a virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Create the config file

```bash
sudo mkdir -p /etc/rpidriver
sudo cp config/config.ini.tmpl /etc/rpidriver/config.ini
sudo nano /etc/rpidriver/config.ini
```

### 4. Run manually (for testing)

```bash
RPIDRIVER_CONFIG=/etc/rpidriver/config.ini .venv/bin/rpidriver
```

Open `http://<pi-ip>:8069` in your browser.

---

## Configuring Odoo POS

1. Go to **Point of Sale → Configuration → Settings**
2. Enable **IoT Box**
3. Set the IoT Box IP to your Raspberry Pi's IP address, port `8069`
4. Save and reload — Odoo will call `/hw_proxy/hello` to verify connectivity

---

## Hardware Setup

### ESC/POS Printer

Connect via USB. The udev rules installed by the script grant access automatically.
Edit `/etc/rpidriver/config.ini` → `[escpos_driver]` if you need to set a custom `paper_width`.

### Scale (Toledo / Adam)

Connect via USB-to-Serial adapter. Set `port`, `baudrate`, and `protocol` under `[scale_driver]`.

### Customer Display

Connect via USB (Bixolon BCD-1000 appears as `/dev/ttyACM0`).
Set `port` under `[display_driver]`.

---

## Service Management

```bash
# Check status
systemctl status rpidriver

# View live logs
journalctl -u rpidriver -f

# Restart after config change
sudo systemctl restart rpidriver

# Update to latest version
sudo bash /opt/rpidriver/scripts/update.sh
```

---

## Arabic Font Setup

For correct Arabic receipt printing, install the Noto Sans Arabic font:

```bash
sudo apt-get install fonts-noto-extra
```

Then set in `/etc/rpidriver/config.ini`:

```ini
[escpos_driver]
arabic_font_path = /usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No ESC/POS printer found on USB` | Check USB cable; run `lsusb`; verify udev rules |
| Arabic prints as `???` | Set `arabic_font_path` in config |
| Scale reads `0.0` always | Check `port` and `protocol` in `[scale_driver]` |
| Odoo can't connect | Ensure port 8069 is not blocked by a firewall |

---

## Links

- Website: [ia.sa/rpidriver](https://ia.sa/rpidriver)
- Docs: [ia.sa/rpidriver/docs](https://ia.sa/rpidriver/docs)
- Support: [info@ia.sa](mailto:info@ia.sa)

---

## License

AGPL-3.0 — same as [pywebdriver](https://github.com/akretion/pywebdriver) (Akretion).
Commercial license available: [info@ia.sa](mailto:info@ia.sa)
