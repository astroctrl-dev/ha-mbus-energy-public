"""Ephemeral discovery-test reservation state; no serial I/O or persistent settings.

Caller must serialize admission with competing jobs, drain under the shared
bus lease, and establish the durable timing guard before calling drained().
A backend worker (not a browser request) must advance/expire the reservation.
"""
import math
import threading
import time
import uuid


class SearchTestReservation:
    def __init__(self, monotonic=time.monotonic, idle_seconds=180):
        self._clock = monotonic
        self._idle_seconds = idle_seconds
        self._lock = threading.RLock()
        self._phase = "off"
        self._token = None
        self._deadline = None
        self._context = None
        self._reason = None

    def busy(self):
        with self._lock:
            return self._phase != "off"

    def snapshot(self):
        with self._lock:
            remaining = None if self._deadline is None else math.ceil(max(0, self._deadline-self._clock()))
            return dict(phase=self._phase, active=self._phase in ("draining", "waiting", "ready", "scanning"),
                        remaining=remaining, reason=self._reason, reservation_id=self._token)

    def reserve(self, context):
        with self._lock:
            if self._phase != "off":
                raise ValueError("test reservation already active")
            self._token = uuid.uuid4().hex
            self._context = dict(context)
            self._phase = "draining"
            self._deadline = self._clock()+180
            self._reason = None
            return self._token

    def _require(self, token, *phases):
        if token is None or token != self._token or self._phase not in phases:
            raise ValueError("stale or invalid test reservation")

    def drained(self, token, guard_deadline):
        """Called only after the in-flight exchange and durable guard."""
        with self._lock:
            self._require(token, "draining")
            self._phase = "waiting"
            self._deadline = max(self._clock()+60, guard_deadline)
            self._prepare_expiry = self._deadline+180

    def advance(self, token, *, guard_ready, context):
        """Backend worker tick. Return True if cleanup must be performed."""
        with self._lock:
            self._require(token, "draining", "waiting", "ready", "scanning", "cleanup")
            if self._phase == "cleanup":
                return True
            if dict(context) != self._context:
                self.cancel(token, "registry_changed")
                return True
            now = self._clock()
            if self._phase == "draining" and now >= self._deadline:
                self.cancel(token, "drain_timeout")
                return True
            if self._phase == "waiting" and now >= self._prepare_expiry:
                self.cancel(token, "guard_timeout")
                return True
            if self._phase == "waiting" and now >= self._deadline and guard_ready:
                self._phase = "ready"
                self._deadline = now+self._idle_seconds
            elif self._phase == "ready":
                if now >= self._deadline or not guard_ready:
                    self.cancel(token, "expired" if now >= self._deadline else "guard_changed")
                    return True
            return False

    def start(self, token, context, *, guard_ready):
        with self._lock:
            self._require(token, "ready")
            if self._clock() >= self._deadline or not guard_ready or dict(context) != self._context:
                self.cancel(token, "start_rejected")
                raise ValueError("test reservation no longer ready")
            self._phase = "scanning"
            self._deadline = None

    def cancel(self, token, reason="cancelled"):
        """Retain exclusivity until caller drains and establishes exit guard."""
        with self._lock:
            self._require(token, "draining", "waiting", "ready", "scanning", "cleanup")
            if self._phase != "cleanup":
                self._phase = "cleanup"
                self._deadline = None
                self._reason = reason

    def fail(self, token, reason):
        """Visible fail-closed terminal state; controlled restart required."""
        with self._lock:
            self._require(token, "draining", "waiting", "ready", "scanning", "cleanup", "cooldown")
            self._phase = "failed"
            self._deadline = None
            self._reason = reason

    def guarded_exit(self, token, guard_deadline):
        """Only after all scan I/O stopped and durable exit guard established."""
        with self._lock:
            self._require(token, "cleanup")
            self._phase = "cooldown"
            self._deadline = max(self._clock()+60, guard_deadline)

    def release_if_safe(self, token, *, guard_ready):
        with self._lock:
            self._require(token, "cooldown")
            if not guard_ready or self._clock() < self._deadline:
                return False
            self._phase = "off"
            self._deadline = self._context = self._token = None
            return True
