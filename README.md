# RPiDriver

**Smart hardware proxy for Odoo POS — built for Raspberry Pi**  
Full Arabic language support · Odoo 17 / 18 / 19 compatible · AGPL-3.0

---

## What is RPiDriver?

RPiDriver runs as a Flask server on a Raspberry Pi and bridges Odoo POS to physical hardware — exactly like an official Odoo IoT Box, but open-source and optimised for the Arab market.

| Feature | Details |
|---|---|
| **Odoo compatibility** | 17, 18, 19 (hw_proxy protocol) |
| **Arabic printing** | RTL reshaping → Pillow bitmap → GS v 0 raster |
| **Printers** | Epson TM-T20/T82/T88, Star Micronics, any ESC/POS |
| **Scales** | Mettler Toledo 8217, Adam Equipment |
| **Customer display** | Bixolon BCD-1000/1100, Epson OCD300 |
| **Network printing** | CUPS IPP |

---

## Quick Install

```bash
curl -fsSL https://ia.sa/rpidriver/install | sudo bash
```

Then open `http://<pi-ip>:8069` in your browser.

Full instructions: [docs/en/install.md](docs/en/install.md) · [docs/ar/install.md](docs/ar/install.md)  
Online docs: [ia.sa/rpidriver/docs](https://ia.sa/rpidriver/docs)

---

## Architecture

```
Odoo POS  ──JSON-RPC──►  RPiDriver (Flask)
                              │
                    ┌─────────┼──────────┐
                    ▼         ▼          ▼
              ESC/POS      Toledo     Customer
              Printer       Scale      Display
              (USB)        (Serial)   (USB-CDC)
```

The Arabic printing pipeline:

```
Arabic text  →  arabic_reshaper  →  python-bidi  →  Pillow  →  GS v 0 raster  →  Printer
```

---

## Configuration

Copy and edit the config template:

```bash
sudo cp /opt/rpidriver/config/config.ini.tmpl /etc/rpidriver/config.ini
sudo nano /etc/rpidriver/config.ini
```

Key settings:

```ini
[rpidriver]
drivers = escpos_driver, scale_driver

[escpos_driver]
paper_width = 576
arabic_font_path = /usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf

[scale_driver]
port     = /dev/ttyUSB0
protocol = toledo8217
```

---

## hw_proxy API

| Method | Endpoint | Response |
|---|---|---|
| `GET` | `/hw_proxy/hello` | `"ping"` |
| `POST` | `/hw_proxy/handshake` | `true` |
| `POST` | `/hw_proxy/status_json` | `{"escpos": {...}, "scale": {...}}` |
| `POST` | `/hw_proxy/scale_read` | `{"weight": 1.23, "unit": "kg"}` |
| `POST` | `/hw_proxy/print_receipt` | `true` / `false` |

---

## Development

```bash
git clone https://github.com/ibrahimaljuhani/rpidriver.git
cd rpidriver
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
RPIDRIVER_CONFIG=config/config.ini.tmpl python -m rpidriver
```

Run tests:

```bash
pytest tests/ -v
```

---

## Links

| | |
|---|---|
| Website | [ia.sa/rpidriver](https://ia.sa/rpidriver) |
| Docs | [ia.sa/rpidriver/docs](https://ia.sa/rpidriver/docs) |
| Install | `curl -fsSL https://ia.sa/rpidriver/install \| sudo bash` |
| Support | [info@ia.sa](mailto:info@ia.sa) |

---

## License

**AGPL-3.0** — same as [pywebdriver](https://github.com/akretion/pywebdriver) (Akretion), from which this project is forked.

Commercial license available: [info@ia.sa](mailto:info@ia.sa)

---

## Author

**Ibrahim Aljuhani** · [ia.sa](https://ia.sa) · [@ibrahimaljuhani](https://github.com/ibrahimaljuhani)
