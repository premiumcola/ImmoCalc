"""N332 — die Hauptordner ziehen auf die neue Gliederung um.

Der Bestand ist über Jahre von Hand gewachsen: derselbe Sachverhalt liegt bei
der einen Immobilie unter „60_Nebenkosten", bei der anderen unter
„32_Nebenkosten", Fotos heissen mal „10_Fotos_Lage", mal „10_Fotos_Lagepläne".
Der Umzug muss deshalb drei Fälle beherrschen — umbenennen, zusammenlegen,
auflösen — und darf dabei nichts überschreiben und nichts löschen.
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.routers.cloud as cloud_modul
from app.db import engine
from app.main import app
from app.models import Dokument, Einstellung, Objekt
from app.nextcloud import NextcloudFehler

HOME = "/[010]_Immobilien"


def _norm(pfad: str) -> str:
    return "/" + "/".join(t for t in (pfad or "").split("/") if t)


class _Wolke:
    """Nextcloud-Ersatz: der Ordnerbaum als Menge von Pfaden."""

    def __init__(self, ordner=(), dateien=()):
        self.ordner = {_norm(p) for p in ordner}
        self.dateien = {_norm(p) for p in dateien}
        self.verschoben: list[tuple[str, str]] = []

    def existiert(self, pfad: str) -> bool:
        return _norm(pfad) in self.ordner or _norm(pfad) in self.dateien

    def liste(self, pfad: str):
        eltern = _norm(pfad)
        if eltern not in self.ordner:
            raise NextcloudFehler(f"Ordner nicht gefunden: {eltern}")
        return [SimpleNamespace(name=p.rsplit("/", 1)[-1], pfad=p,
                                ordner=p in self.ordner, groesse=0)
                for p in sorted(self.ordner | self.dateien)
                if p.startswith(eltern + "/") and "/" not in p[len(eltern) + 1:]]

    def ordner_anlegen(self, pfad: str) -> bool:
        neu = not self.existiert(pfad)
        self.ordner.add(_norm(pfad))
        return neu

    def verschiebe(self, von: str, nach: str) -> None:
        von, nach = _norm(von), _norm(nach)
        if self.existiert(nach):
            raise NextcloudFehler(f"Ziel belegt: {nach}")
        for menge in (self.ordner, self.dateien):
            for p in sorted(menge):
                if p == von or p.startswith(von + "/"):
                    menge.discard(p)
                    menge.add(nach + p[len(von):])
        self.verschoben.append((von, nach))


def _einstellung(schluessel: str, wert: str) -> None:
    with Session(engine) as s:
        e = s.get(Einstellung, schluessel)
        if e:
            e.wert = wert
        else:
            e = Einstellung(schluessel=schluessel, wert=wert)
        s.add(e)
        s.commit()


def _cloud_bereit() -> None:
    for schluessel, wert in (("nc_url", "https://wolke.example"),
                             ("nc_benutzer", "roman"), ("nc_passwort", "geheim"),
                             ("nc_home", HOME)):
        _einstellung(schluessel, wert)
    with Session(engine) as s:
        for o in s.exec(select(Objekt)).all():
            o.nc_ordner = ""
            s.add(o)
        s.commit()


def _objekt(c, name: str, ordner: str) -> str:
    slug = c.post("/api/objekte", json={"name": name, "ort": "Eschenau",
                                        "strasse": "Laufer Str. 5"}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = ordner
        s.add(o)
        s.commit()
    return slug


def _dokument(slug: str, pfad: str) -> int:
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        d = Dokument(pfad=pfad, dateiname=pfad.rsplit("/", 1)[-1],
                     objekt_id=o.id, kategorie="Nebenkosten", jahr=2024,
                     status="zugeordnet")
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def _pfad_von(dokument_id: int) -> str:
    with Session(engine) as s:
        return s.get(Dokument, dokument_id).pfad


def test_freier_zielname_wird_zur_umbenennung(monkeypatch):
    """Der häufigste Fall: es gibt nur den alten Ordner. Dann genügt ein
    einziger MOVE — der ganze Ordner samt Inhalt wandert auf den neuen Namen,
    und die Belege darin zeigen anschliessend auf den neuen Pfad."""
    wurzel = f"{HOME}/Haus A"
    alt = f"{wurzel}/60_Nebenkosten"
    beleg = f"{alt}/2024/2024_NK-Wasser.pdf"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Haus A", wurzel)
        dok = _dokument(slug, beleg)
        wolke = _Wolke(ordner=[HOME, wurzel, alt, f"{alt}/2024"], dateien=[beleg])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        plan = c.get("/api/nextcloud/struktur-umzug").json()
        assert plan["ordner"] == 1
        assert plan["schritte"][0]["zuege"][0] == {
            "von": "60_Nebenkosten", "nach": "32_Nebenkosten", "art": "umzug"}

        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["fehler"] == []
        assert ergebnis["verschoben"][0]["art"] == "umbenannt"
        assert _pfad_von(dok) == f"{wurzel}/32_Nebenkosten/2024/2024_NK-Wasser.pdf"
        assert wolke.existiert(_pfad_von(dok))
        # Der alte Name ist weg, weil der Ordner selbst gewandert ist — hier
        # bleibt also keine leere Hülle zurück.
        assert f"{wurzel}/60_Nebenkosten" not in wolke.ordner
        assert ergebnis["leer"] == []


def test_belegter_zielname_wird_zusammengelegt(monkeypatch):
    """Unterschöllenbach hat beides: den umbenannten Ordner UND den alten, den
    die Vorlage wieder angelegt hat. Dann zieht Kind für Kind hinüber, und die
    leere Hülle steht danach in der Aufräumliste."""
    wurzel = f"{HOME}/Haus B"
    alt, neu = f"{wurzel}/60_Nebenkosten", f"{wurzel}/32_Nebenkosten"
    beleg = f"{alt}/2024_NK-Strom.pdf"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Haus B", wurzel)
        dok = _dokument(slug, beleg)
        wolke = _Wolke(ordner=[HOME, wurzel, alt, neu, f"{neu}/2025"],
                       dateien=[beleg])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["fehler"] == []
        assert ergebnis["verschoben"][0]["art"] == "zusammengelegt"
        assert _pfad_von(dok) == f"{neu}/2024_NK-Strom.pdf"
        # Nichts gelöscht: der ausgeräumte Ordner steht noch da …
        assert alt in wolke.ordner
        # … und genau dafür gibt es die Liste zum Aufräumen.
        assert [e["pfad"] for e in ergebnis["leer"]] == [alt]


def test_gleichnamiges_bleibt_liegen_statt_ueberschrieben_zu_werden(monkeypatch):
    """Heisst im Ziel schon etwas genauso, wird nichts überschrieben — die
    Datei bleibt liegen und wird gemeldet. Der Ordner gilt dann auch nicht als
    leer, sonst würde der Nutzer ihn mitsamt Inhalt wegwerfen."""
    wurzel = f"{HOME}/Haus C"
    alt, neu = f"{wurzel}/60_Nebenkosten", f"{wurzel}/32_Nebenkosten"
    with TestClient(app) as c:
        _cloud_bereit()
        _objekt(c, "Haus C", wurzel)
        wolke = _Wolke(ordner=[HOME, wurzel, alt, neu],
                       dateien=[f"{alt}/2024.pdf", f"{neu}/2024.pdf"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["geblieben"] == [
            {"objekt": ergebnis["verschoben"][0]["objekt"], "von": alt,
             "namen": ["2024.pdf"]}]
        assert f"{alt}/2024.pdf" in wolke.dateien
        assert ergebnis["leer"] == []


def test_sonstiges_wird_auf_die_oberste_ebene_aufgeloest(monkeypatch):
    """Kein Auffangordner mehr: was drin lag, liegt danach offen im Objekt-
    ordner — im Explorer sofort als unsortiert erkennbar."""
    wurzel = f"{HOME}/Haus D"
    alt = f"{wurzel}/99_Sonstiges"
    beleg = f"{alt}/irgendwas.pdf"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Haus D", wurzel)
        dok = _dokument(slug, beleg)
        wolke = _Wolke(ordner=[HOME, wurzel, alt], dateien=[beleg])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["verschoben"][0]["art"] == "aufgeloest"
        assert _pfad_von(dok) == f"{wurzel}/irgendwas.pdf"
        assert [e["pfad"] for e in ergebnis["leer"]] == [alt]


def test_mieterhoehungen_werden_zum_unterordner(monkeypatch):
    """Ein eigener Hauptordner für einen Fall, den es bei einer von fünf
    Immobilien gibt, ist zu viel — er wird Unterordner der Vermietung. Der
    Elternordner muss dafür notfalls erst entstehen."""
    wurzel = f"{HOME}/Haus E"
    alt = f"{wurzel}/51_Mieterhoehungen"
    with TestClient(app) as c:
        _cloud_bereit()
        _objekt(c, "Haus E", wurzel)
        wolke = _Wolke(ordner=[HOME, wurzel, alt], dateien=[f"{alt}/2023.pdf"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["fehler"] == []
        ziel = f"{wurzel}/30_Vermietung_Verpachtung/Mieterhoehungen"
        assert ziel in wolke.ordner
        assert f"{ziel}/2023.pdf" in wolke.dateien


def test_zweiter_lauf_hat_nichts_mehr_zu_tun(monkeypatch):
    """Ein Umzug, der schon gelaufen ist, findet keine alten Namen mehr — der
    Knopf darf gefahrlos zweimal gedrückt werden."""
    wurzel = f"{HOME}/Haus F"
    with TestClient(app) as c:
        _cloud_bereit()
        _objekt(c, "Haus F", wurzel)
        wolke = _Wolke(ordner=[HOME, wurzel, f"{wurzel}/32_Nebenkosten",
                               f"{wurzel}/70_Steuer_Finanzamt"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        assert c.get("/api/nextcloud/struktur-umzug").json()["ordner"] == 0
        ergebnis = c.post("/api/nextcloud/struktur-umzug").json()
        assert ergebnis["verschoben"] == []
        assert wolke.verschoben == []


def test_jedes_umzugsziel_ist_ein_gueltiger_hauptordner():
    """Wächter: ein Tippfehler in der Umzugstabelle würde einen Ordner
    erfinden, den weder Vorlage noch Anzeige kennen."""
    from app.cloudkern import (STRUKTUR_GRUNDSTUECK, STRUKTUR_MFH,
                               STRUKTUR_WEG, HAUPTORDNER_LESBAR)
    from app.routers.cloud import STRUKTUR_UMZUG

    gueltig = set(STRUKTUR_GRUNDSTUECK + STRUKTUR_WEG + STRUKTUR_MFH)
    for alt, neu in STRUKTUR_UMZUG.items():
        if not neu:
            continue
        haupt = neu.split("/", 1)[0]
        assert haupt in gueltig, f"{alt} zieht nach {haupt} — kein Vorlagenordner"
        assert alt in HAUPTORDNER_LESBAR, f"{alt} hat keine lesbare Beschriftung"
