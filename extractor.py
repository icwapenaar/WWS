"""WWS plattegrond-extractor: vector-PDF -> JSON volgens Data Export Specification.
Deterministisch: tekst + coordinaten (PyMuPDF), woninglabels als ankers, spatiele koppeling.
"""
import fitz, re, math

RUIMTE_FUNCTIES = {
    "woonkamer/keuken": ("living", True), "woonkeuken": ("living", True),
    "woonkamer": ("living", False), "verblijfsruimte": ("living", False),
    "slaapkamer": ("bedroom", False), "keuken": ("kitchen", False),
    "badkamer": ("bathroom", False), "doucheruimte": ("bathroom", False),
    "toilet": ("toilet_room", False), "wc": ("toilet_room", False),
    "hal": ("hall_circulation", False), "entree": ("hall_circulation", False),
    "gang": ("hall_circulation", False), "overloop": ("hall_circulation", False),
    "berging": ("internal_storage", False), "bergruimte": ("internal_storage", False),
    "kast": ("internal_storage", False), "wasruimte": ("internal_storage", False),
    "bijkeuken": ("internal_storage", False), "zolder": ("attic", False),
    "t.r.": ("technical", False), "techniekruimte": ("technical", False),
    "technische ruimte": ("technical", False), "cv": ("technical", False),
    "meterkast": ("technical", False), "buitenruimte": ("outdoor_private", False),
    "buitenr.": ("outdoor_private", False), "buitenr": ("outdoor_private", False),
    "terras": ("outdoor_private", False), "balkon": ("outdoor_private", False),
    "dakterras": ("outdoor_private", False), "tuin": ("outdoor_private", False),
    "loggia": ("outdoor_private", False), "patio": ("outdoor_private", False),
    "garage": ("garage", False),
}
GEMEENSCHAPPELIJK = ["collectie", "gemeenschap", "gezamenlijk", "fietsenberging", "fietsen"]
NEGEER = ["winkel", "kantoor", "commercieel", "lift", "schacht", "trappenhuis", "noodstroom"]
M2_RE = re.compile(r"^(?:ca\.?\s*)?(\d{1,3}(?:[.,]\d{1,2})?)\s*m²$")
WONING_RE = re.compile(r"^woning\s+([0-9]{1,3}|[A-Z])\b\.?$", re.I)
VERDIEPING_RE = re.compile(r"souterrain|kelder|begane\s*grond|(\w+)\s*verdieping|plattegrond\s*[-0-9]+", re.I)

def _lijnen(page):
    words = page.get_text("words")
    groep = {}
    for w in words:
        groep.setdefault((w[5], w[6]), []).append(w)
    uit = []
    for ws in groep.values():
        ws.sort(key=lambda w: w[0])
        uit.append({"x": min(w[0] for w in ws), "y": min(w[1] for w in ws),
                    "tekst": " ".join(w[4] for w in ws).strip()})
    return uit

def _m2(t):
    m = M2_RE.match(t.replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None

def _functie(tekst):
    t = tekst.lower().strip()
    for naam in sorted(RUIMTE_FUNCTIES, key=len, reverse=True):
        if t == naam or t.startswith(naam + " ") or re.match(rf"^{re.escape(naam)}\s*\d*$", t):
            return RUIMTE_FUNCTIES[naam]
    return None

def _afstand(a, b): return math.hypot(a["x"] - b["x"], a["y"] - b["y"])

def extract(pdf_pad, building_overrides=None):
    doc = fitz.open(pdf_pad)
    units, spaces, vragen, aannames = {}, [], [], []
    sid = 0
    for pno in range(len(doc)):
        lijnen = _lijnen(doc[pno])
        if not lijnen: continue
        verdieping = next((l["tekst"] for l in lijnen if VERDIEPING_RE.search(l["tekst"]) and len(l["tekst"]) < 40), f"pagina {pno+1}")
        # 1. m2-labels verzamelen
        m2s = [dict(l, m2=_m2(l["tekst"]), gebruikt=False) for l in lijnen if _m2(l["tekst"]) is not None]
        # 2. woning-ankers (label + GO = dichtstbijzijnde m2 binnen 80pt)
        ankers = []
        for l in lijnen:
            m = WONING_RE.match(l["tekst"])
            if not m: continue
            uid = "Woning " + m.group(1)
            kand = [z for z in m2s if not z["gebruikt"] and _afstand(l, z) < 80]
            go = None
            if kand:
                z = min(kand, key=lambda z: _afstand(l, z)); z["gebruikt"] = True; go = z["m2"]
            ankers.append({"uid": uid, "x": l["x"], "y": l["y"]})
            u = units.setdefault(uid, {"unit_id": uid, "gross_floor_area_m2": 0, "_lagen": []})
            if go: u["gross_floor_area_m2"] += go
            u["_lagen"].append(verdieping)
        # 3. ruimtelabels koppelen aan m2 + anker
        for l in lijnen:
            t = l["tekst"].lower()
            if any(n in t for n in NEGEER): continue
            gemeensch = any(g in t for g in GEMEENSCHAPPELIJK)
            f = _functie(l["tekst"]) if not gemeensch else ("communal_indoor", False)
            if not f: continue
            functie, open_keuken = f
            kand = [z for z in m2s if not z["gebruikt"] and _afstand(l, z) < 70]
            if not kand:
                vragen.append(f"{verdieping}: '{l['tekst']}' herkend maar geen m²-label gevonden binnen koppelafstand")
                continue
            z = min(kand, key=lambda z: _afstand(l, z)); z["gebruikt"] = True
            sid += 1
            ruimte = {"space_id": f"s{sid}", "space_name": l["tekst"], "space_function": functie,
                      "area_m2_wws": z["m2"], "floor": verdieping}
            if gemeensch:
                ruimte["unit_id"] = None
                ruimte["access_addresses_count"] = None  # contractdata -> aanvulscherm
                vragen.append(f"{verdieping}: gemeenschappelijke ruimte '{l['tekst']}' — aantal adressen met toegang invullen")
            elif ankers:
                anker = min(ankers, key=lambda a: _afstand(l, a))
                ruimte["unit_id"] = anker["uid"]
            else:
                ruimte["unit_id"] = None
                vragen.append(f"{verdieping}: '{l['tekst']}' kon niet aan een woning worden gekoppeld (geen woning-anker op deze pagina)")
            if functie in ("living", "bedroom", "kitchen", "bathroom"):
                ruimte["heated"] = True  # aanname renovatie/nieuwbouw
            if open_keuken: ruimte["is_open_kitchen"] = True
            spaces.append(ruimte)
        # 4. niet-gebruikte m2-labels = open vragen
        for z in m2s:
            if not z["gebruikt"] and z["m2"] and z["m2"] < 200:
                vragen.append(f"{verdieping}: m²-label '{z['tekst']}' niet gekoppeld aan een ruimtenaam — controleren")
    aannames.append("heated=true aangenomen voor alle vertrekken — bevestigen")
    aannames.append("GO per woning = som van GO-labels over alle lagen; bij maisonnettes kan een totaal-label dubbel tellen — GO is informatief en telt niet mee in de punten")
    aannames.append("WOZ, energielabel, keuken- en sanitairspecificaties staan niet op een tekening — aanvullen (M/C-velden)")
    for u in units.values():
        if len(set(u["_lagen"])) > 1:
            aannames.append(f"{u['unit_id']}: ruimtes op meerdere lagen ({', '.join(dict.fromkeys(u['_lagen']))}) — maisonnette")
        del u["_lagen"]
        if not u["gross_floor_area_m2"]: u["gross_floor_area_m2"] = None
    building = {"building_id": "GEBOUW-1", "project_name": pdf_pad.split("/")[-1],
                "building_type": "multi_family", "heritage_status": "none",
                "total_addresses": len(units) or 1,
                "care_step_free": False, "care_alarm_in_contract": False, "care_communal_rooms_in_contract": False}
    if building_overrides: building.update(building_overrides)
    return {"_meta": {"bron": pdf_pad.split("/")[-1], "open_vragen": vragen, "aannames": aannames},
            "building": building, "units": list(units.values()), "spaces": spaces}
