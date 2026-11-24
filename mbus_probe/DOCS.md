# M-Bus T230 energimåling

Appen leser Landis+Gyr T230 via kablet M-Bus og publiserer gyldige aktuelle poster med MQTT Discovery. [Full installasjonsveiledning](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md) dekker kobling, oppdatering, kontroll og tilbakeføring.

## Innstillinger

| Felt | Beskrivelse |
| --- | --- |
| `serial_port` | Serieenheten som faktisk er tilgjengelig i Home Assistant OS. |
| `baud` | Hastigheten dokumentert for måleren. |
| `interval_seconds` | Normal lesing: 90, 120, 300 eller 600 sekunder; standard 120. Eldre v1-valg under 90 vises fremdeles for kompatibilitet, men kjøres som 120. Velg 90 eller høyere når du lagrer nye innstillinger. |
| `read_before_full_hour` | Valgfri ekstra lesing før hel time, med minst 61 sekunder mellom busstilgangene. |
| `seconds_before_full_hour` | Forskyvning 0–300 sekunder. |
| `allow_clock_sync` | Tillater bekreftet manuell synk til HA-tid med verifisert tilbakelesning. Av som standard. |
| `auto_clock_sync` | Valgfri sjekk ved oppstart etter første gyldige avlesning. Skriver bare etter tidligere verifisert manuell synk og ved avgrenset tidsavvik. |
| `clock_timezone` | Målerens lokale tidssone, standard `Europe/Oslo`; kontroller før synk. |
| `allow_monthly_history` | Aktiverer separat historikkhandling i webgrensesnittet. |
| `mqtt_host` og `mqtt_port` | Broker, normalt `core-mosquitto:1883`. |
| `mqtt_username` og `mqtt_password` | Legges inn lokalt og må ikke deles. |

Trykk **Save** etter endring og **Restart** appen. Bruk **Open Web UI** til å søke etter og velge målere. Funn viser ID og primæradresse sammen. Hver valgt måler vises under **Settings → Devices & services → MQTT**.

## Aktuelle verdier

Appen viderefører energi, volum, effekt, volumstrøm, turtemperatur, returtemperatur og temperaturdifferanse, samt status og datakvalitet. Den viser målerens lokale dato/tid som tekst, sommertidsflagget separat, og UTC-tidspunktet for siste vellykkede avlesning. Målerens tid har ingen kodet tidssone og konverteres ikke automatisk. En ugyldig målepost gir `unknown` for den aktuelle sensoren uten å avvise andre gyldige verdier. Negativ effekt støttes. Gyldige timetellere for driftstid, vannstrømstid og tid uten måling vises separat; de er akkumulerte timer.

## Historikk og eksport

Når `allow_monthly_history` er aktivert, pauser **Hent månedshistorikk** ordinær polling, velger historisk ramme, leser 24 akkumulerte kWh-stander og gjenoppretter og verifiserer normalrammen. Operasjonen tar flere minutter; ved mislykket kontroll forblir normal polling blokkert. Komplett historikk vises som 24 stander og 23 differanser i webgrensesnittet og arkene **Månedshistorikk** og **Månedsforbruk** i Excel-filen. Ved verifisert målerklokke kan første dag i hver måned vises som **beregnet** dato etter 15 minutter inn i ny måned. Historikkrammen har ikke levert en faktisk avregningsdato, og beregnet dato er tydelig merket. MQTT viser 24 historiske målerstander og 23 differanser som diagnostikk etter manuell innhenting; nye installasjoner får tosifrede posisjoner i foreslåtte navn og entitets-ID-er. Historikken mates ikke som dagens forbruk til HA Energy.

**Last ned analyse (.xlsx)** eksporterer bare lokalt lagrede, validerte data; nedlasting leser ikke måleren. Alias skjuler måler-ID og råtelegram utelates. Måleverdiene er reelle og bør kontrolleres før deling.
