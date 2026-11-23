# M-Bus T230 energimåling for Home Assistant

Denne appen leser Landis+Gyr ULTRAHEAT T230 over kablet M-Bus og publiserer målinger via MQTT Discovery. Den viser aktuell energi, volum, effekt, volumstrøm, temperaturer og diagnostikk. Målerens lokale klokke vises separat fra tidspunktet Home Assistant leste telegrammet.

## Installer

Legg til dette repositoryet under **Settings → Apps → Install app → ⋮ → Repositories → Add**:

```text
https://github.com/astroctrl-dev/ha-mbus-energy-public
```

Åpne **M-Bus T230 energimåling**, velg **Install**, sett serieport og MQTT-tilgang i **Configuration**, trykk **Save**, og deretter **Start**. Bruk **Open Web UI** til å søke etter og legge til måleren. Søkefunn viser ID og primæradresse sammen. Les [installasjonsveiledningen](INSTALLASJON.md) før fysisk tilkobling og oppdatering.

## Målinger og historikk

De sju eksisterende målesensorene og statusdiagnostikken er bevart. I tillegg vises **Målerens lokale tid**, **Sommertidsflagg** og **Siste vellykkede avlesning**. Målerens dato og tid gjengis slik de står i telegrammet, uten antatt UTC-konvertering. Sommertidsflagget er en separat diagnostikk.

Aktiver `allow_monthly_history` i **Configuration** og velg **Hent månedshistorikk** i **Open Web UI** når du ønsker historikk. Appen pauser normal polling, velger historisk ramme, leser opptil 24 akkumulerte energistander, gjenoppretter normalrammen og verifiserer den før polling fortsetter. Et uverifisert tilbakeskifte blokkerer normal polling. Tabellen viser 24 stander og 23 differanser ved komplett svar. En arkivposisjon er ikke en målt avregningsdato. Historikken registreres ikke som nytt forbruk i dagens Home Assistant Energy-periode.

**Last ned analyse (.xlsx)** eksporterer lagrede validerte avlesninger og eventuell månedshistorikk. Nedlasting sender ingen kommando til måleren. Filen har et alias i stedet for måler-ID og inneholder ikke råtelegram eller tilgangsopplysninger. Den inneholder reelle måleverdier; kontroller den før deling.

Appen bruker minst 61 sekunder mellom busstilgangene, også ved omstart. Standard normalintervall er 120 sekunder. Tidligere v1-innstillinger på 10, 20, 30 og 60 sekunder godtas ved oppgradering og kjøres som 120 sekunder. Velg 90 sekunder eller mer i **Configuration** når du lagrer nye innstillinger.

Ingen ekte måler-ID eller private råtelegram finnes i dette repositoryet. Testfiksturen er syntetisk. Eksempel-ID `12345678` og adresse `7` er fiktive.

## Dokumentasjon og verifisering

- [Installasjon, oppdatering og tilbakeføring](INSTALLASJON.md)
- [Appens dokumentasjon](mbus_probe/DOCS.md)

Kjør offline-testene fra repositoryroten med `PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -p 'test_*.py' -v`. Testene erstatter ikke kontroll av fysisk måler, klokke og tilkobling i eget oppsett.
