"""Vier Lücken in den Belegdiensten — je ein Wächter.

Alle vier sind Fälle, in denen eine Prüfung an EINER Stelle vorhanden war und
an ihrer Geschwisterstelle fehlte. Genau dort fällt so etwas nie auf: der
Normalfall läuft weiter, nur der Randfall geht still den falschen Weg.

1. `ocr.pdf_geradedrehen` drehte OHNE Seitendeckel — seine Geschwister
   (`_gerade_seiten_bilder`, `durchsuchbar_machen`) brechen bei
   `pdftext.MAX_SEITEN` ab. Je Seite ein Pixmap plus OSD-Lauf oder KI-Aufruf:
   ein PDF mit dreistelliger Seitenzahl hielt den Endpunkt unbegrenzt fest.
2. `kiauslese._datum` prüfte nur die ISO-Form, nicht die Plausibilität —
   „9999-01-15" wurde ein Belegdatum, während das Jahr auf derselben Zeile
   still zurechtgerückt wurde.
3. `kiauslese._betrag` hatte gegen missgelesene Serien-/Gerätenummern nur die
   Bitte im Systemprompt; der heuristische Pfad hat dafür einen Riegel im Code.
4. `einheitenzuordnung.zuordne` meldete ein bewusst übergangenes „WG" als
   „gehört zu keiner Einheit" — ein Dauer-Warnbanner ohne Weg zum Beheben.

Kein Netzaufruf: die Modellantwort ist gestellt, das PDF wird zur Laufzeit
gebaut.
"""
import os
import sys
import tempfile
from datetime import date

import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(),
                                              "test_dienste_luecken.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import einheitenzuordnung as ez  # noqa: E402
from app import kiauslese, ocr, pdftext  # noqa: E402
from app.dokumente.datum import _zum_datum  # noqa: E402
from app.models import Zaehler  # noqa: E402


class _FakeAntwort:
    """Eine HTTP-Antwort, wie das Modell sie schickt — Status 200, ein
    Textblock mit dem JSON darin."""
    status_code = 200

    def __init__(self, text: str) -> None:
        self._text = text

    def json(self) -> dict:
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeHttpx:
    """Steht an der Stelle von `httpx` — dieselbe Bauart wie in
    `test_kiauslese.py`, damit die Auslese ohne Netz prüfbar bleibt."""

    def __init__(self, text: str) -> None:
        self._text = text

    def post(self, *_a, **_k) -> _FakeAntwort:
        return _FakeAntwort(self._text)


# --------------------------------------------------------------------------
# 1) Der fehlende Seitendeckel beim Geradedrehen
# --------------------------------------------------------------------------

def _leeres_pdf(seiten: int) -> bytes:
    """Ein PDF mit `seiten` leeren Seiten — zur Laufzeit gebaut, damit kein
    Beispieldokument im Repo gepflegt werden muss."""
    fitz = pytest.importorskip("fitz")
    dokument = fitz.open()
    for _ in range(seiten):
        dokument.new_page(width=200, height=280)
    roh = dokument.tobytes()
    dokument.close()
    return roh


def _drehung_zaehlen(monkeypatch, grad_erste_seite: int = 90) -> list[bytes]:
    """Stellt die Orientierungserkennung: sie merkt sich jede Seite, die ihr
    vorgelegt wird, und richtet nur die erste auf.

    So misst der Test, wie viele Seiten überhaupt ANGESEHEN werden — genau das
    ist die Arbeit, die ohne Deckel unbegrenzt wächst (Pixmap plus OSD-Lauf
    mit 15 s Zeitlimit oder ein KI-Aufruf je Seite)."""
    gesehen: list[bytes] = []

    def gestellt(png: bytes, ki_key: str = "") -> int:
        gesehen.append(png)
        return grad_erste_seite if len(gesehen) == 1 else 0

    monkeypatch.setattr(ocr, "verfuegbar", lambda: True)
    monkeypatch.setattr(ocr, "_seiten_drehung", gestellt)
    return gesehen


def test_geradedrehen_sieht_nie_mehr_als_den_seitendeckel_an(monkeypatch):
    """Der Fund: `for i in range(d.page_count)` — ohne jede Obergrenze.

    Ein Bestandsscan mit dreistelliger Seitenzahl ergab dreistellig viele
    Pixmaps und ebenso viele OSD-/KI-Läufe; `POST /api/dokumente/{id}/
    geradedrehen` lief dadurch beliebig lange. Die Geschwister im selben Modul
    brechen längst bei `pdftext.MAX_SEITEN` ab."""
    roh = _leeres_pdf(pdftext.MAX_SEITEN + 5)
    gesehen = _drehung_zaehlen(monkeypatch)

    neu, bericht = ocr.pdf_geradedrehen(roh)

    assert len(gesehen) == pdftext.MAX_SEITEN
    # Gedreht wird trotzdem, was innerhalb des Deckels schief lag.
    assert neu is not None
    assert list(bericht) == [{"seite": 0, "grad": 90}]


def test_geradedrehen_sagt_wie_viele_seiten_ungeprueft_blieben(monkeypatch):
    """Deckeln allein genügt nicht: die halbe Datei stillschweigend zu
    überspringen wäre schlimmer als langsam zu sein. Der Bericht nennt die
    Zahl der Seiten, die gar nicht erst angesehen wurden."""
    gesehen = _drehung_zaehlen(monkeypatch)
    _neu, bericht = ocr.pdf_geradedrehen(_leeres_pdf(pdftext.MAX_SEITEN + 5))
    assert bericht.ungeprueft == 5
    assert len(gesehen) == pdftext.MAX_SEITEN

    # Ein normales Dokument bleibt vollständig geprüft — dann gibt es nichts
    # zu melden, und der Bericht verhält sich wie die Liste, die er war.
    gesehen.clear()
    _neu2, kurz = ocr.pdf_geradedrehen(_leeres_pdf(3))
    assert kurz.ungeprueft == 0
    assert len(gesehen) == 3
    assert isinstance(kurz, list) and len(kurz) == 1


def test_geradedrehen_ohne_befund_bleibt_folgenlos(monkeypatch):
    """Lag keine Seite schief, bleibt das Original unberührt — auch der
    Deckel ändert daran nichts."""
    _drehung_zaehlen(monkeypatch, grad_erste_seite=0)
    neu, bericht = ocr.pdf_geradedrehen(_leeres_pdf(3))
    assert neu is None
    assert list(bericht) == [] and bericht.ungeprueft == 0


# --------------------------------------------------------------------------
# 2) Ein Belegdatum, das es nicht geben kann
# --------------------------------------------------------------------------

UNSINNSDATUM = "9999-01-15"


def test_ki_datum_wird_auf_plausibilitaet_geprueft():
    """„9999-01-15" ist ein gültiges ISO-Datum und trotzdem kein Belegdatum.

    Geprüft wurde bisher nur die Form. Das Geschwister-Feld `_jahr` begrenzt
    seit N14 auf 1990…heute+1 — dieselbe Grenze gilt jetzt für das Datum."""
    assert kiauslese._datum(UNSINNSDATUM) is None
    assert kiauslese._datum("1989-12-31") is None
    # Was ein Beleg tragen kann, kommt unverändert durch.
    assert kiauslese._datum("2025-03-14") == "2025-03-14"
    naechstes_jahr = date(date.today().year + 1, 6, 1)
    assert kiauslese._datum(naechstes_jahr.isoformat()) == naechstes_jahr.isoformat()


def test_zum_datum_verwirft_dasselbe_unsinnsdatum():
    """Dieselbe Lücke an der zweiten Stelle: `dokumente.datum._zum_datum`
    schreibt direkt nach `Dokument.belegdatum`."""
    assert _zum_datum(UNSINNSDATUM) is None
    assert _zum_datum("1989-12-31") is None
    assert _zum_datum("2025-11-14") == date(2025, 11, 14)
    # Ein halbes Datum bleibt wie bisher keins (CLXXII).
    assert _zum_datum("2025-11") is None


def test_kein_widerspruechlicher_datensatz_aus_der_auslese(monkeypatch):
    """Der eigentliche Schaden: `belegdatum` und `jahr` werden in
    `ocr._ki_ergaenzen` auf DERSELBEN Zeile gesetzt. Das Jahr wurde still
    korrigiert, das Datum nicht — heraus kam ein Datensatz, der sich selbst
    widerspricht, und das Belegdatum steuert die Zeitraum-Zuordnung."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(
        '{"datum":"%s","abrechnungsjahr":9999,"betrag":120.50,'
        '"kostenart":"Wasser","kategorie":"Nebenkosten"}' % UNSINNSDATUM))
    ergebnis = {"datum": None, "jahr": None, "monat": None, "betrag": None,
                "kategorie": "", "sache": "", "ist_kosten": True,
                "kosten_relevant": None, "nebenkosten": None,
                "zeitraum_hinweis": "", "zusammenfassung": "",
                "einordnung": "", "absender": ""}
    ocr._ki_ergaenzen(ergebnis, "OCR-Text", ki_key="test-key")

    assert ergebnis["datum"] is None
    assert ergebnis["jahr"] is None and ergebnis["monat"] is None
    # Alles Übrige der Auslese bleibt erhalten — verworfen wird nur das Datum.
    assert ergebnis["betrag"] == 120.50
    assert ergebnis["kategorie"] == "Nebenkosten"


# --------------------------------------------------------------------------
# 3) Eine Gerätenummer ist kein Betrag
# --------------------------------------------------------------------------

def test_ki_betrag_verwirft_die_seriennummer():
    """Der heuristische Pfad hat dafür `ocr.plausibler_betrag`; der KI-Pfad
    hatte nur die Bitte im Systemprompt. Eine Bitte ist kein Riegel.

    Unterschieden wird an der Schreibweise: ein echter Millionenbetrag steht
    gegliedert da, eine Serien-/Zählernummer nackt."""
    assert kiauslese._betrag("6138521,20") is None
    assert kiauslese._betrag(6138521.20) is None
    assert kiauslese._betrag("6.138.521,20") == 6138521.20
    # Was ein Beleg wirklich fordert, kommt unverändert durch.
    assert kiauslese._betrag(862.51) == 862.51
    assert kiauslese._betrag("1.234,56") == 1234.56
    assert kiauslese._betrag("104.15") == 104.15
    # Ein Betrag ist die Höhe der Forderung: positiv (CCCXCIII) und nie null.
    assert kiauslese._betrag(-61.40) == 61.40
    assert kiauslese._betrag(0) is None


def test_ausgelesener_beleg_bekommt_keine_geraetenummer_als_betrag(monkeypatch):
    """Ende zu Ende: was das Modell als Betrag zurückgibt, landete ungeprüft
    in `Dokument.betrag` und damit in einer Kostenposition."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(
        '{"datum":"2025-03-14","betrag":6138521.20,"kostenart":"Wartung",'
        '"kategorie":"Nebenkosten","kosten_relevant":true}'))
    ki = kiauslese.lies_beleg("OCR-Text", schluessel="test-key")
    assert ki is not None
    assert ki["betrag"] is None
    # Der Beleg selbst bleibt brauchbar — nur die unglaubwürdige Zahl fehlt.
    assert ki["datum"] == "2025-03-14"
    assert ki["kostenart"] == "Wartung"


# --------------------------------------------------------------------------
# 4) Warnungen, die nichts zu beheben lassen
# --------------------------------------------------------------------------

KARTE = {"wohnung eg": "Wohnung EG", "wohnung og": "Wohnung OG"}
HAUPTHAUS = ("Wohnung EG", "Wohnung OG")


def test_bewusst_uebergangenes_wg_wird_nicht_als_fund_gemeldet():
    """Trägt ein Zähler „WG, Wohnung EG", greift N111: die echte Einheit
    gewinnt, „WG" wird BEWUSST fallen gelassen. Es trotzdem zu melden ergab
    die Warnung „„WG" gehört zu keiner Einheit dieses Objekts — die Zuordnung
    bitte am Zähler nachtragen." Sie ist sachlich falsch (die Zuordnung IST
    nachgetragen) und nicht abstellbar."""
    treffer = ez.zuordne(["WG", "Wohnung EG"], KARTE, HAUPTHAUS)
    assert treffer.ziele == ["Wohnung EG"]
    assert treffer.unbekannt == []
    assert ez.warnungen(treffer.unbekannt) == []


def test_wg_allein_loest_weiter_auf_das_haupthaus_auf():
    """Die Gegenprobe: ohne echte Einheit steht „WG" nach wie vor für die
    Haupthaus-Wohnungen — daran ändert sich nichts."""
    treffer = ez.zuordne(["WG"], KARTE, HAUPTHAUS)
    assert treffer.ziele == list(HAUPTHAUS)
    assert treffer.unbekannt == []
    # Und ohne Haupthaus-Einheiten ist „WG" wirklich nicht aufzulösen — dann
    # gehört der Hinweis hin, denn dort gibt es etwas nachzutragen.
    ohne = ez.zuordne(["WG"], KARTE)
    assert ohne.ziele == [] and ohne.unbekannt == ["WG"]


def test_leerraum_ist_kein_label():
    """`einheiten=""` mit `einheit_bezug="   "` ergab das Ziel-Label `"   "`
    und daraus die Warnung „„   " gehört zu keiner Einheit" — nicht zu
    beheben, weil es nichts zu beheben gibt."""
    z = Zaehler(objekt_id=1, name="Keller", einheiten="", einheit_bezug="   ")
    assert ez.parse_einheiten(z) == []
    assert ez.zuordne_zaehler(z, KARTE).unbekannt == []
    # Auch direkt gereicht wird Leerraum kein Fund.
    assert ez.zuordne(["   "], KARTE).unbekannt == []
    assert ez.warnungen(["   "]) == []


def test_ein_label_ergibt_einen_hinweis_egal_wie_geschrieben():
    """Nachgeschlagen wird über `schluessel()` (casefold, Leerraum
    vereinheitlicht) — gemeldet wurde exakt. „Keller" und „keller" ergaben
    zwei Warnungen für dasselbe Label."""
    treffer = ez.zuordne(["Keller", "keller", "  Keller  "], KARTE)
    assert treffer.unbekannt == ["Keller"]
    assert len(ez.warnungen(["Keller", "keller"])) == 1
