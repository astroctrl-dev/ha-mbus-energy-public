# M-Bus T230 energy metering v2.5.0

- Home Assistant configuration translations: English, Norwegian Bokmål, Norwegian Nynorsk and German.
- Independent web interface and Excel Info in English.
- Native Home Assistant temperature-difference conversion via temperature_delta. Existing MQTT values and sensor identities unchanged.
- No extra language or temperature options. Excel retains decoded units and existing workbook structure.
- M-Bus communication, clock synchronization, history capture and scheduling remain unchanged from v2.4.0.

Validation: automated tests and Docker build passed for beta.3; stable publication is gated by the same tests. User verified regular readings, delta Celsius conversion and simplified configuration. Independent review and full physical/statistics validation remain incomplete. Some legacy labels and technical errors remain untranslated. Back up existing app data before updating; restore previous version and backup if required.
