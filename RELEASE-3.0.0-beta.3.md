# v3.0.0-beta.3 — primary-address discovery and Web UI

- Resume a stopped full search within the current app session, retaining completed results and progress. A new full search discards previous results after confirmation. A changed registered address context prevents resumption.
- Larger three-digit address input, compact search controls and color-coded candidates: green for no response, yellow for conflict risk, red for blocked results and neutral for the current address. Red and neutral results cannot be selected. Selecting a candidate only fills the input.
- Excel and raw telegram downloads are grouped under Data export with shorter descriptions. Two DST status lines are removed from the meter card; underlying diagnostics and clock behavior are retained.
- Missing responses do not guarantee availability. Physical address writing remains disabled. Protocol diagnostics are opt-in and disabled by default.

Isolated-test preview, not a production release. Resume after app restart is not supported. Back up app data before upgrading. Do not downgrade with pending recovery state. Automated verification is performed in the development repository; physical and mobile acceptance remain outstanding.
