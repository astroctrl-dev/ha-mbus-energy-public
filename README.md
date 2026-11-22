# M-Bus energimåling i Home Assistant

Åpen kildekode og installasjonsveiledning for en M-Bus-leser med MQTT Discovery. Appen søker primæradresser fortløpende, lar deg stoppe søket når en ønsket måler er funnet, og lar deg legge til flere identifiserte målere. Hver støttet måler får egen enhet i Home Assistant. Denne utgaven validerer telegram fra Landis+Gyr T230; andre modeller krever særskilt støtte.

**Bruk bare i et isolert testmiljø inntil du har kontrollert egen måler, M-Bus-kobling og installasjonen.** Denne README-en beskriver gjeldende installasjon via **Repositories**. Se også [teknisk A–Å-veiledning](INSTALLASJON.md).

## Legg til som custom app-repository

Bruk **repository-URL-en**, ikke lenken til en GitHub Release, en ZIP-fil eller installasjonssiden:

```text
https://github.com/astroctrl-dev/ha-mbus-energy-public
```

**Viktig:** GitHub-taggen v1.0.0 er et tidligere øyeblikksbilde. Bruk URL-en over, uten tagg eller /releases, for oppdatert apptekst, dokumentasjon og repository-oppsett. Appens versjonsfelt er fortsatt 1.0.0.

1. I den isolerte Home Assistant-instansen: åpne **Settings → Apps → Install app**.
2. Åpne menyen øverst til høyre og velg **Repositories**.
3. Lim inn URL-en ovenfor og velg **Add**. Lukk dialogen. Appen vises under **M-Bus energimåling** i appbutikken. Hvis den ikke vises med en gang, oppdater appbutikken.
4. Åpne **M-Bus T230 energimåling** (v1.0.0) og velg **Install**.
5. Kontroller at USB-adapteren er tilgjengelig i denne instansen. Installer og start MQTT-broker, og aktiver MQTT-integrasjonen.
6. Åpne appens **Configuration**, velg faktisk serieport, baud, leseintervall og MQTT-tilgang, og trykk **Save**. Start appen under **Info** med **Start**.
7. Åpne appens **GUI/webgrensesnitt** etter første oppstart. Velg **Søk etter målere**, og trykk **Legg til** for hver måler du vil bruke. Kontroller at de står under **Etablerte målere**.
8. Gå tilbake til appens **Info**-side. Trykk **Stop**, vent til appen er stoppet, og trykk **Start** igjen. Dette er et nødvendig trinn i den observerte førstegangsprosedyren etter at målerne er lagt til.
9. Kontroller at valgte målere og deres sensorverdier vises under **Settings → Devices & services → MQTT**. Dersom verdier mangler, undersøk app- og MQTT-loggene.

Ved endring i appens konfigurasjon: trykk **Save** og **Restart** appen. Du trenger ikke kopiere filer manuelt til `/local_apps` når du bruker denne repository-URL-en. Les [INSTALLASJON.md](INSTALLASJON.md) for kontroll og tilbakeføring.

Ingen reelle måler-ID-er, private nettverksadresser, passord eller råtelegram inngår i dette repositoryet. Eventuelle testtelegram er syntetiske. Måler-ID `12345678` og primæradresse `7` er fiktive eksempler.

Koden sender bare M-Bus-leseforespørsler (REQ_UD2). Den skriver ikke oppsett til måleren. Støttede måleposter må finnes i gyldig telegram; ugyldig identitet eller avlesning gir ikke en ny verdi. Les [INSTALLASJON.md](INSTALLASJON.md) for verifisering, feilsøking og tilbakeføring.

## Lokal verifisering

```sh
PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -v
```

Testene bruker syntetiske telegram og dekker blant annet målersøk, tidlig stopp, validering, MQTT og timeavlesning. Fysisk installasjon i et bestemt miljø må kontrolleres separat.
