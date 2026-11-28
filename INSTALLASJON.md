# Installation, updates and rollback

## Preparation

Verify documented M-Bus terminals, adapter bus supply and baud rate. Wire colours alone are insufficient; do not use VCC/GND or an external supply without documentation. Ensure the USB serial device is accessible to Home Assistant OS and an MQTT broker and integration are installed. Only one application may use the adapter.

## Install or update

1. Back up Home Assistant, app configuration and app data, including stored history and meter selection.
2. Add https://github.com/astroctrl-dev/ha-mbus-energy-public under Settings → Apps → Install app → Repositories if not already configured.
3. Install or update M-Bus T230 energimåling. Keep the existing app when upgrading. Select the documented serial port and baud rate; default polling interval is 120 seconds. Enter MQTT credentials locally.
4. Start the app. Discover and select the verified meter if not already registered. Check current readings, units, timestamps and MQTT availability. Leave optional features disabled initially on new installations.
5. Enable optional history and clock features individually as described in the [app documentation](mbus_probe/README.md).

## Recover an existing beta diagnostic

If cleanup_required is displayed, preserve the existing marker and data. Use Recover diagnostic session in the web UI. Enter the expected meter identity, fabrication number and primary address matching the pending record. Confirm single-meter/single-master topology only if true. The app verifies two paced normal primary responses, closes the serial connection, records verification evidence and releases the matching marker after successful checks. This takes at least the required transmission intervals. It does not prove secondary deselection.

Verify that fresh normal measurements and MQTT availability return. If recovery fails, preserve the marker and export private evidence for troubleshooting. Do not share identifiers or raw evidence without review. Separate pending address transactions, quarantine or historical restoration can still block operation. Total filesystem failure may prevent durable marker restoration.

## Rollback

Never downgrade or restore an older backup while a diagnostic or address safety state is unresolved. For other failures, stop the app and restore the previous known-good version and corresponding configuration/data backup only after checking safety state. Verify fresh normal measurements and MQTT after restart. Never run two app copies against the same adapter.

See the [app documentation](mbus_probe/README.md) for detailed measurement, clock, archive and diagnostic behavior. Physical recovery of an affected beta installation remains to be verified.
