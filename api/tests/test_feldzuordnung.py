"""N263 — vom KI-Raster zu den Formularfeldern.

Zwei Sorten Prüfung:

* **Übersetzt sie richtig?** Ein Notarvertrag-Raster wird zu genau den Feldern,
  die die Eingabemaske zeigt — mit den richtigen Typen (Datum als ISO, Betrag
  als Zahl), und leere Angaben bleiben leer statt als "" zu landen.
* **Passen die Namen noch zum Modell?** Die Zuordnung nennt Formularfelder beim
  Namen. Wird eines im Modell umbenannt, liefe die Vorbefüllung stumm ins
  Leere — deshalb ein Wächter, der die Namen gegen die Modelle hält.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "fz.db"))

from app import feldzuordnung                                    # noqa: E402
from app.models import (Kredit, Miete, Notarvertrag,             # noqa: E402
                        Versicherung, Zahlung)


def test_notarvertrag_raster_wird_zu_formularwerten():
    ergebnis = {
        "dokumenttyp": "Kaufvertrag",
        "absender": "Notariat Dr. Vogel",
        "betrag": 250000.0,
        "felder": {
            "art": "Kaufvertrag",
            "notar": "Dr. Vogel, Nürnberg",
            "urnr": "123/2024",
            "beurkundet_am": "2024-05-17",
            "kaufpreis": 250000,
            "beteiligte": "Meier → Schmidt",
        },
    }
    werte = feldzuordnung.werte_fuer("notarvertraege", ergebnis)
    assert werte["art"] == "Kaufvertrag"
    assert werte["notar"] == "Dr. Vogel, Nürnberg"
    assert werte["urnr"] == "123/2024"
    assert werte["datum"] == "2024-05-17"          # „Beurkundet am" heisst im Modell `datum`
    assert werte["betrag"] == 250000.0
    assert werte["beteiligte"] == "Meier → Schmidt"


def test_deutsches_datum_und_geldformat_werden_umgesetzt():
    """Die KI liefert meist ISO — kommt doch „17.05.2024" oder „250.000,00 €",
    darf das Feld nicht leer bleiben und der Nutzer es abtippen müssen."""
    werte = feldzuordnung.werte_fuer("notarvertraege", {
        "felder": {"beurkundet_am": "17.05.2024", "kaufpreis": "250.000,00 €"}})
    assert werte["datum"] == "2024-05-17"
    assert werte["betrag"] == 250000.0


def test_leere_angaben_landen_nicht_im_formular():
    """Was die KI nicht gefunden hat, bleibt leer — ein "" im Feld sähe aus wie
    eine Angabe und überschriebe beim Speichern einen Vorgabewert."""
    werte = feldzuordnung.werte_fuer("notarvertraege", {
        "felder": {"art": "Kaufvertrag", "notar": "", "urnr": None}})
    assert werte == {"art": "Kaufvertrag"}


def test_einzelwerte_springen_ein_wenn_das_raster_schweigt():
    """`absender` und `datum` stehen ausserhalb des Rasters — sie sind oft das
    Einzige, was bei einem mageren Beleg zustande kommt."""
    werte = feldzuordnung.werte_fuer("notarvertraege", {
        "absender": "Notariat Vogel", "datum": "2024-05-17", "felder": {}})
    assert werte["notar"] == "Notariat Vogel"
    assert werte["datum"] == "2024-05-17"


def test_versicherung_und_kredit_werden_ebenfalls_uebersetzt():
    v = feldzuordnung.werte_fuer("versicherungen", {"felder": {
        "art": "Gebäudeversicherung", "anbieter": "WWK", "police_nr": "P-9",
        "jahresbeitrag": "1.198,59", "umlagefaehig": "ja"}})
    assert v["art"] == "Gebäudeversicherung"
    assert v["jahresbeitrag"] == 1198.59
    assert v["umlagefaehig"] is True

    k = feldzuordnung.werte_fuer("kredite", {"felder": {
        "bezeichnung": "Annuitätendarlehen", "bank": "Sparkasse",
        "darlehenssumme": 200000, "zinssatz": "3,4"}})
    assert k["urspruenglich"] == 200000.0
    assert k["zinssatz"] == 3.4


def test_unbekannter_bereich_gibt_nichts_zurueck():
    """Ein Tippfehler im Aufruf darf kein halbes Formular füllen."""
    assert feldzuordnung.werte_fuer("gibtsnicht", {"felder": {"art": "x"}}) == {}


def test_namensvorschlag_nennt_art_und_nummer():
    name = feldzuordnung.namensvorschlag(
        "notarvertraege", {"art": "Kaufvertrag", "urnr": "123/2024"})
    assert name == "Notarvertrag Kaufvertrag URNr 123/2024"
    # Sagt die Art nichts Neues, steht sie nicht zweimal da.
    assert feldzuordnung.namensvorschlag(
        "notarvertraege", {"art": "Notarvertrag"}) == "Notarvertrag"


def test_zuordnung_nennt_nur_felder_die_es_im_modell_gibt():
    """Wächter: die Zuordnung schreibt in Modellfelder. Wird eines umbenannt,
    fiele die Vorbefüllung stumm aus — dieser Test macht daraus einen Fehler."""
    modelle = {"notarvertraege": Notarvertrag, "versicherungen": Versicherung,
               "kredite": Kredit, "mieten": Miete, "zahlungen": Zahlung}
    for bereich, zuordnung in feldzuordnung.ZUORDNUNG.items():
        modell = modelle[bereich]
        for feld in zuordnung:
            assert feld in modell.model_fields, f"{bereich}.{feld} fehlt im Modell"
