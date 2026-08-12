"""N366 — Verweise dürfen nach Löschen und Wiederherstellen nie auf Fremdes zeigen.

SQLite vergibt frei gewordene rowids neu. Jeder Fremdschlüssel, der beim
Löschen stehen bleibt oder beim Import unverändert übernommen wird, zeigt
darum früher oder später auf den Datensatz eines ANDEREN Objekts — und die
Oberfläche zeigt ihn wortlos an.

Fünf solche Lücken werden hier zugenagelt:
  1. `Versandprotokoll` blieb beim Löschen stehen → eine Partei am neu
     angelegten Zeitraum galt als schon beliefert und bekam nie ihre
     Abrechnung.
  2. `WegVorauszahlung` fehlte in Sicherung UND Löschen → die Monatsbeträge
     waren nach dem Wiederherstellen weg (Nachforderung um den vollen
     Jahresbetrag zu hoch) und ein fremder Betrag wanderte in den neuen
     Zeitraum.
  3. `quelle_dokument_id` wurde nicht umgehängt → der „Beleg"-Knopf öffnete
     den Mietvertrag eines fremden Objekts.
  4. `Miete.vorgaenger_id` wurde nicht umgehängt → die Mieterhöhungskette und
     der Kautions-Backfill zogen die Daten eines fremden Mieters heran.
  5. `Tanknutzer.person_id`/`Tankladung.person_id` blieben beim Löschen eines
     Eigentümers stehen → die Ladeabrechnung lief auf die nächste angelegte
     Person, samt deren Bankdaten.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_export_verweise.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Dokument, Kostenposition, Miete, Tankladung,  # noqa: E402
                        Tanknutzer, Versandprotokoll, WegVorauszahlung)


def _objekt(c, name):
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Musterstadt", "strasse": name,
        "kaufpreis": 300000.0, "kostenarten": ["Wasser"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Mieter A"}],
    })
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["slug"], antwort.json()["id"]


def _zeitraum(c, slug):
    antwort = c.post(f"/api/objekte/{slug}/zeitraeume",
                     json={"start": "2024-01-01", "ende": "2024-12-31"})
    assert antwort.status_code in (200, 201), antwort.text
    return antwort.json()["id"]


def _zeitraum_ids(c, slug):
    """Zeiträume stehen unter GET /api/objekte/{slug} — es gibt keine eigene Liste."""
    return [z["id"] for z in c.get(f"/api/objekte/{slug}").json()["zeitraeume"]]


def _gesichert(sicherung, zid):
    """Der gesicherte Block genau dieses Zeitraums — ein Objekt hat mehrere."""
    treffer = [z for z in sicherung["zeitraeume"] if z["id"] == zid]
    assert treffer, f"Zeitraum {zid} fehlt in der Sicherung"
    return treffer[0]


def test_versandprotokoll_und_wegvorauszahlung_haengen_am_zeitraum():
    """Beide gehören in die Sicherung und müssen mit dem Zeitraum verschwinden."""
    with TestClient(app) as c:
        slug, _ = _objekt(c, "Verweisweg 1")
        zid = _zeitraum(c, slug)
        with Session(engine) as s:
            s.add(Versandprotokoll(zeitraum_id=zid, partei="Mieter A",
                                   empfaenger="alt@example.org"))
            s.add(WegVorauszahlung(zeitraum_id=zid, einheit="EG",
                                   betrag_monat=250.0))
            s.commit()

        block = _gesichert(c.get(f"/api/objekte/{slug}/export").json(), zid)
        assert block["versandprotokolle"], "Versand fehlt in der Sicherung"
        assert block["wegvorauszahlungen"], "WEG-VZ fehlt in der Sicherung"
        sicherung = c.get(f"/api/objekte/{slug}/export").json()

        assert c.delete(f"/api/objekte/{slug}").status_code == 200
        with Session(engine) as s:
            assert not s.exec(select(Versandprotokoll).where(
                Versandprotokoll.zeitraum_id == zid)).all(), \
                "Versandprotokoll überlebt das Löschen"
            assert not s.exec(select(WegVorauszahlung).where(
                WegVorauszahlung.zeitraum_id == zid)).all(), \
                "WEG-Vorauszahlung überlebt das Löschen"

        # Und die Wiederherstellung bringt beide zurück — am neuen Zeitraum.
        neuer_slug = c.post("/api/objekte/import", json=sicherung).json()["slug"]
        neue_ids = _zeitraum_ids(c, neuer_slug)
        with Session(engine) as s:
            vz = s.exec(select(WegVorauszahlung).where(
                WegVorauszahlung.zeitraum_id.in_(neue_ids))).all()
            assert [v.betrag_monat for v in vz] == [250.0]
            vp = s.exec(select(Versandprotokoll).where(
                Versandprotokoll.zeitraum_id.in_(neue_ids))).all()
            assert [v.empfaenger for v in vp] == ["alt@example.org"]


def test_belegverweis_zeigt_nie_auf_fremdes_dokument():
    """`quelle_dokument_id` wird umgehängt — oder geleert, nie geraten."""
    with TestClient(app) as c:
        slug, objekt_id = _objekt(c, "Belegweg 2")
        zid = _zeitraum(c, slug)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen",
                     json={"kostenart": "Wasser", "betrag": 120.0}).json()["id"]
        with Session(engine) as s:
            d = Dokument(objekt_id=objekt_id, dateiname="rechnung.pdf",
                         pfad="/Home/belegweg/rechnung.pdf")
            s.add(d)
            s.commit()
            s.refresh(d)
            pos = s.get(Kostenposition, pid)
            pos.quelle_dokument_id = d.id
            s.add(pos)
            s.commit()
            alte_dokument_id = d.id

        sicherung = c.get(f"/api/objekte/{slug}/export").json()
        assert c.delete(f"/api/objekte/{slug}").status_code == 200

        # Ein FREMDES Objekt erbt die frei gewordene Nummer.
        fremd, fremd_id = _objekt(c, "Fremdweg 3")
        with Session(engine) as s:
            s.add(Dokument(objekt_id=fremd_id, dateiname="mietvertrag.pdf",
                           pfad="/Home/fremd/mietvertrag.pdf"))
            s.commit()
            geerbt = s.get(Dokument, alte_dokument_id)
            assert geerbt is not None and geerbt.objekt_id == fremd_id, (
                "Aufbau misslungen: die alte Nummer wurde nicht neu vergeben")

        neuer_slug = c.post("/api/objekte/import", json=sicherung).json()["slug"]
        neue_ids = _zeitraum_ids(c, neuer_slug)
        neues_objekt = c.get(f"/api/objekte/{neuer_slug}").json()["objekt"]["id"]
        with Session(engine) as s:
            positionen = s.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id.in_(neue_ids),
                Kostenposition.quelle_dokument_id.isnot(None))).all()
            for p in positionen:
                beleg = s.get(Dokument, p.quelle_dokument_id)
                assert beleg is not None
                assert beleg.objekt_id == neues_objekt, (
                    f"Belegverweis zeigt auf ein fremdes Objekt: {beleg.pfad}")


def test_mieterhoehungskette_zeigt_nie_auf_fremden_mieter():
    with TestClient(app) as c:
        slug, objekt_id = _objekt(c, "Kettenweg 4")
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "ab_datum": "2023-01-01"})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 850.0,
            "ab_datum": "2024-01-01"})
        with Session(engine) as s:
            mieten = s.exec(select(Miete).where(
                Miete.objekt_id == objekt_id).order_by(Miete.ab_datum)).all()
            assert len(mieten) >= 2
            mieten[-1].vorgaenger_id = mieten[0].id
            s.add(mieten[-1])
            s.commit()

        sicherung = c.get(f"/api/objekte/{slug}/export").json()
        assert c.delete(f"/api/objekte/{slug}").status_code == 200

        fremd, _ = _objekt(c, "Fremdkette 5")
        c.post(f"/api/objekte/{fremd}/mieten", json={
            "einheit": "EG", "partei": "Fremdmieter", "kaltmiete": 999.0,
            "ab_datum": "2023-01-01"})

        neuer_slug = c.post("/api/objekte/import", json=sicherung).json()["slug"]
        neue_objekt_id = c.get(f"/api/objekte/{neuer_slug}").json()["objekt"]["id"]
        with Session(engine) as s:
            kette = s.exec(select(Miete).where(
                Miete.objekt_id == neue_objekt_id,
                Miete.vorgaenger_id.isnot(None))).all()
            assert kette, "Die Kette wurde gar nicht wiederhergestellt"
            for m in kette:
                vor = s.get(Miete, m.vorgaenger_id)
                assert vor is not None, "Vorgänger zeigt ins Leere"
                assert vor.objekt_id == neue_objekt_id, (
                    f"Vorgänger gehört einem fremden Objekt: {vor.partei}")


def test_eigentuemer_loeschen_loest_tank_verweise():
    with TestClient(app) as c:
        slug, objekt_id = _objekt(c, "Tankweg 6")
        alt_id = c.post("/api/eigentuemer", json={"name": "Anna Alt"}).json()["id"]
        with Session(engine) as s:
            s.add(Tanknutzer(objekt_id=objekt_id, person_id=alt_id,
                             name="Anna Alt"))
            s.add(Tankladung(objekt_id=objekt_id, jahr=2024, person_id=alt_id,
                             name="Anna Alt", kwh=120.0))
            s.commit()

        assert c.delete(f"/api/eigentuemer/{alt_id}").status_code == 200
        with Session(engine) as s:
            assert not s.exec(select(Tanknutzer).where(
                Tanknutzer.person_id == alt_id)).all(), \
                "Tanknutzer zeigt weiter auf die gelöschte Person"
            assert not s.exec(select(Tankladung).where(
                Tankladung.person_id == alt_id)).all(), \
                "Ladung zeigt weiter auf die gelöschte Person"
            # Die Zeilen selbst bleiben — nur der Verweis ist gelöst.
            assert s.exec(select(Tankladung).where(
                Tankladung.name == "Anna Alt")).all()
