"""Asynchronous address transaction UI adapter, for injected test controllers only.

The production service must not install this adapter until physical transport
and shared operation coordination have been independently verified.
"""
import threading
import uuid
from address_policy import validate_address


class AddressChangeJob:
    def __init__(self, controller, shutdown):
        self.controller, self.shutdown = controller, shutdown
        self.lock = threading.Lock()
        self.state = {"status": "idle", "meter_id": None, "old_address": None,
                      "new_address": None}

    def snapshot(self):
        with self.lock:
            state = dict(self.state)
            if state['status'] == 'running':
                return state
            try:
                intent = self.controller.journal.load()
                if intent is not None:
                    state.update(status='recovery_required', meter_id=intent.identity.meter_id,
                                 old_address=intent.old_address, new_address=intent.new_address,
                                 transaction_id=self.controller.journal.transaction_id(), recoverable=True)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                state.update(status='recovery_required', recoverable=False)
            return state

    def start(self, meter_id, old_address, new_address, *, confirmed, override=False, accepted_risk=None):
        validate_address(old_address)
        validate_address(new_address)
        if not isinstance(meter_id, str) or confirmed is not True or type(override) is not bool:
            raise ValueError("explicit confirmation required")
        with self.lock:
            if self.shutdown.is_set() or self.state["status"] == "running" or self.controller.journal.blocked():
                raise ValueError("address operation unavailable")
            if override is True:
                if (self.state.get("status") != "override_required" or
                        accepted_risk is None or accepted_risk != self.state.get("destination_evidence") or
                        accepted_risk.get("meter_id") != meter_id or
                        accepted_risk.get("old_address") != old_address or
                        accepted_risk.get("new_address") != new_address):
                    raise ValueError("accept the displayed destination risk first")
            self.state = {"status": "running", "operation_id": str(uuid.uuid4()), "meter_id": meter_id,
                          "old_address": old_address, "new_address": new_address}
            try:
                threading.Thread(target=self._run, args=(meter_id, old_address, new_address, override, accepted_risk),
                                 daemon=True).start()
            except RuntimeError as exc:
                self.state["status"]="start_failed"
                raise ValueError("address worker could not start") from exc

    def _run(self, meter_id, old, new, override, accepted_risk):
        try:
            status = self.controller.change(meter_id, new, expected_old=old,
                                            confirmed=True, override=override, accepted_risk=accepted_risk)
        except Exception:
            status = "recovery_required"
        with self.lock:
            self.state["status"] = status
            if status == "override_required":
                self.state["destination_evidence"] = self.controller.destination_evidence


    def recover(self, meter_id, transaction_id, *, confirmed=False):
        if confirmed is not True or not isinstance(meter_id, str):
            raise ValueError("explicit recovery confirmation required")
        with self.lock:
            if self.shutdown.is_set() or self.state["status"] == "running":
                raise ValueError("address operation unavailable")
            intent = self.controller.journal.load()
            if (intent is None or intent.identity.meter_id != meter_id
                    or self.controller.journal.transaction_id() != transaction_id):
                raise ValueError("pending transaction does not match")
            self.state = {"status": "running", "operation_id": str(uuid.uuid4()), "meter_id": meter_id,
                          "old_address": intent.old_address, "new_address": intent.new_address}
            try:
                threading.Thread(target=self._recover, args=(meter_id, transaction_id), daemon=True).start()
            except RuntimeError as exc:
                self.state["status"]="recovery_required"
                raise ValueError("recovery worker could not start") from exc

    def _recover(self, meter_id, transaction_id):
        try:
            status = self.controller.recover(expected_meter=meter_id,
                                             expected_transaction=transaction_id)
        except Exception:
            status = "recovery_required"
        with self.lock:
            self.state["status"] = status


    def quarantine_action(self, meter_id, address, *, action, confirmed=False, new_address=None):
        validate_address(address)
        if confirmed is not True or not isinstance(meter_id,str) or action not in ("enroll","verify","relocate"):
            raise ValueError("explicit quarantine action required")
        if action == "relocate":
            validate_address(new_address)
            if new_address == address:
                raise ValueError("new address must differ")
        elif new_address is not None:
            raise ValueError("unexpected destination")
        with self.lock:
            if self.shutdown.is_set() or self.state["status"] == "running" or self.controller.journal.blocked():
                raise ValueError("address operation unavailable")
            self.state={"status":"running","operation_id":str(uuid.uuid4()),"meter_id":meter_id,
                        "old_address":address,"new_address":new_address,"action":action}
            try:
                threading.Thread(target=self._quarantine_action,args=(meter_id,address,action,new_address),
                                 daemon=True).start()
            except RuntimeError as exc:
                self.state["status"]="quarantine_required"
                raise ValueError("quarantine worker could not start") from exc

    def _quarantine_action(self, meter_id,address,action,new_address):
        try:
            if action=="enroll":
                status=self.controller.enroll_quarantined_peer(meter_id,expected_address=address,confirmed=True)
            elif action=="verify":
                status=self.controller.verify_quarantine(meter_id,expected_address=address,confirmed=True)
            else:
                status=self.controller.change(meter_id,new_address,expected_old=address,
                                              confirmed=True,resolve_conflict=True)
        except Exception:
            status="recovery_required"
        with self.lock:
            self.state["status"]=status
