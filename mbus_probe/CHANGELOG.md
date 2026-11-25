# 2.7.4

- Promotes 2.7.4-beta.1 without runtime code changes.
- Private candidate CI: 171 tests and Docker build passed. Physical clock synchronization and ordinary polling verified; one transient timeout recovered automatically.
- Product lead confirmed restart of v2.7.4-beta.1 and recovery of sensor values. Actual seasonal transition and active alarm persistence remain unverified. Stable promotion approved by product lead.

# 2.7.4-beta.1

- Use the Home Assistant timezone supplied by Supervisor, with configured fallback.
- Check seasonal transitions after the actual UTC transition instant on the next eligible valid polling round, including fixed standard-time policy.
- Verify clock writes using wall time rather than the reported DST bit.
- Retire experimental DST write tests; retain historical evidence and existing diagnostics.
- Seconds-resolution reading remains unverified; minute-based reading is retained.
- Automated private CI: 171 tests passed and Docker build succeeded. Physical seasonal transition and active alarm persistence remain unverified. Controlled beta only.

# 2.7.3-beta.1

- Persistent seasonal transition diagnostics and verified clock override indicator.
- One seasonal check at noon, with catch-up after downtime.
- Automatic large clock corrections restricted to the scheduled seasonal operation and trusted meters.
- Manual alternative DST diagnostic with restoration attempt.
- Physical verification pending; not intended for production use.
