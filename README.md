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

# Current app update: v2.9.0-beta.1

v2.9.0-beta.1: passive maximum values and meter-local event times on existing Power, Flow and temperature sensors, with observation timestamps. Historical data projection includes individual maximum read provenance and group update time when supplemental evidence exists. Existing energy states and original read dates are preserved. Frame 4 acquisition is dev-only and not exposed in the UI; frame 5 battery acquisition is not enabled. No extra automatic bus requests. Physical validation outstanding. Back up before updating.

# Current app update: v2.8.0 (stable)

Adds five individually named historical diagnostic event sensors, a firmware sensor and flow timing attributes. Historical event dates are meter-local text; missing dates are unknown, not active alarms. Excel includes event names and individual historical read timestamps. Aligned existing historical stands and period metadata are preserved. No additional bus requests or estimated battery life. Frame-5 battery diagnostics are not enabled. Back up before updating. See [changelog](mbus_probe/CHANGELOG.md).

# M-Bus T230 energy metering for Home Assistant

This app reads Landis+Gyr ULTRAHEAT T230 over wired M-Bus and publishes energy, volume, power, flow, temperatures and diagnostics via MQTT Discovery. Meter local time is displayed separately from the Home Assistant reading timestamp.

## Important upgrade – v2.4.0

**All users of earlier versions are advised to upgrade to v2.4.0.**

Earlier versions did not fully coordinate the timing of regular polling, monthly history retrieval and clock synchronization. Under certain conditions, requests could occur too close together for the meter's communication timing requirements, potentially causing interrupted or missing readings.

Version 2.4.0 uses a shared transmission gate for all application M-Bus requests, enforcing at least 61 seconds after each transmission attempt, including failed attempts. Regular polling skips slots that cannot meet the timing constraints. This improves communication predictability and reliability.

Back up app data and configuration before upgrading and verify regular polling afterwards.

## Installation

Add this repository under **Settings → Apps → Install app → ⋮ → Repositories → Add**:

```text
https://github.com/astroctrl-dev/ha-mbus-energy-public
```

Open **M-Bus T230 energimåling**, select **Install**, configure the serial port and MQTT credentials, save and start. Use **Open Web UI** to discover and add the meter. Results show ID and primary address. The current app interface may use Norwegian labels. Read the [installation guide](INSTALLASJON.md) before wiring or updating.

## Measurements and history

The seven existing measurement sensors and status diagnostics are preserved. Since 2.1.0, optional cumulative operating, flow and non-measuring hour counters are also exposed. Signed power is supported; an invalid record affects only its sensor. Meter local time, daylight-saving flag and last successful reading are shown separately, without assuming a UTC offset for meter time.

Enable `allow_monthly_history` and use **Hent månedshistorikk** in the web UI. The app pauses regular polling, selects frame 2, reads monthly set-day configuration, selects frame 3, reads 24 cumulative energy readings and restores and verifies the normal frame before resuming. Unverified restoration blocks regular polling. Complete history contains 24 readings and 23 differences. Allow about six minutes per meter. Derived dates use current meter configuration and assume it has not changed. Ambiguous dates and days 29–31 remain unverified. History is not added as current Home Assistant Energy consumption.

The analysis download (**Last ned analyse (.xlsx)**) exports stored validated readings and available history without querying the meter. An alias replaces meter ID; raw telegrams and credentials are omitted. Review the actual measurement data before sharing.

The shared bus gate also applies after restart. Address scans try different primary addresses and should not be repeatedly started against the same meter. Default polling is 120 seconds. Legacy v1 intervals of 10, 20, 30 and 60 seconds are accepted on upgrade and run at 120 seconds. Select 60 seconds or more when saving new settings.

No real meter IDs or private raw telegrams are included in this repository. The test fixture is synthetic. Example ID `12345678` and address `7` are fictional.

## Clock synchronization and history sensors

Clock synchronization is off by default. Enable `allow_clock_sync` to use **Synkroniser målerklokke**, with confirmation and verified readback in the configured time zone. `auto_clock_sync` is separate and requires verified manual synchronization before automatic writes. See the [app documentation](mbus_probe/DOCS.md) for limits and prerequisites.

After manual history retrieval, Home Assistant exposes 24 cumulative historical kWh sensors and 23 difference sensors as diagnostics. New installations use positions 01–24 in suggested names and entity IDs. Existing entity IDs are not automatically renamed.

## Documentation and verification

- [Installation, updates and rollback](INSTALLASJON.md)
- [Application documentation](mbus_probe/DOCS.md)

Run offline tests from the repository root with `PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -p 'test_*.py' -v`. Tests do not replace physical meter, clock and wiring verification.

## First installation and restart

Leave all optional switches off initially. Verify ordinary live measurements first, then enable optional features individually. Startup reads are prioritized before automatic maintenance; same-boot restart waits only the remaining 60-second guard where timing is known. Unknown state uses a full guard. Initial history retrieval takes about six minutes per meter; extended retrieval takes about four minutes per missing position; ordinary values may be stale or temporarily unavailable.

Version 2.6.0 fixes the observed T230 frame-2 labelled diagnostic layout so the monthly set-day can be decoded. Scheduled reads tolerate less than ten seconds of delay, capped at the hour boundary for shifted reads. The 61-second bus guard remains unchanged.
