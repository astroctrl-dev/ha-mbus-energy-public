# M-Bus T230 energimåling 2.1.0

- Signert effekt håndteres per målepost. Gyldige verdier forblir tilgjengelige selv om en annen post i telegrammet er ugyldig.
- Valgfrie timetellere for målerdrift, vannstrøm og tid uten måling vises separat når måleren leverer dem.
- Manuell synkronisering av målerklokken kan aktiveres i Configuration. En separat automatisk klokkesjekk kjøres én gang etter første gyldige normalavlesning ved appstart eller nytt målervalg. Automatisk skriving krever tidligere verifisert manuell synk og avgrenset tidsavvik. Begge valgene er avslått som standard.
- Etter manuell innhenting vises 24 historiske akkumulerte kWh-stander og 23 differanser som diagnostikk i Home Assistant. Historiske verdier mates ikke som dagens forbruk i HA Energy.
- Historiske datoer kan merkes **beregnet** første dag i måneden når klokkegrunnlaget er verifisert. Tidspunktet er ikke lest fra historikkrammen. En karantene på 15 minutter gjelder etter månedsskifte.
- Ved ny installasjon foreslås sorterbare historiske navn og entitets-ID-er med posisjoner 01–24. Eksisterende entitets-ID-er beholdes.
- Appen prioriterer første ordinære avlesning før automatisk klokkesjekk. Normal intervallavlesning er 120 sekunder som standard.

Installer eller oppdater fra https://github.com/astroctrl-dev/ha-mbus-energy-public. Ta backup av appdata og innstillinger før Update. Se INSTALLASJON.md og mbus_probe/DOCS.md for konfigurasjon, tilbakeføring og datogrunnlag.

Offentlige offline-tester og Docker-bygg er bestått. Kontroller fysisk tilkobling, ferske målinger og eventuelle klokkevalg i egen installasjon.
