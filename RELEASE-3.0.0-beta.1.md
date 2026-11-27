# v3.0.0-beta.1 — address protocol diagnostic preview

This beta is distributed through the existing Home Assistant app repository. It includes read-only address discovery and an opt-in address protocol diagnostic with recovery protection and local evidence export. Physical primary-address changes are disabled.

## Validation and limitations

The development candidate passed automated offline tests, compilation, container build and runtime import checks. Multiple-meter operation and communication interruption were simulated; physical multi-meter behavior and live Home Assistant acceptance remain unverified. Independent verification is outstanding. This preview is intended only for an isolated test installation, not production.

Back up application data before updating. Keep address diagnostics disabled until the test environment and procedure have been reviewed. Do not downgrade while a diagnostic recovery guard is pending. The diagnostic can temporarily select a meter and restore its normal state; it does not change the primary address. Do not publish raw diagnostic evidence or meter identifiers.

The public app runtime matches the validated development candidate. New development-only test fixtures and internal test evidence are not distributed.
