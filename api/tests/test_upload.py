"""N292 — der Riegel vor jedem Datei-Upload gilt jetzt überall.

Neun Endpunkte nehmen eine Datei entgegen. Vorher galt das Grössenlimit an
dreien und die Dateiart-Prüfung an einem; überall sonst wanderte eine beliebig
grosse Datei erst vollständig in den Arbeitsspeicher und dann in die Cloud —
darunter `POST /api/dokumente/scannen`, der Weg, über den fast jeder Beleg
hereinkommt.
"""
import asyncio
import io
import os
import sys
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_upload.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException, UploadFile  # noqa: E402

from app import upload  # noqa: E402


def _datei(inhalt: bytes, name: str = "beleg.pdf") -> UploadFile:
    return UploadFile(file=io.BytesIO(inhalt), filename=name)


def _lies(*args, **kw):
    return asyncio.run(upload.lies(*args, **kw))


# --------------------------------------------------------------------------
# Grösse
# --------------------------------------------------------------------------

def test_datei_im_rahmen_kommt_unveraendert_zurueck():
    inhalt = b"%PDF-1.4 hier steht ein Beleg"
    assert _lies(_datei(inhalt)) == inhalt


def test_zu_grosse_datei_wird_abgewiesen():
    with pytest.raises(HTTPException) as fehler:
        _lies(_datei(b"x" * 2048), max_bytes=1024)
    assert fehler.value.status_code == 400
    assert "zu groß" in fehler.value.detail


def test_die_grenze_selbst_geht_noch_durch():
    """Genau `max_bytes` ist erlaubt — sonst wäre die Grenze um ein Byte
    schärfer als angeschrieben."""
    assert len(_lies(_datei(b"x" * 1024), max_bytes=1024)) == 1024


def test_abbruch_faellt_bevor_alles_im_speicher_liegt():
    """Der eigentliche Punkt: früher stand `await datei.read()` VOR der
    Längenprüfung — eine 2-GB-Datei war zuerst vollständig im Speicher und
    wurde dann abgelehnt. Jetzt wird in Häppchen gelesen und beim ersten
    Überschreiten abgebrochen."""
    gelesen = {"bytes": 0}

    class _Endlos:
        """Eine Datei, die nie zu Ende geht — und mitzählt, wie viel schon
        gelesen wurde."""

        def read(self, groesse=-1):
            n = 1024 * 1024 if groesse in (-1, None) else groesse
            gelesen["bytes"] += n
            return b"x" * n

        def seek(self, *a, **kw):
            return 0

        def close(self):
            pass

    datei = UploadFile(file=_Endlos(), filename="riesig.pdf")
    with pytest.raises(HTTPException):
        asyncio.run(upload.lies(datei, max_bytes=4 * 1024 * 1024))
    # Ein paar Häppchen über der Grenze ist in Ordnung, ein Vielfaches nicht.
    assert gelesen["bytes"] < 8 * 1024 * 1024


# --------------------------------------------------------------------------
# Leere Datei
# --------------------------------------------------------------------------

def test_leere_datei_ist_ein_fehler():
    with pytest.raises(HTTPException) as fehler:
        _lies(_datei(b""))
    assert fehler.value.status_code == 400
    assert "leer" in fehler.value.detail.lower()


# --------------------------------------------------------------------------
# Dateiart
# --------------------------------------------------------------------------

def test_erlaubte_endung_geht_durch():
    assert _lies(_datei(b"abc", "vorlage.docx"), endungen=(".pdf", ".docx"))


def test_fremde_endung_wird_abgewiesen_und_sagt_was_geht():
    with pytest.raises(HTTPException) as fehler:
        _lies(_datei(b"abc", "urlaub.mp4"), endungen=(".pdf", ".docx"))
    assert fehler.value.status_code == 400
    assert ".pdf" in fehler.value.detail        # sagt, was möglich WÄRE
    assert ".mp4" in fehler.value.detail


def test_ohne_endungsliste_geht_jede_datei_durch():
    """Der Weg ins eigene Archiv des Nutzers legt unverändert ab — dort wird
    die Dateiart bewusst nicht eingeschränkt."""
    assert _lies(_datei(b"abc", "eigenes.xyz")) == b"abc"


def test_gross_und_kleinschreibung_der_endung_ist_egal():
    assert _lies(_datei(b"abc", "SCAN.PDF"), endungen=(".pdf",)) == b"abc"


# --------------------------------------------------------------------------
# Wirklich überall angeschlossen
# --------------------------------------------------------------------------

def test_kein_endpunkt_liest_mehr_ungeprueft():
    """Ein `await datei.read()` in einem Router heisst: dieser Endpunkt hat
    den Riegel nicht. Genau daran lag es vorher."""
    import pathlib

    wurzel = pathlib.Path(__file__).resolve().parent.parent / "app"
    treffer = []
    for datei in wurzel.rglob("*.py"):
        if datei.name == "upload.py":
            continue                            # dort steht der geprüfte Weg
        for nr, zeile in enumerate(datei.read_text().splitlines(), 1):
            if "await datei.read()" in zeile or "await bild.read()" in zeile:
                treffer.append(f"{datei.relative_to(wurzel)}:{nr}")
    assert not treffer, ("Ungeprüfter Upload — bitte über `upload.lies`: "
                         + ", ".join(treffer))
