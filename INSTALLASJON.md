# Installasjon, oppdatering og tilbakeføring

## Før du begynner

Kontroller målerens dokumenterte M-Bus-terminaler, adapterens terminaler og bussforsyning. Ledningsfarge alene identifiserer ikke tilkoblingen. Bruk ikke adapterens VCC/GND eller ekstern spenning uten dokumentert grunnlag. Sørg for at USB-serieadapteren vises i Home Assistant OS, at MQTT-broker er installert og at MQTT-integrasjonen er tilkoblet. Én app skal bruke adapteren om gangen.

## Ny installasjon

1. Åpne **Settings → Apps → Install app → ⋮ → Repositories**. Legg til `https://github.com/astroctrl-dev/ha-mbus-energy-public` og velg **Add**. Oppdater appbutikken ved behov.
2. Åpne **M-Bus T230 energimåling** og velg **Install**.
3. I **Configuration**: velg faktisk `serial_port`, målerens baudrate og intervall 90 sekunder eller mer. `mqtt_host` er `core-mosquitto` som standard; fyll inn MQTT-bruker og passord lokalt. Ikke del `options.json` eller passord.
4. Trykk **Save**, gå til **Info** og velg **Start**. Åpne **Open Web UI**. Velg **Søk etter målere**. Gyldige funn vises fortløpende med måler-ID og primæradresse; trykk **Legg til** for ønsket måler og **Stopp søk** når du er ferdig.
5. Finn måleren under **Settings → Devices & services → MQTT**. Kontroller måleverdier, enheter, klokke, tidspunkt for siste avlesning og tilgjengelighet. Etter konfigurasjonsendring: **Save** og **Restart**.

Ved ingen serieport: kontroller USB-tilordning og portnavn etter omstart. Ved ingen måler: kontroller dokumentert busstilkobling, baud og appens logg. Et gyldig USB-enhetsnavn alene er ikke bevis på målersvar.

## Oppgradering fra v1.0.0 eller v2.0.0

Bruk samme repository-URL og app. Ta full backup av appdata og noter konfigurasjonen før **Update**. Den installerte appens målervalg og lagrede data ligger i appens `/data`; ta vare på denne sammen med backupen. Stopp appen, velg **Update**, og kontroller **Configuration** før **Start**. Eldre intervallvalg 10, 20, 30 og 60 sekunder behandles som 120 sekunder i v2.1. Velg et gyldig intervall før du lagrer Configuration. Ikke bruk dem for ny konfigurasjon. Velg 120 sekunder eksplisitt og trykk **Save**. Kontroller at de tidligere MQTT-entitetene beholdes og at ny avlesning kommer inn. En lokal app og en repository-app har ulike app-ID-er og deler ikke automatisk appdata.

## Månedshistorikk og klokke

Målerens lokale klokke gjengis som tekst uten UTC-offset; sommertidsflagget vises separat. Siste vellykkede lesetid er Home Assistants UTC-tidspunkt. Klokkesynk er av som standard. Kontroller HA-systemtid og `clock_timezone`, aktiver `allow_clock_sync`, **Save** og **Restart**. Knappen **Synkroniser målerklokke** stiller måleren manuelt etter bekreftelse og krever en verifisert tilbakelesning. `auto_clock_sync` er et separat valg etter verifisert manuell synk; kontroll skjer ved oppstart etter første gyldige måling. Større klokkeavvik krever manuell oppfølging.

For historikk: aktiver `allow_monthly_history`, trykk **Save** og **Restart**, og velg **Hent månedshistorikk** på riktig måler. Vent til status **complete**. Da vises akkumulerte stander og differanser i **Open Web UI**, og **Last ned analyse (.xlsx)** kan eksportere dem sammen med normalavlesningene. Ved verifisert klokke kan første dag i aktuell og tidligere måneder vises som **beregnet** dato, med 15 minutters karantene etter månedsskifte. Datoen er ikke lest fra historikkrammen. Hvis klokkegrunnlaget er usikkert, vises ingen beregnet dato. Ved **restore_unverified** forblir vanlig polling blokkert til normalrammen er kontrollert.

Historikk vises også som 24 diagnostiske historiske målerstander og 23 differanser i MQTT etter manuell innhenting. Ved ren installasjon foreslås tosifrede entitets-ID-er; eksisterende navn/ID-er endres ikke automatisk ved oppdatering.

## Tilbakeføring

Stopp appen. Gjenopprett forrige appversjon og den tilhørende appbackupen med konfigurasjon og appdata. Start appen igjen, kontroller MQTT-enhetene og en fersk normalavlesning. Kjør aldri to appkopier samtidig mot samme adapter og MQTT-identiteter.
