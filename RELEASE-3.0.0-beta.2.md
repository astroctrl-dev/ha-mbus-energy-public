# v3.0.0-beta.2 — primary-address discovery improvements

- The primary-address panel opens directly below the selected meter's identity and has a Close control.
- Consecutive unanswered probes at different primary addresses use a minimum two-second transmission interval and a complete bounded receive window. Repeated addresses, responses, uncertain exchanges and ordinary bus operations retain conservative 60-second pacing. Restart does not preserve the fast-path authorization.
- Physical address changes remain disabled. The optional protocol diagnostic is disabled by default.

This is an isolated-test preview, not a production release. Physical scan timing and mobile layout require validation. Back up app data before upgrading; do not downgrade with pending recovery state. Missing responses do not prove an address is available. New development tests remain in the private development repository; public runtime files must match the validated candidate.
