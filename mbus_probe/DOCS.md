# M-Bus T230 energimåling

Appen leser Landis+Gyr T230 via kablet M-Bus og publiserer gyldige aktuelle poster med MQTT Discovery. [Full installasjonsveiledning](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md) dekker kobling, oppdatering, kontroll og tilbakeføring.

## Viktig oppgradering – v2.4.0

**Vi anbefaler at alle brukere av tidligere versjoner oppgraderer til v2.4.0.**

I tidligere versjoner var tidsstyringen av ordinære avlesninger, historikkinnhenting og klokkesynkronisering ikke fullt ut samordnet. Under enkelte forhold kunne forespørsler derfor komme for tett i forhold til målerens nødvendige kommunikasjonsintervall, med risiko for avbrutte eller manglende avlesninger.

Fra v2.4.0 benytter alle appens M-Bus-sendinger en felles tidsstyring med minst 61 sekunders ventetid etter hvert sendeforsøk, også ved mislykket sending. Ordinær polling hopper over avlesningstidspunkter som ikke kan gjennomføres innenfor tidskravene. Dette gir mer forutsigbar kommunikasjon og bedre stabilitet.

Ta sikkerhetskopi av appens data og konfigurasjon før oppgradering. Kontroller ordinær avlesning etter oppdatering.

## Innstillinger

| Felt | Beskrivelse |
| --- | --- |
| `serial_port` | Serieenheten som faktisk er tilgjengelig i Home Assistant OS. |
| `baud` | Hastigheten dokumentert for måleren. |
| `interval_seconds` | Normal lesing: 90, 120, 300 eller 600 sekunder; standard 120. Ved 120 s leses normalt på oddetallsminutter (:01, :03 … :59). |
| `read_before_full_hour` | Valgfri forskyvning av hele den faste avlesningsserien, ikke ekstra lesing. |
| `seconds_before_full_hour` | Forskyvning 0–300 sekunder. |
| `allow_clock_sync` | Tillater bekreftet manuell synk til HA-tid med verifisert tilbakelesning. Av som standard. |
| `auto_clock_sync` | Valgfri sjekk ved oppstart og i timen fra kl. 23 lokal tid etter gyldig avlesning. Skriver bare etter tidligere verifisert manuell synk og ved avgrenset tidsavvik. |
| `clock_timezone` | Målerens lokale tidssone, standard `Europe/Oslo`; kontroller før synk. |
| `allow_monthly_history` | Aktiverer separat historikkhandling i webgrensesnittet. |
| `auto_monthly_history` | Av som standard. Ved oppstart og 1. og 2. i måneden fra kl. 01 lokal tid etter gyldig avlesning. Krever allow_monthly_history. |
| `mqtt_host` og `mqtt_port` | Broker, normalt `core-mosquitto:1883`. |
| `mqtt_username` og `mqtt_password` | Legges inn lokalt og må ikke deles. |

Trykk **Save** etter endring og **Restart** appen. Bruk **Open Web UI** til å søke etter og velge målere. Funn viser ID og primæradresse sammen. Hver valgt måler vises under **Settings → Devices & services → MQTT**.

## Aktuelle verdier

Appen viderefører energi, volum, effekt, volumstrøm, turtemperatur, returtemperatur og temperaturdifferanse, samt status og datakvalitet. Den viser målerens lokale dato/tid som tekst, sommertidsflagget separat, og UTC-tidspunktet for siste vellykkede avlesning. Målerens tid har ingen kodet tidssone og konverteres ikke automatisk. En ugyldig målepost gir `unknown` for den aktuelle sensoren uten å avvise andre gyldige verdier. Negativ effekt støttes. Gyldige timetellere for driftstid, vannstrømstid og tid uten måling vises separat; de er akkumulerte timer.

## Historikk og eksport

Når `allow_monthly_history` er aktivert, pauser **Hent månedshistorikk** ordinær polling, velger historisk ramme, leser 24 akkumulerte kWh-stander og gjenoppretter og verifiserer normalrammen. Operasjonen tar flere minutter; ved mislykket kontroll forblir normal polling blokkert. Komplett historikk vises som 24 stander og 23 differanser i webgrensesnittet og arkene **Månedshistorikk** og **Månedsforbruk** i Excel-filen. Ved verifisert målerklokke kan første dag i hver måned vises som **beregnet** dato etter 15 minutter inn i ny måned. Historikkrammen har ikke levert en faktisk avregningsdato, og beregnet dato er tydelig merket. MQTT viser 24 historiske målerstander og 23 differanser som diagnostikk etter manuell innhenting; nye installasjoner får tosifrede posisjoner i foreslåtte navn og entitets-ID-er. Historikken mates ikke som dagens forbruk til HA Energy.

**Last ned analyse (.xlsx)** eksporterer bare lokalt lagrede, validerte data; nedlasting leser ikke måleren. Alias skjuler måler-ID og råtelegram utelates. Måleverdiene er reelle og bør kontrolleres før deling.

### Recovery (2.3.2)
Recovery logs validation errors and TX/response length. `recovery_raw_log` enables full local RX hex; disable after diagnosis and redact meter ID/data before sharing. `allow_recovery_interface_reset` defaults to false. Enable only on a verified single-meter bus after explicit approval: when a checksum-valid frame with matching address and meter ID contains all 24 history records, recovery may send the existing CI=50 normal interface selection command, wait for ACK and verify a fresh normal frame. No clock write or history collection. Guard remains on failure.

## Timing and upgrade checks (2.4.0)

The application uses one monotonic bus-wide transmission gate with at least 61 seconds between attempted sends. Standalone diagnostics must not share the app's serial device. Ordinary polling skips missed slots; manual jobs do not have an hourly exclusion window. Clock writes target the first second of an eligible minute; readback verifies only the meter's minute-resolution time. Automatic calendar jobs start after a valid poll in the configured hour, not necessarily at its beginning. With multiple meters, rotation increases effective per-meter intervals; a full address scan can take several hours. Multi-meter operation has not been physically verified. Preserve app data and options before updating; test ordinary polling, then manual history, then manual clock, then opt-in automation separately. Roll back to v2.3.4 if necessary, preserving the normal-frame recovery marker.
