# WWS App — puntentelling en maximale huur per appartement

Webapp: upload een plattegrond (PDF) of JSON, krijg per woning de exacte WWS-punten,
sector en maximale kale huur — met volledige verantwoording per punt, handmatige invoer,
kamermodule (WWSO) en optimalisatie-advies richting de vrije sector.

## Starten (2 commando's)

    pip install -r requirements.txt
    python3 -m uvicorn main:app --reload

Open daarna http://localhost:8000

## Wat zit erin
- `main.py` — FastAPI-backend: `POST /api/extract` (PDF → JSON) + statische frontend
- `extractor.py` — deterministische plattegrond-extractie: tekst + coördinaten (PyMuPDF),
  "woning X"-labels als ankers, spatiële koppeling van ruimtenamen aan m²-labels,
  buitenruimte-/terras-herkenning, open-vragenlijst voor review
- `static/index.html` — frontend met rekenkern (WWS zelfstandig + WWSO kamers,
  prijspeil 1-1-2026), audit-log per punt, handmatige invoer, optimalisatie-advies
- `tests/gkb16-fase2.json` — testfixture (echt gebouw, 8 woningen, rijksmonument)
- `CLAUDE.md` — projectbriefing voor doorontwikkeling met Claude Code

## Werkwijze
1. Upload de PDF (vectortekening met "woning X"-labels en m²-aanduidingen)
2. Controleer de open vragen die de extractie meldt
3. Vul de M/C-velden aan (WOZ, energielabel, keuken/sanitair, monumentstatus) via de JSON of handmatig
4. Bereken → prijslijst per woning, klik op een regel voor de volledige verantwoording

## Beperkingen v1
- Gescande (raster-)tekeningen worden niet ondersteund — alleen vector-PDF's met tekstlaag
- GO per woning is informatief; bij maisonnettes kan een totaal-label dubbel tellen
- Jaarlijkse update nodig (prijstabellen, WOZ-kengetallen, grenzen) — zie CFG in index.html
- Indicatief: alleen de Huurcommissie doet bindende uitspraken

## Doorontwikkeling (zie CLAUDE.md)
Fase 2-ideeën: AI-verrijking van de extractie (Claude API) voor gescande tekeningen en
twijfelgevallen, interactief reviewscherm, portefeuillebeheer, PDF-export puntentelling.

## Online draaien (hosting)

De app is deploy-klaar (Dockerfile aanwezig, wachtwoordbeveiliging via env-var).

**Aanbevolen: Render of Railway (± 15 min, geen serverbeheer)**
1. Zet deze map in een GitHub-repository (mag privé)
2. Maak een account op render.com (of railway.app), kies "New Web Service" en koppel de repo
3. Render herkent de Dockerfile automatisch; kies regio Frankfurt (EU)
4. Zet bij Environment de variabele `APP_WACHTWOORD` op een sterk wachtwoord
   (de hele app vraagt dan om inloggen; gebruikersnaam mag willekeurig zijn)
5. Klaar: je krijgt een https-adres, bijv. wws-app.onrender.com

Eigen domein (bijv. wws.icwinvest.nl): Settings → Custom Domain + CNAME-record bij je domeinprovider.

**Kosten**: Render gratis tier (slaapstand na inactiviteit; eerste request daarna ~30 sec)
of ~$7/mnd altijd-aan; Railway ~$5/mnd; Hetzner VPS ~€4/mnd (zelf beheren).

**Let op bij online gebruik**
- Zet ALTIJD `APP_WACHTWOORD` — plattegronden en huurdata zijn bedrijfsgevoelig
- Https wordt door deze platforms automatisch geregeld
- Geüploade PDF's worden alleen tijdelijk verwerkt en direct verwijderd (zie main.py)
