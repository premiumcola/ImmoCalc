"""N290 — eine Datei bleibt verknüpft, auch wenn der Nutzer sie im Explorer
umbenennt UND verschiebt.

Vorher erkannte `_wiedergefunden` eine Datei nur über ihren NAMEN (dann darf
sie umziehen) oder über ihre GRÖSSE im SELBEN Ordner (dann darf sie umbenannt
werden). Beides zusammen — die häufigste Handbewegung beim Aufräumen — riss die
Verknüpfung: der Beleg galt als vermisst, Kostenposition und Mietstand zeigten
ins Leere.

Jetzt entscheiden zuerst Nextclouds Dateinummer und die Prüfsumme.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_wiedererkennung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.nextcloud import Eintrag  # noqa: E402
from app.routers.dokumente import (_kennzeichen_nachtragen,  # noqa: E402
                                   _umzugsart, _wiedergefunden)


class _Dok:
    """Nur die Felder, die `_wiedergefunden` liest."""

    def __init__(self, pfad, name, groesse=1000, fileid="", sha1=""):
        self.pfad = pfad
        self.dateiname = name
        self.groesse = groesse
        self.nc_fileid = fileid
        self.sha1 = sha1


def _datei(pfad, name, groesse=1000, fileid="", sha1=""):
    return Eintrag(name=name, pfad=pfad, ordner=False, groesse=groesse,
                   sha1=sha1, fileid=fileid)


ALT = "/Haus/60_Nebenkosten/2025_NK-Wasser_120,00€.pdf"


# --------------------------------------------------------------------------
# Der Fall, den der Nutzer beschrieben hat
# --------------------------------------------------------------------------

def test_umbenannt_und_verschoben_bleibt_verknuepft():
    """Beides zugleich — vorher der sichere Verlust der Verknüpfung."""
    d = _Dok(ALT, "2025_NK-Wasser_120,00€.pdf", fileid="88421")
    neu = "/Haus/98_Archiv/Wasser Endabrechnung.pdf"
    dateien = {neu: _datei(neu, "Wasser Endabrechnung.pdf", fileid="88421")}

    ziel, art = _wiedergefunden(d, dateien, set())
    assert ziel == neu
    assert art == "verschoben"


def test_pruefsumme_greift_wenn_die_dateinummer_fehlt():
    """Nach einem Neu-Hochladen ist die Nummer eine andere — die Bytes nicht."""
    d = _Dok(ALT, "2025_NK-Wasser_120,00€.pdf", sha1="abc123")
    neu = "/Haus/98_Archiv/Wasser.pdf"
    dateien = {neu: _datei(neu, "Wasser.pdf", fileid="99999", sha1="abc123")}

    ziel, art = _wiedergefunden(d, dateien, set())
    assert ziel == neu


def test_zwei_byte_gleiche_kopien_werden_nicht_geraten():
    """Byte-Gleichheit heisst nicht „dieselbe Datei" — zwei Kopien desselben
    Belegs sind ebenfalls byte-gleich. Bei zwei Kandidaten wird nicht geraten;
    der Eintrag bleibt lieber vermisst als falsch verknüpft."""
    d = _Dok(ALT, "2025_NK-Wasser_120,00€.pdf", sha1="abc123")
    a, b = "/Haus/98_Archiv/A.pdf", "/Haus/99_Sonstiges/B.pdf"
    dateien = {a: _datei(a, "A.pdf", sha1="abc123"),
               b: _datei(b, "B.pdf", sha1="abc123")}

    ziel, _art = _wiedergefunden(d, dateien, set())
    assert ziel == ""


def test_dateinummer_schlaegt_den_gleichen_namen():
    """Eine gleichnamige FREMDE Datei darf den Eintrag nicht abgreifen, wenn
    die Nummer eindeutig woanders hinzeigt."""
    d = _Dok(ALT, "Rechnung.pdf", fileid="88421")
    echt = "/Haus/98_Archiv/Umbenannt.pdf"
    fremd = "/Haus/99_Sonstiges/Rechnung.pdf"
    dateien = {echt: _datei(echt, "Umbenannt.pdf", fileid="88421"),
               fremd: _datei(fremd, "Rechnung.pdf", fileid="70000")}

    ziel, _art = _wiedergefunden(d, dateien, set())
    assert ziel == echt


def test_vergebene_datei_wird_nicht_zweimal_verknuepft():
    """Eine Datei gehört immer nur einem Eintrag."""
    d = _Dok(ALT, "Rechnung.pdf", fileid="88421")
    neu = "/Haus/98_Archiv/Umbenannt.pdf"
    dateien = {neu: _datei(neu, "Umbenannt.pdf", fileid="88421")}

    ziel, _art = _wiedergefunden(d, dateien, {neu})
    assert ziel == ""


# --------------------------------------------------------------------------
# Die alten Wege bleiben, für den Bestand ohne Kennzeichen
# --------------------------------------------------------------------------

def test_alter_bestand_wird_weiter_ueber_den_namen_gefunden():
    d = _Dok(ALT, "2025_NK-Wasser_120,00€.pdf")          # kein fileid, kein sha1
    neu = "/Haus/98_Archiv/2025_NK-Wasser_120,00€.pdf"
    dateien = {neu: _datei(neu, "2025_NK-Wasser_120,00€.pdf")}

    ziel, art = _wiedergefunden(d, dateien, set())
    assert (ziel, art) == (neu, "verschoben")


def test_alter_bestand_wird_weiter_ueber_die_groesse_gefunden():
    d = _Dok(ALT, "2025_NK-Wasser_120,00€.pdf", groesse=4711)
    neu = "/Haus/60_Nebenkosten/Wasser.pdf"              # selber Ordner
    dateien = {neu: _datei(neu, "Wasser.pdf", groesse=4711)}

    ziel, art = _wiedergefunden(d, dateien, set())
    assert (ziel, art) == (neu, "umbenannt")


# --------------------------------------------------------------------------
# Verschoben oder umbenannt?
# --------------------------------------------------------------------------

def test_umzugsart_unterscheidet_ordner_und_name():
    assert _umzugsart("/a/b/x.pdf", "/a/b/y.pdf") == "umbenannt"
    assert _umzugsart("/a/b/x.pdf", "/a/c/x.pdf") == "verschoben"
    # Beides geändert: der Ordnerwechsel wiegt schwerer
    assert _umzugsart("/a/b/x.pdf", "/a/c/y.pdf") == "verschoben"


# --------------------------------------------------------------------------
# Nachtragen am Bestand
# --------------------------------------------------------------------------

def test_kennzeichen_werden_nachgetragen():
    d = _Dok(ALT, "x.pdf")
    assert _kennzeichen_nachtragen(d, _datei(ALT, "x.pdf", fileid="1", sha1="a"))
    assert (d.nc_fileid, d.sha1) == ("1", "a")
    # Zweiter Lauf ändert nichts mehr — sonst schriebe jeder Abgleich den
    # ganzen Bestand neu in die Datenbank.
    assert not _kennzeichen_nachtragen(
        d, _datei(ALT, "x.pdf", fileid="1", sha1="a"))


def test_leere_angabe_loescht_kein_vorhandenes_kennzeichen():
    """Nicht jede Nextcloud liefert für jede Datei eine Prüfsumme. Ein Lauf
    ohne Angabe darf das Kennzeichen nicht wegräumen — sonst verlöre der
    Bestand genau die Wiedererkennung, für die er gerade gefüllt wurde."""
    d = _Dok(ALT, "x.pdf", fileid="1", sha1="a")
    assert not _kennzeichen_nachtragen(d, _datei(ALT, "x.pdf"))
    assert (d.nc_fileid, d.sha1) == ("1", "a")


def test_ersetzte_datei_bekommt_das_neue_kennzeichen():
    """Legt der Nutzer eine neue Fassung an denselben Platz, folgt der Eintrag."""
    d = _Dok(ALT, "x.pdf", fileid="1", sha1="a")
    assert _kennzeichen_nachtragen(d, _datei(ALT, "x.pdf", fileid="2", sha1="b"))
    assert (d.nc_fileid, d.sha1) == ("2", "b")


# --------------------------------------------------------------------------
# Die Spalten müssen wirklich in der Datenbank ankommen
# --------------------------------------------------------------------------

def test_dokument_traegt_die_kennzeichen_und_bleibt_additiv():
    from sqlmodel import Session

    from app.db import engine
    from app.models import Dokument

    with Session(engine) as s:
        # Ohne Angabe anlegbar — sonst bräche der gesamte Bestand.
        d = Dokument(pfad="/probe/kennzeichen.pdf", dateiname="kennzeichen.pdf")
        s.add(d)
        s.commit()
        s.refresh(d)
        assert d.nc_fileid == ""
        assert d.sha1 == ""
        d.nc_fileid, d.sha1 = "4711", "deadbeef"
        s.add(d)
        s.commit()
        s.refresh(d)
        assert (d.nc_fileid, d.sha1) == ("4711", "deadbeef")
        s.delete(d)
        s.commit()
