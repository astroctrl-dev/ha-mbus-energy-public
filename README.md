# Opt-in beta: v2.5.0-beta.1

Add `https://github.com/astroctrl-dev/ha-mbus-energy-public#beta` to the Home Assistant App Store on an isolated test instance. Do not run stable and beta against the same adapter or MQTT identity. This channel may create a separate app identity. See [beta release notes](RELEASE-2.5.0-beta.1.md).

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

Enable `allow_monthly_history` and use **Hent månedshistorikk** in the web UI. The app pauses regular polling, selects the history frame, reads 24 cumulative energy readings and restores and verifies the normal frame before resuming. Unverified restoration blocks regular polling. Complete history contains 24 readings and 23 differences. Estimated first-of-month dates require verified clocks and retrieval outside the first 15 minutes of a new month; they are not measured billing dates. History is not added as current Home Assistant Energy consumption.

The analysis download (**Last ned analyse (.xlsx)**) exports stored validated readings and available history without querying the meter. An alias replaces meter ID; raw telegrams and credentials are omitted. Review the actual measurement data before sharing.

The shared bus gate also applies after restart. Address scans try different primary addresses and should not be repeatedly started against the same meter. Default polling is 120 seconds. Legacy v1 intervals of 10, 20, 30 and 60 seconds are accepted on upgrade and run at 120 seconds. Select 90 seconds or more when saving new settings.

No real meter IDs or private raw telegrams are included in this repository. The test fixture is synthetic. Example ID `12345678` and address `7` are fictional.

## Clock synchronization and history sensors

Clock synchronization is off by default. Enable `allow_clock_sync` to use **Synkroniser målerklokke**, with confirmation and verified readback in the configured time zone. `auto_clock_sync` is separate and requires verified manual synchronization before automatic writes. See the [app documentation](mbus_probe/DOCS.md) for limits and prerequisites.

After manual history retrieval, Home Assistant exposes 24 cumulative historical kWh sensors and 23 difference sensors as diagnostics. New installations use positions 01–24 in suggested names and entity IDs. Existing entity IDs are not automatically renamed.

## Documentation and verification

- [Installation, updates and rollback](INSTALLASJON.md)
- [Application documentation](mbus_probe/DOCS.md)

Run offline tests from the repository root with `PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -p 'test_*.py' -v`. Tests do not replace physical meter, clock and wiring verification.
