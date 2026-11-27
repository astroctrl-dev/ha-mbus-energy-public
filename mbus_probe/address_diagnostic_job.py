"""Opt-in diagnostic job candidate. No automatic execution or address writes."""
import threading
import uuid
import os
import stat
from address_policy import SecondaryIdentity, validate_address
from address_telegrams import select_enhanced


class AddressDiagnosticJob:
    def __init__(self,runner,guard,shutdown,history_blocked,enabled=False, recovery_history_blocked=None):
        self.runner,self.guard,self.shutdown=runner,guard,shutdown
        self.history_blocked=history_blocked
        self.recovery_history_blocked=recovery_history_blocked or history_blocked
        self.enabled=enabled is True
        self.lock=threading.Lock()
        self.state={"status":"idle"}

    def busy(self):
        with self.lock:
            return self.state["status"]=="running"

    def snapshot(self):
        with self.lock:
            state=dict(self.state)
        state["enabled"]=self.enabled
        state["recovery_required"]=self.guard.blocked()
        if state["recovery_required"] and self.enabled and state["status"]!="running":
            try:
                state["pending"]=self.guard.load()
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                state["pending"]=None
        return state

    def start(self,data):
        if not self.enabled or data.get("confirm") is not True or data.get("single_meter") is not True:
            raise ValueError("explicit diagnostic permission and isolated topology confirmation required")
        identity=SecondaryIdentity(data["meter_id"],data["manufacturer"],data["version"],data["medium"])
        number=data["number"]
        address=validate_address(data["address"])
        select_enhanced(identity,number)
        recovery=data.get("recovery",False)
        if type(recovery) is not bool:
            raise ValueError("invalid recovery flag")
        with self.lock:
            if (self.state["status"]=="running" or self.shutdown.is_set()
                    or (self.recovery_history_blocked() if recovery else self.history_blocked()) or self.guard.blocked()!=recovery):
                raise ValueError("diagnostic unavailable")
            if recovery:
                from dataclasses import asdict
                record=self.guard.load()
                if (data.get("guard_id")!=record["id"] or record["identity"]!=asdict(identity)
                        or record["number"]!=number or record["address"]!=address):
                    raise ValueError("pending diagnostic does not match")
            self.state={"status":"running","operation_id":str(uuid.uuid4())}
            try:
                threading.Thread(target=self._run,args=(identity,number,address,recovery),daemon=True).start()
            except RuntimeError as exc:
                self.state["status"]="start_failed"
                raise ValueError("diagnostic worker could not start") from exc

    def _run(self,identity,number,address,recovery):
        try:
            if (self.recovery_history_blocked() if recovery else self.history_blocked()) or self.shutdown.is_set():
                raise ValueError("normal communication not verified")
            result=self.runner(identity=identity,number=number,address=address,
                               confirmed=True,single_meter=True,recovery=recovery)
            safe={k:result[k] for k in ("status","cleanup_verified","selected_address","evidence_file") if k in result}
        except Exception:
            safe={"status":"cleanup_required" if self.guard.blocked() else "failed"}
        with self.lock:
            self.state.update(safe)

    def export(self,name):
        # Exact generated UUID filename only. No directory listing or path traversal.
        if not self.enabled or not isinstance(name,str) or not name.endswith(".jsonl"):
            raise ValueError("evidence export unavailable")
        if str(uuid.UUID(name[:-6]))+".jsonl"!=name:
            raise ValueError("invalid evidence filename")
        if self.busy():
            raise ValueError("diagnostic running")
        path=self.guard.path.parent/"diagnostic-evidence"/name
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>262144:
                raise ValueError("invalid evidence file")
            payload=stream.read(262145)
            if len(payload)>262144:
                raise ValueError("evidence too large")
            return payload
