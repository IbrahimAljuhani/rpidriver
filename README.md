<div align="center">

```
██████╗ ██████╗ ██╗    ██████╗ ██████╗ ██╗██╗   ██╗███████╗██████╗
██╔══██╗██╔══██╗██║    ██╔══██╗██╔══██╗██║██║   ██║██╔════╝██╔══██╗
██████╔╝██████╔╝██║    ██║  ██║██████╔╝██║██║   ██║█████╗  ██████╔╝
██╔══██╗██╔═══╝ ██║    ██║  ██║██╔══██╗██║╚██╗ ██╔╝██╔══╝  ██╔══██╗
██║  ██║██║     ██║    ██████╔╝██║  ██║██║ ╚████╔╝ ███████╗██║  ██║
╚═╝  ╚═╝╚═╝     ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝
```

**Smart hardware proxy for Odoo — built for Raspberry Pi**

[![Release](https://img.shields.io/badge/release-v1.0.0-brightgreen?style=flat-square&logo=github)](https://github.com/ibrahimaljuhani/rpidriver/releases)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg?style=flat-square)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20ARM64-red?style=flat-square&logo=raspberry-pi)](https://www.raspberrypi.org)
[![Odoo](https://img.shields.io/badge/Odoo-17%20%7C%2018%20%7C%2019-purple?style=flat-square)](https://odoo.com)
[![Lang](https://img.shields.io/badge/interface-Arabic%20%2B%20English-orange?style=flat-square)](https://github.com/ibrahimaljuhani/rpidriver)

*A fork of [pywebdriver](https://github.com/akretion/pywebdriver) — rebuilt for the Arab market*

</div>

---

## What is RPiDriver?

RPiDriver is a lightweight, open-source hardware proxy that connects **Odoo POS** to physical hardware through a **Raspberry Pi**. It acts as a local server that bridges your Odoo instance with receipt printers, scales, and customer displays — with **full Arabic language support** built in from day one.

Most existing solutions are either expensive, lack Arabic support, or don't run reliably on ARM hardware. RPiDriver fixes all three.

```bash
# Install with one command
curl -fsSL https://ia.sa/rpidriver/install | sudo bash
```

---

## The Problem

Running Odoo POS in Arabic-speaking markets comes with a specific set of hardware challenges:

- **Arabic receipt printing** on ESC/POS printers requires RTL text shaping — most drivers get this wrong
- **Odoo's official IoT Box** is expensive and often overkill for small retailers
- **Existing open-source proxies** are built for x86 and don't support ARM64 natively
- **Setup complexity** puts hardware integration out of reach for non-technical shop owners

RPiDriver is the answer: a single `curl` command turns a $35 Raspberry Pi into a fully capable Odoo hardware hub.

---

## Features

### Free — Open Source (AGPL-3.0)

| Feature | Details |
|---|---|
| **Arabic ESC/POS Printing** | Correct RTL rendering via arabic-reshaper + python-bidi + Pillow bitmap engine |
| **Odoo 17, 18 & 19** | Full hw_proxy protocol — verified against all three versions |
| **Image Receipt Printing** | Odoo 17+ sends base64 JPEG receipts — rendered and printed natively |
| **Cash Drawer** | ESC p pulse command triggered from Odoo POS |
| **Bilingual Dashboard** | Web interface in Arabic and English with RTL layout |
| **Serial Scale Support** | Mettler Toledo 8217 (7E1) and Adam Equipment (8N1) protocols |
| **Customer Display** | Bixolon BCD-1000/1100, Epson OCD300 — 2×20 LCD over USB-CDC |
| **CUPS Network Printing** | Send jobs to shared CUPS printers over the network via IPP |
| **HTTPS / SSL** | Auto-generated self-signed certificate — required for Odoo 17+ |
| **Plugin Architecture** | Enable only the drivers you need via a single config line |
| **ARM64 Native** | Built and tested on Raspberry Pi 3B+, 4, and 5 |
| **systemd Service** | Auto-start on boot, crash recovery, secret key management |
| **udev Rules** | Automatic USB and serial port permissions — no `sudo` after setup |

### Pro — Coming Soon

| Feature | Details |
|---|---|
| **Web Config Panel** | Edit all settings from the browser — no SSH needed |
| **OTA Updates** | One-click updates from the dashboard |
| **Watchdog + Alerts** | Telegram notifications on hardware failures |
| **Visual Event Log** | Real-time status and error history |
| **SSL Certificate** | Signed certificate from ia.sa — zero setup |
| **Config Backup** | Automated settings backup and restore |
| **Email Support** | 48-hour response guarantee |
| **Commercial License** | No AGPL obligations |

> $9/month per device · $79/year · [Contact info@ia.sa](mailto:info@ia.sa)

---

## Hardware Compatibility

### Raspberry Pi

| Model | Status |
|---|---|
| Raspberry Pi 3B / 3B+ | ✓ Supported |
| Raspberry Pi 4 (all RAM variants) | ✓ Supported |
| Raspberry Pi 5 | ✓ Supported |

### Receipt Printers

| Brand | Models | Connection |
|---|---|---|
| Epson TM series | T20, T82, T88 | USB |
| Star Micronics | TSP series | USB |
| Any ESC/POS printer | Generic | USB |
| Network printers | via CUPS/IPP | Network |

### Scales

| Brand | Protocol | Serial Parameters |
|---|---|---|
| Mettler Toledo | Toledo 8217 | 9600 baud, 7E1 |
| Adam Equipment | Adam | 4800 baud, 8N1 |

### Customer Displays

| Brand | Model | Connection |
|---|---|---|
| Bixolon | BCD-1000, BCD-1100 | USB-CDC (ttyACM) |
| Epson | OCD300 | RS-232 |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Odoo POS (browser)             │
└──────────────────┬──────────────────────────┘
                   │  hw_proxy / JSON-RPC 2.0
                   ▼
┌─────────────────────────────────────────────┐
│         RPiDriver  (Raspberry Pi)           │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  escpos  │  │  scale   │  │ display  │  │
│  │  driver  │  │  driver  │  │  driver  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
└───────┼──────────────┼──────────────┼───────┘
        │              │              │
        ▼              ▼              ▼
   ESC/POS          Toledo /       Customer
   Printer          Adam Scale     Display
```

RPiDriver exposes a local Flask server on port `8069`. Odoo connects to it exactly like it would connect to an official IoT Box — no Odoo module required, no cloud dependency.

### hw_proxy Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/hw_proxy/hello` | GET | Connectivity probe |
| `/hw_proxy/handshake` | POST | POS startup handshake |
| `/hw_proxy/status_json` | POST | Driver status for all devices |
| `/hw_proxy/scale_read` | POST | Read current weight |
| `/hw_proxy/default_printer_action` | POST | Print receipt / open cashbox (Odoo 17–19) |
| `/hw_proxy/print_receipt` | POST | Legacy print endpoint (Odoo 13–16) |
| `/hw_proxy/open_cashbox` | POST | Dedicated cash drawer (Odoo 13–16) |
| `/hw_proxy/send_text_customer_display` | POST | Show text on customer display |
| `/hw_proxy/log` | POST | Receive and log POS client messages |

---

## Quick Start

### One-Command Install (Recommended)

```bash
# Run on your Raspberry Pi
curl -fsSL https://ia.sa/rpidriver/install | sudo bash
```

The installer will:
1. Install system dependencies (libusb, CUPS, Noto Arabic fonts)
2. Create a dedicated `rpidriver` system user with correct permissions
3. Install udev rules for USB printers and serial devices
4. Generate a secure Flask secret key
5. Register and enable the systemd service

```bash
# After install:
sudo nano /etc/rpidriver/config.ini     # edit your hardware config
sudo systemctl start rpidriver
# Open https://[your-pi-ip]:8069
```

> **SSL Note:** The installer auto-generates a self-signed certificate and enables HTTPS automatically. Before connecting Odoo POS, open `https://[pi-ip]:8069` in your browser and accept the certificate warning once. This is required because Odoo 17+ runs on HTTPS and the browser blocks connections to HTTP devices (mixed-content policy).

### Development Install

```bash
git clone https://github.com/ibrahimaljuhani/rpidriver.git
cd rpidriver

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp config/config.ini.tmpl config/config.ini
# Edit config.ini to match your hardware

export RPIDRIVER_SECRET="your-dev-secret"
rpidriver
```

---

## Configuration

Copy `config/config.ini.tmpl` to `/etc/rpidriver/config.ini` and edit to match your hardware. The Flask secret key is set via the environment variable `RPIDRIVER_SECRET` (generated automatically by the installer).

```ini
[rpidriver]
host    = 0.0.0.0
port    = 8069
debug   = false
# Enable only the drivers you need:
drivers = escpos_driver, scale_driver


[escpos_driver]
# Paper width in pixels: 576 = 80mm @ 203dpi | 384 = 58mm @ 203dpi
paper_width = 576

# Arabic font — required for correct RTL receipt printing
# arabic_font_path = /usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf

# Message printed at the bottom of every receipt
# thank_you_message = Thank you! — شكراً لزيارتكم

# USB vendor/product IDs (leave blank to auto-detect)
# usb_vendor  = 04b8
# usb_product = 0e15


[scale_driver]
port     = /dev/ttyUSB0
protocol = toledo8217   # toledo8217 | adam
timeout  = 1.0
# baudrate = 9600       # override only if your scale is non-standard


[display_driver]
port     = /dev/ttyACM0
baudrate = 9600


[cups_driver]
cups_host    = localhost
cups_port    = 631
printer_name = Receipt_Printer
```

---

## Roadmap

- [x] Arabic ESC/POS printing engine (reshape → bidi → bitmap → raster)
- [x] Odoo 17, 18 & 19 hw_proxy protocol — verified compatible
- [x] Image receipt printing (base64 JPEG from Odoo 17+ canvas)
- [x] Cash drawer support
- [x] Serial scale drivers — Toledo 8217 and Adam Equipment
- [x] Customer display driver — Bixolon / Epson
- [x] CUPS network printing via IPP
- [x] Bilingual web dashboard (AR / EN)
- [x] One-command installer (`install_pi.sh`)
- [x] systemd service with secret key management
- [x] udev rules for all device types
- [x] SSL / HTTPS with auto-generated self-signed certificate
- [x] `v1.0.0` — Initial public release
- [ ] Debian package for Ubuntu 24.04 ARM64
- [ ] RPiDriver Pro — Web config panel
- [ ] RPiDriver Pro — OTA updates
- [ ] RPiDriver Pro — Watchdog + Telegram alerts
- [ ] Multi-device dashboard

---

## For Non-Profits & Small Projects

RPiDriver is **completely free** for non-profit organizations, schools, relief organizations, early-stage startups, and small local stores.

If your organization qualifies, reach out at [info@ia.sa](mailto:info@ia.sa). The project's sustainability comes from businesses that can afford to pay — not from those who need help.

---

## Built On

RPiDriver is a fork of [pywebdriver](https://github.com/akretion/pywebdriver) by [Akretion](https://akretion.com), licensed under AGPL-3.0.

All modifications are released under the same AGPL-3.0 license.

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository and create a feature branch
2. Run the test suite: `pytest tests/ -v`
3. Open a pull request with a clear description of your change

Please open an issue first for significant changes so we can discuss the approach.

---

## License

RPiDriver is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License v3.0** as published by the Free Software Foundation.

Copyright © 2026 Ibrahim Aljuhani · [info@ia.sa](mailto:info@ia.sa)  
Based on [pywebdriver](https://github.com/akretion/pywebdriver) © Akretion

See the full license text in [LICENSE](LICENSE).  
For commercial licensing (no AGPL obligations), contact [info@ia.sa](mailto:info@ia.sa).

---

<div align="center">

**[Website](https://ia.sa/rpidriver)** · **[Docs](https://ia.sa/rpidriver/docs)** · **[Pro](mailto:info@ia.sa)** · **[ia.sa](https://ia.sa)**

Made with care for the Arab market · Ibrahim Aljuhani · 2026

</div>
