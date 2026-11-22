# Installasjon, kontroll og tilbakeføring

## Forutsetninger

- Isolert Home Assistant OS-instans med administratoradgang.
- Dokumentert M-Bus-måler, korrekt M-Bus-adapter og bekreftet busstilkobling.
- USB-adapter synlig i Home Assistant-gjesten; ved Proxmox konfigureres USB-tilgang bare for denne gjesten.
- MQTT-broker og MQTT-integrasjon i samme gjest, med egen bruker. Passord oppbevares bare i appens konfigurasjon.

## A. Fysisk kobling

Finn målerens dokumenterte M-Bus-terminaler og adapterens dokumenterte MBUS-terminaler. Verifiser ledningsparet og bussforsyning mot begge enhetenes dokumentasjon før tilkobling. Farger er ikke en pålitelig identifikasjon. Koble ikke ekstern strøm til VCC/GND uten dokumentert grunnlag. Noter lokalt modell og oppsett; legg ikke merkeplate eller serienummer i en offentlig sak.

**Kontroll:** Adapteren er tilkoblet uten feilindikasjon. **Ved feil:** Koble fra og verifiser dokumentasjonen på nytt.

## B. USB og isolert gjest

Identifiser USB-serieadapteren på verten og gi den isolerte gjesten USB-tilgang. Se hvilken serieport gjesten faktisk får, og bekreft den igjen etter omstart. Portnavn kan variere.

**Kontroll:** Porten finnes i gjesten. Dette viser USB-tilgang, ikke gyldig målerkommunikasjon.

## C. Legg til offentlig app-repository

Bruk URL-en `https://github.com/astroctrl-dev/ha-mbus-energy-public` i **Settings → Apps → Install app → ⋮ → Repositories → Add**. Lukk dialogen, oppdater appbutikken om nødvendig, og åpne **M-Bus T230 energimåling** (v1.0.0). Velg **Install**. Du trenger ikke terminal, manuell kopiering til `/local_apps` eller `ha store reload` med denne metoden.

**Kontroll:** Repositoryet vises med navnet **M-Bus energimåling**, og appen kan åpnes fra appbutikken. Hvis du ikke finner den: kontroller at hele URL-en er lagt inn uten `/releases` eller `.git`, oppdater appbutikken og se Supervisor-loggen for valideringsfeil.

Før oppdatering eller bytte fra en lokal app: Ta backup av appdata og gjeldende konfigurasjon. Et custom repository får en annen app-ID enn `local_mbus_probe`; behandle dette som egen installasjon og kontroller MQTT Discovery-enhetene for duplikater.

## D. Konfigurer og start

Installer appen. Velg faktisk serieport, baud, leseintervall (10, 20, 30, 60, 120, 300 eller 600 sekunder), og MQTT-broker, port, bruker og passord. Ekstra lesing før hel time er valgfri, med 0–300 sekunders forskyvning. Trykk **Save** under **Configuration**; start appen under **Info** med **Start**. Etter endring: trykk **Save** og deretter **Restart**.

**Kontroll:** Appen starter uten serieport- eller MQTT-feil. Del aldri passord eller appens `options.json` offentlig.

## E. Søk og velg

Åpne appens ingress-side. Trykk **Søk etter målere**. Appen spør primæradressene 0–250 i rekkefølge. Gyldige funn vises løpende med ID og adresse. Trykk **Legg til** når du ser en ønsket måler; bruk **Stopp søk** når du ikke trenger flere. Du kan legge til flere målere fra de samme funnene. Automatisk valg er bare aktuelt når et fullført, feilfritt søk har nøyaktig én ledig støttet måler.

**Kontroll:** Den valgte ID-en står under **Etablerte målere**. Ved delt primæradresse eller tvetydig svar: stopp og avklar adressene før valg. Måler-ID tastes ikke inn manuelt.

## F. Verifiser i Home Assistant

Under **Settings → Devices & services → MQTT**: finn enheten for hver valgt måler. Kontroller energi, volum, effekt, volumstrøm og temperaturer som måleren faktisk rapporterer, med riktige enheter og fornuftig oppdatering. Velg **Restart** for appen og kontroller at enhetene gjenfinnes uten duplikater. Ved ugyldig telegram eller brudd skal avlesninger bli utilgjengelige, ikke fremstå som ferske.

## Feilsøking

| Symptom | Kontroller |
| --- | --- |
| Ingen serieport | USB på verten, gjestens USB-tilgang og faktisk enhetsnavn etter omstart. |
| Ingen funn | Dokumentert busstilkobling, baud, tilgang til serieport og timeout i appens logg. |
| Tvetydig svar | Flere målere på samme primæradresse; avklar adresser. |
| Måler funnet, ingen HA-verdi | Gyldig telegram, identitet, måleposter og MQTT-tilkobling. |
| Duplikater etter oppdatering | Sjekk MQTT Discovery-opprydding og tidligere appdata. |

## Tilbakeføring

Stopp den nye appen. Gjenopprett den tidligere appen fra backup med tilhørende appdata og konfigurasjon. Ved overgang fra `local_mbus_probe`: gjenopprett den lokale appen som en egen installasjon; den nye repository-appen har en annen ID. Kontroller MQTT Discovery og rydd kun oppføringer som tilhører den nye installasjonen. Bekreft at tidligere målere vises og avlesningene fungerer. Ingen endring i fysisk kobling eller andre HA-instanser.
