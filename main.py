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
    """Heranalyse met gebruikersopmerking via Claude API — patch-gebaseerd (snel)."""
    if not ANTHROPIC_KEY:
        return JSONResponse({"error": "Geen ANTHROPIC_API_KEY ingesteld. Zet deze als environment-variabele in Render (Settings > Environment)."}, status_code=503)
    opmerking = (payload.get("opmerking") or "").strip()
    data = payload.get("data")
    if not opmerking or not data:
        return JSONResponse({"error": "Opmerking en data zijn verplicht."}, status_code=400)
    ruw = data.get("_ruw", [])
    spaces_kort = [{k: v for k, v in sp.items() if k in ("space_id","unit_id","space_name","space_function","area_m2_wws","floor")} for sp in data.get("spaces", [])]
    prompt = f"""Je bent expert in het Nederlandse woningwaarderingsstelsel (WWS) en het lezen van bouwtekeningen.

Gegeven: (1) de ruwe tekstlaag van een plattegrond-PDF (regels met pagina en x/y-coordinaten; per pagina is "plattegrond"-vermelding de bouwlaag; "woning X"-labels zijn ankers), (2) de huidige lijst herkende ruimtes, (3) een opmerking van de gebruiker.

Bepaal welke WIJZIGINGEN nodig zijn. Antwoord UITSLUITEND met geldige JSON, zonder toelichting eromheen:
{{"uitleg":"korte uitleg in het Nederlands",
 "spaces_toevoegen":[{{"space_id":"nieuw-1","unit_id":"Woning X","space_name":"...","space_function":"living|bedroom|kitchen|bathroom|toilet_room|hall_circulation|internal_storage|attic|outdoor_private|outdoor_communal|communal_indoor|parking|technical","area_m2_wws":0.0,"heated":true}}],
 "spaces_wijzigen":[{{"space_id":"bestaand-id","area_m2_wws":0.0}}],
 "spaces_verwijderen":["space_id"]}}

Regels: verzin geen oppervlaktes — alleen m2 uit de ruwe tekst of expliciet door de gebruiker genoemd; lege lijsten zijn prima; als iets niet vindbaar is, leg dat uit in "uitleg" en wijzig niets.

(1) RUWE TEKST:
{chr(10).join(f"p{r['p']} ({r['x']},{r['y']}): {r['t']}" for r in ruw[:1200])}

(2) HUIDIGE RUIMTES:
{json.dumps(spaces_kort, ensure_ascii=False)}

(3) OPMERKING:
{opmerking}"""
    try:
        async with httpx.AsyncClient(timeout=85) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 3000,
                      "messages": [{"role": "user", "content": prompt}]})
        if resp.status_code != 200:
            return JSONResponse({"error": f"Claude API-fout ({resp.status_code}): {resp.text[:200]}"}, status_code=502)
        tekst = resp.json()["content"][0]["text"]
        patch = json.loads(tekst[tekst.find("{"):tekst.rfind("}")+1])
        # patch toepassen
        spaces = data.get("spaces", [])
        per_id = {sp["space_id"]: sp for sp in spaces}
        for w in patch.get("spaces_wijzigen", []):
            if w.get("space_id") in per_id:
                per_id[w["space_id"]].update({k: v for k, v in w.items() if k != "space_id"})
        weg = set(patch.get("spaces_verwijderen", []))
        spaces = [sp for sp in spaces if sp["space_id"] not in weg]
        for n in patch.get("spaces_toevoegen", []):
            if n.get("area_m2_wws") and n.get("unit_id") is not None:
                spaces.append(n)
        data["spaces"] = spaces
        aantal = len(patch.get("spaces_toevoegen", [])) + len(patch.get("spaces_wijzigen", [])) + len(weg)
        return {"uitleg": patch.get("uitleg", ""), "aantal_wijzigingen": aantal, "data": data}
    except httpx.TimeoutException:
        return JSONResponse({"error": "De AI-analyse duurde te lang (timeout). Probeer het opnieuw of maak de opmerking specifieker."}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": f"Heranalyse mislukt: {type(e).__name__}: {e}"}, status_code=502)

# Static mount altijd als laatste (vangt alle overige paden)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
