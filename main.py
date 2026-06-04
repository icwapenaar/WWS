"""WWS App — FastAPI-backend. Start: uvicorn main:app --reload  ->  http://localhost:8000"""
import json, tempfile, os, secrets, base64
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from extractor import extract
import httpx

app = FastAPI(title="WWS Calculator")

WACHTWOORD = os.environ.get("APP_WACHTWOORD")  # zet deze env-var bij online hosting

@app.middleware("http")
async def basis_auth(request: Request, call_next):
    if WACHTWOORD:
        auth = request.headers.get("Authorization", "")
        ok = False
        if auth.startswith("Basic "):
            try:
                user_pw = base64.b64decode(auth[6:]).decode()
                ok = secrets.compare_digest(user_pw.split(":", 1)[1], WACHTWOORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="WWS"'})
    return await call_next(request)

@app.post("/api/extract")
async def api_extract(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "Alleen PDF-bestanden"}, status_code=400)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read()); pad = tmp.name
    try:
        data = extract(pad)
        if not data["units"]:
            return JSONResponse({"error": "Geen woning-labels gevonden. Is dit een vectortekening met 'woning X'-aanduidingen? Gescande tekeningen worden (nog) niet ondersteund.", "_meta": data["_meta"]}, status_code=422)
        return data
    finally:
        os.unlink(pad)




ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")

@app.post("/api/review")
async def api_review(payload: dict):
    """Heranalyse met gebruikersopmerking via Claude API."""
    if not ANTHROPIC_KEY:
        return JSONResponse({"error": "Geen ANTHROPIC_API_KEY ingesteld. Maak een API-key aan op console.anthropic.com en zet deze als environment-variabele ANTHROPIC_API_KEY in Render (Settings > Environment). Daarna werkt de heranalyse."}, status_code=503)
    opmerking = (payload.get("opmerking") or "").strip()
    data = payload.get("data")
    if not opmerking or not data:
        return JSONResponse({"error": "Opmerking en data zijn verplicht."}, status_code=400)
    ruw = data.pop("_ruw", [])
    prompt = f"""Je bent een expert in het Nederlandse woningwaarderingsstelsel (WWS) en het lezen van bouwtekeningen.

Hieronder staat (1) de ruwe tekstlaag van een plattegrond-PDF (regels met paginanummer en x/y-coordinaten), (2) de huidige geextraheerde JSON (building/units/spaces) en (3) een opmerking van de gebruiker over wat er mis of vergeten is.

Pas de JSON aan op basis van de opmerking en de ruwe tekst. Regels:
- Behoud het schema exact (space_id, unit_id, space_name, space_function, area_m2_wws, heated, etc.).
- space_function: living|bedroom|kitchen|bathroom|toilet_room|hall_circulation|internal_storage|attic|outdoor_private|outdoor_communal|communal_indoor|parking|technical.
- Gebruik de coordinaten om ruimtes aan de juiste woning te koppelen (woning-labels zijn ankers; zelfde pagina = zelfde bouwlaag).
- Verzin geen oppervlaktes: alleen m2 die in de ruwe tekst staan, of door de gebruiker worden genoemd. Als iets niet vindbaar is, meld dat in de uitleg.
- Behoud bestaande velden van units (woz_value_eur, energy_label etc.) ongewijzigd.

Antwoord UITSLUITEND met geldige JSON in dit formaat:
{{"uitleg": "korte uitleg in het Nederlands van wat je hebt aangepast en waarom", "data": {{...volledige aangepaste JSON...}}}}

(1) RUWE TEKST:
{chr(10).join(f"p{r['p']} ({r['x']},{r['y']}): {r['t']}" for r in ruw[:1200])}

(2) HUIDIGE JSON:
{json.dumps(data, ensure_ascii=False)}

(3) OPMERKING GEBRUIKER:
{opmerking}"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 16000,
                      "messages": [{"role": "user", "content": prompt}]})
        if resp.status_code != 200:
            return JSONResponse({"error": f"Claude API-fout ({resp.status_code}): {resp.text[:300]}"}, status_code=502)
        tekst = resp.json()["content"][0]["text"]
        # JSON uit het antwoord halen (evt. omringende tekst/codeblok strippen)
        start = tekst.find("{"); eind = tekst.rfind("}") + 1
        uit = json.loads(tekst[start:eind])
        nieuwe = uit.get("data", {})
        nieuwe["_ruw"] = ruw  # behouden voor volgende ronde
        if not nieuwe.get("units") or not nieuwe.get("spaces"):
            return JSONResponse({"error": "Heranalyse leverde geen geldige structuur op. Probeer de opmerking specifieker te maken."}, status_code=502)
        return {"uitleg": uit.get("uitleg", ""), "data": nieuwe}
    except Exception as e:
        return JSONResponse({"error": f"Heranalyse mislukt: {type(e).__name__}: {e}"}, status_code=502)

# Static mount altijd als laatste (vangt alle overige paden)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
