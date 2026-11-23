# M-Bus T230 energimåling for Home Assistant

Denne appen leser Landis+Gyr ULTRAHEAT T230 over kablet M-Bus og publiserer målinger via MQTT Discovery. Den viser aktuell energi, volum, effekt, volumstrøm, temperaturer og diagnostikk. Målerens lokale klokke vises separat fra tidspunktet Home Assistant leste telegrammet.

## Installer

Legg til dette repositoryet under **Settings → Apps → Install app → ⋮ → Repositories → Add**:

```text
https://github.com/astroctrl-dev/ha-mbus-energy-public
```

Åpne **M-Bus T230 energimåling**, velg **Install**, sett serieport og MQTT-tilgang i **Configuration**, trykk **Save**, og deretter **Start**. Bruk **Open Web UI** til å søke etter og legge til måleren. Søkefunn viser ID og primæradresse sammen. Les [installasjonsveiledningen](INSTALLASJON.md) før fysisk tilkobling og oppdatering.

## Målinger og historikk

De sju eksisterende målesensorene og statusdiagnostikken er bevart. Fra 2.1.0 vises også valgfrie timetellere for driftstid, vannstrømstid og tid uten måling. Signert effekt støttes; en ugyldig målepost gjør bare den berørte sensoren ukjent. I tillegg vises **Målerens lokale tid**, **Sommertidsflagg** og **Siste vellykkede avlesning**. Målerens dato og tid gjengis slik de står i telegrammet, uten antatt UTC-konvertering. Sommertidsflagget er en separat diagnostikk.

Aktiver `allow_monthly_history` i **Configuration** og velg **Hent månedshistorikk** i **Open Web UI** når du ønsker historikk. Appen pauser normal polling, velger historisk ramme, leser opptil 24 akkumulerte energistander, gjenoppretter normalrammen og verifiserer den før polling fortsetter. Et uverifisert tilbakeskifte blokkerer normal polling. Tabellen viser 24 stander og 23 differanser ved komplett svar. Avregningsdato kan vises som **beregnet** første dag i måneden når både målerklokke og systemklokke er verifisert og innhentingen skjer etter det første kvarteret i måneden. Dette er ikke en målt avregningsdato. Historikken registreres ikke som nytt forbruk i dagens Home Assistant Energy-periode.

**Last ned analyse (.xlsx)** eksporterer lagrede validerte avlesninger og eventuell månedshistorikk. Nedlasting sender ingen kommando til måleren. Filen har et alias i stedet for måler-ID og inneholder ikke råtelegram eller tilgangsopplysninger. Den inneholder reelle måleverdier; kontroller den før deling.

Ordinære avlesninger av samme måler er sperret i minst 61 sekunder, også ved omstart. Et adressesøk prøver ulike primæradresser og skal ikke startes gjentatte ganger mot samme måler. Standard normalintervall er 120 sekunder. Tidligere v1-innstillinger på 10, 20, 30 og 60 sekunder godtas ved oppgradering og kjøres som 120 sekunder. Velg 90 sekunder eller mer i **Configuration** når du lagrer nye innstillinger.

Ingen ekte måler-ID eller private råtelegram finnes i dette repositoryet. Testfiksturen er syntetisk. Eksempel-ID `12345678` og adresse `7` er fiktive.

## Klokkesynk og nye historikksensorer

Klokkesynk er av som standard. Etter at `allow_clock_sync` er aktivert kan **Synkroniser målerklokke** stille måleren til Home Assistant-tid i konfigurert tidssone med bekreftelse og tilbakekontroll. `auto_clock_sync` er et separat valg og krever verifisert manuell synk før automatisk skriving. Se [appens dokumentasjon](mbus_probe/DOCS.md) for grenser og forutsetninger.

Etter manuell historikkinnhenting viser HA 24 akkumulerte historiske kWh-sensorer og 23 differansesensorer som diagnostikk. Navn og foreslåtte entitets-ID-er på et nytt oppsett bruker posisjonene `01` til `24`. Eksisterende entitets-ID-er omdøpes ikke automatisk.

## Dokumentasjon og verifisering

- [Installasjon, oppdatering og tilbakeføring](INSTALLASJON.md)
- [Appens dokumentasjon](mbus_probe/DOCS.md)

Kjør offline-testene fra repositoryroten med `PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -p 'test_*.py' -v`. Testene erstatter ikke kontroll av fysisk måler, klokke og tilkobling i eget oppsett.
