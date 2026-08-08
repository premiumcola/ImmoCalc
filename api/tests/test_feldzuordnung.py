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
from app.models import (Grundschuld, Kostenposition, Kredit,     # noqa: E402
                        Miete, Notarvertrag, Objekt,
                        Renovierungsposten, Versicherung, Zahlung)
from app.turnus import TURNUS                                    # noqa: E402


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
    # N276 — „erwerbskosten" ist eine Pseudo-Rubrik: sie hat keinen eigenen
    # Endpunkt, sondern schreibt Zahlungen mit fester Kategorie (siehe
    # RUBRIK_ENDPUNKT in objekt-felder.js). Deshalb steht hier dasselbe Modell.
    # N280-D — „nebenkosten" schreibt eine Kostenposition in den Zeitraum,
    # „stammdaten" patcht das Objekt selbst (Kaufpreis, Grundsteuer-Kette,
    # Gemarkung, WEG-Angaben), „grundschulden" legt eine Belastung an.
    modelle = {"notarvertraege": Notarvertrag, "versicherungen": Versicherung,
               "kredite": Kredit, "mieten": Miete, "zahlungen": Zahlung,
               "erwerbskosten": Zahlung,
               "renovierungsposten": Renovierungsposten,
               "nebenkosten": Kostenposition, "stammdaten": Objekt,
               "grundschulden": Grundschuld}
    for bereich, zuordnung in feldzuordnung.ZUORDNUNG.items():
        modell = modelle[bereich]
        for feld in zuordnung:
            assert feld in modell.model_fields, f"{bereich}.{feld} fehlt im Modell"


# --------------------------------------------------------------------------
# N270 — die Renovierungsposten-Maske: Datum, Betrag, Firma, Gewerk, Notiz
# einer Rechnung, die eine KI-Auslese bereits einem Gewerk zugeordnet hat.
# --------------------------------------------------------------------------
def test_renovierungsposten_raster_wird_zu_formularwerten():
    ergebnis = {
        "datum": "2026-03-04",
        "betrag": 1450.0,
        "absender": "Elektro Mustermann GmbH",
        "gewerk": "Elektro",
        "kostenart": "Zählerschrank erneuert",
    }
    werte = feldzuordnung.werte_fuer("renovierungsposten", ergebnis)
    assert werte["datum"] == "2026-03-04"
    assert werte["betrag"] == 1450.0
    assert werte["firma"] == "Elektro Mustermann GmbH"
    assert werte["gewerk"] == "Elektro"
    assert werte["notiz"] == "Zählerschrank erneuert"


def test_renovierungsposten_ohne_gewerk_bleibt_leer():
    """Ein Beleg, den die KI nicht als Handwerkerleistung erkannt hat (oder
    dessen Gewerk verworfen wurde), lässt das Feld leer statt es zu raten."""
    werte = feldzuordnung.werte_fuer("renovierungsposten", {
        "datum": "2026-03-04", "betrag": 99.0, "absender": "Irgendwer",
        "gewerk": None})
    assert "gewerk" not in werte
    assert werte["betrag"] == 99.0


def test_renovierungsposten_namensvorschlag_kombiniert_gewerk_und_firma():
    name = feldzuordnung.namensvorschlag(
        "renovierungsposten",
        {"gewerk": "Elektro", "firma": "Muster GmbH"})
    assert name == "Renovierung Elektro Muster GmbH"
    # Ohne Gewerk oder Firma bleibt trotzdem ein sinnvoller Name übrig.
    assert feldzuordnung.namensvorschlag("renovierungsposten", {}) == "Renovierung"


def test_renovierungsposten_nimmt_firma_und_leistung_aus_dem_raster():
    """N280-D — die Handwerkerrechnung hat jetzt ein eigenes Raster. Die Firma
    kommt daraus, nicht mehr nur über den allgemeinen `absender`."""
    werte = feldzuordnung.werte_fuer("renovierungsposten", {
        "absender": "Zahlungsdienst AG",
        "felder": {"firma": "Elektro Mustermann GmbH",
                   "leistung": "Zählerschrank erneuert"}})
    assert werte["firma"] == "Elektro Mustermann GmbH"
    assert werte["notiz"] == "Zählerschrank erneuert"


# --------------------------------------------------------------------------
# N280-D — die Bereiche, die es bisher gar nicht gab: eine Nebenkosten-
# Kostenposition, die Stammdaten des Objekts und eine Grundschuld.
# --------------------------------------------------------------------------
def test_nebenkosten_rechnung_wird_zur_kostenposition():
    werte = feldzuordnung.werte_fuer("nebenkosten", {
        "kostenart": "Schornsteinfeger", "betrag": 96.5,
        "felder": {"s35a": True, "verbrauch": "122,00 m³"}})
    assert werte["kostenart"] == "Schornsteinfeger"
    assert werte["betrag"] == 96.5
    assert werte["s35"] is True          # haushaltsnahe Dienstleistung
    # Die Menge trägt ihre Einheit mit — die Zahl davor zählt.
    assert werte["menge"] == 122.0


def test_nebenkosten_ohne_35a_bleibt_das_haekchen_weg():
    """Nur ein klares Signal setzt den § 35a — sonst bliebe ein „vielleicht"
    als gesetztes Häkchen stehen und liefe in die Steuererklärung."""
    werte = feldzuordnung.werte_fuer("nebenkosten", {
        "kostenart": "Müll", "betrag": 412.0, "felder": {}})
    assert "s35" not in werte and werte["betrag"] == 412.0


def test_stammdaten_nehmen_kaufvertrag_und_grundsteuerbescheid_an():
    kauf = feldzuordnung.werte_fuer("stammdaten", {
        "felder": {"kaufpreis": "250.000,00 €", "kaufdatum": "17.05.2024"}})
    assert kauf == {"kaufpreis": 250000.0, "kaufdatum": "2024-05-17"}

    steuer = feldzuordnung.werte_fuer("stammdaten", {
        "felder": {"grundsteuerwert": 2600, "grundsteuer_messbetrag": "1,43",
                   "grundsteuer_hebesatz": 400}})
    assert steuer == {"grundsteuerwert": 2600.0,
                      "grundsteuer_messbetrag": 1.43,
                      "grundsteuer_hebesatz": 400.0}


def test_stammdaten_nehmen_die_weg_abrechnung_an():
    werte = feldzuordnung.werte_fuer("stammdaten", {
        "absender": "Notariat Vogel",          # darf NICHT zum Verwalter werden
        "felder": {"verwalter": "Hausverwaltung Meier",
                   "hausgeld_monatlich": "310,00",
                   "ruecklage_zufuehrung": 85}})
    assert werte["weg_verwalter"] == "Hausverwaltung Meier"
    assert werte["hausgeld_monatlich"] == 310.0
    assert werte["weg_ruecklage_zufuehrung"] == 85.0

    # Ohne WEG-Angaben bleibt der Verwalter leer — der Absender springt nicht ein.
    ohne = feldzuordnung.werte_fuer("stammdaten", {"absender": "Notariat Vogel",
                                                   "felder": {}})
    assert ohne == {}


def test_grundschuld_raster_wird_zu_formularwerten():
    werte = feldzuordnung.werte_fuer("grundschulden", {
        "felder": {"glaeubiger": "Sparkasse Nürnberg", "grundschuld_betrag":
                   "150.000,00 €", "rang": "I", "grundbuch_blatt": "1234"}})
    assert werte == {"betrag": 150000.0, "rang": "I",
                     "grundbuch_blatt": "1234",
                     "glaeubiger": "Sparkasse Nürnberg"}
    assert feldzuordnung.namensvorschlag("grundschulden", werte) == \
        "Grundschuld Sparkasse Nürnberg"


# --------------------------------------------------------------------------
# N280-D — der Turnus: ein Schlüssel der App, kein Freitext.
# --------------------------------------------------------------------------
def test_turnus_wird_auf_den_schluessel_der_app_gebracht():
    """„jährlich" mit Umlaut passt zu keiner Option der Maske und fiel dort auf
    den Vorgabewert zurück — die Angabe war da und wirkte trotzdem nicht."""
    for gelesen, erwartet in (("jährlich", "jaehrlich"),
                              ("vierteljährlich", "vierteljaehrlich"),
                              ("quartalsweise", "vierteljaehrlich"),
                              ("halbjährlich", "halbjaehrlich"),
                              ("monatliche Zahlweise", "monatlich"),
                              ("einmalig", "einmalig")):
        werte = feldzuordnung.werte_fuer("versicherungen",
                                         {"felder": {"turnus": gelesen}})
        assert werte["turnus"] == erwartet
        assert erwartet in TURNUS          # und es gibt den Schlüssel wirklich


def test_unbekannte_zahlweise_bleibt_leer():
    """Lieber kein Turnus als einer, den die Auswahl nicht kennt."""
    werte = feldzuordnung.werte_fuer("versicherungen",
                                     {"felder": {"turnus": "nach Absprache"}})
    assert "turnus" not in werte


def test_zahlung_uebernimmt_keinen_turnus_vom_beleg():
    """N262 rechnet vier Quartalsraten auf den JAHRESbetrag hoch. Käme dazu der
    Turnus „vierteljährlich" ins Formular, stünde derselbe Betrag ein zweites
    Mal mal vier in der Auswertung."""
    werte = feldzuordnung.werte_fuer("zahlungen", {
        "betrag": 348.0, "abrechnungsjahr": 2026,
        "felder": {"jahresbetrag": 348.0, "turnus": "vierteljährlich"}})
    assert werte["betrag"] == 348.0 and werte["jahr"] == 2026
    assert "turnus" not in werte


def test_erwerbskosten_notiz_faellt_auf_die_kostenart_zurueck():
    """„notiz" fragt der Prompt nirgends ab — ohne Rückfall blieb das Feld leer."""
    werte = feldzuordnung.werte_fuer("erwerbskosten", {
        "kostenart": "Beurkundung Kaufvertrag", "betrag": 1890.0,
        "felder": {"erwerbsart": "Notar"}})
    assert werte["notiz"] == "Beurkundung Kaufvertrag"
    assert werte["art"] == "Notar"


def test_mietende_landet_im_feld_beendet_am():
    werte = feldzuordnung.werte_fuer("mieten", {
        "felder": {"mieter": "Schmidt", "mietbeginn": "2024-01-01",
                   "mietende": "31.12.2026"}})
    assert werte["ab_datum"] == "2024-01-01"
    assert werte["bis_datum"] == "2026-12-31"
