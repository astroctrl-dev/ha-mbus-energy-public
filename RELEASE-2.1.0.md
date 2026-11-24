# M-Bus T230 Energy Metering 2.1.0

- Signed power is handled per measurement record. Valid values remain available even when another record in the telegram is invalid.
- Optional counters for meter operating hours, water flow hours and hours without measurement are displayed separately when supplied by the meter.
- Manual meter clock synchronization can be enabled in Configuration. A separate automatic clock check runs once after the first valid normal reading at startup or after selecting a new meter. Automatic writes require previously verified manual synchronization and a bounded clock deviation. Both options are disabled by default.
- Manual history retrieval is designed to expose 24 cumulative historical kWh readings and 23 differences as Home Assistant diagnostics. Historical values are not counted as today's consumption in HA Energy.
- Historical dates may be labelled **estimated** as the first day of the month when clock provenance is verified. The timestamp is not read from the historical frame. A 15-minute exclusion window applies after the month changes.
- New installations suggest sortable historical names and entity IDs using positions 01–24. Existing entity IDs are retained.
- The app prioritizes the first normal reading before the automatic clock check. The default polling interval is 120 seconds.

Install or update from https://github.com/astroctrl-dev/ha-mbus-energy-public. Back up app data and settings before updating. See [installation guide](INSTALLASJON.md) and [app documentation](mbus_probe/DOCS.md) for configuration, rollback and date provenance.

Public offline tests and Docker builds passed for the original release. Verify physical connections, fresh measurements and any clock settings in your own installation.
