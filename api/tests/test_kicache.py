"""N296/N297 — die KI-Auslese hängt am Dateiinhalt, und Sidecars gibt es nicht mehr.

**N296:** Ein KI-Aufruf kostet Budget des Nutzers. Gespeichert war die Auslese
bisher nur am `Dokument`, also an der Eintragsnummer — dieselbe Datei ein
zweites Mal in der App bekam eine neue Nummer und wurde noch einmal bezahlt
gelesen. Jetzt ist der SHA1 des Inhalts der Schlüssel.

**N297:** Der `.immocalc`-Steckbrief wird nicht mehr neben das PDF gelegt. Er
wurde aus den Feldern des Datensatzes erzeugt und nie wieder eingelesen — die
Ordner des Nutzers trugen also die doppelte Dateizahl ohne jeden Nutzen.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_kicache.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import Session, select  # noqa: E402

from app import kicache  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import KiAuslese  # noqa: E402

AUSLESE = {"einordnung": "Grundsteuerbescheid der Gemeinde Eckental",
           "betrag": 104.15, "kategorie": "Nebenkosten",
           "kostenart": "Grundsteuer", "felder": {"jahr": 2025}, "ki": True}


def _sitzung():
    return Session(engine)


# --------------------------------------------------------------------------
# Der Schlüssel ist der Inhalt
# --------------------------------------------------------------------------

def test_gleiche_bytes_ergeben_denselben_schluessel():
    a = kicache.pruefsumme(b"%PDF-1.4 Grundsteuer")
    b = kicache.pruefsumme(b"%PDF-1.4 Grundsteuer")
    c = kicache.pruefsumme(b"%PDF-1.4 Wasserrechnung")
    assert a == b
    assert a != c
    assert len(a) == 40                              # SHA1 als Hex


def test_gemerkte_auslese_kommt_zurueck():
    with _sitzung() as s:
        sha1 = kicache.pruefsumme(b"beleg-eins")
        assert kicache.hole(s, sha1) is None         # noch nichts da
        assert kicache.merke(s, sha1, AUSLESE, "claude-x")
        zurueck = kicache.hole(s, sha1)
    assert zurueck["einordnung"] == AUSLESE["einordnung"]
    assert zurueck["betrag"] == 104.15


def test_dieselbe_datei_unter_neuer_nummer_kostet_nichts():
    """Der eigentliche Zweck: der Beleg ist ein anderer EINTRAG, aber
    derselbe INHALT — und der ist schon einmal bezahlt gelesen worden."""
    with _sitzung() as s:
        inhalt = b"dieselbe rechnung, zweimal gescannt"
        kicache.merke(s, kicache.pruefsumme(inhalt), AUSLESE)
        # Zweiter Upload derselben Datei, ganz ohne Bezug zum ersten Eintrag:
        assert kicache.hole(s, kicache.pruefsumme(inhalt)) is not None


def test_treffer_werden_gezaehlt():
    with _sitzung() as s:
        sha1 = kicache.pruefsumme(b"zaehlprobe")
        kicache.merke(s, sha1, AUSLESE)
        for _ in range(3):
            kicache.hole(s, sha1)
        eintrag = s.exec(select(KiAuslese).where(KiAuslese.sha1 == sha1)).first()
        assert eintrag.treffer == 3


# --------------------------------------------------------------------------
# Was NICHT gemerkt werden darf
# --------------------------------------------------------------------------

def test_leere_auslese_wird_nicht_gemerkt():
    """Sonst käme der Beleg nie wieder an die KI, obwohl ein besseres Modell
    beim nächsten Mal etwas finden könnte."""
    with _sitzung() as s:
        sha1 = kicache.pruefsumme(b"nichts-drin")
        assert not kicache.merke(s, sha1, {})
        assert not kicache.merke(s, sha1, {"ki": True, "felder": {}})
        assert kicache.hole(s, sha1) is None


def test_ohne_pruefsumme_passiert_nichts():
    with _sitzung() as s:
        assert not kicache.merke(s, "", AUSLESE)
        assert kicache.hole(s, "") is None


def test_neu_analysieren_ersetzt_den_alten_stand():
    """Ein ausdrückliches Neu-Lesen soll gelten — sonst hinge der Nutzer für
    immer an der ersten, mit einem älteren Modell erzeugten Auslese."""
    with _sitzung() as s:
        sha1 = kicache.pruefsumme(b"zweimal-gelesen")
        kicache.merke(s, sha1, {**AUSLESE, "einordnung": "alt"}, "modell-alt")
        kicache.merke(s, sha1, {**AUSLESE, "einordnung": "neu"}, "modell-neu")
        assert kicache.hole(s, sha1)["einordnung"] == "neu"
        eintraege = s.exec(select(KiAuslese).where(KiAuslese.sha1 == sha1)).all()
        assert len(eintraege) == 1                   # je Inhalt genau einer
        assert eintraege[0].modell == "modell-neu"


def test_stand_zaehlt_eintraege_und_ersparnis():
    with _sitzung() as s:
        vorher = kicache.stand(s)
        sha1 = kicache.pruefsumme(b"standprobe")
        kicache.merke(s, sha1, AUSLESE)
        kicache.hole(s, sha1)
        nachher = kicache.stand(s)
    assert nachher["eintraege"] == vorher["eintraege"] + 1
    assert nachher["erspart"] == vorher["erspart"] + 1


# --------------------------------------------------------------------------
# N297 — keine Sidecars mehr
# --------------------------------------------------------------------------

def test_kein_code_schreibt_noch_einen_steckbrief():
    """Wächter: ein `lege_ab` auf einen `.immocalc`-Pfad wäre der Rückfall in
    genau das, was der Nutzer nicht mehr will."""
    import pathlib
    import re

    wurzel = pathlib.Path(__file__).resolve().parent.parent / "app"
    treffer = []
    for datei in wurzel.rglob("*.py"):
        for nr, zeile in enumerate(datei.read_text().splitlines(), 1):
            if re.search(r"lege_ab\(\s*sidecar|lege_ab\(.*immocalc", zeile):
                treffer.append(f"{datei.relative_to(wurzel)}:{nr}")
    assert not treffer, "Steckbrief wird wieder geschrieben: " + ", ".join(treffer)


def test_der_steckbrief_baustein_ist_weg():
    """Er hatte nach dem Abschalten keinen Aufrufer mehr — toter Code."""
    import pathlib

    modul = (pathlib.Path(__file__).resolve().parent.parent
             / "app" / "dokumente" / "immocalc_steckbrief.py")
    assert not modul.exists()


def test_entfernen_laeuft_standardmaessig_trocken():
    """Gelöscht wird in der Cloud des Nutzers — die Zahl kommt vorher."""
    import inspect

    from app.routers.dokumente import immocalc_entfernen

    vorgabe = inspect.signature(immocalc_entfernen).parameters["bestaetigt"].default
    assert vorgabe is False
