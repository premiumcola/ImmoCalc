"""N300 — Belege zusammenführen, ohne Verknüpfungen zu verlieren.

Der gemessene Ausgangszustand: **zehn** Tabellen zeigen auf `dokument.id`, und
beim Löschen eines Belegs wurde **keine einzige** umgehängt oder gelöst. Im
Probelauf trugen Renovierungsposten, Versicherung, Kredit, Notarvertrag und
Belegdaten danach weiter die tote Nummer. Auch `duplikat-entfernen` löschte
ersatzlos.

Der Wächter unten (`test_das_register_kennt_jeden_fremdschluessel`) ist der
eigentliche Schutz: die Liste, die es vorher im Router gab, kannte nur sieben
der zehn — es fehlten genau die drei jüngsten Modelle. Eine von Hand gepflegte
Liste hängt hinterher, und das Ergebnis ist ein Verweis ins Leere, den niemand
bemerkt.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_dokumentlinks.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from app import dokumentlinks  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Belegdaten, Dokument, Kredit,  # noqa: E402
                        Notarvertrag, Objekt, Renovierung,
                        Renovierungsposten, Versicherung)


# --------------------------------------------------------------------------
# Das Register
# --------------------------------------------------------------------------

def test_das_register_kennt_jeden_fremdschluessel():
    """Der Wächter: was auf `dokument.id` zeigt, MUSS im Register stehen.

    Wird morgen ein Modell mit `quelle_dokument_id` ergänzt, ist es von selbst
    dabei — und dieser Test bleibt grün, ohne dass jemand eine Liste pflegt."""
    aus_metadaten = set()
    for name, tabelle in SQLModel.metadata.tables.items():
        if name == "dokument":
            continue
        for spalte in tabelle.columns:
            for fk in spalte.foreign_keys:
                if fk.column.table.name == "dokument":
                    aus_metadaten.add(f"{name}.{spalte.name}")
    im_register = {str(v) for v in dokumentlinks.register()}
    assert im_register == aus_metadaten
    # Untergrenze: fällt das Register auf eine Handvoll, prüft der Test nichts
    # mehr. Bei der Einführung waren es zehn.
    assert len(im_register) >= 10


def test_die_drei_jungen_modelle_sind_dabei():
    """Genau sie fehlten in der handgepflegten Liste."""
    im_register = {str(v) for v in dokumentlinks.register()}
    assert "renovierungsposten.quelle_dokument_id" in im_register
    assert "stromjahr.screenshot_dokument_id" in im_register
    assert "belegdaten.dokument_id" in im_register


# --------------------------------------------------------------------------
# Umhängen
# --------------------------------------------------------------------------

def _welt(c: TestClient, name: str):
    """Ein Objekt, zwei byte-gleiche Belege, und an einem hängt alles Mögliche."""
    slug = c.post("/api/objekte", json={"name": name, "einheiten": [
        {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        # Je Welt eine EIGENE Prüfsumme — sonst landen alle Testfälle in
        # derselben Duplikat-Gruppe und die Zählung sagt nichts mehr.
        eigen = f"sha-{slug}"
        alt = Dokument(pfad=f"/{name}/alt.pdf", dateiname="alt.pdf",
                       objekt_id=o.id, groesse=10, sha1=eigen)
        neu = Dokument(pfad=f"/{name}/neu.pdf", dateiname="neu.pdf",
                       objekt_id=o.id, groesse=10, sha1=eigen)
        s.add(alt); s.add(neu); s.commit(); s.refresh(alt); s.refresh(neu)
        r = Renovierung(objekt_id=o.id, name="Sanierung", von=date(2025, 1, 1))
        s.add(r); s.commit(); s.refresh(r)
        s.add(Renovierungsposten(renovierung_id=r.id, betrag=100.0,
                                 firma="Muster", quelle_dokument_id=alt.id))
        s.add(Versicherung(objekt_id=o.id, art="Gebäude", beitrag=100.0,
                           quelle_dokument_id=alt.id))
        s.add(Kredit(objekt_id=o.id, bezeichnung="Darlehen", bank="B",
                     quelle_dokument_id=alt.id))
        s.add(Notarvertrag(objekt_id=o.id, art="Kaufvertrag",
                           quelle_dokument_id=alt.id))
        s.add(Belegdaten(dokument_id=alt.id, objekt_id=o.id))
        s.commit()
        return slug, alt.id, neu.id


def test_zusammenfuehren_zieht_jeden_verweis_mit():
    """Der Fall, der vorher garantiert schiefging."""
    with TestClient(app) as c:
        _slug, alt, neu = _welt(c, "Umhaengeweg 1")
        with Session(engine) as s:
            assert len(dokumentlinks.zaehle(s, alt)) == 5    # fünf Tabellen

        antwort = c.post(f"/api/dokumente/{neu}/zusammenfuehren",
                         json={"weg_ids": [alt], "datei_loeschen": False})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["verweise_umgehaengt"] == 5

        with Session(engine) as s:
            assert s.get(Dokument, alt) is None              # Duplikat weg
            assert s.get(Dokument, neu) is not None          # der bleibt
            # Und alles hängt jetzt am Bleibenden, nicht im Leeren:
            assert len(dokumentlinks.zaehle(s, neu)) == 5
            for modell, feld in ((Renovierungsposten, "quelle_dokument_id"),
                                 (Versicherung, "quelle_dokument_id"),
                                 (Kredit, "quelle_dokument_id"),
                                 (Notarvertrag, "quelle_dokument_id"),
                                 (Belegdaten, "dokument_id")):
                eintrag = s.exec(select(modell)).all()[-1]
                assert getattr(eintrag, feld) == neu


def test_kein_verweis_zeigt_danach_ins_leere():
    """Die Kernaussage, unabhängig von den Zahlen oben."""
    with TestClient(app) as c:
        _slug, alt, neu = _welt(c, "Leerweg 2")
        c.post(f"/api/dokumente/{neu}/zusammenfuehren",
               json={"weg_ids": [alt], "datei_loeschen": False})
        with Session(engine) as s:
            tot = []
            for v in dokumentlinks.register():
                from sqlmodel import text
                reihe = s.exec(text(  # noqa: S608
                    f'SELECT "{v.spalte}" FROM "{v.tabelle}" '
                    f'WHERE "{v.spalte}" IS NOT NULL')).all()
                for (wert,) in reihe:
                    if s.get(Dokument, wert) is None:
                        tot.append(f"{v} -> {wert}")
            assert not tot, "Verweise ins Leere: " + ", ".join(tot)


# --------------------------------------------------------------------------
# Was NICHT passieren darf
# --------------------------------------------------------------------------

def test_verschiedene_pruefsummen_werden_nicht_zusammengefuehrt():
    """Zusammengeführt wird nur, was nachweislich derselbe Inhalt ist —
    sonst wäre es Löschen auf Verdacht."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ungleichweg 3", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            a = Dokument(pfad="/U/a.pdf", dateiname="a.pdf", objekt_id=o.id,
                         sha1="aaa")
            b = Dokument(pfad="/U/b.pdf", dateiname="b.pdf", objekt_id=o.id,
                         sha1="bbb")
            s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
            aid, bid = a.id, b.id

        antwort = c.post(f"/api/dokumente/{aid}/zusammenfuehren",
                         json={"weg_ids": [bid]})
        assert antwort.status_code == 400
        assert "Prüfsumme" in antwort.json()["detail"]
        with Session(engine) as s:
            assert s.get(Dokument, bid) is not None           # nichts gelöscht


def test_ohne_pruefsumme_wird_nicht_geraten():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ohneweg 4", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            a = Dokument(pfad="/O/a.pdf", dateiname="a.pdf", objekt_id=o.id)
            b = Dokument(pfad="/O/b.pdf", dateiname="b.pdf", objekt_id=o.id)
            s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
            aid, bid = a.id, b.id
        antwort = c.post(f"/api/dokumente/{aid}/zusammenfuehren",
                         json={"weg_ids": [bid]})
        assert antwort.status_code == 400
        assert "Prüfsumme" in antwort.json()["detail"]


def test_sich_selbst_zusammenfuehren_geht_nicht():
    with TestClient(app) as c:
        _slug, alt, _neu = _welt(c, "Selbstweg 5")
        antwort = c.post(f"/api/dokumente/{alt}/zusammenfuehren",
                         json={"weg_ids": [alt]})
        assert antwort.status_code == 400


def test_unbekannter_beleg_ergibt_404_und_loescht_nichts():
    with TestClient(app) as c:
        _slug, alt, neu = _welt(c, "Fehlweg 6")
        assert c.post(f"/api/dokumente/{neu}/zusammenfuehren",
                      json={"weg_ids": [999999]}).status_code == 404
        assert c.post("/api/dokumente/999999/zusammenfuehren",
                      json={"weg_ids": [alt]}).status_code == 404
        with Session(engine) as s:
            assert s.get(Dokument, alt) is not None


# --------------------------------------------------------------------------
# Die Liste der Duplikate
# --------------------------------------------------------------------------

def test_duplikate_gruppiert_nach_pruefsumme():
    with TestClient(app) as c:
        _slug, alt, neu = _welt(c, "Gruppenweg 7")
        gruppen = c.get("/api/dokumente/duplikate").json()["gruppen"]
        meine = [g for g in gruppen if {k["id"] for k in g["kopien"]} >= {alt, neu}]
        assert len(meine) == 1
        g = meine[0]
        assert g["anzahl"] == 2
        # Vorn steht, wer die meisten Verknüpfungen trägt — der natürliche
        # Kandidat zum BEHALTEN, den die Oberfläche vorwählt. Der Beleg ganz
        # ohne Verweise steht hinten: er ist der unverfänglichste zum Wegwerfen.
        assert g["kopien"][0]["id"] == alt
        assert g["kopien"][0]["verknuepfungen"]
        assert g["kopien"][0]["pfad"].endswith("alt.pdf")
        assert g["kopien"][1]["id"] == neu
        assert g["kopien"][1]["verknuepfungen"] == []


def test_einzelstuecke_stehen_nicht_in_der_liste():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Einzelweg 8", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            s.add(Dokument(pfad="/E/einzel.pdf", dateiname="einzel.pdf",
                           objekt_id=o.id, sha1="ganz-allein"))
            s.commit()
        gruppen = c.get("/api/dokumente/duplikate").json()["gruppen"]
        assert not [g for g in gruppen if g["sha1"] == "ganz-allein"]


def test_die_liste_traegt_die_pruefsumme():
    """N298 — ohne sie kann die Oberfläche gar nicht gruppieren."""
    with TestClient(app) as c:
        _welt(c, "Sichtweg 9")
        belege = c.get("/api/dokumente").json()["dokumente"]
        assert belege and all("sha1" in b for b in belege)
