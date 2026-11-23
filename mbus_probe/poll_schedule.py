"""UTC-based optional read just BEFORE the next full hour."""
import time


def next_hour_delay(now=None, seconds_before_full_hour=5):
    """Seconds until next hour minus offset; schedule strictly in future."""
    now = time.time() if now is None else float(now)
    offset = int(seconds_before_full_hour)
    if not 0 <= offset <= 300:
        raise ValueError("seconds_before_full_hour must be 0..300")
    target = ((int(now) // 3600) + 1) * 3600 - offset
    if target <= now:
        target += 3600
    return target - now


def next_poll_wait(interval_seconds, read_before_full_hour=False,
                   seconds_before_full_hour=5, now=None):
    interval = int(interval_seconds)
    if not read_before_full_hour:
        return max(61.0, float(interval))
    # Pre-hour scheduling must never shorten the meter reading interval.
    return max(61.0, min(float(interval), next_hour_delay(now, seconds_before_full_hour)))
