"""Opt-in, bounded, local transport evidence. Never sends meter commands."""
import json
import os
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

_context = threading.local()
_active = None

def operation(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            old = getattr(_context, "operation", None)
            if old is None:
                _context.operation = name
            try:
                return fn(*args, **kwargs)
            finally:
                _context.operation = old
        return wrapped
    return decorate

def install(logger):
    global _active
    _active = logger

def capture(direction, frame, status=None):
    """Called only after actual I/O; no disk I/O in the bus thread."""
    try:
        logger = _active
        if logger is None or not logger.enabled:
            return
        if direction == "TX":
            _context.transaction = uuid.uuid4().hex
        if status is None:
            status = classify(frame)
        logger.offer({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                      "transaction_id": getattr(_context, "transaction", None),
                      "operation": getattr(_context, "operation", None) or "read",
                      "direction": direction, "status": status,
                      "hex": bytes(frame).hex(" ")})
    except Exception:
        # Diagnostics must never interfere with bus operations.
        pass

def classify(frame):
    if not frame:
        return "timeout"
    if frame == b"\xe5":
        return "ack"
    if frame[0] == 0x10 and len(frame) == 5:
        return "valid_short" if frame[-1] == 0x16 and sum(frame[1:3]) & 255 == frame[3] else "invalid"
    if frame[0] == 0x68 and len(frame) >= 9:
        if frame[1] == frame[2] and frame[3] == 0x68 and len(frame) == frame[1] + 6:
            return "valid_frame" if frame[-1] == 0x16 and sum(frame[4:-2]) & 255 == frame[-2] else "invalid"
    return "invalid_or_partial"

def receive(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception:
            capture("RX", b"", "read_error")
            raise
        frame = result[1] if isinstance(result, tuple) else result
        capture("RX", frame)
        return result
    return wrapped

class RawLog:
    """Two 5 MiB files, bounded queue; disk failures isolated from polling."""
    def __init__(self, root="/data/analysis/raw", max_file=5*1024*1024):
        self.root = Path(root)
        self.max_file = max_file
        self.enabled = False  # Explicit opt-in each app start.
        self.lock = threading.Lock()
        self.pending = queue.Queue(maxsize=256)
        self.dropped = 0
        self.rotations = 0
        self.error = False
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        self.enabled = enabled

    def offer(self, event):
        if not self.enabled:
            return
        try:
            self.pending.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def _append(self, event):
        data = (json.dumps(event, separators=(",", ":")) + "\n").encode()
        if len(data) > self.max_file:
            self.dropped += 1
            return
        with self.lock:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
            path = self.root / "current.jsonl"
            old = self.root / "previous.jsonl"
            if path.exists() and path.stat().st_size + len(data) > self.max_file:
                os.replace(path, old)
                self.rotations += 1
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "ab") as out:
                out.write(data)
            self.error = False

    def _run(self):
        while True:
            event = self.pending.get()
            try:
                self._append(event)
            except Exception:
                self.error = True
                self.dropped += 1
            finally:
                self.pending.task_done()

    def snapshot(self):
        with self.lock:
            chunks = []
            for name in ("previous.jsonl", "current.jsonl"):
                path = self.root / name
                if path.exists():
                    with path.open("rb") as inp:
                        chunks.append(inp.read(self.max_file))
            return b"".join(chunks)

    def status(self):
        return {"enabled": self.enabled, "queued": self.pending.unfinished_tasks,
                "dropped": self.dropped, "rotations": self.rotations,
                "storage_error": self.error}
