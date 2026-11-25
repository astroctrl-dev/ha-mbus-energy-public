"""Persistent seasonal transition evidence. No bus I/O or clock writes."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def latest_transition(now, zone_name):
    """Most recent actual DST offset transition, located in UTC."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware time required")
    zone = ZoneInfo(zone_name)
    end = int(now.timestamp())
    def at(t):
        return datetime.fromtimestamp(t, timezone.utc).astimezone(zone)
    for _ in range(371):
        start = end - 86400
        prior, current = at(start), at(end)
        if prior.utcoffset() != current.utcoffset() and prior.dst() != current.dst():
            lo, hi = start, end
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if at(mid).utcoffset() == prior.utcoffset():
                    lo = mid
                else:
                    hi = mid
            after = at(hi)
            shift = int((after.utcoffset() - prior.utcoffset()).total_seconds())
            return {"key": zone_name + ":" + after.date().isoformat(),
                    "direction": "forward" if shift > 0 else "backward",
                    "shift_seconds": shift, "expected_dst": bool(after.dst()),
                    "at_utc": datetime.fromtimestamp(hi, timezone.utc).isoformat()}
        end = start
    return None


def evaluate_transition(transition, offset, mismatch, tolerance=120):
    """Offset is meter minus configured wall time. Unknown is not success."""
    if type(offset) not in (int, float):
        return "unknown"
    if not float("-inf") < offset < float("inf"):
        return "unknown"
    if abs(offset) <= tolerance:
        return "independent_success"
    if abs(offset + transition["shift_seconds"]) <= 300:
        return "seasonal_correction_required"
    return "failed"


class TransitionStore:
    """One writer per meter; caller serializes operations.

    Missing state is unknown. Corrupt state raises instead of clearing alarms.
    Persist a failed observation before any corrective write.
    """
    def __init__(self, root, meter_id):
        key = hashlib.sha256(meter_id.encode()).hexdigest()
        self.path = Path(root) / ("dst-transition-" + key + ".json")

    def load(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"dst_transition_failed": None, "dst_clock_override": None,
                    "last_transition": None, "incidents": []}
        if (not isinstance(state, dict) or
                any(k not in state for k in ("dst_transition_failed",
                    "dst_clock_override", "last_transition", "incidents")) or
                any(state[k] is not None and type(state[k]) is not bool
                    for k in ("dst_transition_failed", "dst_clock_override")) or
                not isinstance(state["incidents"], list)):
            raise ValueError("invalid transition state")
        return state

    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".dst-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(state, out, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def establish_baseline(self, transition, policy):
        """On first install or policy change, do not claim an old transition.

        Retain incident flags and history; only future observations can reset them.
        Policy identifies the configured timezone and DST setting.
        """
        state = self.load()
        if state.get("policy") != policy:
            state["policy"] = policy
            state["last_transition"] = transition["key"] if transition else None
            self.save(state)
        return state

    def observe(self, transition, offset, mismatch, now):
        state = self.load()
        if state["last_transition"] == transition["key"]:
            return state
        result = evaluate_transition(transition, offset, mismatch)
        if result == "unknown":
            return state
        state["last_transition"] = transition["key"]
        if result == "independent_success":
            state["dst_transition_failed"] = False
            state["dst_clock_override"] = False
        else:
            state["dst_transition_failed"] = True
            state["incidents"].append({
                "transition": dict(transition), "result": result,
                "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
                "before_offset_seconds": offset, "dst_mismatch": mismatch})
            state["incidents"] = state["incidents"][-32:]
        self.save(state)
        return state

    def record_intervened(self, transition, now):
        """Consume an inconclusive transition without clearing either latch."""
        state = self.load()
        if state["last_transition"] != transition["key"]:
            state["last_transition"] = transition["key"]
            state["incidents"].append({"transition": dict(transition),
                "result": "intervention_unverified",
                "observed_at_utc": now.astimezone(timezone.utc).isoformat()})
            state["incidents"] = state["incidents"][-32:]
            self.save(state)
        return state

    def verified_override(self, transition, after_offset, now):
        """Call only after a transition-related write and fresh verified readback."""
        state = self.load()
        if (state["last_transition"] != transition["key"] or
                state["dst_transition_failed"] is not True or
                type(after_offset) not in (int, float) or
                not abs(after_offset) <= 120 or not state["incidents"] or
                state["incidents"][-1]["result"] != "seasonal_correction_required" or
                state["incidents"][-1].get("transition", {}).get("key") != transition["key"]):
            raise ValueError("unverified transition override")
        state["dst_clock_override"] = True
        state["incidents"][-1].update(
            override_at_utc=now.astimezone(timezone.utc).isoformat(),
            after_offset_seconds=after_offset)
        self.save(state)
        return state
