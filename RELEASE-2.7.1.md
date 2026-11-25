M-Bus v2.7.1

- Rolling monthly history with preserved read timestamps.
- Storage date attribute aliases and monthly storage time diagnostic.
- Archive-aware retrieval and separate monthly configuration check.
- Clock offset assessment and scheduled synchronization when needed.
- Explicit migration gate for saved legacy history.

The physical monthly rollover, settings-only sequence and interrupted recovery have not yet been verified on the meter. Existing migration completed successfully according to the product owner. Stable release is gated by automated tests.
