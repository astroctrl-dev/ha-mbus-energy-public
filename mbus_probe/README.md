# M-Bus T230 energimåling

Les Landis+Gyr T230 over kablet M-Bus, vis målinger i Home Assistant via MQTT Discovery, og last ned validerte normalavlesninger og månedshistorikk som Excel-fil.

## Forberedelse

- Kontroller målerens dokumenterte M-Bus-terminaler og adapterens bussforsyning før fysisk tilkobling. Ledningsfarge alene identifiserer ikke terminalene.
- Gjør USB-serieadapteren tilgjengelig i Home Assistant OS, og installer MQTT-broker og MQTT-integrasjonen.
- Ta backup av appens data og innstillinger før oppdatering. Appdata omfatter målervalg, lagrede normalavlesninger og historikksnapshot.

## Konfigurasjon

1. Velg faktisk `serial_port` i **Settings → Apps → M-Bus T230 energimåling → Configuration**, og bruk baudraten som er dokumentert for måleren.
2. `mqtt_host` er `core-mosquitto` som standard når broker kjører på samme HA-instans. Sett MQTT-bruker og passord lokalt. Velg minst 90 sekunder mellom ordinære avlesninger; standard er 120 sekunder.
3. Trykk **Save** og **Start**. Åpne **Open Web UI**, velg **Søk etter målere**, og bruk **Legg til** på et entydig validert funn. Grensesnittet viser målerens ID og primæradresse lokalt.
4. Kontroller de sju målesensorene og diagnostikk under **Settings → Devices & services → MQTT**. Lagre og start appen på nytt etter endring av innstillinger.

## Klokke og data

Målerens lokale dato og klokkeslett vises som tekst fra normalrammen. Det er et klokkeslett fra måleren uten kodet UTC-offset; Home Assistants tidspunkt for siste vellykkede avlesning vises separat i UTC. Sommertidflagget rapporteres separat. Historiske energiposter er 24 akkumulerte kWh-stander og 23 differanser mellom nabo-stander. Historiske avregningsdatoer vises bare når de faktisk er verifisert; posisjon i arkivet er ikke en avregningsdato.

**Last ned analyse (.xlsx)** lager en fil av allerede lagrede, validerte avlesninger. Nedlasting sender ingen ny M-Bus-forespørsel. Filen bruker et alias i stedet for ekte måler-ID og utelater råtelegrammer og tilgangsopplysninger. Den inneholder likevel reelle måleverdier og bør gjennomgås før deling.

## Månedshistorikk

Aktiver `allow_monthly_history` i **Configuration**, trykk **Save** og start appen på nytt. Velg **Hent månedshistorikk** ved den aktuelle måleren. Operasjonen pauser ordinær polling, velger historisk M-Bus-ramme, leser 24 poster og gjenoppretter og verifiserer normalrammen før polling fortsetter. Den kan ta flere minutter. Trykk ikke gjentatte ganger mens status er **running**. Ved **restore_unverified** stanser ordinær polling; undersøk og verifiser normalrammen før nye avlesninger. Historiske verdier registreres ikke som nytt forbruk i dagens HA Energy-periode.

Når status er **complete**, viser **Open Web UI** en tabell med 24 akkumulerte målerstander og 23 forbruksdifferanser, og Excel-eksporten inneholder arkene **Månedshistorikk** og **Månedsforbruk**. Tabellen kan også vises etter omstart fra lagret snapshot. Uten lagret historikk inneholder eksporten bare normalavlesninger.

## Oppdatering og tilbakeføring

En repository-app oppdateres i **Settings → Apps**. Ta backup av appdata og innstillinger før oppdatering, og kontroller målervalg, MQTT-entiteter og ferske normalavlesninger etterpå. Ved feil: stopp appen, gjenopprett backupen av appdata og tidligere appversjon, start den på nytt, og kontroller MQTT og normalrammestatus. Kjør aldri to appkopier mot samme M-Bus-adapter og MQTT-identiteter samtidig.

## Klokkesynkronisering

Klokkesynk er avslått som standard. Kontroller først at Home Assistant har korrekt systemtid og velg målerens lokale tidssone i `clock_timezone` (standard `Europe/Oslo`). Aktiver `allow_clock_sync`, trykk **Save** og **Restart**. **Synkroniser målerklokke** i **Open Web UI** krever egen bekreftelse. Appen leser klokken, skriver systemtid omregnet til valgt tidssone, og leser tilbake for å verifisere. Måleren rapporterer minutter, ikke sekunder. Hvis kontrollen feiler, vises usikker status; kontroller klokken før du prøver igjen.

`auto_clock_sync` er et separat, frivillig valg. Etter en verifisert manuell synk kontrolleres klokken én gang etter første gyldige avlesning ved appstart eller nytt målervalg. Automatisk retting skjer bare ved avvik over 120 og høyst 300 sekunder eller avvikende sommertidbit innen denne grensen. Større avvik krever manuell handling. Ordningen retter ikke automatisk et helt times avvik ved overgang til sommertid. Innhenting av ferske målinger skjer før denne klokkesjekken. Bruk ikke flere appkopier mot samme adapter.

## Målinger i Home Assistant

Effekt kan være positiv eller negativ. Hver gyldig målepost vurderes for seg; én manglende eller ugyldig verdi gir **unknown** for den sensoren uten å avvise andre gyldige verdier. Volum (m³) og separate akkumulerte timetellere for driftstid, vannstrømstid og tid uten måling vises når de finnes i normalrammen. Timetellerne forteller ikke om pumpa går akkurat nå.

Etter en manuell, fullført historikkinnhenting vises 24 diagnostiske sensorer for akkumulerte kWh-stander og 23 for differanser. Historiske poster har ikke `state_class` som nye energitellere og mates ikke inn som dagens energiforbruk. Et nytt oppsett foreslår sorterbare navn og entitets-ID-er med `−01` … `−24`; eksisterende eller egendefinerte entitets-ID-er omdøpes ikke ved oppdatering. ID-en omfatter en pseudonym målernøkkel, som ikke er anonymisering.

## Datoer for arkiverte verdier

Målerens historikkramme med kWh-stander inneholder ikke verifisert lagringstid for hver post. Appen kan merke dato som **beregnet** fra antatt første dag i måneden: posisjon −01 tilhører innhentingsmåneden, −02 måneden før osv. Dette skjer bare ved ny innhenting etter verifisert manuell klokkesynk, når målerens klokke og valgt Home Assistant-tidssone samsvarer innen 120 sekunder, sommertidbit samsvarer og tidspunktet ikke er innen de første 15 minuttene etter månedsskiftet. Hvis vilkårene ikke er oppfylt, vises ingen beregnet dato. `estimated_date` er et anslag, ikke en målt avregningsdato. En gammel historikk får aldri flyttet datoene når kalenderen skifter.

Ved en senere manuell innhenting kan appen registrere et bekreftet månedsskifte når alle arkivposisjoner er forskjøvet ett trinn og nyeste historiske målerstand er høyere enn før. Dette er bevis for endret arkiv, ikke et målt klokkeslett. Se `history_captured_at_utc` for innhentingstidspunkt og `meter_date_status` for datogrunnlaget.

## Oppdatering

Ta backup av appdata og innstillinger. Ved oppdatering fra 2.0.0: trykk **Update**, kontroller nye klokkevalg (standard avslått), **Save**, og **Start**. Se [installasjonsveiledningen](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md). Tidligere valg under 90 sekunder kjøres som 120 sekunder; velg et gyldig intervall før lagring.
