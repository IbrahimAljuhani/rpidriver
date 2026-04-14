"""
NeoLeap Mada Payment Terminal Driver.

Communicates with a NeoLeap Mada terminal (e.g. N950) over WebSocket.
Implements the PaymentTerminalDriver interface so all three hw_proxy payment
endpoints work out of the box:

  POST /hw_proxy/payment_terminal_transaction_start   → transaction_start()
  POST /hw_proxy/payment_terminal_transaction_status  → transaction_status()
  POST /hw_proxy/payment_terminal_transaction_cancel  → cancel()

NeoLeap WebSocket protocol (confirmed from production device + pos_neoleap)
---------------------------------------------------------------------------
Client → Terminal:
  {"Command": "CHECK_STATUS"}
  {"Command": "SALE", "Amount": "12.50", "AdditionalData": "POS-00042"}
  {"Command": "CANCEL"}

  Note: TerminalID is NOT sent in the SALE command — the terminal knows its
  own ID and ignores (or rejects) the field if provided.

Terminal → Client (two possible formats):

  Format A — JSON (simulator / some firmware versions):
    {"EventName": "TERMINAL_STATUS",   "TerminalStatus": "READY" | "BUSY"}
    {"EventName": "TERMINAL_RESPONSE", "JsonResult": {
        "StatusCode":          "00",        ← "00"=approved "01"=declined "11"=cancelled
        "ECRReferenceNumber":  "00000001",
        "TransactionAuthCode": "175800",
    }}

  Format B — Hybrid JSON+XML (N950 production firmware v1.2.5x):
    {"API_Status":"0", "EventName":"TERMINAL_RESPONSE", <?xml ...>
      <madaTransactionResult>
        <Result English="APPROVED"/>         ← or "DECLINED"
        <ApprovalCode>175800</ApprovalCode>
        <RRN>329705000047</RRN>
        <ResponseCode>000</ResponseCode>     ← "000"=approved
        <TerminalID>8136012001194761</TerminalID>
      </madaTransactionResult>}

  Format B is not valid JSON. The driver detects it and parses the XML part.

Config keys (under [neoleap_driver] in config.ini):
  neoleap_ip  — IP address of the NeoLeap terminal  (required)
  terminal_id — Terminal ID: 8-digit bank TID (Al Rajhi, SNB …)
                OR 16-digit device TID shown on the terminal screen  (required)
  port        — WebSocket port (default: 9998 for N950 over WiFi)
  timeout     — transaction timeout in seconds (default: 90)

Registered in drivers{} as "neoleap_driver".
Requires: pip install websocket-client
"""

import ipaddress
import json
import logging
import re
import threading

from rpidriver.plugins.payment_base_driver import PaymentTerminalDriver

logger = logging.getLogger(__name__)

# ── Dependency guard ──────────────────────────────────────────────────────────

try:
    import websocket  # websocket-client
    _HAS_WEBSOCKET = True
except ImportError:
    websocket = None  # type: ignore[assignment]
    _HAS_WEBSOCKET = False
    logger.warning(
        "NeoLeapDriver: 'websocket-client' is not installed. "
        "Run: pip install websocket-client"
    )

# ── NeoLeap status codes ──────────────────────────────────────────────────────

_STATUS_APPROVED  = "00"
_STATUS_DECLINED  = "01"
_STATUS_CANCELLED = "11"

# Human-readable labels for all known NeoLeap StatusCodes
_STATUS_MESSAGES = {
    "00": "Payment approved",
    "01": "Transaction declined by bank",
    "05": "Do not honour — contact bank",
    "11": "Transaction cancelled",
    "12": "Invalid transaction",
    "14": "Invalid card number",
    "41": "Card reported lost",
    "43": "Card reported stolen",
    "51": "Insufficient funds",
    "54": "Expired card",
    "55": "Incorrect PIN",
    "57": "Transaction not permitted for card",
    "61": "Exceeds withdrawal limit",
    "65": "Exceeds transaction frequency limit",
    "91": "Issuer unavailable",
    "96": "System error — retry",
}

# ── Driver ────────────────────────────────────────────────────────────────────


class NeoLeapDriver(PaymentTerminalDriver):
    """
    Payment terminal driver for NeoLeap Mada devices.

    Transaction state machine
    ─────────────────────────
      idle ──→ waiting ──→ accepted
                       ├──→ cancelled
                       └──→ error

    State is reset to "idle" automatically after _STATE_TTL seconds (default 30)
    once a terminal state is reached, so a fresh transaction can be started
    without a driver restart. Configure via state_ttl in [neoleap_driver].
    """

    name = "neoleap_driver"

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}

        self._neoleap_ip  = cfg.get("neoleap_ip",  "").strip()
        self._terminal_id = cfg.get("terminal_id", "").strip()
        self._port        = int(cfg.get("port",    9998))
        self._timeout     = max(5, min(600, int(cfg.get("timeout", 90))))

        # Seconds before an uncollected final state is auto-reset to "idle".
        # Configurable via state_ttl in [neoleap_driver] config section.
        self._STATE_TTL   = int(cfg.get("state_ttl", 30))

        # Active WebSocket handle (for cancel)
        self._ws: object | None = None

        # ── Transaction state ─────────────────────────────────────────────
        self._tx_lock   = threading.Lock()
        self._tx_event  = threading.Event()
        self._tx_state  = "idle"   # idle | waiting | accepted | cancelled | error
        self._tx_result: dict = {}
        self._reset_timer: threading.Timer | None = None

        # ── Validate required config ──────────────────────────────────────
        errors = []

        if not self._neoleap_ip:
            errors.append("neoleap_ip is required")
        else:
            try:
                ipaddress.ip_address(self._neoleap_ip)
            except ValueError:
                errors.append(
                    f"neoleap_ip {self._neoleap_ip!r} is not a valid IP address"
                )

        # terminal_id is optional — the terminal knows its own ID and does not
        # require it in the SALE command.  We only validate the format if provided.
        if self._terminal_id and (
            not self._terminal_id.isdigit() or len(self._terminal_id) not in (8, 16)
        ):
            errors.append(
                f"terminal_id {self._terminal_id!r} must be 8 digits (bank TID) "
                f"or 16 digits (device TID shown on terminal screen)"
            )

        if errors:
            msg = "; ".join(errors)
            self.set_status("disconnected", msg)
            logger.warning("NeoLeapDriver: %s", msg)
        elif not _HAS_WEBSOCKET:
            self.set_status("disconnected", "websocket-client not installed")
        else:
            # Start a background connectivity check so app startup isn't blocked.
            # Status will update to "connected" or "disconnected" within ~3 s.
            self.set_status("disconnected", "Checking terminal connectivity…")
            logger.info(
                "NeoLeapDriver: config OK — IP=%s  TID=%s  port=%d  timeout=%ds",
                self._neoleap_ip, self._terminal_id, self._port, self._timeout,
            )
            threading.Thread(
                target=self._startup_check,
                daemon=True,
                name="neoleap-startup",
            ).start()

    def get_device(self):
        return self._ws

    # ── Startup connectivity check ────────────────────────────────────────────

    def _startup_check(self):
        """
        Background thread: attempt a TCP connection to the terminal to verify
        it is reachable before the first payment request.  Updates driver status
        so the dashboard shows the real connection state immediately on startup.
        """
        import socket as _sock
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(5)
            s.connect((self._neoleap_ip, self._port))
            s.close()
            self.set_status("connected")
            logger.info(
                "NeoLeapDriver: terminal reachable at %s:%d",
                self._neoleap_ip, self._port,
            )
        except OSError as exc:
            self.set_status(
                "disconnected",
                f"Terminal at {self._neoleap_ip}:{self._port} not reachable ({exc})",
            )
            logger.warning(
                "NeoLeapDriver: terminal not reachable at %s:%d — %s. "
                "Check neoleap_ip and port in config.ini.",
                self._neoleap_ip, self._port, exc,
            )

    # ── PaymentTerminalDriver interface ───────────────────────────────────────

    def transaction_start(self, params: dict) -> dict:
        """
        Start a payment transaction (non-blocking).

        The actual WebSocket communication runs in a daemon thread.
        The caller should poll transaction_status() until a final state
        (accepted / cancelled / error) is received.

        Params accepted:
          amount      — float or str (e.g. 12.50)
          neoleap_ip  — optional override for the driver's configured IP
          terminal_id — optional override for the driver's configured TID
          order_id    — POS order reference (sent as AdditionalData)
        """
        if not _HAS_WEBSOCKET:
            return {"status": "error", "message": "websocket-client not installed"}

        with self._tx_lock:
            if self._tx_state == "waiting":
                return {"status": "error", "message": "Transaction already in progress"}

            self._tx_state = "waiting"
            self._tx_result = {}
            self._tx_event.clear()

            # Cancel any pending reset timer
            if self._reset_timer:
                self._reset_timer.cancel()
                self._reset_timer = None

        # Resolve effective IP and TID (params override config)
        neoleap_ip  = str(params.get("neoleap_ip",  self._neoleap_ip) ).strip()
        terminal_id = str(params.get("terminal_id", self._terminal_id)).strip()
        order_id    = str(params.get("order_id", ""))

        # Normalise amount to 2 decimal places
        try:
            amount = f"{float(params.get('amount', 0)):.2f}"
        except (TypeError, ValueError):
            amount = str(params.get("amount", "0.00"))

        threading.Thread(
            target=self._run_payment,
            args=(amount, order_id, neoleap_ip, terminal_id),
            daemon=True,
            name="neoleap-payment",
        ).start()

        logger.info(
            "NeoLeapDriver: transaction started — amount=%s  TID=%s  order=%s",
            amount, terminal_id, order_id,
        )
        return {"status": "waiting", "message": "Transaction started — waiting for card"}

    def transaction_status(self) -> dict:
        """
        Return the current transaction state.

        Called repeatedly by odoo8.py after transaction_start().
        Once a final state is returned, the state is scheduled to reset to
        "idle" after _STATE_TTL seconds (so the next transaction can start).
        """
        with self._tx_lock:
            state  = self._tx_state
            result = dict(self._tx_result)

        if state == "waiting":
            return {"status": "waiting", "message": "Waiting for card..."}

        if state == "idle":
            return {"status": "idle", "message": "No active transaction"}

        # Final state (accepted / cancelled / error) — schedule reset
        self._schedule_reset()
        return {"status": state, **result}

    def cancel(self) -> dict:
        """
        Cancel the active transaction by sending CANCEL over WebSocket.

        Guard: if the transaction has already reached a final state (accepted /
        error) we do NOT overwrite it — the POS may call cancel() as a
        cleanup step after reading the result, and we must not corrupt the
        already-committed outcome.
        """
        with self._tx_lock:
            current = self._tx_state

        # Never overwrite a terminal state — the CANCEL command would be meaningless
        # and could confuse the terminal if it has already closed the transaction.
        if current == "accepted":
            logger.info(
                "NeoLeapDriver: cancel() ignored — transaction already accepted."
            )
            return {"status": "accepted", "message": "Transaction already accepted"}

        if current == "error":
            logger.info(
                "NeoLeapDriver: cancel() ignored — transaction already ended in error."
            )
            return {"status": "error", "message": "Transaction already ended in error"}

        if current == "cancelled":
            logger.info(
                "NeoLeapDriver: cancel() ignored — transaction already cancelled."
            )
            return {"status": "cancelled", "message": "Transaction already cancelled"}

        if current == "idle":
            return {"status": "idle", "message": "No active transaction to cancel"}

        neoleap_ip = self._neoleap_ip

        if _HAS_WEBSOCKET and neoleap_ip:
            try:
                url = f"ws://{neoleap_ip}:{self._port}"
                ws  = websocket.create_connection(url, timeout=10)
                try:
                    ws.send(json.dumps({"Command": "CANCEL"}))
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass
                logger.info("NeoLeapDriver: CANCEL sent to %s", url)
            except Exception as exc:
                logger.warning("NeoLeapDriver: cancel command failed: %s", exc)

        with self._tx_lock:
            # Re-check state inside the lock — payment may have completed
            # between the first check above and now
            if self._tx_state == "accepted":
                logger.info(
                    "NeoLeapDriver: cancel() ignored after lock — state became accepted."
                )
                return {"status": "accepted", "message": "Transaction already accepted"}
            self._tx_state  = "cancelled"
            self._tx_result = {"message": "Cancelled by operator"}
            self._tx_event.set()

        return {"status": "cancelled", "message": "Transaction cancelled"}

    # ── WebSocket payment flow ────────────────────────────────────────────────

    def _run_payment(self, amount: str, order_id: str, neoleap_ip: str, terminal_id: str):
        """
        Open a WebSocket connection to NeoLeap and execute the payment flow:
          1. Connect
          2. Send CHECK_STATUS
          3. On TERMINAL_STATUS=READY → send SALE
          4. On TERMINAL_RESPONSE   → parse result
        """
        url   = f"ws://{neoleap_ip}:{self._port}"
        event = threading.Event()
        final: dict = {}

        def on_open(ws):
            self._ws = ws
            logger.info("NeoLeapDriver: connected to %s — sending CHECK_STATUS", url)
            ws.send(json.dumps({"Command": "CHECK_STATUS"}))

        def on_message(ws, message):
            nonlocal final
            logger.debug("NeoLeapDriver ← %s", message)
            # Guard against empty/whitespace-only messages (e.g. WebSocket keep-alives)
            if not message or not message.strip():
                logger.debug("NeoLeapDriver: received empty message, ignoring.")
                return

            # ── Format B detection ────────────────────────────────────────────
            # Real N950 firmware sends a hybrid JSON+XML string that is NOT
            # valid JSON.  Detect it before trying json.loads().
            if '"TERMINAL_RESPONSE"' in message and '<madaTransactionResult>' in message:
                logger.info("NeoLeapDriver: received XML response (Format B — N950 production)")
                final = self._parse_xml_response(message)
                try:
                    ws.close()
                except Exception:
                    pass
                finally:
                    event.set()
                return

            # ── Format A — proper JSON ────────────────────────────────────────
            try:
                data = json.loads(message)
            except json.JSONDecodeError as exc:
                logger.error("NeoLeapDriver: unrecognised message format: %s", exc)
                logger.debug("NeoLeapDriver: raw message was: %s", message[:500])
                final = _err(f"Unrecognised terminal response: {exc}")
                try:
                    ws.close()
                except Exception:
                    pass
                finally:
                    event.set()
                return

            event_name = data.get("EventName", "")

            if event_name == "TERMINAL_STATUS":
                terminal_status = data.get("TerminalStatus", "")
                if terminal_status == "READY":
                    # TerminalID is NOT included — the N950 knows its own ID
                    # and the pos_neoleap reference implementation omits it.
                    cmd = {
                        "Command"       : "SALE",
                        "Amount"        : amount,
                        "AdditionalData": order_id,
                    }
                    logger.info(
                        "NeoLeapDriver: terminal READY — sending SALE amount=%s order=%s",
                        amount, order_id,
                    )
                    ws.send(json.dumps(cmd))
                else:
                    final = _err(f"Terminal not ready (status: {terminal_status}). Please try again.")
                    try:
                        ws.close()
                    except Exception:
                        pass
                    finally:
                        event.set()

            elif event_name == "TERMINAL_RESPONSE":
                final = self._parse_json_response(data)
                try:
                    ws.close()
                except Exception:
                    pass
                finally:
                    event.set()

            else:
                logger.debug("NeoLeapDriver: ignored event %r", event_name)

        def on_error(ws, error):
            nonlocal final
            logger.error("NeoLeapDriver: WebSocket error: %s", error)
            final = _err(f"Connection error: {error}")
            event.set()

        def on_close(ws, code, msg):
            logger.info("NeoLeapDriver: WebSocket closed (code=%s msg=%s)", code, msg)
            event.set()

        try:
            ws_app = websocket.WebSocketApp(
                url,
                on_open    = on_open,
                on_message = on_message,
                on_error   = on_error,
                on_close   = on_close,
                # Some NeoLeap firmware versions require an Origin header that
                # resembles a browser request (same behaviour as the POS browser).
                header     = {"Origin": "http://localhost:8069"},
            )
            t = threading.Thread(target=ws_app.run_forever, daemon=True, name="neoleap-ws")
            t.start()

            timed_out = not event.wait(timeout=self._timeout)

            if timed_out:
                ws_app.close()
                # Wait for the WebSocket thread to finish so we don't leave
                # zombie threads accumulating on repeated timeouts.
                t.join(timeout=5)
                if t.is_alive():
                    logger.warning(
                        "NeoLeapDriver: WebSocket thread did not exit within 5 s after close."
                    )
                final = _err(f"Terminal did not respond within {self._timeout} seconds.")
                logger.warning("NeoLeapDriver: transaction timed out.")

        except Exception as exc:
            logger.exception("NeoLeapDriver: unexpected error in _run_payment")
            final = _err(str(exc))
        finally:
            self._ws = None

        # Commit final state
        state = final.get("state", "error")
        with self._tx_lock:
            self._tx_state  = state
            self._tx_result = {k: v for k, v in final.items() if k != "state"}
            self._tx_event.set()

        logger.info("NeoLeapDriver: transaction finished — state=%s", state)

    # ── Response parser ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_response(data: dict) -> dict:
        """
        Parse a Format A (JSON) TERMINAL_RESPONSE from NeoLeap.

        Expected structure:
          {"EventName": "TERMINAL_RESPONSE", "JsonResult": {
              "StatusCode":          "00",
              "ECRReferenceNumber":  "00000001",
              "TransactionAuthCode": "175800",
              "CardType":            "MADA",
              "TerminalID":          "8136012001194761",
          }}
        """
        jr          = data.get("JsonResult") or {}
        status_code = str(jr.get("StatusCode", "")).strip()
        label       = _STATUS_MESSAGES.get(status_code, f"StatusCode {status_code}")

        if status_code == _STATUS_APPROVED:
            return {
                "state"        : "accepted",
                "transactionId": jr.get("ECRReferenceNumber", ""),
                "authCode"     : jr.get("TransactionAuthCode", ""),
                "cardType"     : jr.get("CardType", ""),
                "terminalId"   : jr.get("TerminalID", ""),
                "statusCode"   : status_code,
                "message"      : label,
            }

        if status_code == _STATUS_CANCELLED:
            return {
                "state"     : "cancelled",
                "statusCode": status_code,
                "message"   : label,
            }

        # Everything else (declined, error codes, unknown) → error state
        return {
            "state"     : "error",
            "statusCode": status_code,
            "message"   : label,
        }

    @staticmethod
    def _parse_xml_response(message: str) -> dict:
        """
        Parse a Format B (hybrid JSON+XML) TERMINAL_RESPONSE from the N950.

        The real N950 firmware (v1.2.5x) sends a string that is NOT valid JSON:
          {"API_Status":"0", "EventName":"TERMINAL_RESPONSE", <?xml ...>
            <madaTransactionResult>
              <Result English="APPROVED"/>
              <ApprovalCode>175800</ApprovalCode>
              <RRN>329705000047</RRN>
              <ResponseCode>000</ResponseCode>
              <TerminalID>8136012001194761</TerminalID>
            </madaTransactionResult>}

        StatusCode convention in XML: "000" = approved (3 digits, unlike JSON "00").
        We normalise the result to the same dict shape as _parse_json_response().
        """
        def _find(pattern, default=""):
            m = re.search(pattern, message, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else default

        # Primary approval signal: <Result English="APPROVED" /> or "DECLINED"
        result_english = _find(r'<Result[^>]+English="([^"]+)"')

        # Numeric response code: "000" = approved in XML format
        response_code  = _find(r'<ResponseCode[^>]*>([^<]+)</ResponseCode>')

        approval_code  = _find(r'<ApprovalCode[^>]*>([^<]+)</ApprovalCode>')
        rrn            = _find(r'<RRN[^>]*>([^<]+)</RRN>')
        terminal_id    = _find(r'<TerminalID[^>]*>([^<]+)</TerminalID>')
        card_type      = _find(r'<CardType[^>]*>([^<]+)</CardType>')

        approved = (
            result_english.upper() == "APPROVED"
            or response_code == "000"
        )

        if approved:
            return {
                "state"        : "accepted",
                "transactionId": rrn,           # RRN is the transaction reference
                "authCode"     : approval_code,
                "cardType"     : card_type,
                "terminalId"   : terminal_id,
                "statusCode"   : response_code,
                "message"      : "Payment approved",
            }

        # Declined or other non-approved result
        label = result_english.capitalize() if result_english else f"ResponseCode {response_code}"
        return {
            "state"     : "error",
            "statusCode": response_code,
            "message"   : label or "Transaction declined",
        }

    # ── State TTL reset ───────────────────────────────────────────────────────

    def _schedule_reset(self):
        """
        Schedule automatic reset to "idle" after _STATE_TTL seconds.

        Called once when the POS first reads a final state.  Subsequent calls
        while the timer is already running are no-ops.
        """
        with self._tx_lock:
            if self._reset_timer is not None:
                return          # already scheduled
            if self._tx_state not in ("accepted", "cancelled", "error"):
                return          # not in a final state

            timer = threading.Timer(self._STATE_TTL, self._reset_to_idle)
            timer.daemon = True
            timer.start()
            self._reset_timer = timer

    def _reset_to_idle(self):
        with self._tx_lock:
            self._tx_state  = "idle"
            self._tx_result = {}
            self._reset_timer = None
        logger.debug("NeoLeapDriver: state reset to idle.")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _err(message: str) -> dict:
    """Shorthand for building an error state dict."""
    return {"state": "error", "message": message}


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = NeoLeapDriver
