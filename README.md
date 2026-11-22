# M-Bus energimåling i Home Assistant

Åpen kildekode og installasjonsveiledning for en M-Bus-leser med MQTT Discovery. Appen søker primæradresser fortløpende, lar deg stoppe søket når en ønsket måler er funnet, og lar deg legge til flere identifiserte målere. Hver måler får egen enhet i Home Assistant.

**Bruk bare i et isolert testmiljø inntil du har kontrollert egen måler, M-Bus-kobling og installasjonen.** Brukerrettet veiledning: [åpen installasjonsside](https://mbus-energimaling-guide.muddyvole4097.chatgpt.site/). Teknisk A–Å-veiledning: [INSTALLASJON.md](INSTALLASJON.md).

## Installasjon fra offentlig repository

1. Sørg for at målerens M-Bus-terminaler og adapterens bussterminaler er dokumentert. Ikke bruk terminaler merket VCC/GND basert på antakelser.
2. Gjør USB-serieadapteren tilgjengelig inne i den isolerte Home Assistant-instansen. Kontroller serieporten etter omstart.
3. Installer og start Mosquitto broker, og aktiver MQTT-integrasjonen i samme instans.
4. Klon dette repositoryet i en terminal med tilgang til HA-konfigurasjonen, kopier appen til `/local_apps`, og oppdater appkatalogen:

   ```sh
   git clone https://github.com/astroctrl-dev/ha-mbus-energy-public.git /config/mbus-release
   mkdir -p /local_apps/mbus_probe
   cp -a /config/mbus-release/mbus_probe/. /local_apps/mbus_probe/
   ha store reload
   ```

5. Åpne **Innstillinger → Apper**, installer **M-Bus T230 MQTT bridge (v1.0.0)**. Velg faktisk serieport, baud, leseintervall og MQTT-tilgang. Trykk **Lagre**, og start appen.
6. Åpne appens brukerflate. Start søk, se ID og primæradresse når måleren dukker opp, og trykk **Legg til**. Du kan stoppe søket og legge til flere funn. Kontroller enheten under **Innstillinger → Enheter og tjenester → MQTT**.

Ingen reelle måler-ID-er, adresser, passord, nettverksadresser eller råtelegram inngår i dette repositoryet. Eventuelle testtelegram er syntetiske. Måler-ID `12345678` og primæradresse `7` er fiktive eksempler.

Koden sender bare M-Bus-leseforespørsler (REQ_UD2). Den skriver ikke oppsett til måleren. Støttede måleposter må finnes i gyldig telegram; ugyldig identitet eller avlesning gir ikke en ny verdi. Les [INSTALLASJON.md](INSTALLASJON.md) for verifisering, feilsøking og tilbakeføring.

## Lokal verifisering

```sh
PYTHONPATH=mbus_probe python3 -m unittest discover -s mbus_probe -v
```

Testene bruker syntetiske telegram og dekker blant annet målersøk, tidlig stopp, validering, MQTT og timeavlesning. Fysisk installasjon i et bestemt miljø må kontrolleres separat.
