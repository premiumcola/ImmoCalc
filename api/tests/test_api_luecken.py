"""Vier belegte Lücken an der API — je ein Wächter.

**1 — Zweite WEG-Zeile gleichen Namens unsichtbar.** `weg.uebernehmen` legt für
zwei Einheiten derselben WEG bewusst zwei Positionen gleicher Kostenart an
(N315a). Die Checkliste baute daraus ein Dict `{kostenart: position}`; die
zweite überschrieb die erste, und die Waisen-Schleife übersprang beide, weil der
Name schon in der Liste stand. Der WEG-Stand zeigte beide Zeilen, die
Zeitraum-Seite nur eine — 100 € zu wenig, und die verdeckte Position war über
die Oberfläche nicht mehr erreichbar.

**2 — Entwurf verwerfen hinterließ Waisen.** `entwurf_verwerfen` löschte nur den
Datensatz. Der reguläre Löschweg (`stammdaten.loeschen`) räumt zusätzlich die
Kinder und die Info-Belege weg und rechnet die abgeleiteten Gewichte neu. Ein
Bewohner blieb also an einer gelöschten Miete hängen — N314(d), denn SQLite
vergibt die id neu. Und kein Pfad rief `positionen_neu_ableiten`: ein
bestätigter Miet-Entwurf ist ein echtes Mietverhältnis, trug in den gespeicherten
Anteilen aber 0 %.

**3 — `VorhandenerBeleg.jahr` wurde nie übernommen.** Das Frontend schickt das
Abrechnungsjahr bei jedem erkannten Cloud-Duplikat mit; der Eintrag entstand
trotzdem ohne Jahr und fiel damit aus Jahresfilter und Jahres-Facette.

**4 — Unbekannter Slug einmal 404, dreimal 200 mit Nullen.** Ein veralteter Slug
las sich auf drei der vier Auswertungs-Endpunkte als „dieses Objekt hat 0 €
Einnahmen und 0 € Kosten". Dasselbe bei `GET /zeitraeume/{zid}/positionen`.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_api_luecken.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db, weg  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Bewohner, Dokument, Einheit, Kostenart,  # noqa: E402
                        Miete, Objekt, Zeitraum)


def _objekt(slug: str, *, weg_modus: bool = False,
            einheiten: tuple[str, ...] = ("EG",),
            kostenarten: tuple[str, ...] = ()) -> int:
    """Eine Immobilie samt Einheiten und Kostenart-Katalog — direkt in der
    Datenbank, weil die Entwürfe des Belegscans genauso entstehen."""
    with Session(db.engine) as s:
        o = Objekt(slug=slug, name=slug, start_monat=1, weg=weg_modus)
        s.add(o)
        s.commit()
        s.refresh(o)
        for name in einheiten:
            s.add(Einheit(objekt_id=o.id, bezeichnung=name, flaeche=70.0))
        for name in kostenarten:
            s.add(Kostenart(objekt_id=o.id, name=name))
        s.commit()
        return o.id


def _zeitraum(objekt_id: int, jahr: int = 2025) -> int:
    with Session(db.engine) as s:
        z = Zeitraum(objekt_id=objekt_id, start=date(jahr, 1, 1),
                     ende=date(jahr, 12, 31), typ="regulär", status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        return z.id


def _miete(objekt_id: int, einheit: str, partei: str, *,
           vorlaeufig: bool = False, ab: date = date(2020, 1, 1)) -> int:
    with Session(db.engine) as s:
        m = Miete(objekt_id=objekt_id, einheit=einheit, partei=partei,
                  ab_datum=ab, vorlaeufig=vorlaeufig)
        s.add(m)
        s.commit()
        s.refresh(m)
        return m.id


# --------------------------------------------------------------------------
# 1 — beide WEG-Zeilen gleicher Kostenart stehen in der Checkliste
# --------------------------------------------------------------------------
ART = "WEG-Hausmeister"


def _weg_beleg(betrag: float) -> dict:
    return {"positionen": [{"bezeichnung": ART, "gesamtkosten": betrag * 5,
                            "ihre_kosten": betrag, "umlagefaehig": True}]}


def test_zwei_weg_zeilen_gleicher_kostenart_bleiben_sichtbar():
    """Zwei Wohnungen derselben WEG, beide mit einer Zeile „WEG-Hausmeister":
    100 € und 200 €. Vorher zeigte die Checkliste nur die zweite — die
    Zeitraum-Summe wies 100 € zu wenig aus."""
    oid = _objekt("weg-luecke", weg_modus=True, einheiten=("Whg 1", "Whg 2"),
                  kostenarten=(ART,))
    _miete(oid, "Whg 1", "Mieter 1")
    _miete(oid, "Whg 2", "Mieter 2")
    zid = _zeitraum(oid)

    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        weg.uebernehmen(s, z, _weg_beleg(100.0), einheit="Whg 1")
        weg.uebernehmen(s, z, _weg_beleg(200.0), einheit="Whg 2")
        s.commit()

    with TestClient(app) as c:
        daten = c.get(f"/api/zeitraeume/{zid}").json()
    zeilen = [k for k in daten["checkliste"] if k["kostenart"] == ART]

    assert len(zeilen) == 2, f"Eine WEG-Zeile fehlt: {zeilen}"
    assert {z["nur_einheit"] for z in zeilen} == {"Whg 1", "Whg 2"}
    assert sorted(z["betrag"] for z in zeilen) == [100.0, 200.0]
    # Jede Zeile ist über ihre eigene id bedienbar — sonst wäre die verdeckte
    # Position über die Oberfläche nicht mehr erreichbar.
    assert len({z["position_id"] for z in zeilen}) == 2
    # Und die Summe des Zeitraums stimmt wieder mit der Abrechnung überein.
    assert daten["fortschritt"]["summe"] == 300.0


def test_kostenart_ohne_position_bleibt_eine_zeile():
    """Gegenprobe: ohne Position bleibt es bei genau einer „fehlt"-Zeile."""
    oid = _objekt("weg-leer", kostenarten=("Wasser",))
    zid = _zeitraum(oid)
    with TestClient(app) as c:
        daten = c.get(f"/api/zeitraeume/{zid}").json()
    zeilen = [k for k in daten["checkliste"] if k["kostenart"] == "Wasser"]
    assert len(zeilen) == 1
    assert zeilen[0]["zustand"] == "fehlt"


# --------------------------------------------------------------------------
# 2 — Entwurf verwerfen räumt auf, Entwurf bestätigen rechnet neu
# --------------------------------------------------------------------------
def test_verworfener_miet_entwurf_laesst_keinen_bewohner_zurueck():
    """N314(d) — der Bewohner hing sonst an einer nicht mehr existierenden
    Miete und tauchte beim nächsten Mietverhältnis mit derselben id wieder
    auf."""
    oid = _objekt("entwurf-waise")
    mid = _miete(oid, "EG", "Vorläufig Meier", vorlaeufig=True)
    with Session(db.engine) as s:
        s.add(Bewohner(miete_id=mid, name="Kind Meier"))
        s.commit()

    with TestClient(app) as c:
        antwort = c.post(f"/api/entwuerfe/miete/{mid}/verwerfen")
    assert antwort.status_code == 200, antwort.text

    with Session(db.engine) as s:
        assert s.get(Miete, mid) is None
        waisen = s.exec(select(Bewohner).where(Bewohner.miete_id == mid)).all()
    assert not waisen, f"Bewohner ohne Mietverhältnis übrig: {waisen}"


def test_bestaetigter_miet_entwurf_traegt_seinen_anteil():
    """Die Verteilung filtert `vorlaeufig` nicht — der bestätigte Mieter muss
    deshalb sofort in den abgeleiteten Anteilen stehen. Vorher trug er 0 %, die
    übrigen Parteien absorbierten seinen Anteil."""
    oid = _objekt("entwurf-anteil", einheiten=("EG", "OG"))
    _miete(oid, "EG", "Bestand EG")
    zid = _zeitraum(oid)

    with TestClient(app) as c:
        angelegt = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 1000.0, "schluessel": "flaeche"})
        assert angelegt.status_code == 201, angelegt.text

        mid = _miete(oid, "OG", "Neu OG", vorlaeufig=True,
                     ab=date(2025, 1, 1))
        bestaetigt = c.post(f"/api/entwuerfe/miete/{mid}/bestaetigen")
        assert bestaetigt.status_code == 200, bestaetigt.text

        positionen = c.get(f"/api/zeitraeume/{zid}/positionen").json()

    anteile = positionen[0]["anteile"]
    assert "Neu OG" in anteile, f"Bestätigter Mieter trägt nichts: {anteile}"


# --------------------------------------------------------------------------
# 3 — das Abrechnungsjahr eines vorhandenen Belegs geht nicht verloren
# --------------------------------------------------------------------------
def _zuordnen(c, slug: str, pfad: str, jahr: int | None) -> dict:
    antwort = c.post("/api/dokumente/vorhandenen-zuordnen", json={
        "objekt": slug, "pfad": pfad, "kategorie": "Nebenkosten", "jahr": jahr})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _dokument(did: int) -> Dokument:
    with Session(db.engine) as s:
        return s.get(Dokument, did)


def test_vorhandener_beleg_behaelt_sein_jahr():
    """Ohne `jahr` fehlte der Eintrag im Jahresfilter und der Beleg-Abgleich
    meldete ihn als Grenzfall „kein_datum", statt ihn zu verschieben."""
    _objekt("belegjahr")
    with TestClient(app) as c:
        neu = _zuordnen(c, "belegjahr", "/Belegjahr/2024/Wasser.pdf", 2024)
    assert _dokument(neu["id"]).jahr == 2024


def test_vorhandener_beleg_traegt_jahr_additiv_nach():
    """Der Idempotenz-Zweig: ein Eintrag ohne Jahr bekommt es nachgetragen, ein
    gepflegtes Jahr wird nie überschrieben."""
    _objekt("belegjahr-2")
    with TestClient(app) as c:
        ohne = _zuordnen(c, "belegjahr-2", "/Belegjahr2/ohne.pdf", None)
        assert _dokument(ohne["id"]).jahr is None
        nochmal = _zuordnen(c, "belegjahr-2", "/Belegjahr2/ohne.pdf", 2024)
        assert nochmal["id"] == ohne["id"]
        assert _dokument(ohne["id"]).jahr == 2024

        # Bestehendes Jahr bleibt stehen.
        _zuordnen(c, "belegjahr-2", "/Belegjahr2/ohne.pdf", 2019)
        assert _dokument(ohne["id"]).jahr == 2024


# --------------------------------------------------------------------------
# 4 — ein unbekannter Slug ist überall ein 404
# --------------------------------------------------------------------------
def test_unbekanntes_objekt_ist_ueberall_404():
    """Vorher: `/auswertung`, `/sankey` und `/mietverlauf` antworteten mit 200
    und lauter Nullen — ein veralteter Slug sah aus wie ein Objekt ohne
    Einnahmen und ohne Kosten."""
    with TestClient(app) as c:
        for pfad in ("/api/auswertung", "/api/auswertung/cashflow",
                     "/api/auswertung/sankey", "/api/auswertung/mietverlauf"):
            antwort = c.get(pfad, params={"objekt": "gibtsnicht"})
            assert antwort.status_code == 404, f"{pfad}: {antwort.status_code}"


def test_auswertung_ohne_objekt_bleibt_offen():
    """Gegenprobe: ohne Slug wird weiterhin über alle Objekte ausgewertet."""
    with TestClient(app) as c:
        for pfad in ("/api/auswertung", "/api/auswertung/sankey",
                     "/api/auswertung/mietverlauf"):
            assert c.get(pfad).status_code == 200, pfad


def test_positionen_unbekannter_zeitraum_ist_404():
    """Eine leere Liste liest sich als „keine Positionen", obwohl es den
    Zeitraum gar nicht gibt — alle Nachbarn dort geben 404."""
    with TestClient(app) as c:
        assert c.get("/api/zeitraeume/987654/positionen").status_code == 404
