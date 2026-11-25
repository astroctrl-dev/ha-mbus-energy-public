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
