# M-Bus T230 v3.0.0

Stable primary-address search and guarded legacy recovery.

## Changes

- Retain primary search, optional Fast scan, result colors and read-only destination checks.
- Permanently disable physical primary-address changes in the supported service, including legacy configuration and direct API calls.
- Restrict transmission to supported primary operations, including established clock and historical-frame commands.
- Disable new secondary-address diagnostic sessions and creation of new diagnostic safety markers.
- Recover existing experimental diagnostic markers through two validated primary responses, durable evidence and verified serial closure before marker release.

## Validation and compatibility

590 automated tests passed, including recovery, injected storage and serial-close faults, production discovery worker, transmission allowlist and simulated MQTT resumption. Container build and runtime imports succeeded. Independent software review approved the application candidate.

Existing app slug, entity identifiers and stored measurement/history formats are retained. Back up before updating. Physical beta-marker recovery, actual Supervisor upgrade behavior and complete physical post-search MQTT acceptance remain unverified. Fast scan remains experimental. Full filesystem loss may prevent durable recovery-marker restoration. Separate pending address transactions or historical recovery are not resolved by this procedure.

## Update and rollback

Update the existing app normally. Follow the [installation and recovery guide](INSTALLASJON.md). Do not uninstall or downgrade while safety state is unresolved. Verify fresh readings and MQTT availability following installation.
