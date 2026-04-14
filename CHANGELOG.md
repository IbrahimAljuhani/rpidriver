# Changelog

All notable changes to RPiDriver are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-04-14

### Added
- **Core Flask server** — hw_proxy protocol (JSON-RPC 2.0), compatible with Odoo 17, 18, 19
- **ESC/POS driver** — Arabic RTL printing via arabic-reshaper + python-bidi + Pillow bitmap engine
- **Scale driver** — Mettler Toledo 8217 (7E1) and Adam Equipment (8N1) serial protocols
- **Customer display driver** — Bixolon BCD-1000/1100, Epson OCD300 over USB-CDC
- **CUPS driver** — Network printing via IPP (auto-detects pycups when available)
- **NeoLeap driver** — Mada payment terminal (N950) over WebSocket port 9998
  - Dual response format: JSON (Format A) and hybrid JSON+XML (Format B — production N950)
  - Accepts 8-digit bank TID or 16-digit device TID
  - Background TCP connectivity check on startup
- **Bilingual dashboard** — Arabic / English with RTL layout (Flask-Babel)
- **Web config panel** — Edit all settings from the browser, no SSH required
- **Live log viewer** — SSE streaming with REST polling fallback
- **Service restart button** — One-click restart from the dashboard
- **SSL / HTTPS** — Auto-generated self-signed certificate (required for Odoo 17+)
- **One-command installer** — `install_pi.sh` covers venv, systemd, udev, sudoers, SSL
- **Updater** — `update.sh` with git stash, ff-only pull, pybabel compile
- **Plugin architecture** — Load only needed drivers via config.ini
- **`ia_mada_rpidriver` Odoo module** — Odoo 17, 18, 19 support for NeoLeap Mada payments

### Security
- Flask secret key generated at install time and stored in `/etc/rpidriver/secrets`
- Serial device fallback removed from `serial_read` / `serial_write` — only loaded driver allowed
- Dedicated `rpidriver` system user with minimal permissions
- udev rules grant USB access without running as root
