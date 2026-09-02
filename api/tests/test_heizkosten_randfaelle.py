"""N453 — Randfälle der Heizkostenverteilung, die bisher still falsch rechneten.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. Beide Fälle sind
keine Exoten: ein frisch angelegter Heizkörperverteiler hat per Vorgabe
KEINEN Bewertungsfaktor (`Zaehler.bewertungsfaktor` ist `Optional`), und eine
Wohnung, in der ein Jahr lang niemand geheizt hat, liest sich mit 0 ab.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_heizkosten_randfaelle.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import db  # noqa: E402
from app.heizkosten import nutzer_aus_zaehlern  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Zeitraum  # noqa: E402


def _objekt(c, name):
    neu = c.post("/api/objekte", json={
        "name": name,
        "einheiten": [{"bezeichnung": "Whg A", "flaeche": 50.0, "partei": "A"},
                      {"bezeichnung": "Whg B", "flaeche": 30.0, "partei": "B"}]}
    ).json()
    slug = neu["slug"]
    det = c.get(f"/api/objekte/{slug}").json()
    laufend = next(z for z in det["zeitraeume"] if z["status"] == "in Arbeit")
    return slug, laufend["id"]


def _zaehler(c, slug, zid, *, name, bezug, wert, faktor=None,
             messeinheit="Einheiten", kostenart="Heizung"):
    zae = c.post(f"/api/objekte/{slug}/zaehler", json={
        "name": name, "kostenart": kostenart, "einheit_bezug": bezug,
        "messeinheit": messeinheit, "typ": "direkt",
        **({"bewertungsfaktor": faktor} if faktor is not None else {}),
    }).json()
    r = c.post(f"/api/zaehler/{zae['id']}/ablesungen",
              json={"datum": "2026-09-30", "stand": wert, "zeitraum_id": zid})
    assert r.status_code in (200, 201), r.text
    return zae["id"]


def _nutzer(zid):
    with Session(db.engine) as s:
        return nutzer_aus_zaehlern(s, s.get(Zeitraum, zid))


def test_heizkoerperverteiler_ohne_bewertungsfaktor_zaehlt_mit():
    """Ein HKV ohne gepflegten Faktor darf nicht auf null fallen.

    Vorher: `anteil * (bewertungsfaktor or 0.0)` — der Zähler bekam Gewicht 0,
    die Wohnung zahlte 0 €, und die gesamte Heizung landete beim Nachbarn.
    Der PDF-Nachweis behauptete dabei das Gegenteil: `_vergleichswert` liest
    einen fehlenden Faktor als „roher Wert zählt", also faktisch 1,0, und wies
    dem Mieter seinen vollen Anteil aus. Zwei Stellen derselben Datei mit
    gegensätzlicher Auslegung — der Mieter bekam eine Anlage über Kosten, die
    ihm die Abrechnung nie berechnet hat.

    Beide lesen einen fehlenden Faktor jetzt als 1,0."""
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Faktorweg 1")
        _zaehler(c, slug, zid, name="HKV A", bezug="Whg A", wert=600)
        _zaehler(c, slug, zid, name="HKV B", bezug="Whg B", wert=400,
                 faktor=1.0)

        nach_name = {n["name"]: n for n in _nutzer(zid)[0]}
        assert nach_name["Whg A"]["ehkv"] == 600.0, \
            "HKV ohne Faktor fällt aus der Verteilung"
        assert nach_name["Whg B"]["ehkv"] == 400.0


def test_ablesewert_null_bekommt_trotzdem_seine_grundkosten():
    """Wer nicht geheizt hat, zahlt trotzdem die verbrauchsUNabhängigen Kosten.

    § 7 HeizkostenV verteilt 30–50 % der Heizkosten nach Fläche, unabhängig
    vom Verbrauch. Vorher liess `if not menge: continue` die Wohnung mit
    Ablesewert 0 komplett aus der Nutzerliste fallen — sie tauchte in keiner
    Zeile auf, ihre Fläche fehlte in der Grundkostenverteilung, und die
    Nachbarn trugen deren Anteil mit. Gemeldet wurde nichts.

    `None` (gar keine Ablesung) wird weiterhin übersprungen — da ist der
    Verbrauch schlicht unbekannt."""
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Nullweg 2")
        _zaehler(c, slug, zid, name="HKV A", bezug="Whg A", wert=1000,
                 faktor=1.0)
        _zaehler(c, slug, zid, name="HKV B", bezug="Whg B", wert=0,
                 faktor=1.0)

        nutzer, _ = _nutzer(zid)
        nach_name = {n["name"]: n for n in nutzer}
        assert "Whg B" in nach_name, \
            "Wohnung mit Ablesewert 0 fehlt in der Verteilung"
        assert nach_name["Whg B"]["ehkv"] == 0.0
        # Entscheidend: ihre Fläche zählt bei den Grundkosten mit.
        assert nach_name["Whg B"]["flaeche"] == 30.0
        assert nach_name["Whg A"]["flaeche"] == 50.0


def test_nachweis_und_verteilung_lesen_denselben_faktor():
    """Gegenprobe zur Ursache von Fund 1: die beiden Stellen dürfen einen
    fehlenden Faktor nicht mehr unterschiedlich auslegen."""
    from app.heizkosten import _vergleichswert

    ohne = {"verbrauch": 600.0, "bewertungsfaktor": None,
            "messeinheit": "Einheiten"}
    mit_eins = {"verbrauch": 600.0, "bewertungsfaktor": 1.0,
                "messeinheit": "Einheiten"}
    assert _vergleichswert(ohne) == _vergleichswert(mit_eins) == 600.0
