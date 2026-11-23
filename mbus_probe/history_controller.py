"""Explicit, gated frame-3 collection. Never called by polling or download."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from analysis_export import _alias
from history_model import build_snapshot, save_snapshot
from monthly_diagnostic import RestorationError, run as read_months

LOG = logging.getLogger("mbus.history")


def history_file(root, meter_id):
    root = Path(root)
    alias = _alias(meter_id, root / "alias.key")
    return root / "history" / (alias + ".json")


def load_history(root, selected):
    """Only snapshots for currently selected meters enter the workbook."""
    result = []
    for row in selected:
        path = history_file(root, row["meter_id"])
        if not path.exists():
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if len(snapshot.get("stands", ())) != 24 or len(snapshot.get("bounded_periods", ())) != 23:
            raise ValueError("invalid saved monthly history")
        result.append((path.stem, snapshot))
    return result


class HistoryController:
    def __init__(self, registry, config, bus_lock, stop, root="/data/analysis",
                 reader=read_months, pause=time.sleep):
        self.registry, self.config, self.bus_lock, self.stop = registry, config, bus_lock, stop
        self.root, self.reader, self.pause = Path(root), reader, pause
        self.lock = threading.Lock()
        self.marker = self.root / "normal_frame_unverified"
        self.blocked = threading.Event()
        if self.marker.exists():
            self.blocked.set()
        self.state = {"status": "restore_unverified" if self.blocked.is_set() else "not_started",
                      "error": "Normalramme ikke verifisert; polling stoppet" if self.blocked.is_set() else None,
                      "captured_at_utc": None}
        self.worker = None

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, meter_id):
        if self.config.get("allow_monthly_history") is not True:
            raise ValueError("Aktiver månedshistorikk i appens Configuration først")
        if self.stop.is_set() or self.blocked.is_set():
            raise ValueError("app is stopping or normal frame is unverified")
        with self.registry.lock:
            address = self.registry.selected.get(meter_id)
            if address is None:
                raise ValueError("select a meter before history collection")
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("monthly history is already running")
            self.state = {"status": "running", "error": None, "captured_at_utc": None}
            self.worker = threading.Thread(target=self._collect, args=(meter_id, address), daemon=True)
            self.worker.start()

    def _collect(self, meter_id, address):
        try:
            with self.bus_lock:
                with self.registry.lock:
                    if self.registry.selected.get(meter_id) != address or self.stop.is_set():
                        raise ValueError("selected meter changed or app is stopping")
                # A normal poll or scan may have finished immediately before the lock.
                self.pause(61)
                # Marker survives process crash. Clear only after verified restore.
                self.root.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.close(fd)
                months = self.reader(self.config["serial_port"], int(self.config.get("baud", 2400)),
                                     address, meter_id)
                # The reader returns only after a checksum/identity-verified normal frame.
                self.marker.unlink()
                snapshot = build_snapshot(months, datetime.now(timezone.utc).isoformat())
                path = history_file(self.root, meter_id)
                save_snapshot(path, snapshot)
                with self.lock:
                    self.state = {"status": "complete", "error": None,
                                  "captured_at_utc": snapshot["captured_at_utc"]}
        except Exception as exc:
            # No ID, raw telegram, serial path or exception details in UI/logs.
            uncertain = isinstance(exc, RestorationError) or self.marker.exists()
            if uncertain:
                # A reader exception before verified return is also an unknown frame state.
                self.blocked.set()  # Persistent marker forbids further ordinary polling.
            LOG.error("Monthly history failed: %s%s", type(exc).__name__,
                      "; normal frame unverified, polling stopped" if uncertain else "")
            with self.lock:
                self.state = {"status": "restore_unverified" if uncertain else "failed",
                              "error": "Normalramme ikke verifisert; polling stoppet" if uncertain
                                       else "Historikkavlesning feilet; tidligere data beholdt",
                              "captured_at_utc": None}
