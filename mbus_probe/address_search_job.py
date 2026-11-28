"""Read-only address search job state for ingress presentation."""
import threading
import uuid
from address_search import search_addresses, adaptive_search, verify_destination, verify_known_addresses
from address_policy import validate_address


class AddressSearchJob:
    def __init__(self, registry, transport, bus_lock, shutdown):
        self.registry, self.transport, self.bus_lock = registry, transport, bus_lock
        self.shutdown = shutdown
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self._context = None
        self._range = None
        self._fast_checkpoint = {}
        self.state = {"status": "idle", "meter_id": None, "results": [], "total": 0}

    def snapshot(self):
        # Status and admission must never wait for the registry lock held by
        # a long-running address transaction. Snapshot under the job lock,
        # then try the registry lock without blocking. Start revalidates under
        # both locks before any resume is admitted.
        with self.lock:
            state = dict(self.state, results=[dict(r) for r in self.state["results"]])
            context, bounds = self._context, self._range
        state["can_resume"] = False
        if state.get("scan_guard") and hasattr(self.transport,"remaining_guard"):
            import math
            state["guard_remaining"]=math.ceil(self.transport.remaining_guard())
        if context is not None and state["status"] not in ("running", "stopping"):
            if self.registry.lock.acquire(blocking=False):
                try:
                    same = context == dict(self.registry.selected)
                finally:
                    self.registry.lock.release()
                if not same:
                    state.update(status="invalidated", results=[])
                state["can_resume"] = (same and state["status"] == "cancelled"
                    and bounds == (0, 250) and (state.get('fast') is True and (state.get('phase')!='done' or len(state['results'])<state['total']) or len(state["results"]) < state["total"])
                    and not self.shutdown.is_set())
        return state

    def start(self, meter_id, first, last, *, resume=False, fast=False):
        if type(fast) is not bool or (fast and (first,last)!=(0,250)):
            raise ValueError('fast mode requires full address search')
        validate_address(first)
        validate_address(last)
        if first > last:
            raise ValueError("invalid address range")
        with self.registry.lock, self.lock:
            if meter_id not in self.registry.selected:
                raise ValueError("meter not selected")
            if first == last and first == self.registry.selected[meter_id]:
                raise ValueError("destination equals current address")
            if self.state["status"] in ("running", "stopping") or self.shutdown.is_set():
                raise ValueError("search unavailable")
            if resume is True:
                if (self.state["status"] != "cancelled" or self.state["meter_id"] != meter_id
                        or self._context != dict(self.registry.selected) or self._range != (0, 250)
                        or (first, last) != self._range or (not self.state.get('fast') and len(self.state["results"]) >= self.state["total"]) or (self.state.get('phase')=='done' and len(self.state['results'])>=self.state['total'])):
                    raise ValueError("no resumable search; start a new search")
                # Resume always retains the original search mode.
                if not self.state.get('fast') and not hasattr(self.transport,'observe_identity'):
                    first += len(self.state["results"])
                self.state["status"] = "running"
                self.state.pop("scan_guard",None)
            elif resume is False:
                self._context = dict(self.registry.selected)
                self._range = (first, last)
                self._fast_checkpoint = {}
                self.state = {"status": "running", "search_id": str(uuid.uuid4()), "meter_id": meter_id, "results": [],
                              "total": last - first + 1, "fast":fast}
            else:
                raise ValueError("invalid resume flag")
            self.cancel.clear()
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
                if self.state.get('fast') or hasattr(self.transport,'observe_identity'):
                    self.state['results']=[r for r in self.state['results'] if r['address']!=row['address']]+[row]
                    self.state['results'].sort(key=lambda r:r['address'])
                else:
                    self.state["results"].append(row)
        def phase(value,scanned,verified,total):
            with self.lock:
                # Adaptive pass completion is not full job completion.
                self.state.update(phase=("finalizing" if value=="done" else value),scanned=scanned,rechecked=verified,recheck_total=total)
        try:
            if first == last and self._range != (0,250) and hasattr(self.transport,'check_conservative'):
                with self.registry.lock:
                    known=any(a==first for a in self.registry.selected.values())
                if known:
                    result=search_addresses(range(first,last+1),self.registry,meter_id,self.transport,self.bus_lock,self,progress)
                else:
                    with self.bus_lock:
                        availability, observations=verify_destination(first,self.transport,self)
                    progress({'address':first,'status':availability.value,'known_meter_count':None,'observations':observations},1,1)
                    result={'cancelled':self.is_set()}
            elif self._range == (0,250) and hasattr(self.transport,'observe_identity'):
                # Production transport: retain known addresses until all other
                # probes and deferred fast rechecks have completed.
                known=sorted(set(self._context.values()))
                unknown=[a for a in range(251) if a not in known]
                completed={r["address"] for r in self.state["results"]}
                if self.state.get('fast') is True:
                    result=adaptive_search(unknown,self.registry,meter_id,self.transport,self.bus_lock,self,
                        progress,checkpoint=self._fast_checkpoint,phase_callback=phase)
                else:
                    result=search_addresses([a for a in unknown if a not in completed],self.registry,meter_id,
                        self.transport,self.bus_lock,self,progress)
                if not self.is_set():
                    phase("known",len(unknown),0,len(known))
                    verify_known_addresses([a for a in known if a not in completed],self.registry,meter_id,
                        self.transport,self.bus_lock,self,progress)
                result={"cancelled":self.is_set()}
                if not self.is_set():
                    phase("finalizing",251,0,0)
            else:
                if self.state.get('fast') is True and hasattr(self.transport,'check_fast'):
                    result=adaptive_search(range(first,last+1),self.registry,meter_id,self.transport,self.bus_lock,self,progress,checkpoint=self._fast_checkpoint,phase_callback=phase)
                else:
                    result=search_addresses(range(first,last+1),self.registry,meter_id,self.transport,self.bus_lock,self,progress)
            status = "cancelled" if result["cancelled"] else "completed"
        except Exception:
            status = "failed"
        if hasattr(self.transport,"finish_scan"):
            try:
                with self.bus_lock:
                    self.transport.finish_scan()
                with self.lock:
                    self.state["scan_guard"]=True
            except Exception:
                status="failed"
        with self.registry.lock, self.lock:
            self.state["status"] = status if self._context == dict(self.registry.selected) else "invalidated"
            if self.state["status"]=="completed":
                self.state["phase"]="done"
