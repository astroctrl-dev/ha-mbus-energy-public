"""Persist selected meters separately from scan results and app options."""
import json
import os
import threading
from pathlib import Path
from dataclasses import asdict
from address_policy import SecondaryIdentity, validate_address


def valid_id(value):
    return isinstance(value, str) and len(value) == 8 and value.isdecimal()


class MeterRegistry:
    def __init__(self, path="/data/meters.json"):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.selected = {}
        self.identities = {}
        self.quarantined = set()
        self.persistence_failed = False
        self.pending_cleanup = []
        self.found = {}
        self.scan_status = "not_started"
        self.scan_progress = 0
        self.scan_errors = []
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
                if meter_id in self.selected:
                    raise ValueError("duplicate persisted meter selection")
                self.selected[meter_id] = address
                if "identity" in row:
                    identity = SecondaryIdentity(**row["identity"])
                    if identity.meter_id != meter_id:
                        raise ValueError("persisted identity mismatch")
                    self.identities[meter_id] = identity
            quarantine = data.get("quarantined", [])
            if not isinstance(quarantine, list) or any(key not in self.selected for key in quarantine):
                raise ValueError("invalid quarantine")
            self.quarantined = set(quarantine)
            for key, address in self.selected.items():
                if list(self.selected.values()).count(address) > 1:
                    self.quarantined.add(key)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps({"selected": [
            {"meter_id": meter_id, "address": address, **({"identity": asdict(self.identities[meter_id])} if meter_id in self.identities else {})}
            for meter_id, address in sorted(self.selected.items())
        ], "pending_cleanup": self.pending_cleanup, "quarantined": sorted(self.quarantined)}, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            self.persistence_failed = True
            raise

    def snapshot(self):
        with self.lock:
            found = [dict(row, selected=row["meter_id"] in self.selected)
                     for row in self.found.values()]
            return {"selected": [{"meter_id": key, "address": addr}
                                 for key, addr in sorted(self.selected.items())],
                    "quarantine": [{"meter_id": key, "address": self.selected[key],
                                    "identity_enrolled": key in self.identities,
                                    "registered_conflict": sum(a == self.selected[key] for a in self.selected.values()) > 1}
                                   for key in sorted(self.quarantined)],
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
                raise ValueError("ambiguous duplicate meter identity")
            self.found = {row["meter_id"]: dict(row) for row in rows}

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
            if self.persistence_failed or meter_id in self.quarantined:
                raise ValueError("quarantined meter requires verified reconciliation before removal")
            address = self.selected.pop(meter_id)
            identity = self.identities.pop(meter_id, None)
            was_quarantined = meter_id in self.quarantined
            self.quarantined.discard(meter_id)
            self.pending_cleanup.append(meter_id)
            try:
                self._save()
            except OSError:
                self.selected[meter_id] = address
                if identity is not None:
                    self.identities[meter_id] = identity
                if was_quarantined:
                    self.quarantined.add(meter_id)
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


    def enroll_identity(self, meter_id, observed, *, exclusive, confirmed, physical_address):
        """Explicit enrollment of a legacy meter; caller supplies fresh bus proof."""
        with self.lock:
            if (self.persistence_failed or exclusive is not True or confirmed is not True
                    or not isinstance(observed, SecondaryIdentity) or observed.meter_id != meter_id
                    or meter_id not in self.selected or type(physical_address) is not int
                    or self.selected[meter_id] != physical_address or meter_id in self.quarantined):
                raise ValueError("identity enrollment blocked")
            existing = self.identities.get(meter_id)
            if existing is not None and existing != observed:
                raise ValueError("identity mismatch")
            self.identities[meter_id] = observed
            try:
                self._save()
            except OSError:
                if existing is None:
                    self.identities.pop(meter_id, None)
                raise

    def address_blocked(self, meter_id):
        with self.lock:
            return self.persistence_failed or meter_id in self.quarantined

    def record_verified_address(self, intent, observed, physical_address, *, exclusive, destination_risk):
        """Registry half of journal reconciliation; not a live bus operation."""
        from address_journal import Intent
        with self.lock:
            if (self.persistence_failed or not isinstance(intent, Intent)
                    or exclusive is not True or observed != intent.identity
                    or self.identities.get(intent.identity.meter_id) != intent.identity
                    or type(physical_address) is not int or physical_address != intent.new_address
                    or type(destination_risk) is not bool):
                raise ValueError("address verification blocked")
            key = intent.identity.meter_id
            previous = self.selected.get(key)
            if previous not in (intent.old_address, intent.new_address):
                raise ValueError("stale registry address")
            old_quarantine = self.quarantined.copy()
            self.selected[key] = validate_address(physical_address)
            peers = {k for k, a in self.selected.items() if a == physical_address and k != key}
            if peers or destination_risk:
                self.quarantined.update(peers | {key})
            try:
                self._save()
            except OSError:
                self.selected[key] = previous
                self.quarantined = old_quarantine
                self.persistence_failed = True
                raise


    def clear_verified_quarantine(self, meter_id, observed, physical_address, *, exclusive, primary_verified):
        """Registry commit only: caller must hold bus lock and obtain fresh proof.

        primary_verified means independent physical evidence of an unambiguous
        primary response for this identity, not merely a secondary selection ACK.
        No address is changed, and no identity is created by this operation.
        """
        with self.lock:
            if (self.persistence_failed or meter_id not in self.quarantined
                    or not isinstance(observed, SecondaryIdentity)
                    or observed.meter_id != meter_id or self.identities.get(meter_id) != observed
                    or exclusive is not True or primary_verified is not True
                    or type(physical_address) is not int
                    or self.selected.get(meter_id) != physical_address
                    or any(k != meter_id and a == physical_address for k, a in self.selected.items())):
                raise ValueError("quarantine reconciliation not verified")
            self.quarantined.remove(meter_id)
            try:
                self._save()
            except OSError:
                self.quarantined.add(meter_id)
                self.persistence_failed = True
                raise


    def enroll_quarantined_identity(self, meter_id, observed, *, exclusive, confirmed, physical_address):
        """Persist newly established full identity without clearing quarantine."""
        with self.lock:
            if (self.persistence_failed or confirmed is not True or exclusive is not True
                    or not isinstance(observed, SecondaryIdentity) or observed.meter_id != meter_id
                    or meter_id not in self.quarantined or meter_id in self.identities
                    or type(physical_address) is not int or self.selected.get(meter_id) != physical_address
                    or any(k != meter_id and a == physical_address for k, a in self.selected.items())):
                raise ValueError("quarantined identity enrollment blocked")
            self.identities[meter_id] = observed
            try:
                self._save()
            except OSError:
                self.identities.pop(meter_id, None)
                self.persistence_failed = True
                raise
