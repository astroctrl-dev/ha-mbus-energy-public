"""Read-only address search, one paced probe at a time.

No result proves that an address is free. Cancellation is cooperative between
probes; ordinary bus work may run between probes. No selection or writes.
"""
from address_policy import Availability, validate_address


def _test_probe(address, transport, count, fast=False):
    """Actual discovery evidence is separate from registered conflict protection."""
    identity = None
    try:
        result, identity = transport.test_observation(address, fast=fast)
        observed = result.value if isinstance(result, Availability) else "failed"
    except (OSError, ValueError, RuntimeError):
        observed = "failed"
    # Silence at a registered address must never advertise availability.
    status = "failed" if count and observed == "no_response" else observed
    return {"address": address, "status": status, "known_meter_count": count or None,
            "test_observation": observed, "observed_identity": identity}


def search_addresses(addresses, registry, meter_id, transport, bus_lock, stop, progress=None, *, test=False):
    candidates = list(dict.fromkeys(validate_address(a) for a in addresses))
    rows = []
    for address in candidates:
        if stop.is_set():
            break
        with bus_lock:
            if stop.is_set():
                break
            with registry.lock:
                known_count = sum(a == address for a in registry.selected.values())
                occupied = any(k != meter_id and a == address for k, a in registry.selected.items())
                own = registry.selected.get(meter_id) == address
            if test:
                row = _test_probe(address, transport, known_count)
            elif own:
                status = "current_address_conflict" if occupied else "current_address"
            elif occupied:
                status = "occupied_multiple" if known_count > 1 else Availability.OCCUPIED.value
            else:
                try:
                    result = transport.check(address)
                    status = result.value if isinstance(result, Availability) else Availability.FAILED.value
                except (OSError, ValueError, RuntimeError):
                    status = Availability.FAILED.value
        if not test:
            row = {"address": address, "status": status,
                   "known_meter_count": known_count if known_count else None}
        rows.append(row)
        if progress is not None:
            progress(dict(row), len(rows), len(candidates))
    return {"results": rows, "cancelled": stop.is_set(), "total": len(candidates)}


def verify_destination(address, transport, stop):
    """Two fresh conservative observations; transport owns the full bus guard.
    A silent pair is evidence only, never proof of exclusivity.
    """
    check=getattr(transport,"check_conservative",transport.check)
    observations=[]
    for _ in range(2):
        if stop.is_set():
            return Availability.FAILED, observations
        try:
            result=check(address)
        except (OSError,ValueError,RuntimeError):
            result=Availability.FAILED
        if not isinstance(result,Availability):
            result=Availability.FAILED
        observations.append(result.value)
        if result is not Availability.NO_RESPONSE:
            return result,observations
    return Availability.NO_RESPONSE,observations


# Fixed block boundaries plus one adjacent address on either side.
# This is a provisional margin, not proof that every late response is detectable.
BLOCK_SIZE=8
BOUNDARY_MARGIN=1

def affected_addresses(address):
    start=(address//BLOCK_SIZE)*BLOCK_SIZE
    return range(max(0,start-BOUNDARY_MARGIN),min(250,start+BLOCK_SIZE-1+BOUNDARY_MARGIN)+1)


def adaptive_search(addresses, registry, meter_id, transport, bus_lock, stop,
                    progress=None, *, checkpoint=None, phase_callback=None, test=False):
    """Full fast pass, then deduplicated conservative rechecks.
    All pending cells stay red. Resume retains the original observations and
    restarts the full quiet guard before any remaining recheck.
    """
    candidates=list(dict.fromkeys(validate_address(a) for a in addresses))
    state=checkpoint if checkpoint is not None else {}
    original=state.setdefault("original",{})
    rows=state.setdefault("rows",{})
    pending=state.setdefault("pending",set())
    checked=state.setdefault("checked",set())
    phase=state.setdefault("phase","fast")
    def phase_changed(value):
        state["phase"]=value
        if phase_callback:
            phase_callback(value,len(original),len(checked),len(pending|checked))
    def publish(row):
        rows[row["address"]]=dict(row)
        if progress:
            progress(dict(row),len(original),len(candidates))
    def probe(address, fast):
        with bus_lock:
            if stop.is_set():
                return None
            with registry.lock:
                count=sum(a==address for a in registry.selected.values())
                own=registry.selected.get(meter_id)==address
            if test:
                return _test_probe(address, transport, count, fast)
            if own:
                status="current_address_conflict" if count>1 else "current_address"
            elif count:
                status="occupied_multiple" if count>1 else "occupied"
            else:
                try:
                    result=transport.check_fast(address,.2,.01) if fast else transport.check(address)
                    status=result.value if isinstance(result,Availability) else "failed"
                except (OSError,ValueError,RuntimeError):
                    status="failed"
            return {"address":address,"status":status,"known_meter_count":count or None}
    def mark_pending(address):
        pending.add(address)
        old=original.get(address,{})
        # Known current and registered occupied addresses never become green.
        if not test and old.get("status") in ("current_address","current_address_conflict","occupied_multiple","occupied") and old.get("known_meter_count"):
            return
        row={"address":address,"status":"recheck_required","known_meter_count":old.get("known_meter_count")}
        if test and old:
            row["initial_observation"]=dict(old)
        publish(row)
    if phase=="fast":
        phase_changed("fast")
        for address in candidates:
            if stop.is_set():
                break
            if address in original:
                continue
            row=probe(address,True)
            if row is None:
                break
            original[address]=row
            if row["status"] in ("ambiguous","failed"):
                for affected in affected_addresses(address):
                    if affected in candidates:
                        mark_pending(affected)
            if address in pending:
                mark_pending(address)
            else:
                publish(row)
            phase_changed("fast")
        if len(original)==len(candidates) and not stop.is_set():
            phase_changed("waiting" if pending else "done")
    if state["phase"] in ("waiting","recheck") and not stop.is_set():
        phase_changed("waiting")
        # Test scan rechecks the current instrument first, if needed. Its
        # per-address cooldown is enforced by the transport, not a new timer.
        # Normal scan retains its existing conservative recheck guard.
        if not test:
            with bus_lock:
                if not stop.is_set() and hasattr(transport,"begin_quiet_guard"):
                    transport.begin_quiet_guard()
        with registry.lock:
            own_address=registry.selected.get(meter_id)
        if test and pending and own_address in candidates and own_address not in checked:
            mark_pending(own_address)
        for address in sorted(pending,key=lambda a: (a!=own_address,a) if test else (False,a)):
            if stop.is_set():
                break
            row=probe(address,False)
            if row is None:
                break
            old=original.get(address,{})
            if test:
                recheck=dict(row)
                if row["test_observation"]=="no_response" and old.get("test_observation") in ("ambiguous","failed","occupied"):
                    row=dict(old)
                row["initial_observation"]=dict(old)
                row["recheck_observation"]=recheck
            elif row["status"]=="no_response" and old.get("status") in ("ambiguous","failed","occupied"):
                # Silence cannot erase an earlier observed reply or uncertainty.
                row=dict(old)
            pending.remove(address)
            checked.add(address)
            publish(row)
            phase_changed("recheck")
        if not pending and not stop.is_set():
            phase_changed("done")
    return {"results":[rows[a] for a in sorted(rows)],"cancelled":stop.is_set(),"total":len(candidates)}


def verify_known_addresses(addresses, registry, meter_id, transport, bus_lock, stop, progress):
    """Read registered destinations last; never infer exclusivity from one reply."""
    for address in addresses:
        if stop.is_set():
            break
        with bus_lock:
            if stop.is_set():
                break
            with registry.lock:
                peers={k for k,a in registry.selected.items() if a==address}
                expected={k:v for k,v in getattr(registry,"identities",{}).items() if k in peers}
            if not peers:
                status="failed"
            else:
                try:
                    observed=getattr(transport,'observe_final_identity',transport.observe_identity)(address)
                    match=observed.meter_id in peers and (observed.meter_id not in expected or expected[observed.meter_id]==observed)
                    if len(peers)>1 or not match:
                        status="current_address_conflict" if meter_id in peers else "occupied_multiple"
                    else:
                        status="current_address" if meter_id in peers else "occupied"
                except (OSError,ValueError,RuntimeError):
                    status="current_address_conflict" if meter_id in peers else "failed"
            progress({"address":address,"status":status,"known_meter_count":len(peers) or None},0,0)
