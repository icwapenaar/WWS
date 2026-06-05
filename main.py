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



@app.post("/api/chat")
async def api_chat(payload: dict):
    """Chat-assistent met geheugen en tool-use voor ruimte-aanpassingen."""
    if not ANTHROPIC_KEY:
        return JSONResponse({"error": "Geen ANTHROPIC_API_KEY ingesteld (Render > Environment)."}, status_code=503)
    berichten = payload.get("messages") or []
    data = payload.get("data") or {}
    samenvatting = payload.get("samenvatting", "")
    spaces_kort = [{k: v for k, v in sp.items() if k in ("space_id","unit_id","space_name","space_function","area_m2_wws","heated")} for sp in data.get("spaces", [])]
    tools = [{
        "name": "pas_ruimtes_aan",
        "description": "Voeg ruimtes toe aan, wijzig of verwijder ruimtes uit de huidige gebouwdata. Gebruik dit UITSLUITEND als de gebruiker expliciet om een aanpassing vraagt.",
        "input_schema": {"type": "object", "properties": {
            "toevoegen": {"type": "array", "items": {"type": "object", "properties": {
                "unit_id": {"type": "string"}, "space_name": {"type": "string"},
                "space_function": {"type": "string", "enum": ["living","bedroom","kitchen","bathroom","toilet_room","hall_circulation","internal_storage","attic","outdoor_private","outdoor_communal","communal_indoor","parking","technical"]},
                "area_m2_wws": {"type": "number"}, "heated": {"type": "boolean"}},
                "required": ["unit_id","space_name","space_function","area_m2_wws"]}},
            "wijzigen": {"type": "array", "items": {"type": "object", "properties": {
                "space_id": {"type": "string"}, "area_m2_wws": {"type": "number"},
                "space_name": {"type": "string"}, "space_function": {"type": "string"}, "heated": {"type": "boolean"}},
                "required": ["space_id"]}},
            "verwijderen": {"type": "array", "items": {"type": "string"}}
        }, "required": []}
    }]
    systeem = f"""Je bent de assistent van een WWS-huurpuntencalculator (Nederlands woningwaarderingsstelsel).
Beantwoord vragen over de berekening kort, concreet en in de taal van de gebruiker.
Gebruik de tool pas_ruimtes_aan alleen bij een expliciet wijzigingsverzoek; verzin geen oppervlaktes.
Na een wijziging rekent de app zelf opnieuw — noem dus geen nieuwe puntentotalen, zeg wat je hebt aangepast.

HUIDIGE BEREKENING:
{samenvatting}

HUIDIGE RUIMTES (space_id | unit | naam | functie | m2):
{json.dumps(spaces_kort, ensure_ascii=False)}"""
    conv = [{"role": m.get("role"), "content": m.get("content")} for m in berichten if m.get("role") in ("user","assistant") and m.get("content")]
    totaal_wijz = 0
    try:
        async with httpx.AsyncClient(timeout=85) as client:
            for _ in range(4):
                resp = await client.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-sonnet-4-6", "max_tokens": 1500, "system": systeem,
                          "messages": conv, "tools": tools})
                if resp.status_code != 200:
                    return JSONResponse({"error": f"Claude API-fout ({resp.status_code}): {resp.text[:200]}"}, status_code=502)
                antw = resp.json()
                if antw.get("stop_reason") != "tool_use":
                    tekst = " ".join(b.get("text","") for b in antw.get("content",[]) if b.get("type")=="text").strip()
                    return {"reply": tekst or "(geen antwoord)", "data": data, "changes": totaal_wijz}
                conv.append({"role": "assistant", "content": antw["content"]})
                resultaten = []
                for blok in antw["content"]:
                    if blok.get("type") != "tool_use": continue
                    inp = blok.get("input", {})
                    spaces = data.get("spaces", [])
                    per_id = {sp["space_id"]: sp for sp in spaces}
                    n = 0
                    for w in inp.get("wijzigen", []):
                        if w.get("space_id") in per_id:
                            per_id[w["space_id"]].update({k: v for k, v in w.items() if k != "space_id"}); n += 1
                    weg = set(inp.get("verwijderen", []))
                    if weg:
                        data["spaces"] = spaces = [sp for sp in spaces if sp["space_id"] not in weg]; n += len(weg)
                    for i, nieuw in enumerate(inp.get("toevoegen", [])):
                        nieuw.setdefault("space_id", f"chat-{len(spaces)}-{i}")
                        nieuw.setdefault("heated", nieuw.get("space_function") in ("living","bedroom","kitchen","bathroom"))
                        spaces.append(nieuw); n += 1
                    data["spaces"] = spaces
                    totaal_wijz += n
                    resultaten.append({"type": "tool_result", "tool_use_id": blok["id"], "content": f"OK, {n} ruimte(s) aangepast."})
                conv.append({"role": "user", "content": resultaten})
            return {"reply": "Aanpassingen doorgevoerd.", "data": data, "changes": totaal_wijz}
    except httpx.TimeoutException:
        return JSONResponse({"error": "De assistent deed er te lang over (timeout). Probeer het opnieuw."}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": f"Chat mislukt: {type(e).__name__}: {e}"}, status_code=502)

# Static mount altijd als laatste (vangt alle overige paden)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
