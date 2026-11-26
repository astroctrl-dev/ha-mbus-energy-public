"""Read-only primary-address scan; does not send SND_UD or broadcasts."""
from mbus_probe import read_one, validate
from ha_measurements import select_measurements


def scan_bus(port, baud, registry, bus_lock, stop, history_blocked=None):
    rows = []
    errors = []
    try:
        for address in range(251):
            if stop.is_set():
                raise RuntimeError("scan interrupted")
            with registry.lock:
                registry.scan_progress = address
            try:
                with bus_lock:
                    if stop.is_set() or (history_blocked is not None and history_blocked.is_set()):
                        raise RuntimeError("scan interrupted: normal frame unverified or app stopping")
                    _, frame = read_one(port, baud, address, timeout=2,
                                        first_byte_timeout=0.6)
                if not frame:
                    continue
                decoded = validate(frame)
                if (decoded.get("type") != "long" or
                        decoded.get("control") not in (8, 24) or
                        decoded.get("address") != address or
                        not decoded.get("meter_id")):
                    raise ValueError("response lacks unique long-frame identity")
                try:
                    select_measurements(decoded, decoded["meter_id"])
                    supported = True
                except ValueError:
                    supported = False
                rows.append({"meter_id": decoded["meter_id"], "address": address,
                             "manufacturer": decoded.get("manufacturer", "unknown"),
                             "supported": supported})
                # Expose the ID and primary address as soon as the reply is validated.
                registry.set_found(rows)
            except (OSError, ValueError) as exc:
                # Do not log the raw response or imply a collision can be identified.
                errors.append({"address": address, "reason": type(exc).__name__})
        registry.set_found(rows)
        with registry.lock:
            registry.scan_errors = errors
            registry.scan_progress = 251
            registry.scan_status = "completed"
    except (OSError, ValueError, RuntimeError) as exc:
        with registry.lock:
            registry.scan_errors = errors + [{"reason": type(exc).__name__}]
            registry.scan_status = "failed"
