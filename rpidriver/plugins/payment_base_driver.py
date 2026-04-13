"""
Base class for payment terminal drivers.

Provides a common interface for all payment terminal integrations
(Telium / Ingenico, Adyen, etc.).  Concrete drivers inherit from
PaymentTerminalDriver and implement the abstract methods.

This module intentionally contains no hardware-specific code — it is a
contract that future drivers must fulfil so that odoo8.py can interact
with any terminal through a single, stable API.

Registered drivers should use the key "payment_driver" in the drivers dict.

Example future drivers:
  - TeliumDriver    — Ingenico/Verifone serial terminals (pypostelium)
  - AdyenDriver     — Adyen cloud terminal API
"""

import logging
from abc import abstractmethod

from rpidriver.plugins.base_driver import AbstractDriver

logger = logging.getLogger(__name__)


class PaymentTerminalDriver(AbstractDriver):
    """
    Abstract base class for payment terminal drivers.

    Subclasses must implement:
      - transaction_start(params)  — initiate a payment transaction
      - transaction_status()       — poll the current transaction state
      - cancel()                   — abort the current transaction

    Optional overrides:
      - print_receipt(receipt)     — print the payment receipt on the terminal
      - get_payment_info()         — return terminal hardware / firmware info
    """

    name = "payment_driver"

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def transaction_start(self, params: dict) -> dict:
        """
        Initiate a payment transaction.

        Parameters (from Odoo POS hw_proxy payment_terminal_transaction_start):
            params["amount"]        — amount in smallest currency unit (e.g. fils/halalas)
            params["currency_id"]   — ISO 4217 numeric currency code
            params["payment_mode"]  — "debit" | "credit"

        Returns a dict:
            {"status": "waiting" | "accepted" | "error", "message": str}
        """

    @abstractmethod
    def transaction_status(self) -> dict:
        """
        Return the current state of the active transaction.

        Returns a dict:
            {
                "status":   "waiting" | "accepted" | "cancelled" | "error",
                "message":  str,
                "ticket":   str | None,   # text receipt from terminal (if available)
            }
        """

    @abstractmethod
    def cancel(self) -> dict:
        """
        Cancel / abort the current transaction.

        Returns {"status": "cancelled" | "error", "message": str}
        """

    # ── Optional overrides ────────────────────────────────────────────────

    def print_receipt(self, receipt: str) -> None:
        """
        Print a payment receipt on the terminal display / printer.
        Default: log and ignore (terminal may print automatically).
        """
        logger.debug("[%s] print_receipt called (not implemented).", self.name)

    def get_payment_info(self) -> dict:
        """Return terminal hardware / firmware information."""
        return {"name": self.name, "status": self.get_status()}

    # ── AbstractDriver ────────────────────────────────────────────────────

    def get_device(self):
        """Return the underlying device handle, or None."""
        return None
