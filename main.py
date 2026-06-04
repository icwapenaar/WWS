"""WWS App — FastAPI-backend. Start: uvicorn main:app --reload  ->  http://localhost:8000"""
import json, tempfile, os, secrets, base64
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from extractor import extract

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

app.mount("/", StaticFiles(directory="static", html=True), name="static")
