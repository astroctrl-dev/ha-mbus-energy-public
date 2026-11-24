# Installation, updates and rollback

## Before you begin

Verify the documented M-Bus terminals on the meter, the adapter terminals and the bus power supply. Wire colours alone do not identify connections. Do not use the adapter's VCC/GND terminals or an external power supply without supporting documentation. Ensure that the USB serial adapter is visible in Home Assistant OS, an MQTT broker is installed and the MQTT integration is connected. Only one app may use the adapter at a time.

## New installation

1. Open **Settings → Apps → Install app → ⋮ → Repositories**. Add `https://github.com/astroctrl-dev/ha-mbus-energy-public` and refresh the app store if necessary.
2. Open **M-Bus T230 Energy Metering** and select **Install**.
3. Under **Configuration**, select the actual `serial_port`, the documented meter baud rate and a polling interval of at least 90 seconds. The default `mqtt_host` is `core-mosquitto`. Enter MQTT credentials locally. Never share `options.json` or passwords.
4. Select **Save**, open **Info** and select **Start**. Open **Open Web UI** and start meter discovery. Valid results appear progressively with meter ID and primary address. Add the desired meter and stop discovery when finished.
5. Locate the meter under **Settings → Devices & services → MQTT**. Verify measurements, units, clock, last successful reading and availability. After configuration changes, select **Save** and **Restart**.

If no serial port appears, check USB passthrough and the device path after restarting. If no meter responds, check the documented bus wiring, baud rate and app logs. A visible USB device alone does not prove meter communication.

## Upgrading from v1.0.0 or v2.0.0

Use the same repository URL and app. Create a full backup of app data and record the configuration before selecting **Update**. Meter selections and stored data are held in the app's `/data`; preserve these in the backup. Stop the app, select **Update**, and review **Configuration** before selecting **Start**.

Legacy polling intervals of 10, 20, 30 and 60 seconds are treated as 120 seconds in v2.1. Select a valid interval before saving new settings. Explicitly select 120 seconds and save. Verify that existing MQTT entities remain available and fresh readings arrive. Local apps and repository apps have different app IDs and do not automatically share app data.

## Monthly history and clock

The meter's local clock is displayed as text without a UTC offset. The daylight saving flag is displayed separately. The last successful reading is Home Assistant's UTC timestamp.

Clock synchronization is disabled by default. Verify Home Assistant system time and `clock_timezone`, enable `allow_clock_sync`, save and restart. The manual clock synchronization action requires confirmation and verified readback. `auto_clock_sync` is a separate option following verified manual synchronization; the check runs at startup after the first valid reading. Larger clock discrepancies require manual attention.

For history, enable `allow_monthly_history`, save and restart. Request monthly history for the selected meter and wait for status **complete**. Cumulative readings and differences appear in the web UI, and the analysis download (.xlsx) exports them alongside normal readings.

With verified clocks, the first day of the current and previous months may be displayed as an **estimated** date, subject to a 15-minute exclusion window after the month changes. The date is not read from the historical frame. If clock provenance is uncertain, no estimated date is displayed. Status **restore_unverified** blocks normal polling until the normal frame has been verified.

After manual retrieval, the intended MQTT representation is 24 diagnostic historical cumulative readings and 23 differences. New installations suggest two-digit entity IDs; existing names and IDs are not automatically changed during upgrades.

## Rollback

Stop the app. Restore the previous app version and its corresponding backup, including configuration and app data. Start the app again and verify MQTT devices and a fresh normal reading. Never run two copies of the app simultaneously against the same adapter and MQTT identities.
