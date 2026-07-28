"""CCCXLI — die rechte Sankey-Seite eines Objekts ist strikt einheitenbasiert.

Empfänger des Kostenflusses sind Einheiten (bzw. der Sammelknoten „Ohne
Einheit"), nie Bewohner- oder Parteinamen. Ein Mietverhältnis mit leerem
`einheit`-Feld darf nicht als Parteiname erscheinen und die zugehörige Einheit
nicht zusätzlich als Dopplung.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_sankey_einheit.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt_mit_loser_partei(c) -> str:
    """Zwei Einheiten, drei Mietverhältnisse — eines mit leerem `einheit`-Feld."""
    slug = c.post("/api/objekte", json={
        "name": "Mischhaus CCCXLI", "turnus": "kalender",
        "einheiten": [
            {"bezeichnung": "Wohnung 1.OG", "flaeche": 80.0},
            {"bezeichnung": "Studio 1.OG", "flaeche": 40.0},
        ],
    }).json()["slug"]
    # sauber zugeordnet
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "Wohnung 1.OG", "partei": "Heuser - Teubert",
        "kaltmiete": 800.0, "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "Studio 1.OG", "partei": "Nicklas",
        "kaltmiete": 400.0, "ab_datum": "2025-01-01"})
    # leeres Einheit-Feld -> früher erschien hier der Parteiname als Knoten,
    # während „Studio 1.OG"/„Wohnung 1.OG" zugleich als Leerstand auftauchte
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "", "partei": "Roman",
        "kaltmiete": 500.0, "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/kredite", json={
        "bezeichnung": "Kauf", "rate_monatlich": 100.0})
    return slug


def test_rechte_sankey_seite_zeigt_nur_einheiten():
    with TestClient(app) as c:
        slug = _objekt_mit_loser_partei(c)
        s = c.get("/api/auswertung/sankey",
                  params={"objekt": slug, "jahr": 2025}).json()

        parteien = {"Heuser - Teubert", "Nicklas", "Roman"}
        erlaubt = {"Wohnung 1.OG", "Studio 1.OG", "Ohne Einheit"}

        # Empfänger des Kostenflusses = Quellknoten (spalte 0), ohne den
        # Ausgleichsknoten „Fehlbetrag" (rolle=minus)
        empfaenger = [k for k in s["knoten"]
                      if k["spalte"] == 0 and k.get("rolle") != "minus"]
        namen = [k["name"] for k in empfaenger]

        # kein Parteiname als eigener Empfänger
        assert not (set(namen) & parteien), namen
        # jeder Empfänger ist eine Einheit oder der Sammelknoten
        assert set(namen) <= erlaubt, namen
        # keine Dopplung: jeder Empfänger genau einmal
        assert len(namen) == len(set(namen)), namen
        # die lose Partei landet unter „Ohne Einheit"
        assert "Ohne Einheit" in namen

        # nichts geht verloren oder doppelt: Summe der Zuflüsse == Einnahmen
        mitte = next(i for i, k in enumerate(s["knoten"])
                     if k["name"] == "Einnahmen")
        empfaenger_idx = {s["knoten"].index(k) for k in empfaenger}
        zufluss = sum(f["wert"] for f in s["fluss"]
                      if f["nach"] == mitte and f["von"] in empfaenger_idx)
        # 800*12 + 400*12 + 500*12 = 20400
        assert abs(zufluss - 20400.0) < 0.01, zufluss
        assert abs(s["einnahmen"] - 20400.0) < 0.01, s["einnahmen"]
