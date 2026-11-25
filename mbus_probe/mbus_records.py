"""Conservative EN 13757-3 variable data record decoder.

Unknown VIFs are retained as raw data; unsupported DIF types stop parsing rather
than silently assigning incorrect units. All measurements require frame validation
by mbus_probe.validate before calling this module.
"""
from decimal import Decimal
from datetime import datetime

def bcd_le(raw):
    digits = []
    negative = bool(raw) and (raw[-1] >> 4) == 0xF
    for position, b in enumerate(reversed(raw)):
        hi, lo = b >> 4, b & 15
        if position == 0 and negative:
            hi = 0
        if hi > 9 or lo > 9:
            raise ValueError("invalid BCD digit")
        digits.extend((str(hi), str(lo)))
    value = int("".join(digits))
    return -value if negative else value

def vif_unit(vif):
    v = vif & 0x7f
    if 0x00 <= v <= 0x07:
        return "energy", "kWh", Decimal(10) ** (v - 6)
    if 0x08 <= v <= 0x0f:
        return "energy", "MJ", Decimal(10) ** (v - 8 - 6)
    if 0x10 <= v <= 0x17:
        return "volume", "m3", Decimal(10) ** (v - 16 - 6)
    if 0x28 <= v <= 0x2f:
        return "power", "kW", Decimal(10) ** (v - 0x28 - 6)
    if 0x38 <= v <= 0x3f:
        return "flow", "m3/h", Decimal(10) ** (v - 0x38 - 6)
    if 0x58 <= v <= 0x5b:
        return "flow_temperature", "C", Decimal(10) ** (v - 0x58 - 3)
    if 0x5c <= v <= 0x5f:
        return "return_temperature", "C", Decimal(10) ** (v - 0x5c - 3)
    if 0x60 <= v <= 0x63:
        return "temperature_difference", "K", Decimal(10) ** (v - 0x60 - 3)
    if v in (0x22, 0x23):
        return "missing_time", "h" if v == 0x22 else "d", Decimal(1)
    if v in (0x26, 0x27):
        return "flow_time", "h" if v == 0x26 else "d", Decimal(1)
    if v == 0x70:
        return "averaging_interval", "s", Decimal(1)
    if v == 0x71:
        return "averaging_interval", "min", Decimal(1)
    if v == 0x72:
        return "averaging_interval", "h", Decimal(1)
    if v == 0x74:
        return "actuality_duration", "s", Decimal(1)
    if v == 0x78:
        return "fabrication_number", None, Decimal(1)
    return None, None, None

def decode_records(data):
    result = []
    i = 0
    lengths = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 4, 6: 6, 7: 8, 9: 1, 10: 2, 11: 3, 12: 4, 14: 6}
    while i < len(data):
        start = i
        dif = data[i]
        i += 1
        if dif in (0x0f, 0x1f):
            result.append({"raw_hex": data[start:].hex(" "), "kind": "manufacturer_specific"})
            break
        if dif in (0x2f,):
            continue
        difes = []
        more = bool(dif & 0x80)
        while more:
            if i >= len(data) or len(difes) >= 10:
                raise ValueError("truncated/too many DIFE")
            b = data[i]; i += 1; difes.append(b)
            more = bool(b & 0x80)
        if i >= len(data):
            raise ValueError("missing VIF")
        vif = data[i]; i += 1
        vifes = []
        more = bool(vif & 0x80)
        while more:
            if i >= len(data) or len(vifes) >= 10:
                raise ValueError("truncated/too many VIFE")
            b = data[i]; i += 1; vifes.append(b)
            more = bool(b & 0x80)
        # T230 frame 2 contains vendor diagnostic labels following FC 6E.
        # Only the observed fixed-width labelled diagnostic format is supported;
        # retain the value as opaque data rather than interpreting its meaning.
        label_hex = None
        if dif == 0x34 and not difes and vif == 0xfc and vifes == [0x6e]:
            if i >= len(data) or data[i] not in (2, 3):
                raise ValueError("unsupported T230 diagnostic label length")
            label_length = data[i]
            i += 1
            if i + label_length > len(data):
                raise ValueError("truncated T230 diagnostic label")
            label = data[i:i+label_length]
            if any(not 0x20 <= b <= 0x7e for b in label):
                raise ValueError("invalid T230 diagnostic label")
            label_hex = label.hex(" ")
            i += label_length
        typ = dif & 0x0f
        if typ not in lengths:
            raise ValueError(f"unsupported DIF encoding 0x{typ:02x} at offset {start}")
        n = lengths[typ]
        if i + n > len(data):
            raise ValueError("truncated record payload")
        raw = data[i:i+n]; i += n
        storage = (dif >> 6) & 1
        tariff = 0
        subunit = 0
        for index, extension in enumerate(difes):
            storage |= (extension & 0x0f) << (1 + 4 * index)
            tariff |= ((extension >> 4) & 3) << (2 * index)
            subunit |= ((extension >> 6) & 1) << index
        record = {"offset": start, "dif": dif, "dife_hex": bytes(difes).hex(" "),
                  "vif": vif, "vife_hex": bytes(vifes).hex(" "), "raw_hex": raw.hex(" "),
                  "storage": storage, "tariff": tariff, "subunit": subunit,
                  "function": (dif >> 4) & 3}
        record["current_record"] = storage == 0 and tariff == 0 and subunit == 0 and record["function"] == 0
        kind, unit, scale = vif_unit(vif)
        if kind == "missing_time" and record["function"] == 0:
            kind = "operating_time"
        # Extended VIFs need explicit interpretation; do not mislabel.
        if vifes:
            kind = unit = scale = None
        if (vif & 0x7f) == 0x6d and typ == 4 and not vifes:
            minute, hour, day, month = (raw[0] & 63, raw[1] & 31,
                                         raw[2] & 31, raw[3] & 15)
            year = ((raw[2] >> 5) & 7) | ((raw[3] >> 4) << 3)
            if (dif == 0xc4 and difes == [0x8f, 0x0f] and vif == 0x6d
                    and year == 127 and month == 15 and not raw[0] & 0x80
                    and 1 <= day <= 31 and hour < 24 and minute < 60):
                record.update(kind="monthly_set_day", day=day, hour=hour, minute=minute)
            elif year == 127 and record["storage"] == 510:
                record.update(kind="annual_set_day", month=month, day=day)
            elif raw[0] & 0x80 or year > 99:
                record["kind"] = "invalid_meter_time"
            else:
                try:
                    stamp = datetime(2000 + year, month, day, hour, minute)
                except ValueError:
                    record["kind"] = "invalid_meter_time"
                else:
                    record.update(kind="meter_local_time", value=stamp.isoformat(timespec="minutes"),
                                  timezone="unspecified", summer_time=bool(raw[1] & 0x80))
        elif typ in (9, 10, 11, 12, 14):
            try:
                value = bcd_le(raw)
                if kind is not None:
                    record.update(kind=kind, unit=unit, value=float(Decimal(value)*scale))
                else:
                    record.update(kind="unknown_vif", bcd_value=value)
            except ValueError:
                record["kind"] = "invalid_bcd"
        elif typ in (1, 2, 3, 4, 6, 7):
            if typ == 3:
                integer = int.from_bytes(raw, "little", signed=False)
            else:
                integer = int.from_bytes(raw, "little", signed=True)
            if kind is not None:
                record.update(kind=kind, unit=unit, value=float(Decimal(integer)*scale))
            else:
                record.update(kind="unknown_vif", integer=integer)
        else:
            record["kind"] = "unsupported_value"
        if label_hex is not None:
            record.update(kind="vendor_diagnostic_opaque", label_hex=label_hex)
        result.append(record)
    return result
