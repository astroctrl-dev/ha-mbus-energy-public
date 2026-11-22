"""Persist selected meters separately from scan results and app options."""
import json
import os
import threading
from pathlib import Path


def valid_id(value):
    return isinstance(value, str) and len(value) == 8 and value.isdecimal()


class MeterRegistry:
    def __init__(self, path="/data/meters.json"):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.selected = {}
        self.pending_cleanup = []
        self.found = {}
        self.scan_status = "not_started"
        self.scan_progress = 0
        self.scan_errors = []
        self.scan_stop = threading.Event()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.pending_cleanup = data.get("pending_cleanup", [])
            if not isinstance(self.pending_cleanup, list) or not all(
                    valid_id(item) for item in self.pending_cleanup):
                raise ValueError("invalid pending cleanup")
            for row in data.get("selected", []):
                meter_id, address = row["meter_id"], row["address"]
                if not valid_id(meter_id) or type(address) is not int or not 0 <= address <= 250:
                    raise ValueError("invalid persisted meter selection")
                if meter_id in self.selected or address in self.selected.values():
                    raise ValueError("duplicate persisted meter selection")
                self.selected[meter_id] = address

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"selected": [
            {"meter_id": meter_id, "address": address}
            for meter_id, address in sorted(self.selected.items())
        ], "pending_cleanup": self.pending_cleanup}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def migrate_legacy(self, meter_id, address):
        if not valid_id(meter_id):
            return
        with self.lock:
            if self.path.exists():
                return
            self.selected[meter_id] = address
            self._save()

    def snapshot(self):
        with self.lock:
            found = [dict(row, selected=row["meter_id"] in self.selected)
                     for row in self.found.values()]
            return {"selected": [{"meter_id": key, "address": addr}
                                 for key, addr in sorted(self.selected.items())],
                    "available": sorted((row for row in found if not row["selected"]
                                         and row["meter_id"] not in self.pending_cleanup),
                                        key=lambda row: (row["address"], row["meter_id"])),
                    "cleanup_pending": len(self.pending_cleanup),
                    "scan_status": self.scan_status,
                    "scan_progress": self.scan_progress,
                    "scan_errors": list(self.scan_errors)}

    def set_found(self, rows):
        with self.lock:
            ids = [row["meter_id"] for row in rows]
            if len(ids) != len(set(ids)):
                raise RuntimeError("ambiguous duplicate meter identity")
            self.found = {row["meter_id"]: dict(row) for row in rows}

    def add_found(self, row):
        with self.lock:
            previous = self.found.get(row["meter_id"])
            if previous is not None and previous["address"] != row["address"]:
                raise RuntimeError("ambiguous duplicate meter identity")
            self.found[row["meter_id"]] = dict(row)

    def select(self, meter_id):
        with self.lock:
            if not valid_id(meter_id):
                raise ValueError("invalid meter identity")
            row = self.found.get(meter_id)
            if not row or not row.get("supported"):
                raise ValueError("meter is not a discovered supported device")
            if meter_id in self.pending_cleanup:
                raise ValueError("previous MQTT cleanup still pending")
            if meter_id in self.selected or row["address"] in self.selected.values():
                raise ValueError("meter or bus address already selected")
            self.selected[meter_id] = row["address"]
            try:
                self._save()
            except OSError:
                del self.selected[meter_id]
                raise

    def select_auto(self):
        with self.lock:
            choices = [row["meter_id"] for row in self.snapshot()["available"]
                       if row["supported"]]
            if len(choices) != 1 or self.scan_status != "completed" or self.scan_errors:
                raise ValueError("automatic selection requires exactly one unassigned meter and a clean scan")
            self.select(choices[0])
            return choices[0]

    def remove(self, meter_id):
        with self.lock:
            if not valid_id(meter_id):
                raise ValueError("invalid meter identity")
            if meter_id not in self.selected:
                raise ValueError("meter not selected")
            address = self.selected.pop(meter_id)
            self.pending_cleanup.append(meter_id)
            try:
                self._save()
            except OSError:
                self.selected[meter_id] = address
                self.pending_cleanup.remove(meter_id)
                raise

    def cleanup_done(self, meter_id):
        with self.lock:
            if meter_id not in self.pending_cleanup:
                return
            self.pending_cleanup.remove(meter_id)
            try:
                self._save()
            except OSError:
                self.pending_cleanup.append(meter_id)
                raise
