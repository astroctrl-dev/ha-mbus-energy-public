"""Read-only address search job state for ingress presentation."""
import threading
import uuid
from address_search import search_addresses
from address_policy import validate_address


class AddressSearchJob:
    def __init__(self, registry, transport, bus_lock, shutdown):
        self.registry, self.transport, self.bus_lock = registry, transport, bus_lock
        self.shutdown = shutdown
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.state = {"status": "idle", "meter_id": None, "results": [], "total": 0}

    def snapshot(self):
        with self.lock:
            return dict(self.state, results=[dict(r) for r in self.state["results"]])

    def start(self, meter_id, first, last):
        validate_address(first)
        validate_address(last)
        if first > last:
            raise ValueError("invalid address range")
        with self.registry.lock:
            if meter_id not in self.registry.selected:
                raise ValueError("meter not selected")
        with self.lock:
            if self.state["status"] in ("running", "stopping") or self.shutdown.is_set():
                raise ValueError("search unavailable")
            self.cancel.clear()
            self.state = {"status": "running", "search_id": str(uuid.uuid4()), "meter_id": meter_id, "results": [],
                          "total": last - first + 1}
        threading.Thread(target=self._run, args=(meter_id, first, last), daemon=True).start()

    def request_stop(self, meter_id):
        with self.lock:
            if self.state["meter_id"] != meter_id or self.state["status"] not in ("running", "stopping"):
                raise ValueError("no matching search")
            self.cancel.set()
            self.state["status"] = "stopping"

    def is_set(self):
        return self.cancel.is_set() or self.shutdown.is_set()

    def _run(self, meter_id, first, last):
        def progress(row, done, total):
            with self.lock:
                self.state["results"].append(row)
        try:
            result = search_addresses(range(first, last + 1), self.registry, meter_id,
                self.transport, self.bus_lock, self, progress)
            status = "cancelled" if result["cancelled"] else "completed"
        except Exception:
            status = "failed"
        with self.lock:
            self.state["status"] = status
