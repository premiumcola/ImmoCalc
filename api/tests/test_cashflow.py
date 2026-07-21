"""Cashflow je Einheit, Miete pro m² und der Fluss fürs Sankey-Diagramm."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_cashflow.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.cashflow import EinheitZahlen, verteile  # noqa: E402
from app.main import app  # noqa: E402


def test_verteilung_nach_flaeche():
    einheiten = [
        EinheitZahlen("EG", "Wohnen", 60.0, None, None),
        EinheitZahlen("OG", "Wohnen", 40.0, None, None),
    ]
    assert verteile(1000.0, einheiten) == [600.0, 400.0]


def test_verteilung_ohne_flaeche_zu_gleichen_teilen():
    einheiten = [
        EinheitZahlen("A", "Wohnen", None, None, None),
        EinheitZahlen("B", "Wohnen", None, None, None),
    ]
    assert verteile(500.0, einheiten) == [250.0, 250.0]


def _objekt_mit_einheiten(c) -> str:
    slug = c.post("/api/objekte", json={
        "name": "Flusshaus 1", "turnus": "kalender",
        "einheiten": [
            {"bezeichnung": "EG", "flaeche": 60.0, "partei": "Mieter EG"},
            {"bezeichnung": "OG", "flaeche": 40.0, "partei": "Mieter OG"},
        ],
    }).json()["slug"]
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "EG", "partei": "Mieter EG", "kaltmiete": 600.0,
        "stellplatz": 50.0, "sonstige": 10.0, "nebenkosten_vz": 150.0,
        "email": "eg@example.org", "telefon": "0170 1234567",
        "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "OG", "partei": "Mieter OG", "kaltmiete": 400.0,
        "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/kredite", json={
        "bezeichnung": "Kauf", "rate_monatlich": 500.0})
    c.post(f"/api/objekte/{slug}/versicherungen", json={
        "art": "Gebäude", "jahresbeitrag": 300.0})
    return slug


def test_cashflow_je_einheit():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        daten = c.get("/api/auswertung/cashflow",
                      params={"objekt": slug, "jahr": 2025}).json()

        eg = next(e for e in daten["einheiten"] if e["bezeichnung"] == "EG")
        og = next(e for e in daten["einheiten"] if e["bezeichnung"] == "OG")

        # Einnahmen inkl. Stellplatz und Sonstigem
        assert eg["einnahmen_monat"] == 660.0
        assert eg["einnahmen_jahr"] == 7920.0
        assert og["einnahmen_jahr"] == 4800.0

        # Miete je m² zählt nur die Kaltmiete: 600 / 60
        assert eg["miete_pro_qm"] == 10.0
        assert og["miete_pro_qm"] == 10.0

        # Kosten 6000 Kredit + 300 Versicherung nach Fläche 60:40
        assert eg["bloecke"]["Kredit"] == 3600.0
        assert og["bloecke"]["Kredit"] == 2400.0
        assert eg["kosten_jahr"] == 3780.0
        assert og["kosten_jahr"] == 2520.0
        assert eg["saldo_jahr"] == 4140.0

        assert daten["gesamt"]["einnahmen"] == 12720.0
        assert daten["gesamt"]["kosten"] == 6300.0
        assert daten["gesamt"]["saldo"] == 6420.0

        # Kontaktdaten bleiben am Mietverhältnis
        miete = c.get(f"/api/objekte/{slug}/mieten").json()
        assert any(m["email"] == "eg@example.org" for m in miete)


def test_sankey_fluss_ist_ausgeglichen():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        daten = c.get("/api/auswertung/cashflow",
                      params={"objekt": slug, "jahr": 2025}).json()
        s = daten["sankey"]

        namen = [k["name"] for k in s["knoten"]]
        assert "EG" in namen and "OG" in namen and "Einnahmen" in namen

        mitte = namen.index("Einnahmen")
        zufluss = sum(f["wert"] for f in s["fluss"] if f["nach"] == mitte)
        abfluss = sum(f["wert"] for f in s["fluss"] if f["von"] == mitte)
        # Was hereinkommt, geht auch wieder heraus — Überschuss inbegriffen
        assert abs(zufluss - abfluss) < 0.01
        assert abs(zufluss - 12720.0) < 0.01
        assert "Überschuss" in namen


def _mieterobjekt(c, name: str, vz_monat: dict[str, float],
                  umlagen: dict[str, float], jahr: int = 2025) -> str:
    """Ein Objekt, dessen Vorauszahlungen je Einheit und Umlage feststehen.

    Damit lassen sich beide Richtungen der Abrechnung nachstellen: zu wenig
    vorausgezahlt (Nachzahlung) und zu viel (Guthaben)."""
    slug = c.post("/api/objekte", json={
        "name": name, "turnus": "kalender",
        "kostenarten": list(umlagen),
        "einheiten": [{"bezeichnung": b, "flaeche": 60.0, "partei": f"Mieter {b}"}
                      for b in vz_monat],
    }).json()["slug"]
    for bezeichnung, vz in vz_monat.items():
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": bezeichnung, "partei": f"Mieter {bezeichnung}",
            "kaltmiete": 500.0, "nebenkosten_vz": vz,
            "ab_datum": f"{jahr}-01-01"})
    zid = c.post(f"/api/objekte/{slug}/zeitraeume",
                 json={"jahr": jahr}).json()["id"]
    for art, betrag in umlagen.items():
        c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": art, "betrag": betrag, "status": "erledigt"})
    return slug


def _bilanz(s: dict, mitte: str) -> tuple[float, float]:
    """Zufluss und Abfluss des Mittelknotens."""
    namen = [k["name"] for k in s["knoten"]]
    i = namen.index(mitte)
    return (sum(f["wert"] for f in s["fluss"] if f["nach"] == i),
            sum(f["wert"] for f in s["fluss"] if f["von"] == i))


def test_sankey_zeigt_die_nachzahlung_als_quelle():
    """CLVII — 2.400 Umlage gegen 1.200 Vorauszahlung schliesst sich nur,
    wenn die Nachzahlung als eigene Quelle im Bild steht."""
    with TestClient(app) as c:
        slug = _mieterobjekt(c, "Nachzahlhaus", {"EG": 100.0},
                             {"Heizkosten": 2400.0})
        s = c.get("/api/auswertung/sankey", params={
            "objekt": slug, "jahr": 2025, "sicht": "mieter"}).json()

        namen = [k["name"] for k in s["knoten"]]
        assert "Nachzahlung" in namen
        # die Quelle steht links neben den Vorauszahlungen, nicht rechts davon
        assert s["knoten"][namen.index("Nachzahlung")]["spalte"] == 0
        assert s["fehlbetrag"] == 1200.0

        zufluss, abfluss = _bilanz(s, "Vorauszahlungen")
        assert abs(zufluss - abfluss) < 0.01
        assert abs(zufluss - 2400.0) < 0.01


def test_sankey_zeigt_das_guthaben_als_ziel():
    with TestClient(app) as c:
        slug = _mieterobjekt(c, "Guthabenhaus", {"EG": 300.0},
                             {"Heizkosten": 2400.0})
        s = c.get("/api/auswertung/sankey", params={
            "objekt": slug, "jahr": 2025, "sicht": "mieter"}).json()

        namen = [k["name"] for k in s["knoten"]]
        assert "Guthaben" in namen and "Nachzahlung" not in namen
        assert s["ueberschuss"] == 1200.0

        zufluss, abfluss = _bilanz(s, "Vorauszahlungen")
        assert abs(zufluss - abfluss) < 0.01
        assert abs(zufluss - 3600.0) < 0.01


def test_sankey_bleibt_geschlossen_wenn_beides_vorkommt():
    """Eine Partei zahlt nach, die andere bekommt zurück.

    EG hat 1.800 vorausgezahlt und trägt 1.200, OG hat 600 vorausgezahlt und
    trägt ebenfalls 1.200. Über das Objekt hebt sich das auf — im Bild bleibt
    dann weder Guthaben noch Nachzahlung übrig, und trotzdem geht der Fluss
    auf."""
    with TestClient(app) as c:
        slug = _mieterobjekt(c, "Mischhaus", {"EG": 150.0, "OG": 50.0},
                             {"Heizkosten": 2400.0})
        s = c.get("/api/auswertung/sankey", params={
            "objekt": slug, "jahr": 2025, "sicht": "mieter"}).json()

        namen = [k["name"] for k in s["knoten"]]
        assert "Guthaben" not in namen and "Nachzahlung" not in namen
        assert s["fehlbetrag"] == 0 and s["ueberschuss"] == 0

        zufluss, abfluss = _bilanz(s, "Vorauszahlungen")
        assert abs(zufluss - abfluss) < 0.01
        assert abs(zufluss - 2400.0) < 0.01


def test_kategorienfilter_wirkt_auf_sankey():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        nur_kredit = c.get("/api/auswertung/sankey", params={
            "objekt": slug, "jahr": 2025, "kategorien": "Kredit"}).json()
        namen = [k["name"] for k in nur_kredit["knoten"]]
        assert "Kredit" in namen
        assert "Versicherung" not in namen
        assert nur_kredit["kosten"] == 6000.0

        alles = c.get("/api/auswertung/sankey",
                      params={"objekt": slug, "jahr": 2025}).json()
        assert alles["kosten"] == 6300.0


def test_grundstueck_heisst_in_der_auswertung_pacht():
    """CLXVII — dasselbe Miete-Modell, aber ein Grundstück wird verpachtet."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Steigäcker", "typ": "lg-grundstueck", "turnus": "kalender",
        }).json()["slug"]
        c.patch(f"/api/objekte/{slug}",
                json={"grundstueck_nutzungsart": "Ackerland",
                      "grundstueck_flaeche": 12000.0})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Hof Meier", "kaltmiete": 250.0, "turnus": "jaehrlich",
            "ab_datum": "2025-01-01"})

        satz = c.get("/api/auswertung/cashflow",
                     params={"objekt": slug, "jahr": 2025}).json()
        assert satz["mietwort"] == "Pacht"
        # Die Pseudo-Einheit trägt die Nutzungsart des Grundstücks, nicht
        # „Wohnen“ — die Zahlen bleiben davon unberührt.
        pacht = satz["einheiten"][0]
        assert pacht["nutzungsart"] == "Ackerland"
        assert pacht["einnahmen_jahr"] == 250.0

        verlauf = c.get("/api/auswertung/mietverlauf",
                        params={"objekt": slug}).json()
        assert verlauf["reihen"][0]["mietwort"] == "Pacht"

        zeile = next(z for z in c.get("/api/auswertung", params={"jahr": 2025})
                     .json()["objekte"] if z["slug"] == slug)
        assert zeile["mietwort"] == "Pacht"
