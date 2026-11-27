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

    def _read_primary(self, address, *, discovery=False):
        address = validate_address(address)
        if not self.bus_lock.owned_by_current_thread() or self.shutdown.is_set():
            raise RuntimeError("address probe unavailable")
        factory = self.serial_factory
        if factory is None:
            from serial import Serial
            factory = Serial
        frame = bytes((0x10,0x5B,address,(0x5B+address)&255,0x16))
        with factory(self.config["serial_port"], baudrate=int(self.config.get("baud",2400)),
                     bytesize=8, parity="E", stopbits=1, timeout=2, write_timeout=2) as serial:
            serial.reset_input_buffer()
            send = self.gate.write_primary_probe if discovery else self.gate.write
            if send(serial,frame) != len(frame):
                raise OSError("partial primary probe")
            raw=receive_window(serial)
            capture("RX",raw)
        if discovery:
            self.gate.complete_primary_probe(address, raw)
        return raw

    def check(self, address):
        return assess_destination(address,{},"",self._read_primary(address, discovery=True),checked=True)

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
        with factory(config["serial_port"],baudrate=int(config.get("baud",2400)),
                     bytesize=8,parity="E",stopbits=1,timeout=2,write_timeout=2,
                     exclusive=True) as serial:
            result=run_diagnostic(serial,gate,bus_lock,shutdown,identity=identity,
                number=number,address=address,guard=guard,confirmed=True,
                single_meter=True,recovery=recovery,owned_lease=True,evidence=evidence)
            result['evidence_file']=evidence.path.name
            return result
