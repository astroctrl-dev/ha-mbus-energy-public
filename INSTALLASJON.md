# Installation, updates and rollback

## Before you begin

Verify the documented M-Bus terminals of the meter, the adapter terminals and bus power supply. Wire colours alone do not identify terminals. Do not use adapter VCC/GND or an external supply without documentation. Ensure the USB serial adapter is available in Home Assistant OS and that an MQTT broker and the MQTT integration are installed and connected. Only one application may use the adapter at a time.

## New installation

1. Open **Settings → Apps → Install app → ⋮ → Repositories**, add `https://github.com/astroctrl-dev/ha-mbus-energy-public`, and refresh the store if needed.
2. Open **M-Bus T230 energimåling** and select **Install**.
3. In **Configuration**, select the actual `serial_port`, documented meter baud rate and an interval of at least 90 seconds. Default MQTT host is `core-mosquitto`. Enter MQTT credentials locally; do not share passwords or options.json.
4. Save, start, and open the web UI. Choose meter discovery (**Søk etter målere**), add (**Legg til**) the desired verified meter and stop discovery (**Stopp søk**) when finished. Results show meter ID and primary address. The current application may display Norwegian labels.
5. Find the meter under **Settings → Devices & services → MQTT**. Check readings, units, meter time, last successful reading and availability. Save and restart after configuration changes.

If no serial port appears, verify USB assignment and the port name after restart. If no meter responds, check documented wiring, baud rate and app logs. A valid USB device name alone does not prove meter communication.

## Upgrade to v2.4.0

All users of earlier versions are advised to upgrade. Regular polling, history retrieval and clock synchronization now share a transmission gate with a minimum 61-second wait after each attempted transmission. Missed polling slots are skipped rather than retried outside their planned time.

Use the same repository URL and app. Back up app data and configuration before updating. Meter selection and stored readings are held in the application's /data directory. Stop, update, check configuration and start. Legacy intervals of 10, 20, 30 and 60 seconds run at 120 seconds; explicitly select a supported interval before saving. Verify existing MQTT entities and a fresh regular reading. Local apps and repository apps have different app IDs and do not automatically share data.

## Monthly history and clock

Meter local time is displayed as text without a UTC offset; the daylight-saving flag and last successful reading in UTC are separate. Clock synchronization is off by default. Verify HA system time and clock_timezone, enable allow_clock_sync, save and restart. Manual synchronization (**Synkroniser målerklokke**) requires confirmation and verified readback. The optional auto_clock_sync setting requires verified manual synchronization and checks at startup after a valid reading and during the configured nightly hour. Larger deviations require manual intervention.

For history, enable allow_monthly_history, save and restart, then select **Hent månedshistorikk** for the correct meter. Wait for complete status. The web UI shows cumulative readings and differences, and **Last ned analyse (.xlsx)** exports stored data. Estimated first-of-month dates require verified clocks and retrieval outside the first 15 minutes after month rollover. They are not measured archive timestamps. If clock verification is uncertain, no estimated date is shown. With restore_unverified status, regular polling stays blocked until the normal frame is verified.

After manual history retrieval, MQTT exposes 24 diagnostic historical readings and 23 differences. New installations suggest two-digit entity IDs; existing IDs are not automatically changed.

## Rollback

Stop the app. Restore the previous app version and corresponding backup, including configuration and app data. Restart and verify MQTT entities and a fresh normal reading. Never run two copies against the same adapter and MQTT identities.
