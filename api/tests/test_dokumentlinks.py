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


# --------------------------------------------------------------------------
# N299 — die Wissensdatenbank zieht beim Umzug mit
# --------------------------------------------------------------------------

def test_belegdaten_folgen_dem_umbenannten_beleg():
    """`Belegdaten` führt eine ZWEITE Kopie von Pfad und Dateiname. Kein Umzug
    hat sie je nachgezogen — benennt der Nutzer im Explorer um, folgte der
    Beleg (N290), die Wissensdatenbank aber nicht, und die Suche zeigte auf
    eine veraltete Wahrheit."""
    from app import kidb

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Kidbweg 10", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            d = Dokument(pfad="/K/alt.pdf", dateiname="alt.pdf", objekt_id=o.id)
            s.add(d); s.commit(); s.refresh(d)
            s.add(Belegdaten(dokument_id=d.id, objekt_id=o.id,
                             pfad="/K/alt.pdf", dateiname="alt.pdf"))
            s.commit()
            did = d.id

        with Session(engine) as s:
            d = s.get(Dokument, did)
            d.pfad, d.dateiname = "/K/anders/neu.pdf", "neu.pdf"
            assert kidb.pfad_nachziehen(s, d) is True
            s.add(d); s.commit()

        with Session(engine) as s:
            satz = s.exec(select(Belegdaten).where(
                Belegdaten.dokument_id == did)).first()
            assert satz.pfad == "/K/anders/neu.pdf"
            assert satz.dateiname == "neu.pdf"
            # Zweiter Lauf ändert nichts mehr — sonst schriebe jeder Abgleich
            # die ganze Wissensdatenbank neu.
            assert kidb.pfad_nachziehen(s, s.get(Dokument, did)) is False


def test_pfad_nachziehen_haelt_nichts_auf():
    """Ein hakender Abgleich der Wissensdatenbank darf nie einen Dateiumzug
    scheitern lassen."""
    from app import kidb

    with Session(engine) as s:
        assert kidb.pfad_nachziehen(s, None) is False


# --------------------------------------------------------------------------
# N302 — die Arbeitsliste und der Text, beides ohne KI-Aufruf
# --------------------------------------------------------------------------

def test_ohne_auslese_listet_nur_belege_ohne_einschaetzung():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Leseweg 11", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            leer = Dokument(pfad="/L/leer.pdf", dateiname="leer.pdf",
                            objekt_id=o.id)
            voll = Dokument(pfad="/L/voll.pdf", dateiname="voll.pdf",
                            objekt_id=o.id, ki_einordnung="Ein Bescheid")
            s.add(leer); s.add(voll); s.commit()
            s.refresh(leer); s.refresh(voll)
            leer_id, voll_id = leer.id, voll.id

        ids = {b["id"] for b in c.get("/api/dokumente/ohne-auslese").json()["belege"]}
        assert leer_id in ids
        assert voll_id not in ids


def test_text_endpunkt_meldet_unbekannten_beleg_sauber():
    with TestClient(app) as c:
        assert c.get("/api/dokumente/999999/text").status_code == 404


# --------------------------------------------------------------------------
# N286 — Ablageordner von Hand ändern
# --------------------------------------------------------------------------

def test_ziel_bleibt_im_objektordner():
    """Der eigentliche Riegel: ein Beleg dieser Immobilie hat ausserhalb ihres
    Ordners nichts verloren, auch nicht auf ausdrücklichen Wunsch. Sonst liesse
    er sich in den Ordner einer FREMDEN Immobilie schieben, und deren Abgleich
    nähme ihn beim nächsten Lauf als eigenen Beleg auf."""
    from fastapi import HTTPException

    from app.routers.dokumente import _ziel_im_objekt

    class _O:
        nc_ordner = "/Immobilien/(Ort) Weg 5"

    o = _O()
    # Absolut, innerhalb → bleibt
    assert _ziel_im_objekt(o, "/Immobilien/(Ort) Weg 5/60_Nebenkosten") \
        == "Immobilien/(Ort) Weg 5/60_Nebenkosten"
    # Relativ → wird unter dem Objektordner verstanden
    assert _ziel_im_objekt(o, "60_Nebenkosten/2025") \
        == "Immobilien/(Ort) Weg 5/60_Nebenkosten/2025"
    # Fremder Objektordner → landet UNTER dem eigenen, nie daneben
    fremd = _ziel_im_objekt(o, "/Immobilien/(Anderswo) Gasse 1/60_Nebenkosten")
    assert fremd.startswith("Immobilien/(Ort) Weg 5/")
    # Ausbruchsversuch
    for boese in ("../../etc", "/Immobilien/../../root"):
        try:
            ergebnis = _ziel_im_objekt(o, boese)
        except HTTPException:
            continue
        assert ergebnis.startswith("Immobilien/(Ort) Weg 5")


def test_ohne_cloud_ordner_wird_nicht_verschoben():
    from fastapi import HTTPException

    from app.routers.dokumente import _ziel_im_objekt

    class _O:
        nc_ordner = ""

    try:
        _ziel_im_objekt(_O(), "60_Nebenkosten")
    except HTTPException as fehler:
        assert fehler.status_code == 400
    else:
        raise AssertionError("Ohne Cloud-Ordner darf nichts verschoben werden")


def test_verschieben_meldet_saubere_fehler_statt_500():
    with TestClient(app) as c:
        assert c.post("/api/dokumente/999999/verschieben",
                      json={"ordner": "x"}).status_code == 404
        _slug, alt, _neu = _welt(c, "Umzugsweg 12")
        # Ohne Ziel: klare Ansage statt Absturz
        assert c.post(f"/api/dokumente/{alt}/verschieben",
                      json={}).status_code == 400
        # Unbekannte Dokumentart
        antwort = c.post(f"/api/dokumente/{alt}/verschieben",
                         json={"kategorie": "Gibtsnicht"})
        assert antwort.status_code == 400
        assert "Dokumentart" in antwort.json()["detail"]


def test_ablageziele_meldet_unbekannten_beleg():
    with TestClient(app) as c:
        assert c.get("/api/dokumente/999999/ablageziele").status_code == 404


def test_ablageziele_zeigt_lesbare_namen_statt_rohe_ordnercodes():
    """N331g — Nutzer-Fund: die „Ordner verschieben"-Liste zeigte den rohen
    Ordnercode unverändert als Beschriftung. Jetzt Klartext, ohne laufende
    Nummer und mit Umlauten. Die geprüften Ordner tragen seit N332 ihre neuen
    Namen (früher „40_Kauf_Eigentum_Finanzierung" und
    „20_Mietvertraege_Vermietung")."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Lesbarweg 9"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "/Immobilien/Lesbarweg 9"
            s.add(o)
            pfad = "/Immobilien/Lesbarweg 9/70_Steuer_Finanzamt/beleg.pdf"
            d = Dokument(pfad=pfad, dateiname="beleg.pdf", objekt_id=o.id,
                        kategorie="Steuer")
            s.add(d)
            s.commit()
            s.refresh(d)
            doc_id = d.id

        antwort = c.get(f"/api/dokumente/{doc_id}/ablageziele")
        assert antwort.status_code == 200
        namen = {z["ordner"].rsplit("/", 1)[-1]: z["name"]
                for z in antwort.json()["ziele"]}
        assert namen["11_Kauf_Bau_Finanzierung"] == "Kauf, Bau & Finanzierung"
        assert namen["30_Vermietung_Verpachtung"] == "Vermietung & Verpachtung"
        assert "_" not in namen["11_Kauf_Bau_Finanzierung"]
        assert not namen["11_Kauf_Bau_Finanzierung"][0].isdigit()


class _WolkeVerschieben:
    """Nextcloud-Ersatz: merkt sich Anlegen/Verschieben, `belegt` simuliert
    Namen, die am Ziel schon liegen (für den Kollisionstest)."""

    def __init__(self, belegt=None):
        self.belegt = set(belegt or [])
        self.angelegt = []
        self.verschoben = []

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        return pfad.strip("/") in self.belegt

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))


class _WolkeKaputt(_WolkeVerschieben):
    """MOVE scheitert immer — simuliert eine nicht erreichbare Cloud."""

    def verschiebe(self, von, nach):
        from app.nextcloud import NextcloudFehler
        raise NextcloudFehler("503 Nextcloud nicht erreichbar")


def test_verschieben_bewegt_datei_und_zieht_links_nach(monkeypatch):
    """Erfolgreicher Umzug: Pfad UND Dateiname wandern in der Datenbank mit,
    die Wissensdatenbank-Kopie (`Belegdaten.pfad`) zieht nach (N299) — und ein
    Verweis über `dokument.id` (hier: eine Versicherung) bleibt gültig, weil
    er nie auf den Pfad zeigte, sondern auf die id."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Zielweg 4"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "/Immobilien/Zielweg 4"
            s.add(o)
            alt_pfad = "/Immobilien/Zielweg 4/01_Allgemein_Hauskonto/alt.pdf"
            d = Dokument(pfad=alt_pfad, dateiname="alt.pdf", objekt_id=o.id,
                        kategorie="Versicherung")
            s.add(d)
            s.commit()
            s.refresh(d)
            doc_id = d.id
            s.add(Versicherung(objekt_id=o.id, art="Gebäude", beitrag=100.0,
                               quelle_dokument_id=doc_id))
            s.add(Belegdaten(dokument_id=doc_id, pfad=alt_pfad,
                             dateiname="alt.pdf"))
            s.commit()

        wolke = _WolkeVerschieben()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.post(f"/api/dokumente/{doc_id}/verschieben",
                         json={"ordner": "70_Steuer_Finanzamt"})
        assert antwort.status_code == 200, antwort.text
        daten = antwort.json()
        assert daten["verschoben"] is True
        neu_pfad = "/Immobilien/Zielweg 4/70_Steuer_Finanzamt/alt.pdf"
        assert daten["pfad"] == neu_pfad
        assert daten["von"] == alt_pfad

        with Session(engine) as s:
            db_doc = s.get(Dokument, doc_id)
            assert db_doc.pfad == neu_pfad
            assert db_doc.dateiname == "alt.pdf"
            # Verweis über die id bleibt gültig, ohne dass hier etwas zu tun war
            db_v = s.exec(select(Versicherung).where(
                Versicherung.quelle_dokument_id == doc_id)).first()
            assert db_v is not None
            # Wissensdatenbank-Kopie zieht nach (N299)
            db_bd = s.exec(select(Belegdaten).where(
                Belegdaten.dokument_id == doc_id)).first()
            assert db_bd.pfad == neu_pfad
            assert db_bd.dateiname == "alt.pdf"

        assert len(wolke.verschoben) == 1
        von, nach = wolke.verschoben[0]
        assert von.lstrip("/") == alt_pfad.lstrip("/")
        assert nach.lstrip("/") == neu_pfad.lstrip("/")


def test_verschieben_weicht_bei_namenskollision_aus(monkeypatch):
    """Liegt am Ziel schon eine Datei mit demselben Namen, wird nie
    überschrieben — `_freier_name` weicht auf „…-2" aus, live gegen die
    Cloud geprüft."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Zielweg 5"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "/Immobilien/Zielweg 5"
            s.add(o)
            d = Dokument(pfad="/Immobilien/Zielweg 5/01_Allgemein_Hauskonto/alt.pdf",
                        dateiname="alt.pdf", objekt_id=o.id)
            s.add(d)
            s.commit()
            s.refresh(d)
            doc_id = d.id

        # Am Ziel liegt schon eine „alt.pdf" — die echte Cloud meldet sie belegt.
        wolke = _WolkeVerschieben(
            belegt={"Immobilien/Zielweg 5/70_Steuer_Finanzamt/alt.pdf"})
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.post(f"/api/dokumente/{doc_id}/verschieben",
                         json={"ordner": "70_Steuer_Finanzamt"})
        assert antwort.status_code == 200, antwort.text
        daten = antwort.json()
        assert daten["dateiname"] == "alt-2.pdf"
        assert daten["pfad"] == \
            "/Immobilien/Zielweg 5/70_Steuer_Finanzamt/alt-2.pdf"

        # Nie überschrieben: das MOVE zielt auf „-2", nicht auf den belegten Namen
        _von, nach = wolke.verschoben[0]
        assert nach.endswith("alt-2.pdf")

        with Session(engine) as s:
            assert s.get(Dokument, doc_id).dateiname == "alt-2.pdf"


def test_verschieben_bei_cloud_fehler_bleibt_alles_unveraendert(monkeypatch):
    """Scheitert der Cloud-MOVE (Nextcloud nicht erreichbar), bleibt die
    Datenbank unangetastet — kein halber Zustand, sondern ein klarer Fehler."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Zielweg 6"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "/Immobilien/Zielweg 6"
            s.add(o)
            alt_pfad = "/Immobilien/Zielweg 6/01_Allgemein_Hauskonto/alt.pdf"
            d = Dokument(pfad=alt_pfad, dateiname="alt.pdf", objekt_id=o.id)
            s.add(d)
            s.commit()
            s.refresh(d)
            doc_id = d.id

        wolke = _WolkeKaputt()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.post(f"/api/dokumente/{doc_id}/verschieben",
                         json={"ordner": "70_Steuer_Finanzamt"})
        assert antwort.status_code == 400
        assert "nicht erreichbar" in antwort.json()["detail"]

        with Session(engine) as s:
            db_doc = s.get(Dokument, doc_id)
            assert db_doc.pfad == alt_pfad
            assert db_doc.dateiname == "alt.pdf"


# --------------------------------------------------------------------------
# N314 — Löschen lässt keinen Verweis stehen
# --------------------------------------------------------------------------

def test_beleg_entfernen_loest_jeden_verweis():
    """Der gefährlichste Fund der Fehlersuche.

    SQLite läuft hier ohne `PRAGMA foreign_keys` und vergibt eine frei
    gewordene id NEU. Ein stehen gelassener Verweis zeigt deshalb nicht ins
    Leere, sondern nach kurzer Zeit auf einen FREMDEN Beleg — der nächste Scan
    erbt die Nummer und steht als „Quelle" einer Versicherung da, die er nie
    gesehen hat."""
    with TestClient(app) as c:
        _slug, alt, _neu = _welt(c, "Loeschweg 20")
        with Session(engine) as s:
            assert len(dokumentlinks.zaehle(s, alt)) == 5

        antwort = c.delete(f"/api/dokumente/{alt}")
        assert antwort.status_code == 200
        assert antwort.json()["verweise_geloest"] == 5

        with Session(engine) as s:
            assert s.get(Dokument, alt) is None
            # Und niemand zeigt mehr auf die tote Nummer.
            assert dokumentlinks.zaehle(s, alt) == {}


def test_nach_dem_entfernen_zeigt_kein_verweis_mehr_ins_leere():
    """Dieselbe Aussage über ALLE Fremdschlüssel, unabhängig von Zahlen."""
    from sqlmodel import text

    with TestClient(app) as c:
        _slug, alt, _neu = _welt(c, "Leerweg 21")
        c.delete(f"/api/dokumente/{alt}")
        with Session(engine) as s:
            tot = []
            for v in dokumentlinks.register():
                for (wert,) in s.exec(text(  # noqa: S608
                        f'SELECT "{v.spalte}" FROM "{v.tabelle}" '
                        f'WHERE "{v.spalte}" IS NOT NULL')).all():
                    if s.get(Dokument, wert) is None:
                        tot.append(f"{v} -> {wert}")
            assert not tot, "Verweise ins Leere: " + ", ".join(tot)
