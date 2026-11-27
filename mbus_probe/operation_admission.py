"""Serialize admission of long bus operations, not their serial I/O.

Admission callbacks must publish their busy state before returning. All callers
(manual and automatic) must use the same instance. Polling retains the bus lock.
"""
import threading
from contextlib import contextmanager


class OperationAdmission:
    def __init__(self):
        self._lock = threading.RLock()
        self._checks = {}

    def register(self, name, busy):
        with self._lock:
            if name in self._checks:
                raise ValueError("duplicate operation")
            self._checks[name] = busy

    @contextmanager
    def start(self, name, *, worker=False):
        if worker and name not in ('address_diagnostic','diagnostic_recover'):
            raise ValueError('invalid worker admission')
        # Only an already reserved diagnostic worker waits for the POST handoff.
        acquired = self._lock.acquire(timeout=5) if worker else self._lock.acquire(blocking=False)
        if not acquired:
            raise ValueError("another operation is starting")
        try:
            for other, busy in self._checks.items():
                if name in ("address_recover", "address_quarantine", "diagnostic_recover") and other == "address_safety":
                    continue
                if name == "diagnostic_recover" and other == "address_diagnostic":
                    continue
                if other != name and busy():
                    raise ValueError("operation busy: " + other)
            yield
        finally:
            self._lock.release()
