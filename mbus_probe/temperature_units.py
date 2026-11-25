"""Presentation-only conversion of canonical Celsius and Kelvin differences."""
import math

UNITS = ("C", "K", "F")
SYMBOLS = {"C": "°C", "K": "K", "F": "°F"}
ABSOLUTE = frozenset(("flow_temperature", "return_temperature"))
DIFFERENCE = "temperature_difference"

def convert_temperature(kind, value, source, target):
    """Return numeric value and display unit; never mutate a measurement."""
    if kind not in ABSOLUTE and kind != DIFFERENCE:
        return value, source
    if source not in UNITS or target not in UNITS:
        raise ValueError("unsupported temperature unit")
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("invalid temperature")
    if source == target:
        return value, SYMBOLS[target]
    if kind == DIFFERENCE:
        base = value * 5 / 9 if source == "F" else value
        result = base * 9 / 5 if target == "F" else base
    else:
        base = value - 273.15 if source == "K" else (value - 32) * 5 / 9 if source == "F" else value
        result = base + 273.15 if target == "K" else base * 9 / 5 + 32 if target == "F" else base
    return result, SYMBOLS[target]
