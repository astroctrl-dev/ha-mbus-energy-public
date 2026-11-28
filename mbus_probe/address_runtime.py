"""Read-only address discovery integration; physical address writes disabled.

Open the adapter only within the shared bus lease, for one bounded exchange.
No serial handle survives a probe. No secondary selector or write method exists
on the production search transport.
"""
from address_policy import assess_destination, validate_address, SecondaryIdentity
from address_response import receive_window, reported_device_number
from raw_telegram_log import capture
from address_search_job import AddressSearchJob


class ReadOnlyAddressTransport:
    def __init__(self, config, gate, bus_lock, shutdown, serial_factory=None):
        self.config, self.gate, self.bus_lock, self.shutdown = config, gate, bus_lock, shutdown
        self.serial_factory = serial_factory
        self.scan_guard_deadline = None

    def _read_primary(self, address, *, discovery=False, fast_timeout=None, quiet=0.01, final_verification=False):
        address = validate_address(address)
        if not self.bus_lock.owned_by_current_thread() or self.shutdown.is_set():
            raise RuntimeError("address probe unavailable")
        factory = self.serial_factory
        if factory is None:
            from serial import Serial
            factory = Serial
        frame = bytes((0x10,0x5B,address,(0x5B+address)&255,0x16))
        try:
            with factory(self.config["serial_port"], baudrate=int(self.config.get("baud",2400)),
                         bytesize=8, parity="E", stopbits=1, timeout=2, write_timeout=2) as serial:
                if fast_timeout is not None:
                    # Never discard already buffered bytes in experimental mode.
                    if serial.in_waiting:
                        self.gate.invalidate_primary_probe()
                        raise ValueError('unexpected buffered input before probe')
                    written=self.gate.write_primary_probe(serial,frame,interval=fast_timeout,quiet=quiet,defer_completion=True,scan_transition=True)
                elif final_verification:
                    if serial.in_waiting:
                        raise ValueError('unexpected buffered input before final verification')
                    written=self.gate.write_primary_probe(serial,frame,quiet=quiet,defer_completion=True)
                else:
                    serial.reset_input_buffer()
                    send = self.gate.write_primary_probe if discovery else self.gate.write
                    written=send(serial,frame,defer_completion=True)
                if written != len(frame):
                    raise OSError("partial primary probe")
                if fast_timeout is None:
                    raw=receive_window(serial)
                else:
                    # Short first-byte window only; any byte triggers full conservative receive.
                    serial.timeout=fast_timeout
                    first=serial.read(1)
                    serial.timeout=2
                    raw=first+receive_window(serial,limit=261) if first else b''
                    if serial.in_waiting:
                        raise ValueError('extra buffered input')
                capture("RX",raw)
            self.gate.complete_read_exchange()
            if discovery or final_verification:
                continued = self.gate.complete_primary_probe(address, raw, fast_response=fast_timeout is not None)
                if raw and not continued:
                    self.gate.invalidate_primary_probe()
        except Exception:
            # Include failed reads, partial TX, and adapter-close failures.
            # A failed exchange must never retain the silent-probe shortcut.
            self.gate.invalidate_primary_probe()
            raise
        return raw

    def check(self, address):
        return assess_destination(address,{},"",self._read_primary(address, discovery=True),checked=True)

    def check_fast(self, address, timeout, quiet=0.01):
        if int(self.config.get('baud',2400)) != 2400:
            return self.check(address)
        return assess_destination(address,{},'',self._read_primary(address,discovery=True,fast_timeout=timeout,quiet=quiet),checked=True)

    def test_observation(self, address, *, fast=False):
        """Classify the actual reply and decode identity from that same exchange."""
        raw = self._read_primary(address, discovery=True,
            fast_timeout=.2 if fast and int(self.config.get("baud", 2400)) == 2400 else None)
        result = assess_destination(address, {}, "", raw, checked=True)
        identity = None
        if result.value == "occupied":
            from dataclasses import asdict
            from mbus_probe import validate
            identity = asdict(SecondaryIdentity.from_decoded(validate(raw)))
        return result, identity

    def begin_quiet_guard(self):
        if not self.bus_lock.owned_by_current_thread():
            raise RuntimeError('shared bus lease required')
        self.gate.invalidate_primary_probe()

    def reservation_guard(self):
        """Establish durable quiet protection under the existing bus lease."""
        self.begin_quiet_guard()
        return self.gate.eligible

    def reservation_ready(self):
        """A countdown alone cannot authorize a new operation."""
        from bus_timing import AddressSafetyBlocked
        try:
            self.gate.check_address_safety()
        except AddressSafetyBlocked:
            return False
        return self.gate.ready() and not self.shutdown.is_set()

    def finish_scan(self):
        # Called under the shared bus lease before publishing terminal status.
        self.begin_quiet_guard()
        self.scan_guard_deadline = self.gate.eligible

    def remaining_guard(self):
        if self.scan_guard_deadline is None:
            return 0.0
        return max(0.0,self.scan_guard_deadline-self.gate.monotonic())

    def check_conservative(self, address):
        self.begin_quiet_guard()
        return assess_destination(address,{},'',self._read_primary(address),checked=True)

    def observe_final_identity(self,address):
        from mbus_probe import validate
        raw=self._read_primary(address,final_verification=True)
        decoded=validate(raw)
        identity=SecondaryIdentity.from_decoded(decoded)
        if decoded.get('address')!=address:
            raise ValueError('primary response address mismatch')
        return identity

    def observe_identity(self, address):
        return self.observe_identity_and_number(address)[0]

    def observe_identity_and_number(self, address):
        from mbus_probe import validate
        raw=self._read_primary(address)
        decoded=validate(raw)
        identity=SecondaryIdentity.from_decoded(decoded)
        if decoded.get("address") != address:
            raise ValueError("primary response address mismatch")
        return identity, reported_device_number(raw,identity)


def build_read_only_jobs(config, registry, gate, bus_lock, shutdown, *, serial_factory=None):
    transport=ReadOnlyAddressTransport(config,gate,bus_lock,shutdown,serial_factory)
    # Deliberately no change job until physical evidence and activation approval.
    return AddressSearchJob(registry,transport,bus_lock,shutdown), None



def build_experimental_change_job(config, registry, gate, journal, bus_lock, shutdown, *, serial_factory=None):
    """Single-meter beta: operator-attested topology, independently entered label.
    
    Configuration is an operator attestation, not measured proof of topology.
    Every transaction still requires fresh exact identity and fabrication number.
    """
    if config.get("address_test_isolated") is not True:
        return None
    try:
        import re
        identity = SecondaryIdentity(config.get("address_test_meter_id"),
            config.get("address_test_manufacturer"), config.get("address_test_version"),
            config.get("address_test_medium"))
        number = config.get("address_test_device_number")
        if not isinstance(number,str) or not re.fullmatch(r"[0-9]{8}",number):
            return None
    except (ValueError,TypeError):
        return None

    def qualified(meter_id,address):
        with registry.lock:
            if (shutdown.is_set() or registry.persistence_failed or registry.quarantined
                    or meter_id != identity.meter_id or set(registry.selected) != {meter_id}
                    or registry.identities.get(meter_id,identity) != identity):
                return False
            if journal.blocked():
                try:
                    intent=journal.load()
                    return (intent is not None and intent.identity==identity
                            and intent.old_address==address
                            and registry.selected[meter_id] in (intent.old_address,intent.new_address))
                except (ValueError,OSError,TypeError,KeyError):
                    return False
            return registry.selected[meter_id]==address

    def exclusive(observed, device_number, raw):
        # Physical isolation is explicitly attested, not inferred from an ACK.
        return (observed==identity and device_number==number
                and reported_device_number(raw,identity)==number
                and config.get("address_test_isolated") is True
                and set(registry.selected)=={identity.meter_id})

    return build_qualified_change_job(config,registry,gate,journal,bus_lock,shutdown,
        qualification=qualified,serial_resolver=lambda i:number if i==identity else None,
        exclusivity=exclusive,serial_factory=serial_factory, enrollment_identity=identity)


def build_qualified_change_job(config, registry, gate, journal, bus_lock, shutdown,
                               *, qualification=None, serial_resolver=None,
                               exclusivity=None, serial_factory=None, enrollment_identity=None):
    """Runtime assembly boundary; never infer qualification from configuration."""
    if not all(callable(x) for x in (qualification,serial_resolver,exclusivity)):
        return None
    if config.get("allow_address_write") is not True and not journal.blocked():
        return None
    from address_change_job import AddressChangeJob
    controller=AddressTransactionRuntime(config,registry,gate,journal,bus_lock,shutdown,
        qualification=qualification,serial_resolver=serial_resolver,
        exclusivity=exclusivity,serial_factory=serial_factory, enrollment_identity=enrollment_identity)
    return AddressChangeJob(controller,shutdown,first_write_admission=controller.admission)


class AddressTransactionRuntime:
    """Qualified transaction adapter. One exclusive serial session per operation.

    No default qualification or exclusivity provider is available. Production
    must not construct this adapter until the physical evidence is accepted.
    """
    def __init__(self, config, registry, gate, journal, bus_lock, shutdown,
                 *, qualification, serial_resolver, exclusivity, serial_factory=None, enrollment_identity=None):
        from first_write_admission import FirstWriteAdmission
        if not all(callable(x) for x in (qualification,serial_resolver,exclusivity)):
            raise ValueError("independent evidence providers required")
        self.config,self.registry,self.gate,self.journal=config,registry,gate,journal
        self.bus_lock,self.shutdown=bus_lock,shutdown
        self.qualification,self.serial_resolver,self.exclusivity=qualification,serial_resolver,exclusivity
        self.serial_factory=serial_factory
        self.enrollment_identity=enrollment_identity
        self.admission=FirstWriteAdmission(config.get("allow_address_write") is True,qualification)
        self.destination_evidence=None
        self.failed=False

    def _execute(self, operation, meter_id, old_address):
        from address_controller import AddressController
        from address_transport import CandidateTransport
        with self.bus_lock, self.registry.lock:
            if self.shutdown.is_set() or self.qualification(meter_id,old_address) is not True:
                raise ValueError("qualified isolated operation required")
            factory=self.serial_factory
            if factory is None:
                from serial import Serial
                factory=Serial
            # Preserve full pacing after the final receive/close, including faults.
            try:
                self.gate.invalidate_primary_probe()
                with factory(self.config["serial_port"],baudrate=int(self.config.get("baud",2400)),
                             bytesize=8,parity="E",stopbits=1,timeout=2,write_timeout=2,
                             exclusive=True) as serial:
                    transport=CandidateTransport(serial,self.gate,self.journal,self.bus_lock,
                                                 self.serial_resolver,self.exclusivity,shutdown=self.shutdown)
                    if self.enrollment_identity is not None and not self.journal.blocked():
                        identity=self.enrollment_identity
                        raw=transport._exchange(bytes((0x10,0x5B,old_address,(0x5B+old_address)&255,0x16)))
                        from address_response import readback_address
                        if (readback_address(raw,identity)!=old_address or
                                self.exclusivity(identity,self.serial_resolver(identity),raw) is not True):
                            raise ValueError('fresh primary identity qualification failed')
                        self.registry.enroll_identity(meter_id,identity,exclusive=True,confirmed=True,physical_address=old_address)
                    # Controller runs inside this already-owned nonrecursive lease.
                    from contextlib import nullcontext
                    controller=AddressController(self.registry,self.journal,nullcontext(),transport)
                    result=operation(controller)
                    self.destination_evidence=controller.destination_evidence
                    self.failed=self.failed or controller.failed
                return result
            except Exception:
                self.failed=True
                raise
            finally:
                try:
                    self.gate.invalidate_primary_probe()
                except Exception:
                    self.failed=True
                    raise

    def change(self,meter_id,new_address,*,expected_old,confirmed=False,
               override=False,accepted_risk=None,resolve_conflict=False):
        self.admission.require(meter_id,expected_old,new_address,confirmed=confirmed,
                               override=override,accepted_risk=accepted_risk)
        if self.failed or resolve_conflict is not False:
            raise ValueError("first-write transaction unavailable")
        return self._execute(lambda controller: controller.change(
            meter_id,new_address,expected_old=expected_old,confirmed=True),
            meter_id,expected_old)

    def recover(self,*,expected_meter=None,expected_transaction=None):
        # Recovery does not enable writing, even if the config switch is off.
        intent=self.journal.load()
        if (intent is None or intent.identity.meter_id!=expected_meter
                or self.journal.transaction_id()!=expected_transaction):
            return "recovery_required"
        result=self._execute(lambda controller: controller.recover(
            expected_meter=expected_meter,expected_transaction=expected_transaction),
            expected_meter,intent.old_address)
        if result in ("verified_old","verified_new"):
            self.failed=False
        return result

    def enroll_quarantined_peer(self,*args,**kwargs):
        raise ValueError("quarantine enrollment not enabled in first-write beta")

    def verify_quarantine(self,*args,**kwargs):
        raise ValueError("quarantine operations not enabled in first-write beta")


def enroll_verified_identity(registry, transport, bus_lock, meter_id, address, *,
                             expected_identity, bindings, verify_exclusivity, confirmed=False):
    """Read-only physical enrollment candidate; no default evidence provider.

    Expected identity and binding must come from independently established
    evidence, not from the same response used here. Never infer exclusivity
    from a clean telegram. No runtime caller is installed yet.
    """
    validate_address(address)
    if (confirmed is not True or not isinstance(expected_identity,SecondaryIdentity)
            or expected_identity.meter_id != meter_id or not callable(verify_exclusivity)):
        raise ValueError("explicit verified identity required")
    from address_policy import DeviceNumberBindings
    if not isinstance(bindings,DeviceNumberBindings):
        raise ValueError("verified device-number bindings required")
    number=bindings.resolve(expected_identity)
    if number is None:
        raise ValueError("device-number binding unavailable")
    with bus_lock, registry.lock:
        if (registry.persistence_failed or registry.quarantined
                or registry.selected.get(meter_id)!=address
                or any(k!=meter_id and a==address for k,a in registry.selected.items())
                or registry.identities.get(meter_id,expected_identity)!=expected_identity):
            raise ValueError("identity enrollment unavailable")
        observed,reported=transport.observe_identity_and_number(address)
        if observed!=expected_identity or reported!=number or verify_exclusivity(observed,number,address) is not True:
            raise ValueError("physical identity proof unavailable")
        registry.enroll_identity(meter_id,observed,exclusive=True,confirmed=True,physical_address=address)
        return observed


def run_isolated_diagnostic(config, registry, gate, bus_lock, shutdown, admission,
                            *, identity, number, address, confirmed=False,
                            single_meter=False, recovery=False, serial_factory=None):
    """Offline integration candidate; no HTTP/CLI entrypoint or automatic start.

    Admission remains held throughout the maintenance operation. Serial opens
    only under the shared bus lease. Recovery bypasses admission's combined
    safety flag only; gate still checks independent address safety.
    """
    from address_diagnostic import run_diagnostic, DiagnosticEvidence
    from bus_timing import StableBusTiming
    if isinstance(gate, StableBusTiming) and not recovery:
        raise ValueError('new diagnostic disabled in stable build')
    from address_telegrams import select_enhanced
    if confirmed is not True or single_meter is not True or not isinstance(identity,SecondaryIdentity):
        raise ValueError("explicit isolated diagnostic approval required")
    validate_address(address)
    select_enhanced(identity,number)
    guard=gate.diagnostic_guard
    if guard is None or guard.blocked()!=bool(recovery):
        raise ValueError("diagnostic guard state mismatch")
    if shutdown.is_set():
        raise RuntimeError("service stopping")
    with admission.start("diagnostic_recover" if recovery else "address_diagnostic",worker=True), bus_lock:
        with registry.lock:
            if (registry.persistence_failed or registry.quarantined
                    or registry.selected!={identity.meter_id:address}):
                raise ValueError("exactly one matching registered meter required")
        if gate.address_blocked is not None and gate.address_blocked():
            raise ValueError("address safety state blocks diagnostic")
        if guard.blocked()!=bool(recovery) or shutdown.is_set():
            raise RuntimeError("diagnostic state changed")
        if recovery:
            from dataclasses import asdict
            record=guard.load()
            if (record["identity"]!=asdict(identity) or record["number"]!=number
                    or record["address"]!=address):
                raise ValueError("diagnostic recovery identity mismatch")
        factory=serial_factory
        if factory is None:
            from serial import Serial
            factory=Serial
        evidence=DiagnosticEvidence(guard.path.parent/"diagnostic-evidence",identity,number,address,recovery)
        stable=isinstance(gate, StableBusTiming)
        result={"status":"cleanup_required" if recovery else "failed","cleanup_verified":False}
        try:
            with factory(config["serial_port"],baudrate=int(config.get("baud",2400)),
                         bytesize=8,parity="E",stopbits=1,timeout=2,write_timeout=2,
                         exclusive=True) as serial:
                result=run_diagnostic(serial,gate,bus_lock,shutdown,identity=identity,
                    number=number,address=address,guard=guard,confirmed=True,
                    single_meter=True,recovery=recovery,owned_lease=True,evidence=evidence,
                    primary_recovery=stable,defer_guard_finish=stable)
            if stable:
                gate.complete_address_exchange()
                if result["status"]=="primary_verified_pending_close":
                    if shutdown.is_set() or (gate.address_blocked is not None and gate.address_blocked()):
                        raise RuntimeError("recovery state changed before completion")
                    if gate.persistence_failed:
                        raise RuntimeError("timing persistence failed")
                    evidence.record("serial_closed",{"guard_id":record["id"]})
                    evidence.record("cleanup_verified",{"guard_id":record["id"]})
                    guard.finish(record)
                    result.update(status="restored",cleanup_verified=True)
        except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
            if not stable:
                raise
            result.update(status="cleanup_required",cleanup_verified=False,cleanup_error=str(exc))
            try:
                gate.complete_address_exchange()
            except (OSError,ValueError,RuntimeError):
                pass
        if stable:
            try:
                evidence.record("runtime_result",result)
            except OSError as exc:
                result["evidence_error"]=str(exc)
                if result["cleanup_verified"]:
                    result["status"]="evidence_failed"
        result['evidence_file']=evidence.path.name
        return result
