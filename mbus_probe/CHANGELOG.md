# 2.6.0

- Stable promotion of beta.5; no runtime code changes.
- Physical T230 verification: monthly set day, history retrieval, normal-frame restoration and HA history date attribute demonstrated.
- Dates are derived, not meter-stamped; actual month rollover and delayed slot behavior remain unverified on hardware.

# 2.6.0-beta.5

- Allow scheduled polls up to ten seconds late, including shifted polls capped at the hour boundary; preserve the minimum bus interval.

- Decode observed T230 frame-2 labelled diagnostic records as opaque values, retaining strict frame validation and enabling monthly set-day dates.

# 2.6.0-beta.4

- Prioritize first ordinary reads and new meter selection; reuse safe same-boot request timing after restart.

- All optional configuration switches default off for fresh installations, including measurement logging.
- Document ordinary polling first, six-minute history retrieval and potential temporary stale/unavailable live measurements.

# 2.6.0-beta.3

- Read monthly set-day configuration before frame 3; derive historical timestamps conservatively.
- Separate measurement and raw logging configuration; raw download as text.
- History retrieval takes about six minutes per meter. Physical frame-2 verification pending.

# Changelog

## 2.6.0-beta.2

- Skip raw frame classification when capture is disabled. TX capture occurs after the timing gate updates eligibility and releases its lock. Pending count includes in-flight disk writes. No new meter operations.

## 2.6.0-beta.1

- Opt-in local raw transport evidence for investigation of historical dates. No additional bus commands. Capture defaults off on every restart; saved log remains downloadable. Two rotating 5 MiB files, bounded asynchronous queue. Raw JSONL is separate from existing anonymized Excel export. Physical validation pending; exact historical dates not yet implemented.

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
