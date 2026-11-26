"""Bounded, manually confirmed frame-5 evidence capture. No automatic schedule.

Caller must own exclusive bus lock, shared timing and durable restoration
marker. Never extract ABCDEF from an unverified layout.
"""
from datetime import datetime, timezone
from mbus_probe import validate, request
from monthly_diagnostic import restore_normal_frame, verify_normal_frame, RestorationError


class CaptureError(ValueError):
    """Capture failed, normal frame verified."""


def select_frame5(address):
    if type(address) is not int or not 0 <= address <= 250:
        raise ValueError("invalid primary address")
    data = bytes((0x53, address, 0x50, 0x05))
    return bytes((0x68, 4, 4, 0x68)) + data + bytes((sum(data) & 255, 0x16))


def validate_capture(frame, address, meter_id):
    decoded = validate(frame)
    if (decoded.get("type") != "long" or decoded.get("ci") != 0x72
            or decoded.get("control") not in (8, 24)
            or decoded.get("address") != address
            or decoded.get("meter_id") != meter_id
            or decoded.get("manufacturer") != "LUG"
            or decoded.get("medium_code") != 4):
        raise ValueError("frame-5 capture identity mismatch")
    # Header status may be abnormal: diagnostics must not infer healthy state.
    # Frame number and layout are intentionally NOT asserted here.
    return decoded


def collect_capture(address, meter_id, exchange, *, approved=False):
    if approved is not True:
        raise ValueError("physical capture not approved")
    if not isinstance(meter_id, str) or len(meter_id) != 8 or not meter_id.isascii() or not meter_id.isdigit():
        raise ValueError("invalid meter identity")
    selection = select_frame5(address)
    req = request(address)
    failure = None
    try:
        if exchange(selection) != b"\xe5":
            raise ValueError("frame-5 selection not acknowledged")
        response = exchange(req)
        validate_capture(response, address, meter_id)
        # A normal telegram after selection is not evidence of a new layout.
        # Keep the raw capture for analysis, but explicitly identify this case.
        try:
            verify_normal_frame(response, address, meter_id)
            normal_layout = True
        except ValueError:
            normal_layout = False
        captured = {"response_hex": response.hex(" "),
                    "read_at_utc": datetime.now(timezone.utc).isoformat(),
                    "layout_verified": False, "normal_layout_detected": normal_layout}
    except Exception as exc:
        failure = exc
    finally:
        restored = False
        last_error = None
        for _ in range(3):
            try:
                if not restored:
                    if exchange(restore_normal_frame(address)) != b"\xe5":
                        raise ValueError("restore not acknowledged")
                    restored = True
                response = exchange(req)
                if not response:
                    raise TimeoutError("normal verification timeout")
                verify_normal_frame(response, address, meter_id)
                break
            except Exception as exc:
                last_error = exc
                if not restored or not isinstance(exc, TimeoutError):
                    restored = False
        else:
            raise RestorationError("normal frame not verified; stop polling") from last_error
    if failure is not None:
        raise CaptureError("frame-5 capture rejected") from failure
    return captured


from bus_timing import shared_timing_active, write_frame
from monthly_diagnostic import read_response
from raw_telegram_log import operation


@operation("diagnostic_frame5")
def read_capture(port, baud, address, meter_id, *, approved=False):
    if approved is not True or not shared_timing_active():
        raise ValueError("capture requires approval and shared timing")
    if baud not in (300, 2400):
        raise ValueError("unsupported baud")
    import serial
    with serial.Serial(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                       timeout=5, write_timeout=5, exclusive=True) as ser:
        def exchange(tx):
            ser.reset_input_buffer()
            if write_frame(ser, tx) != len(tx):
                raise IOError("partial serial write")
            ser.flush()
            return read_response(ser)
        return collect_capture(address, meter_id, exchange, approved=True)


def redact_capture(result):
    """Redact header meter ID and recompute checksum; preserve layout."""
    frame = bytearray.fromhex(result["response_hex"])
    decoded = validate(bytes(frame))
    if decoded.get("ci") != 0x72 or "meter_id" not in decoded:
        raise ValueError("invalid capture evidence")
    frame[7:11] = bytes(4)
    frame[-2] = sum(frame[4:-2]) & 255
    return {"response_hex": frame.hex(" "), "read_at_utc": result["read_at_utc"],
            "layout_verified": False, "header_id_redacted": True,
            "normal_layout_detected": result.get("normal_layout_detected"),
            "privacy_note": "Other payload fields may contain identifying data or measurements."}
