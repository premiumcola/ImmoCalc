"""N14 — das Abrechnungsjahr (der abgerechnete Zeitraum) bestimmt die Ablage,
nicht das Rechnungs-/Briefdatum.

Der Müll-Bescheid „Abrechnung 2025, Grundgebühr 2026" war am 30.01.2026 datiert
und landete deshalb im Jahr 2026 — falsch, er rechnet 2025 ab.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_abrechnungsjahr.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import kiauslese, ocr  # noqa: E402


def test_jahr_parser():
    assert kiauslese._jahr(2025) == 2025
    assert kiauslese._jahr("2025") == 2025
    assert kiauslese._jahr("2025-06") == 2025
    assert kiauslese._jahr(1500) is None          # zu weit in der Vergangenheit
    assert kiauslese._jahr("Unfug") is None
    assert kiauslese._jahr(True) is None           # bool ist kein Jahr


def _leeres_ergebnis():
    return {"jahr": None, "monat": None, "datum": None, "kategorie": "",
            "ist_kosten": True, "sache": "", "betrag": None}


def test_abrechnungsjahr_schlaegt_das_rechnungsdatum(monkeypatch):
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "datum": "2026-01-30", "abrechnungsjahr": 2025, "betrag": 256.36,
        "kategorie": "Nebenkosten"})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "beliebiger belegtext", ki_key="x")
    assert erg["datum"] == "2026-01-30"    # Rechnungsdatum bleibt erhalten
    assert erg["jahr"] == 2025             # Ablage folgt dem Abrechnungsjahr


def test_ohne_abrechnungsjahr_bleibt_das_rechnungsjahr(monkeypatch):
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "datum": "2025-03-15", "abrechnungsjahr": None})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["jahr"] == 2025             # Fallback: Jahr aus dem Datum


def test_zusatzbeleg_ohne_kosten_nutzt_dokumenttyp_als_sache(monkeypatch):
    """N237 — eine Abbuchungsvorankündigung ist NICHT der Grundsteuerbescheid:
    der Dateiname darf nicht wie der Hauptbeleg heissen."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "kostenart": "Grundsteuer", "dokumenttyp": "Abbuchungsvorankündigung",
        "kosten_relevant": False, "ist_kosten": False, "betrag": None})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["sache"] == "Abbuchungsvorankündigung"
    assert erg["betrag"] is None


def test_echter_beleg_behaelt_die_kostenart_als_sache(monkeypatch):
    """N237 — der normale Fall (echte Rechnung) ändert sich nicht: die Sache
    bleibt die Kostenart, wie schon vor dem Fix."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "kostenart": "Grundsteuer", "dokumenttyp": "Grundsteuerbescheid",
        "kosten_relevant": True, "ist_kosten": True, "betrag": 256.36})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["sache"] == "Grundsteuer"
    assert erg["betrag"] == 256.36


def test_nebendokument_mit_betrag_nutzt_trotzdem_den_dokumenttyp(monkeypatch):
    """N244 — der echte Fall aus der Praxis: eine Abbuchungsvorankündigung
    nennt sehr wohl einen Betrag (2 × 87,00 €) und gilt der KI deshalb als
    kostenrelevant. Sie ist trotzdem NICHT der Grundsteuerbescheid und darf
    nicht wie er heissen — sonst hiessen beide „NK-Grundsteuer" und die
    Ankündigung bekäme nur ein angehängtes „-2"/„-3"."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "kostenart": "Grundsteuer", "dokumenttyp": "Abbuchungsvorankündigung",
        "kosten_relevant": True, "ist_kosten": True, "betrag": 174.00})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["sache"] == "Abbuchungsvorankündigung"
    # Der Betrag bleibt erhalten — erkannt ist erkannt; nur der NAME ändert sich.
    assert erg["betrag"] == 174.00


def test_nebendokument_erkennt_auch_zusaetze_im_typ(monkeypatch):
    """N244 — der Dokumenttyp trägt oft einen Zusatz („… der Stadt Eckental").
    Der Teiltreffer über `regel_kompakt` muss ihn trotzdem erwischen."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "kostenart": "Wasser",
        "dokumenttyp": "Abbuchungs-Vorankündigung der Stadt Eckental",
        "kosten_relevant": True, "ist_kosten": True, "betrag": 117.00})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["sache"] == "Abbuchungs-Vorankündigung der Stadt Eckental"


def test_hauptbelegarten_gelten_nicht_als_nebendokument():
    """N244 — die Wortliste darf keinen echten Hauptbeleg einfangen: sonst
    verlöre die ganze Ablage ihre einheitlichen Kostenart-Namen."""
    for typ in ("Grundsteuerbescheid", "Jahresabrechnung", "Rechnung",
                "Gebührenbescheid", "Betriebskostenabrechnung",
                "Heizkostenabrechnung", "Schlussrechnung"):
        assert not ocr._ist_nebendokument(typ), typ
    for typ in ("Abbuchungsvorankündigung", "SEPA-Lastschriftmandat",
                "Zahlungserinnerung", "Mahnung", "Abschlagsplan"):
        assert ocr._ist_nebendokument(typ), typ
    assert not ocr._ist_nebendokument("")
    assert not ocr._ist_nebendokument(None)
