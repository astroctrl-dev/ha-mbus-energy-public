## v2.9.0-beta.3

Manual Retrieve Monthly Archive now reads missing extended monthly records on meters with complete saved energy history. Saves and publishes each successfully validated month after restoring normal operation. Stops on first rejected record; existing data retained. Full collection can take over 90 minutes. Physical frame 4 validation remains pending; frame 5 battery acquisition is not enabled. No automatic extended collection.

## v2.9.0-beta.2

Simplifies monthly consumption sensor attributes to ten top-level fields including Home Assistant metadata. Preserves sensor IDs, energy states and internal read provenance. Monthly maxima share a read timestamp only when all four were read together. Actual instrument archive date takes precedence when available. Frame 4 and 5 physical collection remains disabled; no additional bus requests.

# 2.9.0-beta.1

v2.9.0-beta.1: passive maximum values and meter-local event times on existing Power, Flow and temperature sensors, with observation timestamps. Historical data projection includes individual maximum read provenance and group update time when supplemental evidence exists. Existing energy states and original read dates are preserved. Frame 4 acquisition is dev-only and not exposed in the UI; frame 5 battery acquisition is not enabled. No extra automatic bus requests. Physical validation outstanding. Back up before updating.

# 2.8.0

- Five separate diagnostic event sensors with original codes FT, FF2, FS, FE and FF1. The beta aggregate entity is removed on publication of saved event history.
- Firmware Version is a separate diagnostic sensor. Flow timing intervals are attributes of Flow; extension byte and read time remain on M-Bus status.
- Preserve aligned historical period metadata as well as cumulative stands; reject conflicting saved periods.
- Append individual read timestamps and descriptive event names to Excel. Existing columns remain.
- No extra bus transactions, battery estimates or active frame-5 acquisition. Automated tests and build passed; new entity discovery and preservation of historical provenance still require physical confirmation.

# 2.8.0-beta.1

- Add flow measurement and averaging intervals, firmware version and raw extension byte to the existing meter status attributes.
- Decode and preserve frame-2 historical last-occurrence times; expose them in Home Assistant, ingress and Excel, distinct from active faults.
- Add diagnostic export with existing measurement logging; retain previous sheets and identifiers.
- Include a standalone tested frame-5 flag decoder, not connected to runtime acquisition. Battery warnings and percentage are not yet exposed. No estimated battery life.
- No additional bus transactions. Automated private CI passed; physical validation pending.

# 2.7.5

- Always follow Home Assistant local time, including seasonal changes.
- Remove optional daylight-saving-time configuration and translations; ignore legacy values during upgrade.
- Preserve manual and monthly clock synchronization, seasonal checks, permissions, diagnostics and history.
- Private automated CI passed; physical upgrade and actual seasonal transition remain to be verified.

# 2.7.4

- Promotes 2.7.4-beta.1 without runtime code changes.
- Private candidate CI: 171 tests and Docker build passed. Physical clock synchronization and ordinary polling verified; one transient timeout recovered automatically.
- Product lead confirmed restart of v2.7.4-beta.1 and recovery of sensor values. Actual seasonal transition and active alarm persistence remain unverified. Stable promotion approved by product lead.

# 2.7.4-beta.1

- Use the Home Assistant timezone supplied by Supervisor, with configured fallback.
- Check seasonal transitions after the actual UTC transition instant on the next eligible valid polling round, including fixed standard-time policy.
- Verify clock writes using wall time rather than the reported DST bit.
- Retire experimental DST write tests; retain historical evidence and existing diagnostics.
- Seconds-resolution reading remains unverified; minute-based reading is retained.
- Automated private CI: 171 tests passed and Docker build succeeded. Physical seasonal transition and active alarm persistence remain unverified. Controlled beta only.

# 2.7.3-beta.1

- Persistent seasonal transition diagnostics and verified clock override indicator.
- One seasonal check at noon, with catch-up after downtime.
- Automatic large clock corrections restricted to the scheduled seasonal operation and trusted meters.
- Manual alternative DST diagnostic with restoration attempt.
- Physical verification pending; not intended for production use.
