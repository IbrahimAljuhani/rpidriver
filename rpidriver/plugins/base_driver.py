"""
Base driver classes for RPiDriver plugins.

AbstractDriver  — synchronous base class every plugin inherits from.
ThreadDriver    — adds a background worker thread for hardware polling.
"""

import logging
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AbstractDriver(ABC):
    """Minimal interface every driver must implement."""

    #: Short identifier shown in the dashboard
    name: str = "abstract"

    #: Maximum number of messages kept in the status dict (prevents unbounded growth).
    MAX_MESSAGES = 10

    def __init__(self, config=None):
        self.config = config or {}
        self._status = {"status": "disconnected", "messages": []}

    # ── Public API ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a status dict copy (messages list is not shared with internal state)."""
        return {**self._status, "messages": list(self._status["messages"])}

    def set_status(self, status: str, message: str = ""):
        """Update internal status, capping the messages list at MAX_MESSAGES.

        Transitioning to "connected" clears the message history so stale
        error messages are not shown after a successful reconnect.
        """
        self._status["status"] = status
        if status == "connected":
            self._status["messages"].clear()
        elif message:
            msgs = self._status.setdefault("messages", [])
            msgs.append(message)
            if len(msgs) > self.MAX_MESSAGES:
                del msgs[: len(msgs) - self.MAX_MESSAGES]
        logger.debug("[%s] status=%s  msg=%s", self.name, status, message)

    @abstractmethod
    def get_device(self):
        """Return the underlying hardware device handle, or None."""

    # ── Optional lifecycle hooks (called by plugin loader on teardown) ────

    def open(self):
        """Open/connect to the hardware device."""

    def close(self):
        """Close/disconnect from the hardware device."""


class ThreadDriver(AbstractDriver):
    """
    Driver that runs a continuous polling loop in a daemon thread.

    Subclasses override :meth:`run` with their hardware polling logic.
    :meth:`start` is called automatically by the plugin loader.
    """

    #: Seconds between poll iterations
    poll_interval: float = 0.2

    def __init__(self, config=None):
        super().__init__(config)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── Thread control ────────────────────────────────────────────────────

    def start(self):
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"rpidriver-{self.name}", daemon=True
        )
        self._thread.start()
        logger.info("[%s] background thread started.", self.name)

    def stop(self):
        """Signal the background thread to stop, wait for it, then close the device."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("[%s] thread did not stop within 5s.", self.name)
        self.close()
        logger.info("[%s] background thread stopped.", self.name)

    # ── Internal loop ─────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.run()
            except Exception as exc:
                logger.exception("[%s] error in run loop: %s", self.name, exc)
                self.set_status("error", str(exc))
            self._stop_event.wait(self.poll_interval)

    @abstractmethod
    def run(self):
        """Called repeatedly by the background thread."""

    def get_device(self):
        return None
