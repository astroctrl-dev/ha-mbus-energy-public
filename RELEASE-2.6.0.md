# M-Bus v2.6.0

Stable promotion of v2.6.0-beta.5 without runtime code changes.

- Read monthly set-day configuration and derive historical date attributes for 24 cumulative readings and 23 consumption periods.
- Prioritize initial normal readings before automatic maintenance; preserve the 61-second bus guard across restart when timing is known.
- Optional measurement and raw telegram logging, disabled by default for new installations.
- Scheduled reads tolerate less than ten seconds of delay, capped at the hour boundary for shifted reads.

Physical T230 testing confirmed monthly set day (day 1 at midnight), history retrieval, restoration, ordinary polling and a historical date attribute in Home Assistant. Dates are derived from current configuration, not direct archive timestamps. Actual rollover and delayed polling windows were not physically demonstrated. The automatic maintenance calendar remains unchanged.

Back up app configuration and data before upgrading. Verify normal polling and optional maintenance settings after upgrade. See INSTALLASJON.md and mbus_probe/DOCS.md for operation and rollback. Raw logs can contain identifying meter data; review before sharing.
