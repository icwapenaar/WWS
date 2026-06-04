# WWS App — Projectbriefing

## Wat we bouwen
Een webapp die per gebouw de exacte WWS-puntentelling en maximale huurprijs per appartement of kamer berekent (Nederlands woningwaarderingsstelsel, Wet betaalbare huur). Kernflow:

1. **Upload plattegrond (PDF)** → server-side AI-extractie (tekst + coördinaten via PyMuPDF, interpretatie via Claude API) → gestructureerde JSON volgens de Data Export Specification.
2. **Controlescherm** → gebruiker ziet per ruimte wat herkend is (naam, functie, m², toewijzing aan woning) en corrigeert waar nodig. Niet-toegewezen m²-annotaties worden als openstaande vraag getoond, nooit stilzwijgend overgeslagen.
3. **Aanvulscherm** → velden die niet op een tekening staan: WOZ, energielabel, keuken- en sanitairspecificaties, monumentstatus, contractdata (M/C-velden uit de spec).
4. **Rekenkern** → exacte punten per rubriek, sector (sociaal/midden/vrij), maximale huur incl. prijsopslagen. Twee stelsels: zelfstandig (WWS) en kamers (WWSO).
5. **Output** → prijslijst per gebouw, audit-verantwoording per toegekend punt (controleerbaar), optimalisatie-advies (route naar vrije sector), CSV/PDF-export.

## Referentiebestanden in deze map (al gebouwd en getest)
- `wws-calculator.html` — **werkend prototype met de complete rekenkern in JavaScript**: beide stelsels, prijstabellen 2026, classificatie, WOZ-cap 33% met 186-vangnet, zorgtoeslag, prijsopslagen, audit-log, optimalisatie-advies, handmatige invoer. De rekenlogica hieruit 1-op-1 porten — niet opnieuw bedenken. Regressiegetest tegen het GKB16-gebouw.
- `WWS-Data-Export-Specification.docx` — het JSON-schema (building/units/spaces, veldnamen, enums, bronmarkering A/M/C).
- `WWS-puntentelling-bouwdocument.md` — alle WWS/WWSO-rekenregels met bronverwijzing (beleidsboeken Huurcommissie jan. 2026).
- `gkb16-fase2.json` — testfixture: echt gebouw (8 woningen, rijksmonument). Verwachte uitkomsten met label A + standaard keuken/sanitair: W1 189, W2 192, W3 189, W4 167, W5 162, W6 183, W7 182, W8 183 punten.
- GKB16 PDF-tekeningen — testinput voor de extractie-pipeline.

## Architectuurvoorstel
- **Backend**: Python (FastAPI) of Node. Endpoints: `POST /extract` (PDF → JSON; PyMuPDF voor tekst+coördinaten, Claude API met vision voor interpretatie/koppeling ruimte→woning), `POST /calculate` (JSON → resultaat met audit).
- **Extractie-aanpak (bewezen in pilot)**: woorden met x/y-coördinaten uitlezen; "woning X + GO-m²"-labels als ankers; ruimtelabels (naam + m²) spatieel clusteren per woning; complete woordenlijst ruimtelabels hanteren (woonkamer, slaapkamer, keuken, badkamer, toilet, berging, buitenr., buitenruimte, terras, balkon, tuin, zolder, t.r., hal, verblijfsruimte, …); pagina = bouwlaag; maisonnettes herkennen aan zelfde woningnummer op meerdere pagina's. Confidence per veld meegeven voor het controlescherm.
- **Frontend**: React of server-rendered; het controlescherm is het belangrijkste scherm (zie pilot-lessen hieronder).
- **Config als data**: prijstabellen, WOZ-kengetallen (2026: I=€16.954, II=€268, min-WOZ €85.806), sectorgrenzen (143/186) per tijdvak in een configbestand — wijzigt jaarlijks per 1 januari.
- **Hosting**: Railway/Render/Vercel; Claude API-key via Anthropic Console; kosten per extractie: centen tot dubbeltjes per tekening.

## Lessen uit de pilot (GKB16) — verwerken in het ontwerp
1. Onvolledige labelwoordenlijst miste buitenruimtes → −5 i.p.v. +3 à +6 punten per woning, drie woningen ten onrechte niet in de vrije sector. Elke niet-toegewezen annotatie moet als open vraag in het controlescherm.
2. m²-labels kunnen bij een ander element horen dan verwacht (buitenruimte-label vs. toilet) — koppel op afstand én richting, toon de koppeling in het controlescherm.
3. Zaalwoningen/open ruimtes zonder m²-label: markeren als "geschat", nooit als zeker presenteren.
4. WOZ per woning bestaat vaak nog niet bij transformatie — pand-WOZ naar rato van GO als indicatie, met duidelijke disclaimer (formeel: eigen beschikking of 85% taxatie, anders minimum-WOZ).
5. Toiletruimtes < 2 m² tellen niet mee; toiletruimte/techniekruimte ≥ 2 m² = overige ruimte.

## Juridische kaders
- Bron: beleidsboeken Huurcommissie (versie jan. 2026). Disclaimer in de app: indicatief, alleen de Huurcommissie doet bindende uitspraken.
- Afronding: per rubriek 0,25 (≥ 1/8 omhoog), eindtotaal hele punten. Boven 250 punten: lineair extrapoleren.
- Rijksmonument: +35% op max. huur (contract ≥ 1-7-2024), geen energielabel-minpunten. Gemeentelijk/provinciaal +15%, stadsgezicht +5%, nieuwbouw middenhuur +10% (20 jaar). Monument + stadsgezicht niet cumuleren.
- Kamers (WWSO): altijd gereguleerd; eigen prijstabel; energiepunten per m²; aftrekposten −4; delers op basis van toegang + gebruiksrecht uit huurcontracten.

## Fasering
1. **MVP**: rekenkern als module + API, frontend met JSON-import en handmatige invoer, audit-weergave. (Prototype is de spec.)
2. **PDF-extractie**: upload → extractie → controlescherm → berekening. Acceptatie: GKB16 binnen ±2 punten van handmatige telling, alle afwijkingen verklaard.
3. **Portefeuille**: meerdere gebouwen opslaan, scenario's (label-upgrade, verbouwing), PDF-puntentelling als contractbijlage, jaarlijkse tabel-update.

## Gebruikers/context
Eigenaar: Ivo Wapenaar (ICW Invest B.V.) — vastgoedontwikkelaar. Gebruik: eigen projecten (o.a. transformaties, rijksmonumenten) en snelle WWS-scan bij aankoopkansen. Interface in het Nederlands.
