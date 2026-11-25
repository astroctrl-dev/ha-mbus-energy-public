"""Isolated frame-4 acquisition transaction. Not wired into production polling."""
from datetime import datetime, timezone
from mbus_probe import validate
from monthly_diagnostic import restore_normal_frame, verify_normal_frame, RestorationError
from archive_month import decode_month
from archive_supplement import supplement_month

class ArchiveDataError(ValueError):
    """Acquisition rejected, but normal frame was successfully restored."""


def select_archive(address, month_back):
    if type(address) is not int or not 0 <= address <= 250:
        raise ValueError("invalid primary address")
    if type(month_back) is not int or not 1 <= month_back <= 24:
        raise ValueError("invalid month")
    selector = bytes((0x30 + (month_back & 15),))
    if month_back >= 16:
        selector += b"\x01"
    data = bytes((0x53, address, 0x50)) + selector
    return bytes((0x68,len(data),len(data),0x68))+data+bytes((sum(data)&255,0x16))

def collect_one(snapshot, address, meter_id, month_back, exchange, *, approved=False):
    """Exchange must enforce bus lock, >=60 s spacing and persistent restore guard.
    No file writes; return supplemented copy only after normal verification.
    """
    if approved is not True:
        raise ValueError("physical archive acquisition not approved")
    select = select_archive(address, month_back)
    req = bytes((0x10,0x5b,address,(0x5b+address)&255,0x16))
    failure = None
    try:
        if exchange(select) != b"\xe5":
            raise ValueError("archive selection not acknowledged")
        decoded = validate(exchange(req))
        if (decoded.get("type") != "long" or decoded.get("ci") != 0x72
            or decoded.get("control") not in (8,24) or decoded.get("address") != address
            or decoded.get("meter_id") != meter_id or decoded.get("manufacturer") != "LUG"
            or decoded.get("medium_code") != 4 or decoded.get("status") not in (0,0x10)):
            raise ValueError("archive identity/status mismatch")
        archive = decode_month(decoded, month_back)
        read_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        failure = exc
    finally:
        try:
            if exchange(restore_normal_frame(address)) != b"\xe5":
                raise ValueError("restore not acknowledged")
            verify_normal_frame(exchange(req),address,meter_id)
        except Exception as exc:
            raise RestorationError("normal frame not verified; stop polling") from exc
    if failure is not None:
        raise ArchiveDataError(str(failure)) from failure
    try:
        return supplement_month(snapshot, archive, read_at)
    except (ValueError, KeyError, TypeError) as exc:
        raise ArchiveDataError("archive supplementation rejected") from exc
