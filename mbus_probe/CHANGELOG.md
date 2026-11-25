# Changelog

## 2.5.0

- Final language architecture: Home Assistant configuration translations in four languages, independent web interface and Excel Info in English.
- Native Home Assistant temperature_delta support; no extra configuration parameters.
- Existing sensor identifiers, decoded units, and M-Bus communication unchanged.
- User verified regular readings, Celsius delta conversion and configuration simplification. Full independent verification and long-term statistics verification not completed.

## 2.5.0-beta.3

- Independent web interface and Excel Info use English, regardless of browser preferences.
- Home Assistant configuration translations remain available in four languages.
- No additional settings or API permissions. Existing sensor names, identities and measurement handling unchanged.

## 2.5.0-beta.2

- Removed separate language and Excel temperature configuration options.
- App interface and Excel Info use browser language automatically, with English fallback.
- Excel retains decoded units; Home Assistant entity settings control temperature display.
- Existing sensor names and identities unchanged. Bulk display-name localization deferred.

## 2.5.0-beta.1

- English, Norwegian Bokmål, Norwegian Nynorsk and German interface and configuration translations.
- Excel Info translation and optional Celsius, Kelvin or Fahrenheit temperature display.
- Native MQTT temperature difference uses Home Assistant temperature_delta; native K values and existing sensor identifiers retained.
- Existing workbook sheet and column identifiers retained.
- No changes to bus timing, polling, clock writes, history capture or raw decoding.
- Known limitations: browser language fallback, unmapped technical errors, per-entity HA temperature preferences. Physical validation and existing statistics verification pending.
- Private candidate only; not a stable release.
