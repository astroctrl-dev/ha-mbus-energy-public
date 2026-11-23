"""Manual T230 frame-3 diagnostic for the selected M-Bus meter.

CI=50 application reset changes volatile interface frame selection. The CLI requires confirmation; app use is gated by a disabled-by-default option.
"""
import argparse
import json
import sys
import time
from mbus_probe import validate
from ha_measurements import select_measurements


class RestorationError(RuntimeError):
    """Normal frame was not verified. Ordinary polling must remain stopped."""


def select_frame_three(address):
    if not 0 <= address <= 250:
        raise ValueError("primary address outside 0..250")
    data = bytes((0x53, address, 0x50, 0x03))
    return bytes((0x68, 0x04, 0x04, 0x68)) + data + bytes((sum(data) & 255, 0x16))


def restore_normal_frame(address):
    if not 0 <= address <= 250:
        raise ValueError("primary address outside 0..250")
    data = bytes((0x53, address, 0x50))
    return bytes((0x68, 0x03, 0x03, 0x68)) + data + bytes((sum(data) & 255, 0x16))


def read_response(ser):
    first = ser.read(1)
    if first == b"\xe5" or not first:
        return first
    if first != b"\x68":
        return first
    header = first + ser.read(3)
    if len(header) != 4 or header[1] != header[2] or header[3] != 0x68:
        return header
    return header + ser.read(header[1] + 2)


def extract_months(frame, expected_id):
    decoded = validate(frame)
    if decoded.get("type") != "long" or decoded.get("ci") != 0x72:
        raise ValueError("not a variable-data meter response")
    if decoded.get("meter_id") != expected_id or decoded.get("manufacturer") != "LUG":
        raise ValueError("meter identity/manufacturer mismatch")
    if decoded.get("medium_code") != 4 or decoded.get("status") not in (0, 0x10):
        raise ValueError("unexpected meter medium/status")
    months = {}
    for record in decoded["records"]:
        storage = record.get("storage")
        if (record.get("kind") == "energy" and record.get("tariff") == 0
                and record.get("function") == 0 and record.get("subunit", 0) == 0
                and isinstance(storage, int) and 2 <= storage <= 25):
            if storage in months:
                raise ValueError("duplicate month storage number")
            unit = record.get("unit")
            value = record.get("value")
            if unit not in ("kWh", "MJ") or value is None or value < 0:
                raise ValueError("invalid monthly energy")
            months[storage] = {"month_back": storage - 1, "value": value, "unit": unit}
    if set(months) != set(range(2, 26)):
        raise ValueError("response does not contain exactly 24 month energy records")
    return [months[n] for n in range(2, 26)]


def verify_normal_frame(frame, address, expected_id):
    """ACK is insufficient: require a checksum-valid ordinary 7-value read."""
    decoded = validate(frame)
    if decoded.get("address") != address:
        raise ValueError("restored normal frame address mismatch")
    return select_measurements(decoded, expected_id)


def run(port, baud, address, meter_id, timeout=5):
    import serial
    if baud not in (300, 2400):
        raise ValueError("T230 documented baud is 300 or 2400")
    if not (len(meter_id) == 8 and meter_id.isdigit()):
        raise ValueError("expected meter ID must be eight decimal digits")
    with serial.Serial(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                       timeout=timeout, write_timeout=timeout) as ser:
        ser.reset_input_buffer()
        selected = False
        last_request_at = None
        try:
            selected = True  # Attempt restore even if write/ACK fails.
            last_request_at = time.monotonic()
            ser.write(select_frame_three(address))
            ser.flush()
            if read_response(ser) != b"\xe5":
                raise ValueError("frame selection was not acknowledged")
            # Battery-powered T230: leave more than one minute before each read.
            time.sleep(max(0.0, 61.0 - (time.monotonic() - last_request_at)))
            ser.reset_input_buffer()
            req = bytes((0x10, 0x5B, address, (0x5B + address) & 255, 0x16))
            last_request_at = time.monotonic()
            ser.write(req)
            ser.flush()
            frame = read_response(ser)
            header = validate(frame)
            if header.get("address") != address or header.get("control") not in (8, 24):
                raise ValueError("monthly response address/control mismatch")
            return extract_months(frame, meter_id)
        finally:
            if selected:
                try:
                    ser.reset_input_buffer()
                    ser.write(restore_normal_frame(address))
                    ser.flush()
                    if read_response(ser) != b"\xe5":
                        raise ValueError("restore was not acknowledged")
                    # ACK alone does not prove that ordinary records are back.
                    time.sleep(max(0.0, 61.0 - (time.monotonic() - last_request_at)))
                    ser.reset_input_buffer()
                    req = bytes((0x10, 0x5B, address, (0x5B + address) & 255, 0x16))
                    ser.write(req)
                    ser.flush()
                    verify_normal_frame(read_response(ser), address, meter_id)
                    # Leave the bus idle before regular polling resumes.
                    time.sleep(61)
                except Exception as exc:
                    raise RestorationError("normal frame not verified; stop polling") from exc


def main():
    p = argparse.ArgumentParser(description="Manual T230 24-month diagnostic; changes volatile M-Bus frame selection")
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, choices=[300, 2400], default=2400)
    p.add_argument("--address", type=int, required=True)
    p.add_argument("--expected-id", required=True, help="Actual meter ID; do not include in shared logs")
    p.add_argument("--confirm-interface-reset", action="store_true")
    args = p.parse_args()
    if not args.confirm_interface_reset:
        p.error("requires explicit --confirm-interface-reset after approval of physical test")
    try:
        months = run(args.port, args.baud, args.address, args.expected_id)
    except Exception as exc:
        print(f"monthly diagnostic failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"count": len(months), "monthly_energy": months}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
