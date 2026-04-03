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

[![Status](https://img.shields.io/badge/status-coming%20soon-blue?style=flat-square&logo=github)](https://github.com/ibrahimaljuhani/rpidriver)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20ARM64-red?style=flat-square&logo=raspberry-pi)](https://www.raspberrypi.org)
[![Odoo](https://img.shields.io/badge/Odoo-17%20%7C%2018-purple?style=flat-square)](https://odoo.com)
[![Lang](https://img.shields.io/badge/language-Arabic%20%2B%20English-orange?style=flat-square)](https://github.com/ibrahimaljuhani/rpidriver)

*A fork of [pywebdriver](https://github.com/akretion/pywebdriver) — rebuilt for the Arab market*

</div>

---

> **⚠️ Under Development** — RPiDriver is currently in active development and not yet released. Star the repo to get notified when v1.0.0 drops.

---

## What is RPiDriver?

RPiDriver is a lightweight, open-source hardware proxy that connects **Odoo POS** to physical hardware through a **Raspberry Pi**. It acts as a local server that bridges your Odoo instance with printers, scales, and customer displays — with **full Arabic language support** built in from day one.

Most existing solutions are either expensive, lack Arabic support, or simply don't run reliably on ARM hardware. RPiDriver fixes all three.

```bash
# Install with one command
curl -sSL https://get.ia.sa/install | sudo bash
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
| **Arabic ESC/POS Printing** | Correct RTL rendering via arabic-reshaper + python-bidi |
| **Odoo 17 & 18 Support** | Full hw_proxy protocol compatibility |
| **Bilingual Interface** | Web dashboard in Arabic and English |
| **Toledo Scale** | Mettler Toledo serial integration |
| **Customer Display** | Bixolon BCD-1000/1100, Epson OCD300 |
| **CUPS Network Printing** | Shared printers over the network |
| **Automatic HTTPS** | Self-signed SSL via mkcert — no browser warnings |
| **ARM64 Native** | Built for Raspberry Pi 3B+, 4, and 5 |
| **systemd Service** | Auto-start on boot, crash recovery |

### Pro — Coming Soon

| Feature | Details |
|---|---|
| **Web Config Panel** | Edit all settings from the browser — no SSH needed |
| **OTA Updates** | One-click updates from the dashboard |
| **Watchdog + Alerts** | Telegram notifications on failures |
| **Visual Event Log** | Real-time status and error history |
| **SSL from api.ia.sa** | Signed certificate, zero setup |
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
| Raspberry Pi Zero 2W | ✓ Limited |

### Printers

| Brand | Connection |
|---|---|
| Epson TM series (T20, T82, T88...) | USB, Serial, Network |
| Star Micronics TSP series | USB, Serial |
| Xprinter XP series | USB, Network |
| Any ESC/POS compatible printer | USB, Serial |

### Other Devices

| Device | Protocol |
|---|---|
| Mettler Toledo scales | Serial (RS-232) |
| Bixolon customer displays | USB, Serial |
| Epson OCD300 | USB |
| Adyen payment terminals | Network |
| Telium / Ingenico terminals | Serial |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Odoo POS (browser)             │
└──────────────────┬──────────────────────────┘
                   │  hw_proxy / JSON-RPC
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
   ESC/POS          Toledo         Customer
   Printer           Scale         Display
```

RPiDriver exposes a local Flask server on port `8069`. Odoo connects to it exactly like it would connect to an official IoT Box — no Odoo module required.

---

## Quick Start

> **Note:** RPiDriver is not yet released. The commands below reflect the planned installation flow.

```bash
# 1. Install — auto-detects your Pi model and OS
curl -sSL https://get.ia.sa/install | sudo bash

# 2. Open the dashboard
# Navigate to http://[your-pi-ip]:8069

# 3. Connect Odoo
# POS Settings → IoT Box → Add your Pi's IP address
```

### Manual Installation (development)

```bash
git clone https://github.com/ibrahimaljuhani/rpidriver.git
cd rpidriver

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config/config.ini.tmpl config/config.ini
# Edit config.ini to match your hardware

python3 -m rpidriver
```

---

## Configuration

```ini
[flask]
host         = 0.0.0.0
port         = 8069
cors_origins = *

[rpidriver]
locale  = ar_SA     # ar_SA | en_US
drivers = escpos_driver,scale_driver,display_driver,cups_driver

[escpos]
printer_type = usb      # usb | serial | network
usb_vendor   = 0x04b8   # Epson vendor ID
usb_product  = 0x0e15

[scale]
port     = /dev/ttyUSB0
baudrate = 9600
```

---

## Roadmap

- [x] Architecture design and research
- [x] Arabic ESC/POS printing engine
- [x] ARM64 packaging strategy
- [x] Bilingual web interface (AR/EN)
- [ ] `v1.0.0` — Initial public release
- [ ] `install_pi.sh` — One-command installer
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

RPiDriver is not yet open for external contributions — the codebase is being prepared for initial release. Once v1.0.0 is out, contributions will be welcome.

In the meantime:

- ⭐ Star the repo to stay updated
- 🐛 Open an issue to report bugs or suggest features
- 📧 Email [info@ia.sa](mailto:info@ia.sa) for Pro or partnership inquiries

---

## 📜 License


RPiDriver is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License v3.0** as published by the Free Software Foundation.

Copyright © 2026 Ibrahim Aljuhani <info@ia.sa>  
Based on [pywebdriver](https://github.com/akretion/pywebdriver) © Akretion

📄 See the full license text in [LICENSE](LICENSE).  
💼 For commercial licensing (no AGPL obligations), contact: [info@ia.sa](mailto:info@ia.sa)



<div align="center">

**[Website](https://rpidriver.ia.sa)** · **[Docs](https://docs.ia.sa)** · **[Pro](mailto:info@ia.sa)** · **[ia.sa](https://ia.sa)**

Made with care for the Arab market · Ibrahim Aljuhani · 2026

</div>
