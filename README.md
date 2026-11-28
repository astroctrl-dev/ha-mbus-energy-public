# M-Bus T230 energy metering for Home Assistant

Read Landis+Gyr ULTRAHEAT T230 energy meters over wired M-Bus and publish energy, power, volume, flow, temperatures and diagnostics through MQTT Discovery.

## Stable v3.0.0

- Primary-address discovery, optional Fast scan and read-only destination checks.
- Physical primary-address changes and new experimental secondary-address diagnostics are disabled.
- Controlled recovery of existing experimental diagnostic markers through verified primary communication.
- Established historical readings, extended monthly archives, active diagnostics and optional clock synchronization remain supported.

The candidate passed 590 automated tests, container build and runtime import checks, and independent software review. Physical recovery of a pending beta diagnostic and complete physical MQTT acceptance remain unverified.

## Installation

Add https://github.com/astroctrl-dev/ha-mbus-energy-public to the Home Assistant app store repositories. Install **M-Bus T230 energimåling**, configure the documented serial port and MQTT connection, start the app and discover the meter in the web UI.

Back up app data and settings before updating. Do not uninstall, manually remove safety markers or downgrade an unresolved diagnostic session. Use the controlled recovery procedure described in the application documentation.

## Documentation

- [Installation, updates and rollback](INSTALLASJON.md)
- [Application documentation](mbus_probe/README.md)
- [Changelog](mbus_probe/CHANGELOG.md)

Use only one master/application on the adapter. A silent search response is not proof of address availability. Fast scan remains experimental at 2400 baud.
