"""N126 — den SolarEdge-Screenshot auslesen.

Geprüft wird die reine Logik (`app/solaredge.py`) vollständig: Einheiten,
Anteile, fehlende und unsinnige Werte. Der KI-Aufruf selbst lässt sich hier
nicht scharf testen — es gibt keinen Schlüssel in der Testumgebung. Belegt wird
deshalb die Eigenschaft, auf die es ankommt: **er wirft nie**, sondern liefert
ein leeres Ergebnis, damit der Nutzer die vier Werte von Hand eintragen kann.

Beispiel des Nutzers (01.10.24–30.09.25):
Produktion 12,5 MWh — 33 % ins Netz, 44 % ins Gebäude, 23 % zum Speicher.
Verbrauch  10,8 MWh — 24 % vom Netz, 50 % aus PV, 26 % aus dem Speicher.
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import kiauslese, solaredge, strombloecke
from app.db import engine
from app.main import app
from app.models import Dokument, Objekt, Stromjahr

# Die Antwort, wie sie das Modell für den Screenshot des Nutzers liefern soll.
ANTWORT = {
    "produktion_wert": 12.5, "produktion_einheit": "MWh",
    "produktion_netz_prozent": 33, "produktion_gebaeude_prozent": 44,
    "produktion_speicher_prozent": 23,
    "verbrauch_wert": 10.8, "verbrauch_einheit": "MWh",
    "verbrauch_netz_prozent": 24, "verbrauch_pv_prozent": 50,
    "verbrauch_speicher_prozent": 26,
}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


# --------------------------------------------------------------------------
# Einheiten — die Balken sind in MWh beschriftet, gerechnet wird in kWh.
# --------------------------------------------------------------------------

def test_mwh_wird_zu_kwh():
    assert solaredge.nach_kwh(12.5, "MWh") == (12500.0, "")
    assert solaredge.nach_kwh(10.8, "MWh") == (10800.0, "")


def test_kwh_bleibt_kwh():
    assert solaredge.nach_kwh(2416, "kWh") == (2416.0, "")
    # Groß/Klein und Schreibweise der Oberfläche sind egal.
    assert solaredge.nach_kwh("2416", "kwh") == (2416.0, "")


def test_einheit_darf_im_wert_stehen():
    """Manche Antworten packen die Einheit mit in den Wert."""
    kwh, warnung = solaredge.nach_kwh("12.5 MWh")
    assert (kwh, warnung) == (12500.0, "")


def test_ohne_einheit_gilt_kwh_aber_mit_warnung():
    """Angenommen wird kWh — aber der Nutzer wird auf den Faktor 1000
    hingewiesen, statt dass er ihn übersieht."""
    kwh, warnung = solaredge.nach_kwh(10.8, "", "Verbrauch")
    assert kwh == 10.8
    assert "Einheit" in warnung and "MWh" in warnung


def test_deutsche_und_englische_schreibweise():
    assert solaredge.nach_kwh("10,8", "MWh")[0] == 10800.0
    assert solaredge.nach_kwh("10.8", "MWh")[0] == 10800.0
    # Drei Ziffern hinter einem einzelnen Trenner sind ein Tausendertrenner.
    assert solaredge.nach_kwh("10.800", "kWh")[0] == 10800.0
    assert solaredge.nach_kwh("1.234,5", "kWh")[0] == 1234.5


def test_fehlende_menge_bleibt_none():
    assert solaredge.nach_kwh(None, "MWh") == (None, "")
    assert solaredge.nach_kwh("", "MWh") == (None, "")
    assert solaredge.nach_kwh("keine Angabe", "MWh") == (None, "")


def test_negative_menge_ist_keine_messung():
    kwh, warnung = solaredge.nach_kwh(-3.0, "MWh", "Verbrauch")
    assert kwh is None
    assert "negativ" in warnung


def test_einheit_erkennen():
    assert solaredge.einheit("MWh") == "MWh"
    assert solaredge.einheit("12.5 mwh") == "MWh"
    assert solaredge.einheit("kWh") == "kWh"
    assert solaredge.einheit("Wh") == "Wh"
    assert solaredge.einheit("Prozent") == ""
    assert solaredge.einheit(None) == ""


# --------------------------------------------------------------------------
# Anteile
# --------------------------------------------------------------------------

def test_prozent_grenzen():
    assert solaredge.prozent(33) == 33.0
    assert solaredge.prozent("44 %") == 44.0
    assert solaredge.prozent(0) == 0.0
    assert solaredge.prozent(100) == 100.0
    # Über 100 ist kein Anteil, sondern ein Lesefehler.
    assert solaredge.prozent(120) is None
    assert solaredge.prozent(-5) is None
    assert solaredge.prozent("egal") is None
    assert solaredge.prozent(None) is None


def test_anteile_die_aufgehen_geben_keine_warnung():
    assert solaredge.pruefe_anteile(
        "Verbrauch", {"Netz": 24.0, "PV": 50.0, "Speicher": 26.0}) == []


def test_anteile_die_nicht_aufgehen_geben_eine_warnung():
    warnungen = solaredge.pruefe_anteile(
        "Verbrauch", {"Netz": 24.0, "PV": 50.0, "Speicher": 20.0})
    assert len(warnungen) == 1
    assert "94" in warnungen[0] and "100" in warnungen[0]


def test_rundung_bleibt_innerhalb_der_toleranz():
    """SolarEdge rundet auf ganze Prozent — 33,3/33,3/33,3 ist in Ordnung."""
    assert solaredge.pruefe_anteile(
        "Produktion", {"a": 33.3, "b": 33.4, "c": 33.3}) == []


def test_fehlender_anteil_wird_benannt():
    warnungen = solaredge.pruefe_anteile(
        "Verbrauch", {"Netz": 24.0, "PV": None, "Speicher": 26.0})
    assert len(warnungen) == 1
    assert "PV" in warnungen[0]


def test_ganz_fehlender_balken_gibt_keine_warnung():
    """Fehlt der Balken komplett, sagt das schon das leere Ergebnis."""
    assert solaredge.pruefe_anteile(
        "Produktion", {"a": None, "b": None, "c": None}) == []


def test_prozent_zu_kwh():
    anteile = solaredge.kwh_je_anteil(10800.0,
                                      {"netz": 24.0, "pv": 50.0, "speicher": 26.0})
    assert anteile == {"netz": 2592.0, "pv": 5400.0, "speicher": 2808.0}


def test_prozent_zu_kwh_ohne_gesamtmenge():
    assert solaredge.kwh_je_anteil(None, {"netz": 24.0}) == {"netz": None}
    assert solaredge.kwh_je_anteil(10800.0, {"netz": None}) == {"netz": None}


# --------------------------------------------------------------------------
# Aufbereiten — aus der (unsicheren) Modellantwort eine geprüfte Ablesung
# --------------------------------------------------------------------------

def test_aufbereiten_beispiel_des_nutzers():
    a = solaredge.aufbereiten(ANTWORT)
    assert a.erkannt is True
    assert a.warnungen == []
    assert a.verbrauch_kwh == 10800.0
    assert a.produktion_kwh == 12500.0
    assert (a.verbrauch_netz_prozent, a.verbrauch_pv_prozent,
            a.verbrauch_speicher_prozent) == (24.0, 50.0, 26.0)
    assert (a.produktion_netz_prozent, a.produktion_gebaeude_prozent,
            a.produktion_speicher_prozent) == (33.0, 44.0, 23.0)


def test_aufbereiten_liefert_die_kwh_je_anteil():
    d = solaredge.aufbereiten(ANTWORT).als_dict()
    assert d["verbrauch_kwh_je_anteil"] == {"netz": 2592.0, "pv": 5400.0,
                                            "speicher": 2808.0}
    assert d["produktion_kwh_je_anteil"]["netz"] == 4125.0
    assert d["erkannt"] is True


def test_erkannte_werte_passen_zu_den_kostenbloecken():
    """Die Naht zur bestehenden Weiterverarbeitung: aus den erkannten Zahlen
    macht `strombloecke.aus_solaredge` 2592 kWh zugekauft und 8208 kWh eigen."""
    a = solaredge.aufbereiten(ANTWORT)
    extern, eigen, warnungen = strombloecke.aus_solaredge(
        a.verbrauch_kwh, a.verbrauch_netz_prozent, a.verbrauch_pv_prozent,
        a.verbrauch_speicher_prozent)
    assert warnungen == []
    assert extern.kwh == 2592.0
    assert eigen.kwh == 8208.0


def test_aufbereiten_leeres_dict():
    a = solaredge.aufbereiten({})
    assert a.erkannt is False
    assert a.als_dict()["verbrauch_kwh"] is None
    assert a.als_dict()["produktion_kwh"] is None
    # Genau eine Warnung: die Verbrauchszeile fehlt.
    assert len(a.warnungen) == 1
    assert "Hand" in a.warnungen[0]


def test_aufbereiten_text_statt_json():
    """Liefert das Modell Prosa (oder None, oder eine Liste), fällt nichts um."""
    for unfug in ("Auf dem Bild sehe ich einen Balken.", None, [1, 2, 3], 42):
        a = solaredge.aufbereiten(unfug)
        assert a.erkannt is False
        assert a.verbrauch_kwh is None


def test_aufbereiten_prozente_ueber_hundert():
    kaputt = dict(ANTWORT, verbrauch_netz_prozent=240, verbrauch_pv_prozent=500)
    a = solaredge.aufbereiten(kaputt)
    # Unsinnige Anteile werden verworfen, nicht übernommen — und nicht auf 0
    # gesetzt: eine 0 sähe aus wie eine Messung.
    assert a.verbrauch_netz_prozent is None
    assert a.verbrauch_pv_prozent is None
    assert a.verbrauch_speicher_prozent == 26.0
    assert any("Vom Netz" in w for w in a.warnungen), a.warnungen
    # Die Menge selbst bleibt brauchbar.
    assert a.verbrauch_kwh == 10800.0


def test_aufbereiten_nur_verbrauch():
    """Ohne Produktionszeile bleibt der Verbrauch nutzbar."""
    nur_verbrauch = {k: v for k, v in ANTWORT.items() if k.startswith("verbrauch")}
    a = solaredge.aufbereiten(nur_verbrauch)
    assert a.erkannt is True
    assert a.produktion_kwh is None
    assert a.produktion_netz_prozent is None
    assert a.warnungen == []


def test_aufbereiten_alle_felder_null():
    """Das Modell soll bei einem fremden Bild alles auf null setzen."""
    a = solaredge.aufbereiten({k: None for k in ANTWORT})
    assert a.erkannt is False
    assert a.als_dict()["warnungen"]


def test_aufbereiten_nimmt_auch_verschachtelte_antwort():
    a = solaredge.aufbereiten({
        "verbrauch": {"wert": 10.8, "einheit": "MWh", "netz_prozent": 24,
                      "pv_prozent": 50, "speicher_prozent": 26}})
    assert a.verbrauch_kwh == 10800.0
    assert a.verbrauch_netz_prozent == 24.0


def test_aufbereiten_nimmt_auch_fertige_kwh():
    """Nennt das Modell die Menge gleich in kWh, wird sie nicht nochmal
    multipliziert."""
    a = solaredge.aufbereiten({"verbrauch_kwh": 10800, "verbrauch_einheit": "kWh"})
    assert a.verbrauch_kwh == 10800.0


# --------------------------------------------------------------------------
# Bildtyp
# --------------------------------------------------------------------------

def test_medientyp_aus_der_signatur():
    assert solaredge.medientyp(PNG) == "image/png"
    assert solaredge.medientyp(JPEG) == "image/jpeg"
    assert solaredge.medientyp(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


def test_medientyp_signatur_schlaegt_browserangabe():
    """Handys melden gern „application/octet-stream" — der Inhalt entscheidet."""
    assert solaredge.medientyp(PNG, "application/octet-stream") == "image/png"
    assert solaredge.medientyp(JPEG, "image/png") == "image/jpeg"


def test_medientyp_faellt_auf_die_angabe_zurueck():
    assert solaredge.medientyp(b"nichts erkennbar", "image/jpg") == "image/jpeg"
    assert solaredge.medientyp(b"nichts erkennbar", "text/plain") == ""
    assert solaredge.medientyp(b"", "") == ""


def test_erlaubte_typen_laufen_nicht_auseinander():
    """Was hochgeladen werden darf, muss die Bilderkennung auch annehmen."""
    assert set(solaredge.ERLAUBTE_TYPEN) == set(kiauslese.SOLAREDGE_TYPEN)


# --------------------------------------------------------------------------
# Der KI-Aufruf — er wirft nie, er liefert im Zweifel nichts.
# --------------------------------------------------------------------------

def test_ki_ohne_schluessel_liefert_leeres_ergebnis(monkeypatch):
    """Die Eigenschaft, auf die es ankommt: ohne Schlüssel keine Exception,
    sondern ein leeres dict — der Nutzer tippt die vier Werte selbst."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert kiauslese.lies_solaredge(PNG) == {}
    assert kiauslese.lies_solaredge(PNG, "image/png", schluessel="") == {}


def test_ki_ohne_bild_liefert_leeres_ergebnis(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert kiauslese.lies_solaredge(b"") == {}


def test_ki_lehnt_unbekanntes_bildformat_ab(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert kiauslese.lies_solaredge(PNG, "application/pdf") == {}


class _Antwort:
    """Eine gespielte HTTP-Antwort — der Aufruf selbst geht nie ins Netz."""

    def __init__(self, status: int, text: str = "", kaputt: bool = False):
        self.status_code = status
        self._text = text
        self._kaputt = kaputt

    def json(self) -> dict:
        if self._kaputt:
            raise ValueError("kein JSON")
        return {"content": [{"type": "text", "text": self._text}]}


def test_ki_liest_die_felder_aus_der_antwort(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(kiauslese.httpx, "post",
                        lambda *a, **k: _Antwort(200, json.dumps(ANTWORT)))
    assert kiauslese.lies_solaredge(PNG) == ANTWORT


def test_ki_schickt_bild_und_medientyp(monkeypatch):
    """Das Bild geht als base64 mit dem gemeldeten Typ raus — ein JPEG darf
    nicht als PNG angekündigt werden."""
    gesendet: dict = {}

    def _post(url, headers=None, json=None, timeout=None):
        gesendet.update(json or {})
        return _Antwort(200, "{}")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(kiauslese.httpx, "post", _post)
    kiauslese.lies_solaredge(JPEG, "image/jpeg")

    inhalt = gesendet["messages"][0]["content"]
    assert inhalt[0]["source"]["media_type"] == "image/jpeg"
    assert inhalt[0]["source"]["type"] == "base64"
    assert "SolarEdge" in inhalt[1]["text"]


@pytest.mark.parametrize("antwort", [
    _Antwort(500),
    _Antwort(200, "Ich sehe da leider keinen Balken."),
    _Antwort(200, "", kaputt=True),
])
def test_ki_schluckt_jede_kaputte_antwort(monkeypatch, antwort):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(kiauslese.httpx, "post", lambda *a, **k: antwort)
    assert kiauslese.lies_solaredge(PNG) == {}


def test_ki_schluckt_netzwerkfehler(monkeypatch):
    def _kracht(*a, **k):
        raise OSError("kein Netz")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(kiauslese.httpx, "post", _kracht)
    assert kiauslese.lies_solaredge(PNG) == {}


# --------------------------------------------------------------------------
# Der Endpunkt — rein lesend
# --------------------------------------------------------------------------

class _Upload:
    """Ein hochgeladenes Bild, wie FastAPI es dem Endpunkt reicht."""

    def __init__(self, inhalt: bytes, content_type: str = "image/png"):
        self._inhalt = inhalt
        self.content_type = content_type
        self.filename = "solaredge.png"

    async def read(self) -> bytes:
        return self._inhalt


def _lesen(datei, monkeypatch):
    """Den Endpunkt aufrufen — mit einer Sitzung ohne hinterlegten Schlüssel."""
    import asyncio

    from sqlmodel import Session

    from app import db
    from app.routers import solaredge as router

    with Session(db.engine) as s:
        return asyncio.run(router.lesen(datei, session=s))


def test_endpunkt_ohne_ki_bittet_um_handeingabe(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ergebnis = _lesen(_Upload(PNG), monkeypatch)
    assert ergebnis["erkannt"] is False
    assert ergebnis["verbrauch_kwh"] is None
    assert "Hand" in ergebnis["hinweis"]


def test_endpunkt_liest_den_screenshot(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(kiauslese.httpx, "post",
                        lambda *a, **k: _Antwort(200, json.dumps(ANTWORT)))
    ergebnis = _lesen(_Upload(PNG), monkeypatch)
    assert ergebnis["erkannt"] is True
    assert ergebnis["verbrauch_kwh"] == 10800.0
    assert ergebnis["verbrauch_kwh_je_anteil"]["netz"] == 2592.0
    assert ergebnis["hinweis"] == ""
    assert ergebnis["warnungen"] == []


def test_endpunkt_lehnt_leere_und_fremde_dateien_ab(monkeypatch):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as leer:
        _lesen(_Upload(b""), monkeypatch)
    assert leer.value.status_code == 400

    with pytest.raises(HTTPException) as fremd:
        _lesen(_Upload(b"%PDF-1.4 kein Bild", "application/pdf"), monkeypatch)
    assert fremd.value.status_code == 400


def test_endpunkt_lehnt_zu_grosse_bilder_ab(monkeypatch):
    from fastapi import HTTPException

    riesig = PNG + b"\x00" * (5 * 1024 * 1024)
    with pytest.raises(HTTPException) as fehler:
        _lesen(_Upload(riesig), monkeypatch)
    assert fehler.value.status_code == 400
    assert "5 MB" in fehler.value.detail


# --------------------------------------------------------------------------
# N161 — den Screenshot als Beleg in der Nextcloud ablegen.
#
# Die Cloud wird NIE angefasst: ein Doppel schreibt jeden Zugriff mit und kennt
# keinen zerstörerischen (keine `loesche`/`verschiebe`). Ein Löschversuch beim
# Ersetzen fällt so sofort als AttributeError auf.
# --------------------------------------------------------------------------

class _Wolke:
    """Nextcloud-Ersatz für die Ablage — schreibt mit, löscht nie."""

    def __init__(self):
        self.angelegt = []
        self.abgelegt = []          # (pfad, typ)

    def liste(self, pfad):
        return []

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        # N242 — was hier schon abgelegt wurde, LIEGT auch da. Vorher gab diese
        # Attrappe stur `False` zurück und log damit über den Cloud-Zustand:
        # der echte Client macht ein PROPFIND und meldet eine soeben per PUT
        # hochgeladene Datei sehr wohl als vorhanden. Seit `_freier_name` der
        # Live-Auskunft der Cloud vertraut (statt zusätzlich die Datenbank zu
        # fragen), fiele der zweite Screenshot durch die Unwahrheit auf den
        # Namen des ersten zurück — in Wirklichkeit weicht er auf „-2" aus.
        return any(p == pfad for p, _typ in self.abgelegt)

    def lege_ab(self, pfad, inhalt, typ="application/pdf"):
        self.abgelegt.append((pfad, typ))


def _objekt_mit_cloud(c, name, ordner="Home/Immobilien/SE"):
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = ordner
        s.add(o)
        s.commit()
        return slug, o.id


def _stromjahr(objekt_id, jahr):
    with Session(engine) as s:
        return s.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == objekt_id, Stromjahr.jahr == jahr)).first()


def _screenshot(c, slug, jahr=2025, inhalt=PNG, name="solaredge.png",
                typ="image/png"):
    return c.post(f"/api/solaredge/objekte/{slug}/{jahr}/screenshot",
                  files={"datei": (name, inhalt, typ)})


def test_ablage_setzt_screenshot_dokument_id(monkeypatch):
    """Der Screenshot landet als Dokument im Jahresordner unter 60_Nebenkosten,
    und `Stromjahr.screenshot_dokument_id` zeigt darauf."""
    import app.routers.solaredge as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Screenshot 1")
        wolke = _Wolke()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = _screenshot(c, slug, 2025)
        assert antwort.status_code == 200, antwort.text
        d = antwort.json()
        assert d["abgelegt"] is True
        assert d["dokument_id"]
        # Genau einmal abgelegt, im Jahresordner unter 60_Nebenkosten.
        assert len(wolke.abgelegt) == 1
        pfad, typ = wolke.abgelegt[0]
        assert "60_Nebenkosten/2025" in pfad
        assert pfad.endswith(".png")
        assert typ == "image/png"

        # Die Verknüpfung steht am Strom-Jahr.
        sj = _stromjahr(oid, 2025)
        assert sj is not None
        assert sj.screenshot_dokument_id == d["dokument_id"]
        # Das Dokument trägt Kategorie und Jahr.
        with Session(engine) as s:
            dok = s.get(Dokument, d["dokument_id"])
            assert dok.kategorie == "Nebenkosten"
            assert dok.jahr == 2025
            assert dok.pfad.endswith(d["dateiname"])


def test_ohne_verknuepften_ordner_bleiben_die_werte_erhalten(monkeypatch):
    """Ohne verknüpften Nextcloud-Ordner entfällt nur die Ablage — die zuvor
    gespeicherten Strom-Werte bleiben unangetastet, die Cloud wird nie berührt."""
    import app.routers.solaredge as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Screenshot 2"}).json()["slug"]
        with Session(engine) as s:
            oid = s.exec(select(Objekt).where(Objekt.slug == slug)).first().id

        # Werte wie beim „Übernehmen" gespeichert (eigener Strom-PUT).
        c.put(f"/api/objekte/{slug}/strom/2025", json={"netz_kwh": 2592})

        # Ein Zugriff auf die Cloud wäre hier ein Fehler.
        def _nie(session):
            raise AssertionError("verbindung() darf ohne Ordner nicht laufen")
        monkeypatch.setattr(modul, "verbindung", _nie)

        antwort = _screenshot(c, slug, 2025)
        assert antwort.status_code == 200, antwort.text
        d = antwort.json()
        assert d["abgelegt"] is False
        assert d["grund"]

        # Die Werte stehen unverändert, keine Verknüpfung gesetzt.
        werte = c.get(f"/api/objekte/{slug}/strom/2025").json()
        assert werte["netz_kwh"] == 2592
        sj = _stromjahr(oid, 2025)
        assert sj.screenshot_dokument_id is None


def test_ohne_eingerichtete_cloud_kein_fehler(monkeypatch):
    """Ist ein Ordner verknüpft, aber keine Nextcloud eingerichtet, meldet der
    Verbindungsaufbau 400 — die Ablage entfällt ruhig statt zu krachen."""
    import app.routers.solaredge as modul
    from fastapi import HTTPException

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Screenshot 3")

        def _keine(session):
            raise HTTPException(400, "Nextcloud ist noch nicht eingerichtet")
        monkeypatch.setattr(modul, "verbindung", _keine)

        antwort = _screenshot(c, slug, 2025)
        assert antwort.status_code == 200
        d = antwort.json()
        assert d["abgelegt"] is False
        assert "eingerichtet" in d["grund"]
        assert _stromjahr(oid, 2025) is None or \
            _stromjahr(oid, 2025).screenshot_dokument_id is None


def test_zweiter_screenshot_ersetzt_die_verknuepfung_ohne_zu_loeschen(monkeypatch):
    """Ein zweiter Screenshot bekommt einen eigenen (freien) Namen, die
    Verknüpfung zeigt auf den neuen — der alte Eintrag und die alte Datei
    bleiben. Gelöscht wird nichts (die Cloud kennt kein `loesche`)."""
    import app.routers.solaredge as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Screenshot 4")
        wolke = _Wolke()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        erste = _screenshot(c, slug, 2025).json()
        zweite = _screenshot(c, slug, 2025, name="neu.png").json()

        assert erste["abgelegt"] and zweite["abgelegt"]
        # Zwei verschiedene Dokumente, zwei verschiedene Ablagen (freier Name).
        assert erste["dokument_id"] != zweite["dokument_id"]
        assert erste["pfad"] != zweite["pfad"]
        assert len(wolke.abgelegt) == 2

        # Der alte Eintrag steht noch (nichts gelöscht) …
        with Session(engine) as s:
            assert s.get(Dokument, erste["dokument_id"]) is not None
            assert s.get(Dokument, zweite["dokument_id"]) is not None
        # … die Verknüpfung zeigt jetzt auf den neuen.
        assert _stromjahr(oid, 2025).screenshot_dokument_id == zweite["dokument_id"]


def test_ablage_lehnt_nicht_bilder_ab(monkeypatch):
    """Was kein Bild ist, wird nicht abgelegt (400) — wie beim Lesen."""
    import app.routers.solaredge as modul

    with TestClient(app) as c:
        slug, _ = _objekt_mit_cloud(c, "Screenshot 5")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = _screenshot(c, slug, 2025, inhalt=b"%PDF-1.4 kein Bild",
                              name="x.pdf", typ="application/pdf")
        assert antwort.status_code == 400
