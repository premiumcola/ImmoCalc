"""Ordnernamen von grob nach fein — Vorlagen und der Umzug bestehender Ordner."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_bezeichnung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.bezeichnung import (STANDARD_VORLAGE, anzeigename,  # noqa: E402
                             doppelt_geschachtelt, hierarchie, nach_vorlage,
                             ordnername, ordnerpfad, vorlage_pruefen)


def test_anzeigename_von_grob_nach_fein():
    assert anzeigename("Wohnung 1. OG", ort="Unterschöllenbach",
                       strasse="Hauptstr. 6a") \
        == "Unterschöllenbach · Hauptstr. 6a · Wohnung 1. OG"


def test_keine_doppelungen():
    """Steht der Ort schon in der Bezeichnung, nicht zweimal nennen."""
    assert anzeigename("Eschenau - Laufer Str. 5", ort="Eschenau") \
        == "Eschenau - Laufer Str. 5"


def test_ordnername_folgt_dem_bestand():
    assert ordnername("Wohnung 1. OG", ort="Eschenau", strasse="Laufer Str. 5") \
        == "Eschenau - Laufer Str. 5 - Wohnung 1. OG"


def test_vorlage_mit_klammern():
    ergebnis = nach_vorlage("({ort}) {strasse} · {name}",
                            ort="Unterschöllenbach", strasse="Hauptstr. 6a",
                            name="Wohnung 1. OG")
    assert ergebnis == "(Unterschöllenbach) Hauptstr. 6a · Wohnung 1. OG"


def test_prozent_schreibweise():
    """Die Kurzform %ort funktioniert genauso wie {ort}."""
    assert nach_vorlage("(%ORT) %strasse", ort="Nürnberg",
                        strasse="Klausner Winkel 12") \
        == "(Nürnberg) Klausner Winkel 12"


def test_schraegstrich_wird_entfernt():
    """// wäre ein Pfadtrenner und darf nie im Ordnernamen landen."""
    ergebnis = nach_vorlage("({ort}) {strasse} // {name}", ort="Eschenau",
                            strasse="Laufer Str. 5", name="Wohnung 1. OG")
    assert "/" not in ergebnis
    assert ergebnis.startswith("(Eschenau) Laufer Str. 5")
    assert ergebnis.endswith("Wohnung 1. OG")


def test_leere_felder_lassen_keine_reste():
    """Ohne Ort darf kein leeres Klammerpaar stehenbleiben."""
    assert nach_vorlage(STANDARD_VORLAGE, ort="", strasse="Hauptstr. 6a",
                        name="Wohnung 1. OG") == "Hauptstr. 6a · Wohnung 1. OG"
    assert nach_vorlage(STANDARD_VORLAGE, ort="", strasse="", name="Garage") \
        == "Garage"


def test_anzeigename_nennt_die_strasse_nur_einmal():
    """Enthält der Name die Straße bereits, darf sie nicht angehängt werden."""
    assert anzeigename("(Teststadt) Prüfweg 5 · EG", ort="Teststadt",
                       strasse="Prüfweg 5") == "(Teststadt) Prüfweg 5 · EG"


def test_hierarchie_drei_ebenen():
    h = hierarchie("Wohnung 1. OG", ort="Eschenau", strasse="Laufer Str. 5")
    assert (h["ort"], h["strasse"], h["einheit"]) \
        == ("Eschenau", "Laufer Str. 5", "Wohnung 1. OG")


def test_hierarchie_liest_ort_aus_der_klammer():
    h = hierarchie("(Teststadt) Prüfweg 5 · EG", strasse="Prüfweg 5")
    assert (h["ort"], h["strasse"], h["einheit"]) \
        == ("Teststadt", "Prüfweg 5", "EG")


def test_hierarchie_ignoriert_nutzung_im_ortsfeld():
    """Im Bestand steht in `ort` teils die Nutzung — das ist kein Ort."""
    h = hierarchie("Musterstraße 5", ort="Mixed-Use · 7 Einheiten")
    assert h["ort"] == ""
    assert h["strasse"] == "Musterstraße 5"
    assert h["einheit"] == ""


def test_hierarchie_trennt_ort_von_der_zusatzangabe():
    h = hierarchie("Beispielweg 6a", ort="Musterstadt · 1 Wohnung")
    assert (h["ort"], h["strasse"]) == ("Musterstadt", "Beispielweg 6a")


def test_hierarchie_ohne_strasse_ruecken_einheiten_auf():
    """Keine Straße erkennbar: der Name selbst ist die mittlere Ebene."""
    h = hierarchie("Garage", ort="Nürnberg")
    assert (h["ort"], h["strasse"], h["einheit"]) == ("Nürnberg", "Garage", "")


def test_vorlage_pruefen_meldet_probleme():
    assert vorlage_pruefen("") == ["Die Vorlage ist leer."]
    assert any("Platzhalter" in h for h in vorlage_pruefen("Immobilie"))
    assert any("nicht erlaubt" in h for h in vorlage_pruefen("{ort}/{name}"))
    assert any("Unbekannte" in h for h in vorlage_pruefen("{quatsch} {ort}"))
    assert vorlage_pruefen(STANDARD_VORLAGE) == []


# --------------------------------------------------------------------------
# CXX: der Objektordner steht nicht ein zweites Mal unter sich selbst
# --------------------------------------------------------------------------

def test_ordnerpfad_haengt_den_namen_nur_einmal_an():
    assert ordnerpfad("/[010]_Immobilien", "(Eschenau) Laufer Str. 5") \
        == "[010]_Immobilien/(Eschenau) Laufer Str. 5"


def test_ordnerpfad_verdoppelt_den_ordner_nicht():
    """Zeigt der Home-Ordner schon auf den Objektordner, ist er das Ziel.

    Sonst entstand "(Eschenau) Laufer Str. 5/(Eschenau) Laufer Str. 5" —
    doppelt gemoppelt ohne Mehrwert."""
    home = "/[010]_Immobilien/(Eschenau) Laufer Str. 5"
    assert ordnerpfad(home, "(Eschenau) Laufer Str. 5") \
        == "[010]_Immobilien/(Eschenau) Laufer Str. 5"
    # Schreibweise ist dabei egal
    assert ordnerpfad("/Haus/Wohnung 1.OG", "Wohnung 1. OG") == "Haus/Wohnung 1.OG"


def test_doppelt_geschachtelt_erkennt_den_zwilling():
    assert doppelt_geschachtelt("/a/X/X") is True
    assert doppelt_geschachtelt("/a/Wohnung 1.OG/Wohnung 1. OG") is True
    assert doppelt_geschachtelt("/a/X/Y") is False
    assert doppelt_geschachtelt("/X") is False


# --------------------------------------------------------------------------
# CXIX: das Benennungsschema für alle Immobilien nachziehen
# --------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.cloud as cloud_modul  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Einstellung, Objekt  # noqa: E402
from app.nextcloud import NextcloudFehler  # noqa: E402

HOME = "/[010]_Immobilien"
NEU = f"{HOME}/(Eschenau) Laufer Str. 5"


def _norm(pfad: str) -> str:
    return "/" + "/".join(t for t in (pfad or "").split("/") if t)


class _Wolke:
    """Nextcloud-Ersatz: der Ordnerbaum als Menge von Pfaden.

    `stolpert_bei` lässt genau einen MOVE scheitern — dann darf sich in der
    Datenbank nichts bewegen, und der Rest muss trotzdem umziehen."""

    def __init__(self, ordner=(), dateien=(), stolpert_bei=""):
        self.ordner = {_norm(p) for p in ordner}
        self.dateien = {_norm(p) for p in dateien}
        self.verschoben: list[tuple[str, str]] = []
        self.stolpert_bei = stolpert_bei

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

    def ordner_baum_anlegen(self, wurzel: str, unterordner) -> list[str]:
        neu = [_norm(wurzel)] if self.ordner_anlegen(wurzel) else []
        return neu + [f"{_norm(wurzel)}/{u}" for u in unterordner
                      if self.ordner_anlegen(f"{_norm(wurzel)}/{u}")]

    def verschiebe(self, von: str, nach: str) -> None:
        von, nach = _norm(von), _norm(nach)
        if self.stolpert_bei and self.stolpert_bei in von:
            raise NextcloudFehler(f"Verschieben fehlgeschlagen: {von}")
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
        eintrag = s.get(Einstellung, schluessel)
        if eintrag:
            eintrag.wert = wert
        else:
            eintrag = Einstellung(schluessel=schluessel, wert=wert)
        s.add(eintrag)
        s.commit()


def _cloud_bereit(vorlage: str = "({ort}) {strasse}") -> None:
    """Verbindung und Vorlage so, wie der Nutzer sie eingestellt hat.

    Alle Immobilien früherer Tests werden dabei von ihrem Ordner gelöst — sie
    teilen sich eine Datenbank, und der Umzug geht bewusst über alle."""
    for schluessel, wert in (("nc_url", "https://wolke.example"),
                             ("nc_benutzer", "roman"), ("nc_passwort", "geheim"),
                             ("nc_home", HOME), ("nc_ordner_vorlage", vorlage)):
        _einstellung(schluessel, wert)
    with Session(engine) as s:
        for o in s.exec(select(Objekt)).all():
            o.nc_ordner = ""
            s.add(o)
        s.commit()


def _objekt(c, name: str, ort: str, strasse: str, ordner: str) -> str:
    slug = c.post("/api/objekte", json={"name": name, "ort": ort,
                                        "strasse": strasse}).json()["slug"]
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


def _ordner_von(slug: str) -> str:
    with Session(engine) as s:
        return s.exec(select(Objekt).where(Objekt.slug == slug)).first().nc_ordner


def test_trockenlauf_erkennt_den_doppelten_ordner(monkeypatch):
    """CXX/CXIX: "X/X" wird als Schachtelung erkannt, nicht als Umbenennung.

    Der Trockenlauf zeigt alt → neu, je Ordner und je Beleg — und ändert
    nichts: weder in der Cloud noch in der Datenbank."""
    innen = f"{NEU}/(Eschenau) Laufer Str. 5"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", innen)
        beleg = _dokument(slug, f"{innen}/60_Nebenkosten/2024_Nebenkosten_Wasser.pdf")
        wolke = _Wolke(ordner=[HOME, NEU, innen, f"{innen}/60_Nebenkosten",
                               f"{HOME}/Wohnung 1.OG"],
                       dateien=[f"{innen}/60_Nebenkosten/2024_Nebenkosten_Wasser.pdf"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        plan = c.get("/api/nextcloud/umzug").json()
        schritt = next(s for s in plan["schritte"] if s["objekt"] == slug)
        assert schritt["art"] == "entschachteln"
        assert (schritt["von"], schritt["nach"]) == (innen, NEU)
        assert schritt["dokumente"] == [{
            "id": beleg, "dateiname": "2024_Nebenkosten_Wasser.pdf",
            "von": f"{innen}/60_Nebenkosten/2024_Nebenkosten_Wasser.pdf",
            "nach": f"{NEU}/60_Nebenkosten/2024_Nebenkosten_Wasser.pdf"}]
        # Der Rest aus der alten Benennung wird genannt, aber nicht angefasst
        assert f"{HOME}/Wohnung 1.OG" in plan["verwaist"]
        # Trockenlauf heißt: nichts bewegt sich
        assert wolke.verschoben == []
        assert _pfad_von(beleg).startswith(innen)
        assert _ordner_von(slug) == innen


def test_umzug_zieht_die_belege_mit(monkeypatch):
    """CXIX: die alte Benennung wandert auf die neue — samt Dokumentpfaden.

    Ohne das Nachziehen zeigten alle Scans ins Leere: der Pfad ist eindeutig
    indiziert, die Datei läge längst woanders."""
    alt = f"{HOME}/Wohnung 1.OG"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", alt)
        beleg = _dokument(slug, f"{alt}/60_Nebenkosten/2024_Nebenkosten_Strom.pdf")
        wolke = _Wolke(ordner=[HOME, alt, f"{alt}/60_Nebenkosten"],
                       dateien=[f"{alt}/60_Nebenkosten/2024_Nebenkosten_Strom.pdf"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        plan = c.get("/api/nextcloud/umzug").json()
        assert next(s for s in plan["schritte"]
                    if s["objekt"] == slug)["art"] == "verschieben"

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert ergebnis["fehler"] == []
        assert (alt, NEU) in wolke.verschoben
        assert _ordner_von(slug) == NEU
        assert _pfad_von(beleg) == f"{NEU}/60_Nebenkosten/2024_Nebenkosten_Strom.pdf"
        assert wolke.existiert(_pfad_von(beleg))

        # Ein zweiter Lauf hat nichts mehr zu tun
        assert c.post("/api/nextcloud/umzug").json()["anzahl"] == 0


def test_umzug_hebt_den_doppelten_ordner_auf(monkeypatch):
    """CXX: der Inhalt wandert eine Ebene höher, der leere Ordner bleibt stehen —
    gelöscht wird in der Nextcloud nichts."""
    innen = f"{NEU}/(Eschenau) Laufer Str. 5"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", innen)
        beleg = _dokument(slug, f"{innen}/60_Nebenkosten/2024_Nebenkosten_Muell.pdf")
        wolke = _Wolke(ordner=[HOME, NEU, innen, f"{innen}/60_Nebenkosten"],
                       dateien=[f"{innen}/60_Nebenkosten/2024_Nebenkosten_Muell.pdf"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert ergebnis["fehler"] == []
        assert _ordner_von(slug) == NEU
        assert _pfad_von(beleg) == f"{NEU}/60_Nebenkosten/2024_Nebenkosten_Muell.pdf"
        assert wolke.existiert(f"{NEU}/60_Nebenkosten")
        assert innen in wolke.ordner          # der leere Ordner bleibt liegen


def test_lose_datei_im_objektordner_zieht_mit_um(monkeypatch):
    """CL: eine Datei direkt im Objektordner ist beim Entschachteln selbst ein
    Kind — sie wandert einzeln.

    Vorher wurde nur "alles unterhalb" umgeschrieben: die Datei lag danach eine
    Ebene höher, ihr `Dokument.pfad` zeigte weiter auf den alten Platz — und
    gezählt wurde sie auch nicht, der Nutzer las "0 Belege"."""
    # Eigene Adresse: die Ordner der anderen Tests teilen sich eine Datenbank,
    # und der Umzug geht über die Pfade, nicht über die Objekt-id.
    oben = f"{HOME}/(Losdorf) Loseweg 9"
    innen = f"{oben}/(Losdorf) Loseweg 9"
    lose_datei = f"{innen}/2024_Rechnung_Hausmeister.pdf"
    tiefe_datei = f"{innen}/60_Nebenkosten/2024_Nebenkosten_Lose.pdf"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Erdgeschoss", "Losdorf", "Loseweg 9", innen)
        lose = _dokument(slug, lose_datei)
        tief = _dokument(slug, tiefe_datei)
        wolke = _Wolke(ordner=[HOME, oben, innen, f"{innen}/60_Nebenkosten"],
                       dateien=[lose_datei, tiefe_datei])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        plan = c.get("/api/nextcloud/umzug").json()
        assert plan["dokumente"] == 2

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert ergebnis["fehler"] == []
        assert _pfad_von(lose) == f"{oben}/2024_Rechnung_Hausmeister.pdf"
        assert _pfad_von(tief) == f"{oben}/60_Nebenkosten/2024_Nebenkosten_Lose.pdf"
        # Beide Einträge zeigen auf eine Datei, die es wirklich gibt
        assert wolke.existiert(_pfad_von(lose))
        assert wolke.existiert(_pfad_von(tief))
        # und beide sind gezählt
        zeile = next(z for z in ergebnis["verschoben"] if z["objekt"] == slug)
        assert zeile["dokumente"] == 2
        assert ergebnis["dokumente"] == 2


def test_gescheiterter_move_laesst_die_datenbank_in_ruhe(monkeypatch):
    """CXIX: ein Ordner, der sich nicht verschieben lässt, hält den Rest nicht
    auf — und sein Dokumentpfad bleibt genau da, wo die Datei wirklich liegt."""
    stolper = f"{HOME}/Wohnung 1.OG"
    zweiter = f"{HOME}/Garage alt"
    with TestClient(app) as c:
        _cloud_bereit()
        eins = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", stolper)
        zwei = _objekt(c, "Garage", "Nürnberg", "Klausner Winkel 12", zweiter)
        beleg = _dokument(eins, f"{stolper}/60_Nebenkosten/2024_Nebenkosten_Gas.pdf")
        beleg2 = _dokument(zwei, f"{zweiter}/60_Nebenkosten/2024_Nebenkosten_Gas.pdf")
        wolke = _Wolke(
            ordner=[HOME, stolper, f"{stolper}/60_Nebenkosten",
                    zweiter, f"{zweiter}/60_Nebenkosten"],
            dateien=[f"{stolper}/60_Nebenkosten/2024_Nebenkosten_Gas.pdf",
                     f"{zweiter}/60_Nebenkosten/2024_Nebenkosten_Gas.pdf"],
            stolpert_bei="Wohnung 1.OG")
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert [f["objekt"] for f in ergebnis["fehler"]] == [eins]
        assert "fehlgeschlagen" in ergebnis["fehler"][0]["fehler"]

        # Der gescheiterte bleibt unverändert — Eintrag wie Pfad
        assert _ordner_von(eins) == stolper
        assert _pfad_von(beleg) == f"{stolper}/60_Nebenkosten/2024_Nebenkosten_Gas.pdf"
        # Der andere ist trotzdem umgezogen
        assert _ordner_von(zwei) == f"{HOME}/(Nürnberg) Klausner Winkel 12"
        assert _pfad_von(beleg2) == (f"{HOME}/(Nürnberg) Klausner Winkel 12"
                                     "/60_Nebenkosten/2024_Nebenkosten_Gas.pdf")


def test_haelt_ein_unterordner_nicht_mit_bleibt_sein_beleg_stehen(monkeypatch):
    """CXIX: was schon oben liegt, behält den neuen Pfad; was hängenblieb, den
    alten. Jeder Pfad zeigt auf die Datei, die wirklich dort liegt."""
    innen = f"{NEU}/(Eschenau) Laufer Str. 5"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", innen)
        mit = _dokument(slug, f"{innen}/60_Nebenkosten/2024_Nebenkosten_Kabel.pdf")
        ohne = _dokument(slug, f"{innen}/70_Steuer_Finanzamt/2024_Steuer_Kabel.pdf")
        wolke = _Wolke(
            ordner=[HOME, NEU, innen, f"{innen}/60_Nebenkosten",
                    f"{innen}/70_Steuer_Finanzamt"],
            dateien=[f"{innen}/60_Nebenkosten/2024_Nebenkosten_Kabel.pdf",
                     f"{innen}/70_Steuer_Finanzamt/2024_Steuer_Kabel.pdf"],
            stolpert_bei="70_Steuer_Finanzamt")
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert [f["objekt"] for f in ergebnis["fehler"]] == [slug]
        assert _pfad_von(mit) == f"{NEU}/60_Nebenkosten/2024_Nebenkosten_Kabel.pdf"
        assert _pfad_von(ohne) == f"{innen}/70_Steuer_Finanzamt/2024_Steuer_Kabel.pdf"
        # Der Ordner bleibt verknüpft, wie er war — der Umzug ist nicht fertig
        assert _ordner_von(slug) == innen
        assert wolke.existiert(_pfad_von(mit)) and wolke.existiert(_pfad_von(ohne))


def test_belegter_zielname_wird_umgangen(monkeypatch):
    """Nie überschreiben: liegt der Zielname schon da, weicht der Umzug aus."""
    alt = f"{HOME}/Wohnung 1.OG"
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", alt)
        # Ein fremder Ordner trägt den Zielnamen bereits
        wolke = _Wolke(ordner=[HOME, alt, NEU])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/nextcloud/umzug").json()
        assert ergebnis["fehler"] == []
        assert _ordner_von(slug) == f"{NEU}-2"
        assert NEU in wolke.ordner            # der fremde Ordner bleibt


def test_neue_vorlage_meldet_wie_viel_nachzuziehen_waere(monkeypatch):
    """CXIX: die Vorlage zu ändern verschiebt nichts — sie sagt aber, wie viele
    Ordner noch auf die neue Benennung warten."""
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5",
                       f"{HOME}/Wohnung 1.OG")
        wolke = _Wolke(ordner=[HOME, f"{HOME}/Wohnung 1.OG"])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        antwort = c.post("/api/nextcloud/vorlage",
                         json={"vorlage": "({ort}) {strasse}"}).json()
        assert antwort["umzug_noetig"] == 1
        # gesagt ist nicht getan: der Ordner steht unverändert da
        assert wolke.verschoben == []
        assert _ordner_von(slug) == f"{HOME}/Wohnung 1.OG"


def test_der_wachdienst_zieht_nie_selbst_um():
    """Umgezogen wird nur auf Knopfdruck — echte Unterlagen wandern nicht
    nebenbei alle 15 Minuten."""
    import inspect

    from app import wachdienst
    assert "umzug" not in inspect.getsource(wachdienst).lower()


def test_home_ordner_darf_kein_objektordner_sein(monkeypatch):
    """CXX an der Wurzel: wäre der Objektordner die Heimat, entstünde er
    darunter gleich noch einmal."""
    with TestClient(app) as c:
        _cloud_bereit()
        _objekt(c, "Heimatweg 1", "Fürth", "Heimatweg 1", NEU)
        wolke = _Wolke(ordner=[HOME, NEU])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        antwort = c.post("/api/nextcloud/home", json={"pfad": NEU})
        assert antwort.status_code == 400
        assert "übergeordneten" in antwort.json()["detail"]


def test_struktur_legt_den_ordner_nicht_unter_sich_selbst_an(monkeypatch):
    """CXX: steht die Heimat schon auf dem Objektordner, wird er nicht ein
    zweites Mal darunter angelegt."""
    with TestClient(app) as c:
        _cloud_bereit()
        slug = _objekt(c, "Wohnung 1.OG", "Eschenau", "Laufer Str. 5", "")
        _einstellung("nc_home", NEU)          # Heimat zeigt auf den Objektordner
        wolke = _Wolke(ordner=[HOME, NEU])
        monkeypatch.setattr(cloud_modul, "verbindung", lambda session: wolke)

        antwort = c.post(f"/api/nextcloud/objekte/{slug}/struktur")
        assert antwort.status_code == 200
        assert antwort.json()["ordner"] == NEU
        assert f"{NEU}/(Eschenau) Laufer Str. 5" not in wolke.ordner
        _einstellung("nc_home", HOME)


# --------------------------------------------------------------------------
# CXXII/CXXIII: Dateinamen — Datum vorn, Sache in der Mitte, Betrag hinten
# --------------------------------------------------------------------------

def test_ordnerwort_faellt_aus_der_bezeichnung():
    """CXXII: was der Ordner sagt, sagt der Dateiname nicht noch einmal."""
    from app.bezeichnung import ohne_ordnerwort

    assert ohne_ordnerwort("Nebenkosten Heizkosten", "Nebenkosten") \
        == "Heizkosten"
    # auch im Kompositum — der Rest des Wortes bleibt stehen
    assert ohne_ordnerwort("Nebenkostenabrechnung", "Nebenkosten") \
        == "Abrechnung"
    # aber nie mitten im Wort: „Grundsteuerbescheid" ist kein „Grundbescheid"
    assert ohne_ordnerwort("Grundsteuerbescheid", "Steuer") \
        == "Grundsteuerbescheid"
    # bleibt nichts übrig, kommt nichts zurück
    assert ohne_ordnerwort("Sonstiges", "Sonstiges") == ""


def test_betrag_wird_geschrieben_wie_der_nutzer_ihn_schreibt():
    """Deutsches Komma, Euro-Zeichen, kein Tausenderpunkt — so steht er in
    seinen eigenen Ordnern („2025_Muell_256,36€.pdf")."""
    from app.bezeichnung import betragsteil

    assert betragsteil(256.36) == "256,36€"
    assert betragsteil(2729.9) == "2729,90€"
    # kein zweiter Punkt im Namen: der machte die Endung mehrdeutig
    assert betragsteil(12345.67) == "12345,67€"
    assert betragsteil(None) == ""
    assert betragsteil(0) == ""
    assert betragsteil(-12.5) == ""


def test_datumsteil_sortiert_sich_von_selbst():
    from app.bezeichnung import datumsteil

    assert datumsteil(2026, 3) == "2026-03"
    assert datumsteil(2026) == "2026"
    assert datumsteil(2026, 13) == "2026"        # Unsinn wird verschwiegen
    assert datumsteil(None) == "ohne-Jahr"


def test_datum_und_betrag_aus_echten_dateinamen():
    """Die Beispiele stammen aus dem Bestand des Nutzers."""
    from app.bezeichnung import (betrag_aus_namen, datum_aus_namen,
                                 ohne_betrag, ohne_datum)

    assert datum_aus_namen("2025-10-oel-2729,91€.pdf") == (2025, 10)
    assert datum_aus_namen("2021.09_PROKON_Strom_999,53€.pdf") == (2021, 9)
    # „20230915" ist eine Zahl, kein Datum
    assert datum_aus_namen("2023.09_Ablesung_20230915_666.pdf") == (2023, 9)

    assert betrag_aus_namen("Öl-suft-2025-(2895,27€).pdf") == 2895.27
    assert betrag_aus_namen("Rechnung 1.071,00 € gesamt") == 1071.00
    assert betrag_aus_namen("kein Geld hier") is None

    # Beide fallen aus der Bezeichnung heraus, weil sie neu gesetzt werden
    assert ohne_betrag("DeltaT-2023-(200,75€)") == "DeltaT-2023"
    assert ohne_datum("DeltaT-2023") == "DeltaT"
