"""Uninstalled diagnostic candidate: no persistent meter parameter writes.

Caller must establish isolated single-master/single-meter topology and an
approved maintenance window. Selection is transient instrument state.
No generic send interface, no CI51, no broadcast, no registry mutation.
"""
from address_policy import SecondaryIdentity, validate_address
from address_telegrams import deselect, select_enhanced, selected_read
from address_response import clean_ack, receive_window, reported_device_number
from mbus_probe import request, validate
from raw_telegram_log import capture
from datetime import datetime, timezone
import os
from contextlib import nullcontext
import json
import uuid
from pathlib import Path
from dataclasses import asdict
from bus_timing import AddressSafetyBlocked
from ha_measurements import verify_normal_layout


class DiagnosticEvidence:
    """Private, append-only JSONL evidence, one file per diagnostic attempt."""
    def __init__(self,directory,identity,number,address,recovery):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/(str(uuid.uuid4())+".jsonl")
        self.sequence=0
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
        self.record("session",{"identity":asdict(identity),"number":number,
                               "address":address,"recovery":bool(recovery)})
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def record(self,kind,data):
        item={"sequence":self.sequence,"kind":kind,
              "utc":datetime.now(timezone.utc).isoformat(),"data":data}
        with self.path.open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(item,separators=(",",":"))+"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.sequence+=1


class DiagnosticGuard:
    def __init__(self,path):
        self.path=Path(path)
        self._fresh_id=None

    def blocked(self):
        try:
            self.path.stat()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return True

    def load(self):
        data=json.loads(self.path.read_text())
        if set(data)!={"id","identity","number","address"}:
            raise ValueError("invalid diagnostic guard")
        identity=SecondaryIdentity(**data["identity"])
        select_enhanced(identity,data["number"])
        validate_address(data["address"])
        uuid.UUID(data["id"])
        return data

    def sync(self):
        fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def begin(self,identity,number,address):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("x") as stream:
            json.dump(dict(id=str(uuid.uuid4()),identity=asdict(identity),number=number,address=address),stream)
            stream.flush()
            os.fsync(stream.fileno())
        self.sync()
        self._fresh_id=self.load()["id"]

    def finish(self,record):
        if self.load()!=record:
            raise ValueError("diagnostic guard changed")
        self._fresh_id=None
        self.path.unlink()
        self.sync()


class DiagnosticPermit:
    """Exact frame permission bound to a single lease and durable guard."""
    def __init__(self,guard,lock,record,*,recovery=False,second_read=False):
        self.guard,self.lock,self.record=guard,lock,record
        self.lease=lock.current_lease()
        if self.lease is None or guard.load()!=record:
            raise AddressSafetyBlocked("matching guard and owned lease required")
        if not recovery:
            if guard._fresh_id!=record["id"]:
                raise AddressSafetyBlocked("fresh diagnostic authorization required")
            guard._fresh_id=None
        self.frames={deselect(),request(record["address"])}
        if not recovery:
            self.frames.update((select_enhanced(SecondaryIdentity(**record["identity"]),record["number"]),selected_read(0x7b)))
            if second_read:
                self.frames.add(selected_read(0x5b))

    def check(self,frame):
        if (self.lease is None or self.lock.current_lease() is not self.lease
                or frame not in self.frames or self.guard.load()!=self.record):
            raise AddressSafetyBlocked("diagnostic frame denied")

    def consume(self,frame):
        self.check(frame)


def run_diagnostic(serial, gate, bus_lock, shutdown, *, identity, number,
                   address, guard, confirmed=False, single_meter=False, second_read=False, recovery=False, owned_lease=False, evidence=None):
    if confirmed is not True or single_meter is not True or not isinstance(identity, SecondaryIdentity):
        raise ValueError("explicit isolated diagnostic approval required")
    validate_address(address)
    primary=request(address)
    reset=deselect()
    selector=select_enhanced(identity,number)
    read=selected_read(0x7b)
    followup=selected_read(0x5b)
    allowed={primary,reset,selector,read}
    if second_read is True:
        allowed.add(followup)
    if gate.diagnostic_guard is not guard:
        raise ValueError("shared diagnostic guard required")
    permit=None
    events=[]
    result={"status":"failed","events":events,"cleanup_verified":False,
            "selected_address":None,"exclusive_proven":False}
    def record(kind,data):
        if evidence is not None:
            evidence.record(kind,data)
    def exchange(stage,frame,cleanup=False):
        if frame not in allowed or not bus_lock.owned_by_current_thread():
            raise RuntimeError("diagnostic frame not authorized")
        if shutdown.is_set() and not cleanup:
            raise RuntimeError("diagnostic cancelled")
        event={"stage":stage,"tx":frame.hex(" "),"rx":None,"started_at_utc":datetime.now(timezone.utc).isoformat()}
        events.append(event)
        record("tx_intent",dict(event))
        serial.reset_input_buffer()
        if gate.write(serial,frame,permit=permit)!=len(frame):
            raise OSError("partial transmission")
        record("tx_complete",{"stage":stage,"length":len(frame)})
        raw=receive_window(serial)
        capture("RX",raw)
        event["rx"]=raw.hex(" ")
        event["received_at_utc"]=datetime.now(timezone.utc).isoformat()
        record("rx",dict(event))
        return raw
    def inspect(raw,primary_read):
        decoded=validate(raw)
        if SecondaryIdentity.from_decoded(decoded)!=identity:
            raise ValueError("identity mismatch")
        if reported_device_number(raw,identity)!=number:
            raise ValueError("fabrication number mismatch")
        observed=decoded.get("address")
        if primary_read and observed!=address:
            raise ValueError("primary address mismatch")
        if not primary_read and observed not in (address,0xfd):
            raise ValueError("unexpected selected address")
        events[-1].update(address=observed,access_number=decoded.get("access_number"))
        record("identity_verified",dict(events[-1]))
        if primary_read:
            verify_normal_layout(decoded,identity.meter_id,address)
            record("normal_layout_verified",{"stage":events[-1]["stage"]})
        return observed
    def ack(stage,frame,cleanup=False):
        if not clean_ack(exchange(stage,frame,cleanup)):
            raise ValueError("uncertain acknowledgement: "+stage)
    if owned_lease and not bus_lock.owned_by_current_thread():
        raise RuntimeError('owned diagnostic bus lease required')
    with (nullcontext() if owned_lease else bus_lock):
        selection_attempted=False
        try:
            if recovery:
                pending=guard.load()
                if (pending["identity"]!=asdict(identity) or pending["number"]!=number or pending["address"]!=address):
                    raise ValueError("diagnostic recovery identity mismatch")
                permit=DiagnosticPermit(guard,bus_lock,pending,recovery=True)
                selection_attempted=True
                result["status"]="recovering"
            else:
                inspect(exchange("primary_before",primary),True)
                guard.begin(identity,number,address)
                pending=guard.load()
                permit=DiagnosticPermit(guard,bus_lock,pending,second_read=second_read)
                selection_attempted=True
                ack("normalize",reset)
                ack("select",selector)
                result["selected_address"]=inspect(exchange("selected_read",read),False)
                if second_read is True:
                    inspect(exchange("selected_followup",followup),False)
                result["status"]="observed"
        except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
            result["error"]=str(exc)
        finally:
            if selection_attempted:
                try:
                    ack("cleanup",reset,True)
                    inspect(exchange("primary_after",primary,True),True)
                    record("cleanup_verified",{"guard_id":pending["id"]})
                    guard.finish(pending)
                    result["cleanup_verified"]=True
                    if recovery:
                        result["status"]="restored"
                except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
                    result["status"]="cleanup_required"
                    result["cleanup_error"]=str(exc)
        try:
            record("result",result)
        except OSError as exc:
            result["evidence_error"]=str(exc)
            result["status"]="evidence_failed" if result["cleanup_verified"] else "cleanup_required" if guard.blocked() else "failed"
    return result
