# M-Bus T230 Energy Metering for Home Assistant

This app reads the Landis+Gyr ULTRAHEAT T230 over wired M-Bus and publishes measurements using MQTT Discovery. It displays energy, volume, power, flow rate, temperatures and diagnostics. The meter's local clock is displayed separately from the time Home Assistant read the telegram.

## Installation

Add this repository under **Settings → Apps → Install app → ⋮ → Repositories → Add**:

```text
https://github.com/astroctrl-dev/ha-mbus-energy-public
```

Open **M-Bus T230 Energy Metering**, select **Install**, configure the serial port and MQTT access under **Configuration**, select **Save**, then **Start**. Use **Open Web UI** to discover and add the meter. Discovery results show the meter ID and primary address together. Read the [installation guide](INSTALLASJON.md) before wiring or upgrading.

## Measurements and history

The seven existing measurement sensors and status diagnostics are retained. Version 2.1.0 also exposes optional counters for operating hours, flow hours and hours without measurement. Signed power is supported; an invalid record affects only the corresponding sensor. The meter's local time, daylight saving flag and last successful reading are displayed separately. Meter timestamps are reproduced as received, without assuming a UTC conversion.

Enable `allow_monthly_history` in **Configuration** and request monthly history in **Open Web UI**. The app pauses normal polling, selects the historical frame, reads 24 cumulative energy readings, restores the normal frame and verifies it before polling resumes. An unverified restoration blocks normal polling. A complete response provides 24 readings and 23 differences. Billing dates may be shown as **estimated** first days of the month when both clocks are verified and retrieval occurs after the first 15 minutes of the month. These are not measured billing dates. Historical values are not counted as new consumption in Home Assistant Energy.

The analysis download (.xlsx) exports stored validated readings and any monthly history without sending commands to the meter. It uses an alias instead of the meter ID and excludes raw telegrams and credentials. It contains real measurements; review it before sharing.

Normal readings of the same meter are separated by at least 61 seconds, including across restarts. Address discovery tries different primary addresses and should not be repeatedly started against the same meter. The default polling interval is 120 seconds. Legacy v1 intervals of 10, 20, 30 and 60 seconds are accepted during upgrades and run as 120 seconds. Select at least 90 seconds when saving new settings.

No real meter IDs or private raw telegrams are included in this repository. The test fixture is synthetic. Example ID `12345678` and address `7` are fictional.

## Clock synchronization and historical sensors

Clock synchronization is disabled by default. Enabling `allow_clock_sync` permits confirmed manual synchronization to Home Assistant time in the configured timezone, followed by readback verification. `auto_clock_sync` is a separate option and requires verified manual synchronization before automatic writes. See the [app documentation](mbus_probe/DOCS.md) for limits and prerequisites.

After manual history retrieval, Home Assistant is intended to display 24 cumulative historical kWh sensors and 23 difference sensors as diagnostics. New installations use positions `01` through `24` in names and suggested entity IDs. Existing entity IDs are not automatically renamed.

## Documentation and verification

- [Installation, updates and rollback](INSTALLASJON.md)
- [App documentation](mbus_probe/DOCS.md)

Run offline tests from the repository root:

```sh
PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -p 'test_*.py' -v
```

These tests do not replace verification of the physical meter, clock and connection in your installation.
