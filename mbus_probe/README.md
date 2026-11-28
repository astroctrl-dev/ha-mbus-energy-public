# M-Bus T230 energy metering

Read Landis+Gyr T230 over wired M-Bus, expose measurements via MQTT Discovery, and export validated regular readings and monthly history to Excel.

## Preparation

- Verify documented meter terminals and adapter bus supply before wiring. Wire colours alone do not identify terminals.
- Make the USB serial adapter available to Home Assistant OS and install the MQTT broker and integration.
- Back up app data and settings before updating, including meter selection, stored readings and historical snapshots.

## Configuration

1. Select the actual serial_port under **Settings → Apps → M-Bus T230 energimåling → Configuration** and use the documented meter baud rate.
2. Default mqtt_host is core-mosquitto for a local broker. Enter MQTT credentials locally. Select a polling interval of at least 60 seconds; default 120. Slots that cannot satisfy the shared bus guard are skipped.
3. Save and start, open the web UI and discover meters (**Scan for meters**). Add (**Add**) a verified result. Meter ID and primary address appear locally. The app supports English, Norwegian Bokmål, Norwegian Nynorsk and German.
4. Verify the seven measurement sensors and diagnostics under **Settings → Devices & services → MQTT**. Save and restart after configuration changes.

## Clock and data

Meter local date/time is shown as text without an encoded UTC offset. HA last successful reading is separate and in UTC; the daylight-saving flag is separate. History contains 24 cumulative kWh readings and 23 adjacent differences. Estimated dates are clearly marked and are not measured billing dates.

The analysis download (**Download Excel (.xlsx)**) exports stored validated readings without issuing a request. It substitutes an alias for the meter ID and excludes raw telegrams and credentials, but contains real measurements that should be reviewed before sharing.

## Monthly history

Enable allow_monthly_history, save and restart, then select **Retrieve monthly history** for the meter. The operation pauses regular polling, selects the historical frame, reads 24 records and restores and verifies the normal frame before resuming. It may take several minutes. Do not repeatedly press the button while running. With restore_unverified status, polling stays blocked until normal-frame verification. History is not recorded as new current HA Energy consumption.

On completion, the web UI shows 24 readings and 23 differences. Excel includes the history worksheets (currently named **Månedshistorikk** and **Månedsforbruk**). A stored snapshot may also be displayed after restart. Without stored history, only regular readings are exported.

Extended archive retrieval can be stopped at a safe transaction boundary and resumed later. Complete stored positions appear as Already stored on startup; missing positions show a dash. Recoverable errors are retried up to three times per position. Automatic monthly history retry is limited to three attempts per local day within a ten-day window. An unresolved failure is reported by the Monthly History Failed diagnostic and can be acknowledged in the Web UI.

## Updates and rollback

Version 3.0.0 retains the app slug, existing entity identifiers and stored measurement/history formats. Back up before upgrading, especially from experimental 3.0.0 betas. The application now coordinates M-Bus transmissions using a shared timing gate and skips missed polling slots. Back up app data and settings, update through Settings → Apps, and verify meter selection, MQTT entities and fresh readings. On failure, preserve the data and diagnostic evidence. Do not downgrade or restore an older backup while a diagnostic or address transaction is unresolved. For other failures, stop the app and restore the previous known-good version and corresponding backup only after verifying that no safety state is pending. Never run two copies against the same adapter and MQTT identities.

## Clock synchronization

Off by default. Verify HA system time and the meter time zone (clock_timezone, default Europe/Oslo). Enable allow_clock_sync, save and restart. Manual synchronization (**Synchronize meter clock**) requires confirmation, reads the clock, writes system time in the configured zone and verifies readback. Meter time has minute resolution. If verification fails, check the clock before retrying.

auto_clock_sync is optional and requires verified manual synchronization. Checks run after a valid reading at startup and during the configured nightly hour. Automatic correction is limited to deviations above 120 and up to 300 seconds, or a differing daylight-saving flag within the permitted bound. Larger deviations require manual action, including a full-hour daylight-saving offset. Do not share the adapter with another app.

## Home Assistant measurements

Power may be signed. Each valid record is evaluated independently; an invalid or missing value makes only that sensor unknown. Volume (m³) and cumulative operating, flow and non-measuring hour counters are exposed when present; these counters do not indicate current pump operation.

After completed manual history retrieval, 24 cumulative historical kWh sensors and 23 difference sensors are exposed as diagnostics. They are not new energy counters for the current period. New installations suggest sortable names and IDs with positions −01 through −24; existing or customized IDs are not renamed. IDs include a pseudonymous meter key, which is not anonymization.

## Archive dates

The historical frame has no verified storage timestamp for each record. The app can estimate first-of-month dates, with position −01 assigned to the retrieval month and −02 to the preceding month, and so on. This requires fresh retrieval after verified manual clock synchronization, matching meter and configured HA time within 120 seconds, matching daylight-saving flags and retrieval outside the first 15 minutes after month rollover. Otherwise no estimated date appears. estimated_date is an estimate, not a measured billing date. Stored historical dates do not shift when the calendar changes.

A later manual retrieval can identify a confirmed archive rollover when all positions shift by one and the newest cumulative reading increases. This demonstrates an archive change, not its exact timestamp. See history_captured_at_utc for retrieval time and meter_date_status for date quality.

See the [installation guide](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md). Legacy polling intervals below 90 seconds run at 120 seconds; select a supported interval before saving.

## Language and measurement units (v2.5.0)

The independent app web interface uses English, regardless of browser language. Home Assistant's configuration translations follow its own interface language independently. Technical identifiers and existing sensor names remain unchanged.

The app publishes energy in kWh, power in kW, volume in m³, flow in m³/h and time counters in h. MQTT absolute temperatures retain native °C and the temperature difference retains native K. In Home Assistant versions supporting the temperature_delta device class, select the preferred display unit for each temperature sensor in its entity settings. Excel retains decoded measurement units, including Celsius for absolute temperatures and Kelvin for differences. Home Assistant entity preferences remain independent. Temperature differences convert without an absolute-temperature offset. Existing archive data and Excel column and sheet identities are retained; the Info sheet uses English. Excel numeric cells remain numeric. Some unmapped technical error details remain in their original language.

Before updating from v2.4.0, back up app data and Home Assistant. Verify entity IDs, temperature units, long-term statistics, regular polling, saved history and Excel export afterwards. In particular, verify the existing temperature-difference sensor after the discovery device-class change. If validation fails, stop the app and restore the known-good v2.4.0 version and backup as appropriate. Do not delete existing entities to work around unit problems.


## Active diagnostics (v2.9.2)

- Battery Status: normal, pre-warning, exhausted or unknown; no measured charge percentage.
- Active Meter Faults, Flow Warning and Meter Installation Status.
- Automatic frame-5 acquisition once per local calendar day, at or after 03:15 in clock_timezone, after a valid ordinary reading and when maintenance permits.
- Last valid diagnostic sample retained across restarts; unknown after 26 hours.
- Supported active diagnostic layout: observed T230 firmware 7.12, single selected meter. Unsupported layouts are rejected.
- Optional manual capture requires allow_diagnostic_capture and confirmation. Raw evidence is not fully anonymized; review before sharing.
- Normal-frame restoration is mandatory before ordinary polling resumes.

Physical capture and offline regression tests cover the observed layout. Live automatic scheduling and final Web UI behavior have not yet been verified on hardware. Back up before upgrading; restore the previous app and backup if normal polling cannot be recovered.

## Primary address search and recovery (v3.0.0)

Primary address search (000–250), optional Fast scan, result colors and read-only destination checks are retained. A silent response is not proof that an address is free. Physical primary-address changes and new experimental secondary-address protocol tests are disabled in this version, including with legacy configuration. Ordinary clock synchronization and supported historical-frame operations remain available.

Stable operation cannot create new diagnostic safety markers. Existing beta markers are retained only for controlled recovery. Ordinary communication failures use normal retry handling; history and timing safety remain independent.

If an experimental beta left a diagnostic session pending, back up app data and update normally without uninstalling. In the web UI, use **Recover diagnostic session** with the pending instrument identity, fabrication number and primary address; confirm isolation only if one physical meter and one master are actually connected. Recovery checks two paced primary responses for the expected identity, fabrication number, address and normal telegram layout. It does not require a secondary-address ACK. Successful verification is recorded before removing the matching diagnostic guard. Ordinary polling can then resume without restarting the app. This verifies primary operation, not secondary deselection. If recovery fails, keep the guard and export private evidence; do not delete files or retry address writes. A separate unresolved address-write transaction or history recovery may still block operation.

Validation: 590 automated tests passed on the release candidate, including simulated recovery, MQTT resumption, legacy configuration, API denial and storage failures. Independent software review approved the tested candidate. Physical recovery of a pending beta diagnostic has not yet been verified. Total filesystem failure may prevent durable restoration of a legacy marker; never manually remove an unresolved marker. Private evidence may contain real instrument identifiers; review before sharing.
