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
