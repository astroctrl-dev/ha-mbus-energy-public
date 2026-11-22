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

## C. Installer fra offentlig kilde

Åpne Terminal & SSH i riktig, isolert HA-instans. Kjør kommandoene i [README](README.md#installasjon-fra-offentlig-repository). Kontroller at `ha store reload` fullføres, og at appen vises under **Innstillinger → Apper**. Hvis den ikke vises, kontroller `/local_apps/mbus_probe/config.yaml`, kopieringssti og appkatalogens logg før nytt forsøk.

Før oppdatering: Ta backup av appdata og den eksisterende lokale appmappen, og noter versjonen. Oppdater fra en konkret godkjent commit eller tag, ikke fra ukontrollert flytende `main`.

## D. Konfigurer og start

Installer appen. Velg faktisk serieport, baud, leseintervall (10, 20, 30, 60, 120, 300 eller 600 sekunder), og MQTT-broker, port, bruker og passord. Ekstra lesing før hel time er valgfri, med 0–300 sekunders forskyvning. Trykk **Lagre**; start appen. Etter endring av konfigurasjon: lagre og start appen på nytt.

**Kontroll:** Appen starter uten serieport- eller MQTT-feil. Del aldri passord eller appens `options.json` offentlig.

## E. Søk og velg

Åpne appens ingress-side. Trykk **Søk etter målere**. Appen spør primæradressene 0–250 i rekkefølge. Gyldige funn vises løpende med ID og adresse. Trykk **Legg til** når du ser en ønsket måler; bruk **Stopp søk** når du ikke trenger flere. Du kan legge til flere målere fra de samme funnene. Automatisk valg er bare aktuelt når et fullført, feilfritt søk har nøyaktig én ledig støttet måler.

**Kontroll:** Den valgte ID-en står under **Etablerte målere**. Ved delt primæradresse eller tvetydig svar: stopp og avklar adressene før valg. Måler-ID tastes ikke inn manuelt.

## F. Verifiser i Home Assistant

Under **Innstillinger → Enheter og tjenester → MQTT**: finn enheten for hver valgt måler. Kontroller energi, volum, effekt, volumstrøm og temperaturer som måleren faktisk rapporterer, med riktige enheter og fornuftig oppdatering. Restart appen og kontroller at enhetene gjenfinnes uten duplikater. Ved ugyldig telegram eller brudd skal avlesninger bli utilgjengelige, ikke fremstå som ferske.

## Feilsøking

| Symptom | Kontroller |
| --- | --- |
| Ingen serieport | USB på verten, gjestens USB-tilgang og faktisk enhetsnavn etter omstart. |
| Ingen funn | Dokumentert busstilkobling, baud, tilgang til serieport og timeout i appens logg. |
| Tvetydig svar | Flere målere på samme primæradresse; avklar adresser. |
| Måler funnet, ingen HA-verdi | Gyldig telegram, identitet, måleposter og MQTT-tilkobling. |
| Duplikater etter oppdatering | Sjekk MQTT Discovery-opprydding og tidligere appdata. |

## Tilbakeføring

Stopp appen. Gjenopprett den forrige appmappen, appdata og konfigurasjonen samlet fra backup. Kjør `ha store reload`, velg den tidligere appversjonen og start appen. Rydd kun Discovery-oppføringer som tilhører versjonen som ble fjernet. Bekreft at tidligere målere vises og at avlesningene fungerer. Ikke endre fysisk kobling eller andre HA-instansers konfigurasjon som del av denne tilbakeføringen.
