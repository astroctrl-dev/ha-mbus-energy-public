# Dokumentasjon: M-Bus T230 energimåling

Appen leser Landis+Gyr T230 via M-Bus-til-USB og oppretter sensorer med MQTT Discovery. Andre målere er ikke automatisk støttet. Kontroller ny installasjon i en isolert HA-instans.

## Før du starter

1. Identifiser målerens dokumenterte M-Bus-klemmer, adapterens bussterminaler og forsyning. Ledningsfarge alene er ikke tilstrekkelig. Ikke bruk VCC/GND eller ekstern spenning uten dokumentasjon.
2. Bekreft at USB-adapteren er synlig som serieport i HA-gjesten, også etter omstart.
3. Start MQTT-broker og kontroller at **Settings → Devices & services → MQTT** er tilkoblet. Bruk egen MQTT-bruker; hold passordet privat.
4. Legg til [det offentlige repositoryet](https://github.com/astroctrl-dev/ha-mbus-energy-public) under **Settings → Apps → Install app → Repositories**, og velg **Install**.

## Konfigurasjon

Åpne **Configuration** og fyll inn faktiske verdier:

| Felt | Hva det betyr |
| --- | --- |
| serial_port | Serieporten som finnes i HA-gjesten. |
| baud | M-Bus-hastigheten måleren støtter. |
| interval_seconds | Tid mellom fullførte leseforsøk: 10, 20, 30, 60, 120, 300 eller 600 sekunder. Standard: 120. |
| read_before_full_hour | Valgfri ekstra avlesning før neste hele time. |
| seconds_before_full_hour | Hvor mange sekunder før hel time: 0–300. |
| mqtt_host og mqtt_port | Brokerens vertsnavn og port i denne HA-instansen. |
| mqtt_username og mqtt_password | Egen MQTT-bruker og passord; ikke publiser passordet. |

Trykk **Save**, deretter **Start** på fanen **Info**, og åpne **Open Web UI**. Etter endring: trykk **Save** og **Restart**. Home Assistant Core trenger ikke omstart for disse appinnstillingene.

## Søk og velg målere

1. Trykk **Søk etter målere**. Appen kontrollerer primæradresse 0–250 i rekkefølge. Gyldige funn vises fortløpende med ID og adresse.
2. Trykk **Legg til** for ønsket måler. Fortsett å legge til flere om ønskelig. Trykk **Stopp søk** når du har funnet dem du trenger.
3. Valgte målere vises under **Etablerte målere**. Eksempel-ID 12345678 og adresse 7 er fiktive; ikke bruk dem som dine egne.
4. **Velg eneste ledige automatisk** krever et fullført søk uten uavklarte svar og nøyaktig én ledig, støttet måler.

Målere med samme primæradresse kan gi tvetydige svar. Avklar adressekonflikt før valg.

## Kontroller resultatet

Under **Settings → Devices & services → MQTT** skal hver måler ha egen enhet. Kontroller energi (kWh), volum (m³), effekt (kW), volumstrøm (m³/h), tur- og returtemperatur (°C), temperaturdifferanse (K), M-Bus-status og datakvalitet. Gyldige, aktuelle poster kreves før verdi vises som tilgjengelig. Ved manglende eller ugyldig avlesning blir måleren utilgjengelig. M-Bus-status 0x10 gir datakvalitet **Advarsel**.

## Feilsøking og tilbakeføring

| Symptom | Kontroller |
| --- | --- |
| Appen mangler | Repository-URL, appbutikkens oppdatering og Supervisor-loggen. |
| Ingen serieport | USB-tilgang i gjesten og valgt port etter omstart. |
| Ingen måler funnet | Dokumentert kobling, baud og timeout i loggen. |
| Måler funnet, ingen MQTT-enhet | Broker, MQTT-integrasjon og appens logg. |
| Dublerte enheter | Se om både lokal app og repository-app publiserer samtidig. |

For tilbakeføring: Stopp den nye appen og gjenopprett tidligere app, appdata og konfigurasjon fra backup samlet. En repository-app har en annen intern ID enn en lokal app. Kontroller MQTT Discovery og rydd kun oppføringer fra installasjonen som fjernes.

Se [full A–Å-veiledning](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md).
