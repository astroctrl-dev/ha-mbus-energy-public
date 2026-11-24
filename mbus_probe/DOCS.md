# M-Bus T230 energy metering

The app reads Landis+Gyr T230 over wired M-Bus and publishes valid current records via MQTT Discovery. See the [installation guide](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md) for wiring, updating, verification and rollback.

## Important upgrade – v2.4.0

**All users of earlier versions are advised to upgrade to v2.4.0.**

Earlier versions did not fully coordinate the timing of regular polling, monthly history retrieval and clock synchronization. Under certain conditions, requests could occur too close together for the meter's communication timing requirements, potentially causing interrupted or missing readings.

Version 2.4.0 uses a shared transmission gate for all application M-Bus requests, enforcing at least 61 seconds after each transmission attempt, including failed attempts. Regular polling skips slots that cannot meet the timing constraints. This improves communication predictability and reliability.

Back up app data and configuration before upgrading and verify regular polling afterwards.

## Configuration

| Field | Description |
| --- | --- |
| `serial_port` | Serial device available in Home Assistant OS. |
| `baud` | Baud rate documented for the meter. |
| `interval_seconds` | Regular polling: 90, 120, 300 or 600 seconds; default 120. At 120 seconds, readings normally occur on odd minutes (:01, :03 … :59). |
| `read_before_full_hour` | Optional shift of the entire fixed polling schedule, not an extra reading. |
| `seconds_before_full_hour` | Offset of 0–300 seconds. |
| `allow_clock_sync` | Enables confirmed manual synchronization to HA time with verified readback. Off by default. |
| `auto_clock_sync` | Optional check at startup and during the 23:00 local hour after a valid reading. Writes only after verified manual synchronization and within bounded clock deviation. |
| `clock_timezone` | Meter local time zone; default `Europe/Oslo`. Verify before synchronization. |
| `allow_monthly_history` | Enables the separate history action in the web UI. |
| `auto_monthly_history` | Off by default. Runs at startup and during the 01:00 local hour on the first and second of each month after a valid reading. Requires allow_monthly_history. |
| `mqtt_host` and `mqtt_port` | Broker, normally `core-mosquitto:1883`. |
| `mqtt_username` and `mqtt_password` | Enter locally; do not share. |

Save and restart after changes. Use **Open Web UI** to discover and select meters. Results show meter ID and primary address. Each selected meter appears under **Settings → Devices & services → MQTT**. The current app UI may display Norwegian labels.

## Current measurements

Energy, volume, power, flow, flow and return temperatures, temperature difference, status and data quality are preserved. Meter local date/time is shown as text, with the daylight-saving flag separately and the last successful reading timestamp in UTC. The meter time has no encoded time zone and is not automatically converted. An invalid record makes only the corresponding sensor unknown. Signed power is supported. Valid operating-time, flow-time and non-measuring-time counters are cumulative hours.

## History and export

With `allow_monthly_history` enabled, the history action (**Hent månedshistorikk**) pauses regular polling, selects the history frame, reads 24 cumulative kWh readings and restores and verifies the normal frame. This takes several minutes; failed verification blocks regular polling. Complete history comprises 24 readings and 23 differences in the UI and Excel worksheets **Månedshistorikk** and **Månedsforbruk**. With a verified meter clock, the first day of each month can be shown as an estimated date after the first 15 minutes of a new month. The history frame has not supplied actual billing dates. MQTT exposes 24 historical readings and 23 differences as diagnostics after manual retrieval; new installations use two-digit positions in suggested names and IDs. History is not added as current HA Energy consumption.

The analysis download (**Last ned analyse (.xlsx)**) exports locally stored validated data without querying the meter. An alias replaces the meter ID, and raw telegrams are excluded. Review actual measurement data before sharing.

### Recovery (2.3.2)
Recovery logs validation errors and TX/response length. `recovery_raw_log` enables full local RX hex; disable after diagnosis and redact meter ID/data before sharing. `allow_recovery_interface_reset` defaults to false. Enable only on a verified single-meter bus after explicit approval: when a checksum-valid frame with matching address and meter ID contains all 24 history records, recovery may send the existing CI=50 normal interface selection command, wait for ACK and verify a fresh normal frame. No clock write or history collection. Guard remains on failure.

## Timing and upgrade checks (2.4.0)

The application uses one monotonic bus-wide transmission gate with at least 61 seconds between attempted sends. Standalone diagnostics must not share the app's serial device. Ordinary polling skips missed slots; manual jobs do not have an hourly exclusion window. Clock writes target the first second of an eligible minute; readback verifies only the meter's minute-resolution time. Automatic calendar jobs start after a valid poll in the configured hour, not necessarily at its beginning. With multiple meters, rotation increases effective per-meter intervals; a full address scan can take several hours. Multi-meter operation has not been physically verified. Preserve app data and options before updating; test ordinary polling, then manual history, then manual clock, then opt-in automation separately. Roll back to v2.3.4 if necessary, preserving the normal-frame recovery marker.
