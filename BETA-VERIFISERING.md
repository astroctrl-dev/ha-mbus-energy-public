# Verifikasjonsplan – v2.1.2-beta.1 (Feature #54)

**Status:** Kandidat, ikke publisert release. Ingen fysisk installasjon eller endring i HA er utført. Kode-CI alene er ikke et HA-akseptansebevis.

## Før installasjon – beslutningspunkt

- [ ] Uavhengig reviewer har vurdert PR #7 (MQTT reconnect, asynkron tråd, discovery-konfigurasjon og tilbakeføring).
- [ ] POL har uttrykkelig godkjent hvilken *konkret* HA-instans som skal brukes. Ikke endre HA-Hoved eller eksisterende HA-DEV uten slik godkjenning.
- [ ] Noter fungerende versjon (v2.1.1), app-ID, konfigurasjon og faktisk måleradresse lokalt; ta verifisert backup av appdata.
- [ ] Testkandidat er publisert som sporbar prerelease/tag med eksakt commit. **Branch er ikke en installérbar Home Assistant-repository-release.**
- [ ] Én app om gangen får tilgang til USB/M-Bus. Unngå samtidige MQTT-publisister med samme client_id og discovery-identiteter.

## Akseptansetest (etter godkjenning)

1. **Baseline:** Noter normal avlesning, tidsstempel, energiverdi, måler-ID og tilgjengelighet på eksisterende v2.1.1. Ta skjermbilde av nåværende entiteter. Ikke del passord, rå ID eller private telegram offentlig.
2. **Installasjon:** Installer nøyaktig godkjent beta og bekreft versjon i HA-appens Info. Behold samme måler- og MQTT-konfigurasjon. Kontroller at appen starter.
3. **M-Bus:** Verifiser gyldig telegram og ny dekodet energiverdi. Ordinær polling skal fortsette selv om MQTT Discovery er treg.
4. **Broker:** Kontroller at 47 forskjellige retained `homeassistant/sensor/.../config`-topics finnes for valgt måler (24 `history_stand` og 23 `history_period`). PUBACK er *ikke* bevis på HA-entitet.
5. **Home Assistant:** Under MQTT-enheten kontrolleres **47 opprettede historikk-entiteter**, inkludert entiteter som eventuelt er deaktivert. Noter faktisk antall og eventuelle avvisningsfeil i HA-logg. Historikkverdier kan være `unknown` før innhenting.
6. **Historikk:** Med `allow_monthly_history` og etter manuell innhenting: kontroller 24 stander, 23 differanser, kWh-enhet og `history_captured_at_utc`-attributt der det er tilgjengelig. Historiske stander må ikke inngå som nytt energiforbruk i HA Energy.
7. **Omstart/reconnect:** Restart bare den godkjente testappen, og simuler MQTT-reconnect bare når godkjent. Verifiser ingen duplikatentiteter, normal polling og fortsatt 47 Discovery-konfigurasjoner.
8. **Feilscenario:** Simuler treg/ikke tilgjengelig broker kun i isolert test. Bekreft at M-Bus-avlesning ikke blokkeres av Discovery-kvitteringene. Rapporter eventuelle avvik og logger.
9. **Dokumentasjon:** Lagre testdato, installert SHA, HA-versjon, resultat, antall entiteter, relevante sladdede logger og testansvarlig i Feature #54 / PR #7.

## Tilbakeføring

Stopp betaappen før du gjenoppretter forrige versjon. Gjenopprett **v2.1.1 med tilhørende appdata og konfigurasjon fra backup**; start kun én M-Bus-app. Bekreft en ny normal avlesning og at eksisterende sensorer er intakte. Hvis MQTT Discovery fra beta fortsatt er retained, må eventuell opprydding vurderes eksplisitt; ikke slett ukjente discovery-topics automatisk.

## Releasekriterier

Beta kan først annonseres som installérbar når prerelease/tag er faktisk publisert og versjon/SHA er kontrollert. Stabil v2.1.2 krever bestått fysisk HA-test, dokumenterte 47 entiteter, uavhengig verifikasjon og godkjent tilbakeføringsprosedyre.
