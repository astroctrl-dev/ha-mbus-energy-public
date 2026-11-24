# M-Bus T230 Energy Metering v2.4.0

**Upgrade recommended for all users of earlier versions.**

Earlier versions did not fully coordinate regular polling, history retrieval and clock synchronization. Requests could occur too close together for the meter's communication timing requirements, potentially resulting in interrupted or missing readings.

## Improvements
- Shared bus-wide transmission gate with at least 61 seconds after each transmission attempt.
- Fixed polling schedule; missed slots are skipped instead of retried outside the schedule.
- Optional polling offset before the full hour.
- Clock synchronization aligned with an eligible minute and verified by readback.
- Optional automatic clock checks and monthly history retrieval after valid regular readings.
- English public user documentation.

## Upgrade
Back up application data and configuration, update, and verify regular polling. Existing application language and temperature unit behavior are unchanged. Multi-meter operation has not been physically verified.
