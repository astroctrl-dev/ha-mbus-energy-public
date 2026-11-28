"""Read-only address search job state for ingress presentation."""
import threading
import logging
import uuid
from search_test_reservation import SearchTestReservation
from address_search import search_addresses, adaptive_search, verify_destination, verify_known_addresses
from address_policy import validate_address


class AddressSearchJob:
    def __init__(self, registry, transport, bus_lock, shutdown):
        self.registry, self.transport, self.bus_lock = registry, transport, bus_lock
        self.shutdown = shutdown
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.test_reservation = SearchTestReservation()
        self._test_token = None
        self._test_worker = None
        self._context = None
        self._range = None
        self._fast_checkpoint = {}
        self.state = {"status": "idle", "meter_id": None, "results": [], "total": 0}

    def busy(self):
        with self.lock:
            return self.test_reservation.busy() or self.state['status'] in ('running', 'stopping')

    def _test_context(self):
        """Snapshot registered addresses and enrolled identities under registry lock."""
        with self.registry.lock:
            return {"selected":dict(self.registry.selected),
                    "identities":dict(getattr(self.registry,"identities",{})),
                    "quarantined":frozenset(getattr(self.registry,"quarantined",())),
                    "persistence_failed":bool(getattr(self.registry,"persistence_failed",False))}

    def reserve_test(self):
        """Caller must hold shared operation admission during publication."""
        if not hasattr(self.transport, "reservation_guard"):
            raise ValueError("test reservation unavailable")
        with self.registry.lock, self.lock:
            if self.shutdown.is_set() or self.state["status"] in ("running", "stopping"):
                raise ValueError("search unavailable")
            token = self.test_reservation.reserve(self._test_context())
            self._test_token = token
            worker = threading.Thread(target=self._reservation_loop, args=(token,), daemon=True)
            self._test_worker = worker
            try:
                worker.start()
            except RuntimeError:
                # No worker or bus operation started. Keep reservation blocked
                # rather than silently granting admission after a launch fault.
                self.test_reservation.fail(token, "worker_launch_failed")
                raise

    def cancel_test(self, reservation_id=None):
        with self.lock:
            phase = self.test_reservation.snapshot()["phase"]
            if reservation_id != self._test_token:
                raise ValueError("stale test reservation")
            if phase in ("off", "cooldown", "cleanup", "failed"):
                return
            self.test_reservation.cancel(self._test_token)
            if self.state["status"] in ("running", "stopping"):
                self.cancel.set()
                self.state["status"] = "stopping"

    def _reservation_loop(self, token):
        """Single cleanup owner; independent of ingress requests."""
        try:
            while not self.shutdown.is_set():
                phase = self.test_reservation.snapshot()["phase"]
                if phase == "draining":
                    if self.bus_lock.acquire(timeout=.2):
                        try:
                            with self.lock:
                                if self.test_reservation.snapshot()["phase"] == "draining":
                                    deadline = self.transport.reservation_guard()
                                    self.test_reservation.drained(token, deadline)
                        finally:
                            self.bus_lock.release()
                    with self.registry.lock, self.lock:
                        if self.test_reservation.snapshot()["phase"] == "draining":
                            self.test_reservation.advance(token, guard_ready=False, context=self._test_context())
                elif phase in ("waiting", "ready", "scanning"):
                    with self.registry.lock, self.lock:
                        # Re-read phase under the same lock used by start.
                        current = self.test_reservation.snapshot()["phase"]
                        if current == "scanning" and self.state["status"] not in ("running", "stopping"):
                            self.test_reservation.cancel(token, self.state["status"])
                        elif current in ("waiting", "ready", "scanning", "cleanup"):
                            ready = current in ("waiting", "ready") and self.transport.reservation_ready()
                            self.test_reservation.advance(token, guard_ready=ready,
                                                          context=self._test_context())
                elif phase == "cleanup":
                    with self.lock:
                        running = self.state["status"] in ("running", "stopping")
                        if running:
                            self.cancel.set()
                            self.state["status"] = "stopping"
                    if not running and self.bus_lock.acquire(timeout=.2):
                        try:
                            deadline = self.transport.reservation_guard()
                            self.test_reservation.guarded_exit(token, deadline)
                        finally:
                            self.bus_lock.release()
                elif phase == "cooldown":
                    if self.test_reservation.release_if_safe(token, guard_ready=self.transport.reservation_ready()):
                        return
                else:
                    return
                self.shutdown.wait(.1)
        except Exception:
            # A failed timing persistence or worker failure is fail-closed.
            # Do not drop the reservation without a durable exit guard.
            logging.getLogger(__name__).exception("Discovery reservation failed; restart after safety review")
            with self.lock:
                phase = self.test_reservation.snapshot()["phase"]
                if phase not in ("off", "failed"):
                    self.test_reservation.fail(token, "worker_failed")
                self.cancel.set()

    def snapshot(self):
        # Status and admission must never wait for the registry lock held by
        # a long-running address transaction. Snapshot under the job lock,
        # then try the registry lock without blocking. Start revalidates under
        # both locks before any resume is admitted.
        with self.lock:
            state = dict(self.state, results=[dict(r) for r in self.state["results"]])
            context, bounds = self._context, self._range
        state["test_reservation"] = self.test_reservation.snapshot()
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
                    and not state.get("test") and not self.test_reservation.busy()
                    and not self.shutdown.is_set())
        return state

    def start(self, meter_id, first, last, *, resume=False, fast=False, test=False, reservation_id=None):
        if type(test) is not bool or (test and ((first,last)!=(0,250) or resume is not False)):
            raise ValueError("test mode requires a new full search")
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
            if test:
                if not self.test_reservation.busy() or not hasattr(self.transport, "test_observation"):
                    raise ValueError("test reservation unavailable")
                self.test_reservation.start(reservation_id, self._test_context(),
                                            guard_ready=self.transport.reservation_ready())
            elif self.test_reservation.busy():
                raise ValueError("test reservation active")
            if resume is True:
                if (self.state.get("test") or self.state["status"] != "cancelled" or self.state["meter_id"] != meter_id
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
                              "total": last - first + 1, "fast":fast, "test":test}
            else:
                raise ValueError("invalid resume flag")
            self.cancel.clear()
        try:
            threading.Thread(target=self._run, args=(meter_id, first, last), daemon=True).start()
        except RuntimeError:
            with self.lock:
                self.state["status"] = "failed"
                if test:
                    self.test_reservation.cancel(self._test_token, "scan_launch_failed")
            raise

    def request_stop(self, meter_id, search_id=None):
        with self.lock:
            if self.state["meter_id"] != meter_id or self.state["status"] not in ("running", "stopping"):
                raise ValueError("no matching search")
            if (self.state.get("test") or search_id is not None) and search_id != self.state.get("search_id"):
                raise ValueError("stale search stop request")
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
            if self.state.get("test"):
                if self.state.get("fast"):
                    result=adaptive_search(range(251),self.registry,meter_id,self.transport,self.bus_lock,self,
                        progress,checkpoint=self._fast_checkpoint,phase_callback=phase,test=True)
                else:
                    result=search_addresses(range(251),self.registry,meter_id,self.transport,self.bus_lock,self,progress,test=True)
                if not self.is_set():
                    phase("known",251,0,len(set(self._context.values())))
                    def identity_progress(row, done, total):
                        with self.lock:
                            for existing in self.state["results"]:
                                if existing["address"] == row["address"]:
                                    existing["final_identity_status"] = row["status"]
                                    if row["status"] in ("current_address_conflict","occupied_multiple","failed"):
                                        existing["status"] = row["status"]
                    verify_known_addresses(sorted(set(self._context.values())),self.registry,meter_id,
                        self.transport,self.bus_lock,self,identity_progress)
                    phase("finalizing",251,0,0)
                result={"cancelled":self.is_set()}
            elif first == last and self._range != (0,250) and hasattr(self.transport,'check_conservative'):
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
        # Test reservation owns the single durable exit guard; it stays busy
        # across terminal scan status and until cooldown completes.
        if not self.state.get("test") and hasattr(self.transport,"finish_scan"):
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
