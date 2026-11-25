#!/usr/bin/env python3
"""Minimal, explicitly read-only wired M-Bus probe (EN 13757).

Requires pyserial. No address scanning or write/configuration commands.
Only sends REQ_UD2 to a single explicitly supplied primary address.
"""
from bus_timing import write_frame
from raw_telegram_log import receive, operation
import argparse
import json
from datetime import datetime, timezone

def request(address):
    if not 0 <= address <= 250:
        raise ValueError("Primary address must be 0..250 (no broadcast)")
    return bytes((0x10, 0x5B, address, (0x5B + address) & 0xFF, 0x16))

def validate(frame):
    if not frame:
        raise ValueError("timeout: no meter bytes received")
    if frame == b"\xe5":
        raise ValueError("ACK only: not a meter data telegram")
    if frame[0] == 0x10:
        if len(frame) != 5 or frame[4] != 0x16 or (sum(frame[1:3]) & 255) != frame[3]:
            raise ValueError("invalid short frame")
        return {"type": "short", "control": frame[1], "address": frame[2]}
    if frame[0] != 0x68 or len(frame) < 9:
        raise ValueError("unknown/truncated frame")
    length = frame[1]
    if frame[2] != length or frame[3] != 0x68 or len(frame) != length + 6:
        raise ValueError("invalid length/start delimiter")
    if frame[-1] != 0x16 or (sum(frame[4:-2]) & 255) != frame[-2]:
        raise ValueError("invalid checksum/stop delimiter")
    info = {"type": "long", "control": frame[4], "address": frame[5], "ci": frame[6]}
    if frame[6] == 0x72 and len(frame) >= 19:
        header = frame[7:19]
        bcd = "".join(f"{b >> 4:X}{b & 15:X}" for b in header[3::-1])
        if all(c in "0123456789" for c in bcd):
            info["meter_id"] = bcd
        man = int.from_bytes(header[4:6], "little")
        letters = [((man >> shift) & 31) for shift in (10, 5, 0)]
        if all(1 <= x <= 26 for x in letters):
            info["manufacturer"] = "".join(chr(x + 64) for x in letters)
        info["version"] = header[6]
        info["medium_code"] = header[7]
        info["access_number"] = header[8]
        info["status"] = header[9]
        info["data_records_hex"] = frame[19:-2].hex(" ")
        from mbus_records import decode_records
        info["records"] = decode_records(frame[19:-2])
    return info

@operation("normal_read")
@receive
def read_one(port, baud, address, timeout, first_byte_timeout=None):
    import serial
    tx = request(address)
    with serial.Serial(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                       timeout=timeout, write_timeout=timeout) as ser:
        ser.reset_input_buffer()
        write_frame(ser, tx)
        ser.flush()
        if first_byte_timeout is not None:
            ser.timeout = first_byte_timeout
        first = ser.read(1)
        ser.timeout = timeout
        if not first:
            return tx, b""
        if first == b"\xe5":
            return tx, first
        if first == b"\x10":
            return tx, first + ser.read(4)
        if first == b"\x68":
            head = first + ser.read(3)
            if len(head) != 4:
                return tx, head
            return tx, head + ser.read(head[1] + 2)
        return tx, first

def main():
    p = argparse.ArgumentParser(description="Read-only single-address M-Bus REQ_UD2 probe")
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, choices=[300, 600, 1200, 2400, 4800, 9600], default=2400)
    p.add_argument("--address", type=int, required=True, help="Known primary address 0..250")
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--output", help="Optional local JSON evidence file (review/redact before sharing)")
    args = p.parse_args()
    event = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
             "port": args.port, "baud": args.baud, "address": args.address,
             "serial": "8E1", "result": "not_started"}
    try:
        tx, rx = read_one(args.port, args.baud, args.address, args.timeout)
        event.update(request_hex=tx.hex(" "), response_hex=rx.hex(" "))
        decoded = validate(rx)
        if decoded["type"] != "long" or decoded.get("control") not in (0x08, 0x18):
            raise ValueError("valid frame, but not an RSP_UD meter-data response")
        event.update(result="valid_data_frame", decoded=decoded)
        print(json.dumps(event, indent=2))
        print("NOTE: Verify decoded values against the physical meter display.")
        rc = 0
    except (OSError, ValueError) as exc:
        event.update(result="failed", error=str(exc))
        print(json.dumps(event, indent=2))
        rc = 1
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
