## v3.0.0-beta.6

- Optional experimental Fast scan, off by default. Standard search retains the two-second silent-probe interval.
- At 2400 baud, fast mode starts with a 200 ms first-byte window and 10 ms quiet pause after silent exchanges; complete fast pass followed by a 60-second quiet guard and standard-speed rechecks of affected addresses. Fast results remain provisional evidence, not proof of availability.
- Sequential 000–250 address grid with live status colors and a legend; unresolved addresses remain blocked. Selected-address checks wait 60 seconds before each of two conservative observations where no response is received. Physical address writing remains disabled.

## v3.0.0-beta.5

- Remove automatic meter selection from the Web UI; manual selection remains.
- Remove frame 5 test capture, capture status and evidence controls from the ordinary Web UI.
- Hide completed migration status; retain the migration action when pending.
- Preserve guarded backend operations and existing diagnostic reporting.

## v3.0.0-beta.4

- Compact active diagnostics with visible active warning details and expandable source-labelled attributes. Identical values shared by flow and installation views are consolidated; differences remain visible.
- Display timestamps without fractional seconds while retaining the original UTC or local offset semantics.
- Collapse clock and history help, and historical fault detail; shorten and wrap history table headings.
- Group meter operations and administration, and show completed migration as status rather than a disabled button.
- Presentation-only changes. Physical address writing remains disabled.

## v3.0.0-beta.3

- Improve mobile address entry with a large three-digit numeric field, explicit range validation, and separate compact search controls.
- Group Excel and raw telegram downloads under Data export; shorten descriptions and display storage errors only when present.
- Remove the two DST diagnostic status lines from the meter card; retain the underlying diagnostics and clock behaviour.

- Resume a stopped full primary-address search from the first unfinished address, preserving results and progress within the current app session.
- Starting a new full search can discard previous results after confirmation. Changed registered address context invalidates stopped results.
- Show unanswered candidates as Available (no response), with light-green selectable addresses and ranges. Selection only fills the address field.
- Color-code selectable conflict candidates yellow, failed or blocked candidates red and the current address neutral. Disable selection of red and neutral results.
- Missing responses do not guarantee availability. Physical address writing remains disabled.

## v3.0.0-beta.2

- Place the primary address panel immediately below the selected meter's identity, with a close control.
- Accelerate consecutive unanswered distinct primary-address probes to a minimum two seconds after transmission drain and completion of the full receive window. Retain the 60-second guard for repeated addresses, ordinary operations, responses and uncertain exchanges. Restart retains the conservative global guard.
- Add automated pacing, failure, restart and UI regression checks.
- Physical fast-scan timing and mobile layout require validation in an isolated test installation. Physical address writing remains disabled.

## v3.0.0-beta.1 — diagnostic preview

- Optional address protocol diagnostics in the Web UI, disabled by default.
- Read-only primary-address search and controlled diagnostic sequence with durable recovery guard and private local evidence export.
- Physical primary-address changes remain disabled.
- Simulator coverage includes multiple meters, interrupted telegrams, restart and persistence failures. Physical multi-meter behavior, actual HA acceptance and independent review remain outstanding.
- Use only an approved isolated test environment; back up application data before updating. Do not downgrade while a diagnostic recovery guard is pending.
- Previous executable candidate passed offline tests, image build and runtime imports; this versioned candidate requires its own CI confirmation.

## v2.9.2

- Daily frame-5 diagnostics at 03:15 local time
- Battery Status, Active Meter Faults and Flow Warning
- Meter Installation Status and mounting attributes
- Persistent diagnostic samples; 26-hour validity
- Manual capture and inline Web UI evidence
- Strict firmware 7.12 layout validation; single selected meter
- Shared bus guard and verified normal-frame recovery
- Existing entity IDs and history preserved

**Limitations**
- Live automatic acquisition and final UI hardware acceptance pending
- Unsupported frame layouts remain unknown

## v2.9.2-beta.1

- Active meter fault diagnostics (F0–F9)
- Flow warning diagnostics
- Extension byte diagnostics
- Four-state battery indicator
- MQTT and Web UI diagnostics
- Manual frame-5 test capture (opt-in)
- Safe normal-frame recovery

**Limitations**
- Physical frame-5 validation pending
- Automatic diagnostic acquisition disabled
- Active frame-5 states remain unknown

## v2.9.1 (stable)

- Retry recoverable extended archive errors up to three times per position, and continue after verified normal-mode restoration.
- Stop manual retrieval at a safe transaction boundary, preserving completed data and showing aborted positions.
- Bound automatic monthly history retries to three attempts per local day within a ten-day window; persist retry state and alarm acknowledgement across restarts.
- Show complete saved extended archive positions as Already stored immediately in the Web UI, with a dash for missing data. No additional bus requests.
- Preserve existing entity identifiers, app slug, stored data format and shared 60-second bus guard. No migration required; back up before updating.
- Beta validation: 236 automated tests, image build and runtime imports passed; 21/21 beta.1 and 5/5 beta.2 manual acceptance checks passed. Physical fault-injection and automatic retry exhaustion have not been verified.

## v2.9.1-beta.2

- Show complete locally stored extended archive positions as Already stored on startup; unread or incomplete positions remain unmarked. Preserve retrieval and Stop job statuses. No additional M-Bus requests.
- Manual beta.1 acceptance: 21/21 checklist items reported passed by product owner. Beta.2 acceptance: 5/5 manual checks and 236 automated tests passed.

## v2.9.1-beta.1

- Retry recoverable extended archive errors up to three times per position and continue with remaining positions after verified normal-mode restoration.
- Retry normal-mode restoration up to three times; block normal polling when verification fails.
- Cancel manual history retrieval at a safe transaction boundary; preserve validated data and distinguish failed and aborted positions.
- Bound established monthly history collection to three attempts per local day during a ten-day retry window. Persist attempts and manually acknowledged alarms across restarts.
- Add a Monthly History Failed MQTT diagnostic and Web UI acknowledgement; alarm visibility in HA depends on normal polling availability.
- Reorder Web UI sections and make history tables collapsible per meter.
- Preserve existing entity identifiers, app slug and shared 60-second bus guard. No active frame-5 acquisition.
- Automated validation passed on runtime candidate 6b185d3 (235 tests, image build and imports). Physical acceptance: 21/21 manual checks passed.

## v2.9.0 (stable)

- Extended monthly archive with historical volume and maximum power, flow and temperature measurements.
- Resumable manual retrieval with individual validated archive positions saved and complete positions skipped.
- Responsive Web UI with live per-position progress.
- Read-first startup with immediate publication of verified normal telegrams and automatic restoration from confirmed historical telegram mode.
- Shared minimum 60-second quiet period after serial transmission. A 60-second polling interval is now selectable; slots that cannot meet the guard are skipped.
- Initial readings normally arrive within approximately 60 seconds. Recovery from historical telegram mode may take approximately three minutes; communication errors may extend this time.
- Existing entity identifiers and saved history preserved. No active frame-5 battery acquisition.
- Automated regression tests and container build passed. Physical beta testing confirmed ordinary readings, archive resumption and live progress. Full archive completion and physical verification of revised timing remain outstanding. Back up before updating.

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
