"""Read-only address search, one paced probe at a time.

No result proves that an address is free. Cancellation is cooperative between
probes; ordinary bus work may run between probes. No selection or writes.
"""
from address_policy import Availability, validate_address


def search_addresses(addresses, registry, meter_id, transport, bus_lock, stop, progress=None):
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
            if own:
                status = "current_address_conflict" if occupied else "current_address"
            elif occupied:
                status = "occupied_multiple" if known_count > 1 else Availability.OCCUPIED.value
            else:
                try:
                    result = transport.check(address)
                    status = result.value if isinstance(result, Availability) else Availability.FAILED.value
                except (OSError, ValueError, RuntimeError):
                    status = Availability.FAILED.value
        row = {"address": address, "status": status,
               "known_meter_count": known_count if known_count else None}
        rows.append(row)
        if progress is not None:
            progress(dict(row), len(rows), len(candidates))
    return {"results": rows, "cancelled": stop.is_set(), "total": len(candidates)}
