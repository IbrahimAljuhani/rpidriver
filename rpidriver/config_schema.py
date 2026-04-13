"""
Config schema — defines every configurable option in config.ini.

Each section is a dict of field definitions.  Special keys prefixed with
underscore (_title, _icon, _depends) control display only.

Field definition keys:
    type        — "text" | "number" | "boolean" | "select" | "drivers"
    label       — human-readable label (English; translated in template)
    default     — value used when the key is absent from config.ini
    help        — one-line description shown below the input
    restart     — True  → changing this field requires a service restart
    options     — list of (value, label) tuples  [select only]
    placeholder — hint shown in empty text inputs
    pattern     — HTML input pattern for client-side validation
    maxlength   — max characters  [text only]
    min/max     — range          [number only]
    step        — step           [number only]
"""

AVAILABLE_DRIVERS = [
    "escpos_driver",
    "scale_driver",
    "display_driver",
    "cups_driver",
    "neoleap_driver",
]

DRIVER_LABELS = {
    "escpos_driver"  : "ESC/POS Printer",
    "scale_driver"   : "Scale",
    "display_driver" : "Customer Display",
    "cups_driver"    : "CUPS Network Printer",
    "neoleap_driver" : "Mada Terminal (NeoLeap)",
}

CONFIG_SCHEMA = {
    "rpidriver": {
        "_title"  : "Core",
        "_icon"   : "⚙️",
        "drivers" : {
            "type"   : "drivers",
            "label"  : "Active Drivers",
            "default": "",
            "help"   : "Hardware drivers to load at startup.  Changes require restart.",
            "restart": True,
        },
        "host": {
            "type"   : "text",
            "label"  : "Listen Address",
            "default": "0.0.0.0",
            "help"   : "IP to bind to.  Use 0.0.0.0 for all interfaces.",
            "restart": True,
        },
        "port": {
            "type"   : "number",
            "label"  : "Port",
            "default": "8069",
            "min"    : 1024,
            "max"    : 65535,
            "help"   : "TCP port for the RPiDriver server.",
            "restart": True,
        },
        "debug": {
            "type"   : "boolean",
            "label"  : "Debug Mode",
            "default": False,
            "help"   : "Enable Flask debug mode.  Never use in production.",
            "restart": True,
        },
    },

    "neoleap_driver": {
        "_title"  : "Mada Terminal (NeoLeap)",
        "_icon"   : "💳",
        "_depends": "neoleap_driver",
        "neoleap_ip": {
            "type"       : "text",
            "label"      : "Terminal IP Address",
            "default"    : "",
            "placeholder": "192.168.1.100",
            "help"       : "IP address of the NeoLeap terminal on the local network.",
        },
        "terminal_id": {
            "type"       : "text",
            "label"      : "Terminal ID (TID)",
            "default"    : "",
            "placeholder": "12345678",
            "maxlength"  : 8,
            "pattern"    : r"\d{8}",
            "help"       : "8-digit Terminal ID provided by the acquiring bank (Al Rajhi, SNB …).",
        },
        "port": {
            "type"   : "number",
            "label"  : "WebSocket Port",
            "default": "7000",
            "help"   : "NeoLeap WebSocket port.  Do not change unless instructed by NeoLeap.",
        },
        "timeout": {
            "type"   : "number",
            "label"  : "Transaction Timeout (s)",
            "default": "90",
            "help"   : "Seconds to wait for the customer to complete a payment.",
        },
        "state_ttl": {
            "type"   : "number",
            "label"  : "State Reset Delay (s)",
            "default": "30",
            "help"   : "Seconds before a completed transaction auto-resets to idle.",
        },
    },

    "escpos_driver": {
        "_title"  : "ESC/POS Printer",
        "_icon"   : "🖨️",
        "_depends": "escpos_driver",
        "paper_width": {
            "type"   : "select",
            "label"  : "Paper Width",
            "default": "576",
            "options": [("576", "80 mm — 576 dots"), ("384", "58 mm — 384 dots")],
            "help"   : "Paper width in dots.  80 mm printers use 576; 58 mm use 384.",
        },
        "thank_you_message": {
            "type"   : "text",
            "label"  : "Thank You Message",
            "default": "Thank you! — شكراً لزيارتكم",
            "help"   : "Text printed at the bottom of every receipt.",
        },
        "arabic_font_path": {
            "type"       : "text",
            "label"      : "Arabic Font Path",
            "default"    : "",
            "placeholder": "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
            "help"       : "Full path to a TrueType Arabic font.  Leave empty to use the bundled font.",
        },
    },

    "scale_driver": {
        "_title"  : "Scale",
        "_icon"   : "⚖️",
        "_depends": "scale_driver",
        "port": {
            "type"       : "text",
            "label"      : "Serial Port",
            "default"    : "/dev/ttyUSB0",
            "placeholder": "/dev/ttyUSB0",
            "help"       : "Serial device path for the scale.",
        },
        "protocol": {
            "type"   : "select",
            "label"  : "Protocol",
            "default": "toledo8217",
            "options": [
                ("toledo8217", "Toledo 8217  —  7E1  (Mettler-Toledo)"),
                ("adam",       "Adam Equipment  —  8N1"),
            ],
            "help": "Serial protocol used by the scale model.",
        },
        "unit": {
            "type"   : "select",
            "label"  : "Weight Unit",
            "default": "kg",
            "options": [("kg", "kg"), ("g", "g"), ("lb", "lb"), ("oz", "oz")],
            "help"   : "Unit displayed in Odoo POS.",
        },
        "timeout": {
            "type"   : "number",
            "label"  : "Read Timeout (s)",
            "default": "1.0",
            "step"   : "0.1",
            "help"   : "Serial read timeout per polling cycle.",
        },
    },

    "display_driver": {
        "_title"  : "Customer Display",
        "_icon"   : "🖥️",
        "_depends": "display_driver",
        "port": {
            "type"       : "text",
            "label"      : "Serial Port",
            "default"    : "/dev/ttyACM0",
            "placeholder": "/dev/ttyACM0",
            "help"       : "Serial device path for the customer display (USB-CDC).",
        },
        "baudrate": {
            "type"   : "number",
            "label"  : "Baud Rate",
            "default": "9600",
            "help"   : "Serial baud rate.  Most 2×20 displays use 9600.",
        },
    },

    "cups_driver": {
        "_title"  : "CUPS Network Printer",
        "_icon"   : "🖨️",
        "_depends": "cups_driver",
        "cups_host": {
            "type"   : "text",
            "label"  : "CUPS Host",
            "default": "localhost",
            "help"   : "Hostname or IP of the CUPS server.",
        },
        "cups_port": {
            "type"   : "number",
            "label"  : "CUPS Port",
            "default": "631",
            "help"   : "CUPS server port (default: 631).",
        },
        "printer_name": {
            "type"       : "text",
            "label"      : "Printer Name",
            "default"    : "Receipt_Printer",
            "placeholder": "Receipt_Printer",
            "help"       : "Name of the printer queue in CUPS.",
        },
        "cups_backend": {
            "type"   : "select",
            "label"  : "Backend",
            "default": "auto",
            "options": [
                ("auto",   "Auto — pycups if installed, otherwise IPP"),
                ("ipp",    "IPP only"),
                ("pycups", "pycups only"),
            ],
            "help": "Printing backend.  Auto selects pycups when available.",
        },
    },
}
