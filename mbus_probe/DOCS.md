# M-Bus T230 Energy Metering

The app reads the Landis+Gyr T230 over wired M-Bus and publishes valid current records using MQTT Discovery. The [complete installation guide](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md) covers wiring, updates, verification and rollback.

## Settings

| Field | Description |
| --- | --- |
| `serial_port` | Serial device available in Home Assistant OS. |
| `baud` | Documented meter baud rate. |
| `interval_seconds` | Normal polling: 90, 120, 300 or 600 seconds; default 120. Legacy v1 values below 90 are handled as 120. Select at least 90 when saving new settings. |
| `read_before_full_hour` | Optional additional reading before the hour, with at least 61 seconds between bus accesses. |
| `seconds_before_full_hour` | Offset of 0–300 seconds. |
| `allow_clock_sync` | Allows confirmed manual synchronization to HA time with verified readback. Disabled by default. |
| `auto_clock_sync` | Optional startup check after the first valid reading and daily check at or after 23:00 local time following a valid reading. Automatic writes require prior verified manual synchronization and absolute deviation above 120 and at most 300 seconds. |
| `clock_timezone` | Meter's local timezone, default `Europe/Oslo`. Verify before synchronization. |
| `allow_monthly_history` | Enables manual retrieval and automatic history retrieval after the first valid reading at startup and on days 1 and 2 of each month at or after 01:00 local time. |
| `mqtt_host` and `mqtt_port` | Broker, normally `core-mosquitto:1883`. |
| `mqtt_username` and `mqtt_password` | Enter locally; never share credentials. |

Save changes and restart the app. Use **Open Web UI** to discover and select meters. Results show both meter ID and primary address. Each selected meter appears under **Settings → Devices & services → MQTT**.

## Current measurements

The app retains energy, volume, power, flow rate, supply temperature, return temperature and temperature difference, alongside status and data quality. It displays the meter's local date and time as text, the daylight saving flag separately, and the UTC timestamp of the last successful reading. Meter time has no encoded timezone and is not automatically converted. An invalid record produces `unknown` for the affected sensor without rejecting other valid values. Negative power is supported. Valid operating hours, flow hours and hours without measurement are displayed separately as cumulative hours.

## History and export

When `allow_monthly_history` is enabled, the monthly history action pauses normal polling, selects the historical frame, reads 24 cumulative kWh readings, restores the normal frame and verifies restoration. This takes several minutes. Failed restoration verification blocks normal polling.

Complete history is displayed as 24 readings and 23 differences in the web interface and the corresponding monthly history and consumption worksheets in the Excel export. With verified clocks, the first day of each month may be displayed as an **estimated** date after the first 15 minutes of the new month. The historical frame has not provided an actual billing date; estimated dates are explicitly labelled.

The MQTT representation after manual or automatic retrieval is 24 historical cumulative readings and 23 differences as diagnostics. New installations suggest two-digit positions in names and entity IDs. Historical values are not counted as today's consumption in Home Assistant Energy.

The analysis download (.xlsx) exports only locally stored, validated data and does not read the meter. An alias replaces the meter ID and raw telegrams are omitted. Measurements are real and should be reviewed before sharing.

## Automatic maintenance in v2.2.0

Automatic maintenance uses the configured meter timezone and waits for a valid normal polling round. Bus operations are serialized; maintenance may delay ordinary readings. Failed history retrieval retains the last saved snapshot. Failed restoration blocks polling and maintenance until resolved. Recoverable scheduled failures are retried after 15 minutes; daily clock retries are limited to the evening window. An uncertain clock write requires manual verification. Startup checks run again after an app restart. Back up the app before upgrading; existing options and entity identifiers are retained. If rollback is needed, restore the previous app backup.
