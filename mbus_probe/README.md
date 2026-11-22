# M-Bus T230 energimåling

Les av Landis+Gyr T230-målere via M-Bus og vis måleverdiene i Home Assistant gjennom MQTT Discovery.

- Finn målere fortløpende med ID og primæradresse.
- Stopp søket når du har funnet måleren du trenger, eller legg til flere målere.
- Hver valgt måler vises som en egen enhet med energi, volum, effekt, volumstrøm, temperaturer og diagnostikk.
- Appen sender kun leseforespørsler og markerer måleverdier som utilgjengelige ved ugyldig eller manglende avlesning.

Appen er laget for M-Bus-telegram fra **Landis+Gyr T230**. En annen måler må verifiseres og støttes særskilt.

Se fanen **Documentation** for forberedelser, konfigurasjon, bruk, feilsøking og tilbakeføring. Den offentlige [A–Å-veiledningen](https://github.com/astroctrl-dev/ha-mbus-energy-public/blob/main/INSTALLASJON.md) beskriver hele installasjonen.

Alle ID-er og måleverdier i veiledningen er fiktive eksempler.
