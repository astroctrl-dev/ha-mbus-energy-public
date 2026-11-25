# M-Bus v2.7.2

- Daylight saving time configuration, enabled by default.
- Seasonal clock checks and bounded automatic correction for previously verified meters.
- Manual DST write test with readback of both bits and restoration of configured time.
- Configuration translations and offline regression tests.

Physical DST write and transition verification are still pending. The manual test temporarily writes a deliberately incorrect DST bit; run only when a clock test is acceptable. If restoration fails, manually synchronize and verify the clock before relying on it.
