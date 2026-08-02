"""N84 — die interne Wissens-Datenbank der ausgelesenen Belegdaten.

Zwei Ebenen: die reinen Funktionen (`app.kidb` — bauen, additiv mischen,
suchen) und die Endpunkte (`/api/kidb/…` — übernehmen, lesen, suchen,
entfernen).

Der wichtigste Nachweis steht in `test_uebernahme_fragt_nie_die_ki`: die
Übernahme arbeitet ausschliesslich mit dem, was schon in der Datenbank steht.
Kein Anthropic-Aufruf, kein Laden einer Datei aus der Cloud — das kostet
Tokens und ist ausdrücklich nicht gewollt.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_kidb.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import kidb  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Belegdaten, Dokument, Objekt  # noqa: E402


def _beleg(**abweichung) -> SimpleNamespace:
    """Ein Dokument-artiges Objekt — die Funktionen in `kidb` sind rein und
    brauchen dafür keine Datenbank."""
    daten = dict(
        id=7, objekt_id=3, jahr=2024, kategorie="Nebenkosten",
        kostenart="Wasser", betrag=1420.55, belegdatum=date(2024, 3, 14),
        pfad="/[010]_Immobilien/Tauchersreuther Str. 5/60_Nebenkosten/x.pdf",
        dateiname="2024-03_NK-Wasser.pdf",
        ki_einordnung="Jahresrechnung des Zweckverbands für Wasser 2024.",
        ki_felder={"absender": "Zweckverband Wasserversorgung",
                   "verbrauch_m3": 142.577},
        ki_immobilie="Tauchersreuther Str. 5", ki_einheit="1. OG")
    daten.update(abweichung)
    return SimpleNamespace(**daten)


# --------------------------------------------------------------------------
# 1) falte / ist_leer — die Kleinteile
# --------------------------------------------------------------------------

def test_falte_ist_umlaut_und_schreibweisen_tolerant():
    assert kidb.falte("Zählerablesung") == "zaehlerablesung"
    assert kidb.falte("ZAEHLERABLESUNG") == "zaehlerablesung"
    assert kidb.falte("Müllabfuhr") == kidb.falte("Muellabfuhr")
    assert kidb.falte("Straße") == "strasse"
    assert kidb.falte(None) == ""
    assert kidb.falte(2024) == "2024"


def test_ist_leer_kennt_nichts_aber_nicht_die_null():
    assert kidb.ist_leer(None)
    assert kidb.ist_leer("")
    assert kidb.ist_leer("   ")
    assert kidb.ist_leer({})
    assert kidb.ist_leer([])
    # Eine echte Null ist eine Aussage, kein „noch nichts erfasst".
    assert not kidb.ist_leer(0)
    assert not kidb.ist_leer(0.0)
    assert not kidb.ist_leer(False)


# --------------------------------------------------------------------------
# 2) aus_dokument — der Datensatz aus dem, was schon gespeichert ist
# --------------------------------------------------------------------------

def test_aus_dokument_uebernimmt_die_gespeicherten_ki_daten():
    satz = kidb.aus_dokument(_beleg(), heute=date(2026, 8, 2))
    assert satz["dokument_id"] == 7
    assert satz["objekt_id"] == 3
    assert satz["jahr"] == 2024
    assert satz["kategorie"] == "Nebenkosten"
    assert satz["kostenart"] == "Wasser"
    assert satz["betrag"] == 1420.55
    assert satz["belegdatum"] == date(2024, 3, 14)
    assert satz["zusammenfassung"].startswith("Jahresrechnung des Zweckverbands")
    # Der Aussteller kommt aus dem KI-Raster (`anbieter`, sonst `absender`).
    assert satz["anbieter"] == "Zweckverband Wasserversorgung"
    assert satz["dateiname"] == "2024-03_NK-Wasser.pdf"
    assert satz["pfad"].endswith("/60_Nebenkosten/x.pdf")
    assert satz["quelle"] == "ki"
    assert satz["erfasst_am"] == date(2026, 8, 2)
    # Alle Modellfelder sind belegt — kein Feld fällt still unter den Tisch.
    assert set(satz) == set(kidb.FELDER)


def test_aus_dokument_haengt_immobilie_und_einheit_additiv_an_die_felder():
    satz = kidb.aus_dokument(_beleg())
    assert satz["felder"]["verbrauch_m3"] == 142.577
    assert satz["felder"]["immobilie"] == "Tauchersreuther Str. 5"
    assert satz["felder"]["einheit"] == "1. OG"
    # Ein gleichnamiger Wert aus dem KI-Raster behält Vorrang (setdefault).
    eigen = kidb.aus_dokument(_beleg(
        ki_felder={"einheit": "EG links"}, ki_einheit="1. OG"))
    assert eigen["felder"]["einheit"] == "EG links"


def test_aus_dokument_ohne_ki_bleibt_brauchbar():
    satz = kidb.aus_dokument(_beleg(ki_einordnung="", ki_felder={},
                                    ki_immobilie="", ki_einheit=""))
    assert satz["quelle"] == "regel"
    assert satz["zusammenfassung"] == ""
    assert satz["anbieter"] == ""
    # Was ohne KI feststeht, steht trotzdem drin.
    assert satz["kostenart"] == "Wasser"
    assert satz["betrag"] == 1420.55
    assert satz["pfad"].endswith("x.pdf")


def test_hat_ki_erkennt_jede_spur_einer_auslese():
    assert kidb.hat_ki(_beleg())
    assert not kidb.hat_ki(_beleg(ki_einordnung="", ki_felder={},
                                  ki_immobilie="", ki_einheit=""))
    assert kidb.hat_ki(_beleg(ki_einordnung="", ki_felder={"x": 1},
                              ki_immobilie="", ki_einheit=""))
    assert kidb.hat_ki(_beleg(ki_einordnung="", ki_felder={},
                              ki_immobilie="Haus 5", ki_einheit=""))


# --------------------------------------------------------------------------
# 3) zusammenfuehren — additiv: leer überschreibt nie gefüllt
# --------------------------------------------------------------------------

def test_zusammenfuehren_leere_werte_ueberschreiben_keine_gefuellten():
    vorhanden = {"anbieter": "Zweckverband", "kostenart": "Wasser",
                 "betrag": 1420.55, "zusammenfassung": "Von Hand ergänzt."}
    neu = {"anbieter": "", "kostenart": None, "betrag": None,
           "zusammenfassung": "   "}
    zusammen = kidb.zusammenfuehren(vorhanden, neu)
    assert zusammen["anbieter"] == "Zweckverband"
    assert zusammen["kostenart"] == "Wasser"
    assert zusammen["betrag"] == 1420.55
    assert zusammen["zusammenfassung"] == "Von Hand ergänzt."


def test_zusammenfuehren_ergaenzt_was_noch_fehlt():
    vorhanden = {"anbieter": "", "kostenart": "Wasser"}
    neu = {"anbieter": "Zweckverband", "kostenart": "Wasser/Abwasser",
           "jahr": 2024}
    zusammen = kidb.zusammenfuehren(vorhanden, neu)
    assert zusammen["anbieter"] == "Zweckverband"   # leer -> gefüllt
    assert zusammen["kostenart"] == "Wasser/Abwasser"  # gefüllt -> neu gefüllt
    assert zusammen["jahr"] == 2024                # ganz neues Feld


def test_zusammenfuehren_mischt_die_felder_statt_sie_zu_ersetzen():
    vorhanden = {"felder": {"absender": "Zweckverband", "police_nr": "4711"}}
    neu = {"felder": {"absender": "", "verbrauch_m3": 142.577}}
    zusammen = kidb.zusammenfuehren(vorhanden, neu)
    assert zusammen["felder"] == {"absender": "Zweckverband",
                                  "police_nr": "4711",
                                  "verbrauch_m3": 142.577}


def test_zusammenfuehren_ohne_vorhandenen_satz():
    neu = kidb.aus_dokument(_beleg())
    assert kidb.zusammenfuehren(None, neu)["anbieter"] == \
        "Zweckverband Wasserversorgung"
    assert kidb.zusammenfuehren({}, {}) == {}


def test_zusammenfuehren_laesst_die_eingaben_unangetastet():
    vorhanden = {"felder": {"a": 1}, "anbieter": "Alt"}
    neu = {"felder": {"b": 2}, "anbieter": "Neu"}
    kidb.zusammenfuehren(vorhanden, neu)
    assert vorhanden == {"felder": {"a": 1}, "anbieter": "Alt"}
    assert neu == {"felder": {"b": 2}, "anbieter": "Neu"}


# --------------------------------------------------------------------------
# 4) suche — über Zusammenfassung, Anbieter, Kostenart, Dateiname, Felder
# --------------------------------------------------------------------------

@pytest.fixture()
def saetze() -> list[dict]:
    return [
        kidb.aus_dokument(_beleg()),
        kidb.aus_dokument(_beleg(
            id=8, jahr=2025, kostenart="Müllabfuhr",
            dateiname="2025-01_NK-Muell.pdf",
            ki_einordnung="Gebührenbescheid der Stadt für Abfallentsorgung.",
            ki_felder={"absender": "Stadt Eschenau", "tonnen": 2})),
    ]


def test_suche_findet_ueber_die_zusammenfassung(saetze):
    treffer = kidb.suche(saetze, "Abfallentsorgung")
    assert [t["dokument_id"] for t in treffer] == [8]


def test_suche_findet_ueber_die_felder_werte(saetze):
    # 142.577 steht nur im KI-Raster, nirgends im Text.
    assert [t["dokument_id"] for t in kidb.suche(saetze, "142.577")] == [7]
    assert [t["dokument_id"] for t in kidb.suche(saetze, "Zweckverband")] == [7]


def test_suche_ist_umlaut_und_gross_klein_tolerant(saetze):
    assert [t["dokument_id"] for t in kidb.suche(saetze, "müllabfuhr")] == [8]
    assert [t["dokument_id"] for t in kidb.suche(saetze, "MUELLABFUHR")] == [8]
    assert [t["dokument_id"] for t in kidb.suche(saetze, "gebuehrenbescheid")] == [8]


def test_suche_verknuepft_mehrere_begriffe_und(saetze):
    assert [t["dokument_id"] for t in kidb.suche(saetze, "stadt abfall")] == [8]
    assert kidb.suche(saetze, "stadt wasser") == []


def test_suche_ohne_begriff_gibt_alles_zurueck(saetze):
    assert len(kidb.suche(saetze, "")) == 2
    assert len(kidb.suche(saetze, "   ")) == 2
    assert kidb.suche(saetze, "gibtesnicht") == []


def test_suche_laeuft_auch_ueber_modellobjekte():
    e = Belegdaten(zusammenfassung="Rechnung Kaminkehrer",
                   felder={"absender": "Schornsteinfeger Müller"})
    assert kidb.suche([e], "kaminkehrer") == [e]
    assert kidb.suche([e], "mueller") == [e]
    assert kidb.suche([e], "wasser") == []


# --------------------------------------------------------------------------
# 5) Endpunkte
# --------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def bestand(client) -> Objekt:
    """Ein Objekt mit vier NK-Belegen: drei aktuelle (zwei mit KI-Auslese,
    einer ohne) und einer, der zu alt ist."""
    jetzt = date.today().year
    with Session(engine) as s:
        for e in s.exec(select(Belegdaten)).all():
            s.delete(e)
        for d in s.exec(select(Dokument)).all():
            s.delete(d)
        s.commit()
        o = s.exec(select(Objekt).where(Objekt.slug == "kidb-haus")).first()
        if not o:
            o = Objekt(slug="kidb-haus", name="Tauchersreuther Str. 5",
                       ort="Eschenau")
            s.add(o)
            s.commit()
            s.refresh(o)
        s.add(Dokument(
            pfad=f"/kidb/{o.slug}/wasser.pdf", dateiname="NK-Wasser.pdf",
            objekt_id=o.id, kategorie="Nebenkosten", kostenart="Wasser",
            betrag=1420.55, jahr=jetzt, belegdatum=date(jetzt, 3, 14),
            ki_einordnung="Jahresrechnung des Zweckverbands für Wasser.",
            ki_felder={"absender": "Zweckverband Wasserversorgung",
                       "verbrauch_m3": 142.577},
            ki_immobilie="Tauchersreuther Str. 5"))
        s.add(Dokument(
            pfad=f"/kidb/{o.slug}/muell.pdf", dateiname="NK-Muell.pdf",
            objekt_id=o.id, kategorie="Nebenkosten", kostenart="Müllabfuhr",
            betrag=310.0, jahr=jetzt - 1,
            ki_einordnung="Gebührenbescheid der Stadt für Abfallentsorgung.",
            ki_felder={"absender": "Stadt Eschenau"}))
        s.add(Dokument(
            pfad=f"/kidb/{o.slug}/ohne.pdf", dateiname="NK-Kaminkehrer.pdf",
            objekt_id=o.id, kategorie="Nebenkosten", kostenart="Kaminkehrer",
            betrag=88.0, jahr=jetzt - 1))
        s.add(Dokument(
            pfad=f"/kidb/{o.slug}/alt.pdf", dateiname="NK-Alt.pdf",
            objekt_id=o.id, kategorie="Nebenkosten", kostenart="Wasser",
            jahr=jetzt - 9, ki_einordnung="Uralte Wasserrechnung."))
        # Andere Kategorie — die Übernahme fasst sie nicht an.
        s.add(Dokument(
            pfad=f"/kidb/{o.slug}/steuer.pdf", dateiname="Steuerbescheid.pdf",
            objekt_id=o.id, kategorie="Steuer", jahr=jetzt,
            ki_einordnung="Grundsteuerbescheid."))
        s.commit()
        s.refresh(o)
        return o


def test_uebernahme_legt_an_und_meldet_belege_ohne_ki(client, bestand):
    a = client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    assert a.status_code == 200, a.text
    ergebnis = a.json()
    # Drei NK-Belege der letzten 3 Jahre; der 9 Jahre alte und der
    # Steuerbescheid bleiben aussen vor.
    assert ergebnis["geprueft"] == 3
    assert ergebnis["angelegt"] == 3
    assert ergebnis["aktualisiert"] == 0
    assert [x["dateiname"] for x in ergebnis["ohne_ki"]] == ["NK-Kaminkehrer.pdf"]

    liste = client.get("/api/kidb?objekt=kidb-haus").json()
    assert liste["anzahl"] == 3
    namen = {e["dateiname"] for e in liste["eintraege"]}
    assert namen == {"NK-Wasser.pdf", "NK-Muell.pdf", "NK-Kaminkehrer.pdf"}
    quellen = {e["dateiname"]: e["quelle"] for e in liste["eintraege"]}
    assert quellen["NK-Wasser.pdf"] == "ki"
    assert quellen["NK-Kaminkehrer.pdf"] == "regel"


def test_uebernahme_ist_idempotent(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    zweiter = client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3").json()
    assert zweiter["angelegt"] == 0
    assert zweiter["aktualisiert"] == 3
    # Nichts verdoppelt sich.
    assert client.get("/api/kidb?objekt=kidb-haus").json()["anzahl"] == 3
    with Session(engine) as s:
        assert len(s.exec(select(Belegdaten)).all()) == 3


def test_uebernahme_ueberschreibt_gefuelltes_nicht_mit_leerem(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    eintraege = client.get("/api/kidb?objekt=kidb-haus&q=Kaminkehrer").json()
    eid = eintraege["eintraege"][0]["id"]

    # Der Nutzer ergänzt von Hand, was die KI nicht wusste.
    with Session(engine) as s:
        e = s.get(Belegdaten, eid)
        e.anbieter = "Kaminkehrer Bezirk 3"
        e.zusammenfassung = "Kehrgebühren, von Hand nachgetragen."
        e.felder = {**(e.felder or {}), "hinweis": "Rechnung liegt im Ordner"}
        s.add(e)
        s.commit()

    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    nach = client.get(f"/api/kidb/{eid}").json()
    assert nach["anbieter"] == "Kaminkehrer Bezirk 3"
    assert nach["zusammenfassung"] == "Kehrgebühren, von Hand nachgetragen."
    assert nach["felder"]["hinweis"] == "Rechnung liegt im Ordner"


def test_liste_sucht_ueber_zusammenfassung_und_felder(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    ueber_text = client.get("/api/kidb?q=Abfallentsorgung").json()
    assert [e["dateiname"] for e in ueber_text["eintraege"]] == ["NK-Muell.pdf"]
    # Nur im KI-Raster, nirgends im Text — und umlauttolerant.
    ueber_feld = client.get("/api/kidb?q=142.577").json()
    assert [e["dateiname"] for e in ueber_feld["eintraege"]] == ["NK-Wasser.pdf"]
    umlaut = client.get("/api/kidb?q=muellabfuhr").json()
    assert [e["dateiname"] for e in umlaut["eintraege"]] == ["NK-Muell.pdf"]


def test_liste_filtert_nach_jahr(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    jetzt = date.today().year
    aktuell = client.get(f"/api/kidb?objekt=kidb-haus&jahr={jetzt}").json()
    assert [e["dateiname"] for e in aktuell["eintraege"]] == ["NK-Wasser.pdf"]
    assert client.get("/api/kidb?objekt=kidb-haus").json()["jahre"] == \
        [jetzt, jetzt - 1]


def test_einer_liefert_den_link_zur_datei(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    eid = client.get("/api/kidb?q=Zweckverband").json()["eintraege"][0]["id"]
    e = client.get(f"/api/kidb/{eid}").json()
    assert e["pfad"] == "/kidb/kidb-haus/wasser.pdf"   # der Link, keine Kopie
    assert e["objekt"] == "kidb-haus"
    assert e["felder"]["immobilie"] == "Tauchersreuther Str. 5"
    assert e["belegdatum"] == date(date.today().year, 3, 14).isoformat()
    assert client.get("/api/kidb/999999").status_code == 404


def test_loeschen_entfernt_nur_den_eintrag_die_datei_bleibt(client, bestand):
    client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    eid = client.get("/api/kidb?q=Zweckverband").json()["eintraege"][0]["id"]
    assert client.delete(f"/api/kidb/{eid}").json() == {"ok": True}
    assert client.get(f"/api/kidb/{eid}").status_code == 404
    assert client.get("/api/kidb?objekt=kidb-haus").json()["anzahl"] == 2
    # Der Beleg selbst ist unangetastet.
    with Session(engine) as s:
        d = s.exec(select(Dokument).where(
            Dokument.pfad == "/kidb/kidb-haus/wasser.pdf")).one()
        assert d.ki_einordnung.startswith("Jahresrechnung")


def test_unbekanntes_objekt_meldet_404(client, bestand):
    assert client.post("/api/kidb/uebernehmen?objekt=gibtsnicht").status_code == 404
    assert client.get("/api/kidb?objekt=gibtsnicht").status_code == 404


# --------------------------------------------------------------------------
# 6) Der Wächter: kein KI-Aufruf, kein Griff in die Cloud
# --------------------------------------------------------------------------

def test_uebernahme_fragt_nie_die_ki(client, bestand, monkeypatch):
    """Ausdrücklicher Nutzerwunsch: die Übernahme kostet keine Tokens.

    Jeder Weg zur KI und jeder Griff in die Cloud wird verriegelt — schlägt
    einer davon an, ist der Lauf falsch gebaut."""
    import app.kiauslese as kiauslese
    import app.nextcloud as nextcloud

    def verboten(*a, **k):
        raise AssertionError("Die Übernahme darf weder die KI noch die Cloud "
                             "anfassen — sie liest nur die Datenbank.")

    for modul, name in ((kiauslese, "lies_beleg"), (kiauslese, "_anthropic"),
                        (kiauslese, "frage_ki"), (nextcloud, "hole"),
                        (nextcloud, "Nextcloud")):
        if hasattr(modul, name):
            monkeypatch.setattr(modul, name, verboten)

    ergebnis = client.post("/api/kidb/uebernehmen?objekt=kidb-haus&jahre=3")
    assert ergebnis.status_code == 200
    assert ergebnis.json()["angelegt"] == 3


def test_quelltext_importiert_nichts_das_zur_ki_oder_in_die_cloud_fuehrt():
    """Der zweite Riegel, unabhängig vom Ablauf: die beiden neuen Module
    importieren nichts, worüber ein KI-Aufruf oder ein Download überhaupt
    möglich wäre. Geprüft wird der Syntaxbaum, nicht der Fliesstext — in den
    Kommentaren steht die Regel schliesslich ausgeschrieben."""
    import ast

    verboten = {"anthropic", "kiauslese", "nextcloud", "cloudkern", "ocr",
                "pdftext", "requests", "httpx", "urllib", "http", "socket"}
    hier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for pfad in (os.path.join(hier, "app", "kidb.py"),
                 os.path.join(hier, "app", "routers", "kidb.py")):
        with open(pfad, encoding="utf-8") as f:
            baum = ast.parse(f.read(), filename=pfad)
        namen: set[str] = set()
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                namen.update(a.name.split(".")[0] for a in knoten.names)
            elif isinstance(knoten, ast.ImportFrom):
                namen.update((knoten.module or "").split("."))
                namen.update(a.name for a in knoten.names)
        assert not (namen & verboten), f"{namen & verboten} in {pfad}"
