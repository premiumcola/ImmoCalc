"""N470 — Nextcloud-Ordnerliste bricht bei einem Benutzernamen mit Sonderzeichen.

Gefunden am 03.09.2026 durch den Nutzer: eine neu angelegte Familie hat einen
E-Mail-artigen Nextcloud-Login (`t.luther@reifen-luther.de`). Die Verbindung
liess sich einrichten, aber jeder Klick auf einen Unterordner endete mit
„Ordner nicht gefunden" — obwohl der Ordner existiert.

Ursache in `Nextcloud.liste()`: der `href` aus der PROPFIND-Antwort wird
`unquote()`t, bevor der Wurzel-Pfad davon abgeschnitten wird — der Wurzel-Pfad
selbst blieb aber `quote()`-kodiert. Für einen Benutzernamen ohne
Sonderzeichen kodiert `quote()` auf sich selbst ab, der Unterschied fiel nie
auf. Das `@` im Login kodiert zu `%40`: das `startswith`-Abschneiden traf nie,
der GANZE absolute WebDAV-Pfad blieb als `pfad` jedes Eintrags stehen. Beim
Anklicken eines Unterordners kam dieser volle Pfad ein zweites Mal vor die
Wurzel — ein nicht existierender, verdoppelter Pfad, daher „nicht gefunden".
"""
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_nextcloud_benutzer_mit_at.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.nextcloud import Nextcloud  # noqa: E402

BENUTZER = "t.luther@reifen-luther.de"


def _propfind_antwort(hrefs_ordner: list[str], hrefs_dateien: list[str] = ()):
    """Baut eine minimale PROPFIND-Multistatus-Antwort wie Nextcloud sie
    tatsächlich schickt: der Benutzername im `href` PROZENT-KODIERT (`%40`),
    wie es ein echter Server tut."""
    teile = ['<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">']
    for href in hrefs_ordner:
        teile.append(f"""<d:response><d:href>{href}</d:href>
          <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
        </d:response>""")
    for href in hrefs_dateien:
        teile.append(f"""<d:response><d:href>{href}</d:href>
          <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>10</d:getcontentlength>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
        </d:response>""")
    teile.append("</d:multistatus>")
    return "".join(teile)


class WolkeMitSonderzeichen(Nextcloud):
    """Wie ein echter Server: liefert Ordner unterhalb des angefragten Pfads,
    Hrefs percent-kodiert wie `quote()` es auch für die eigene Wurzel tut."""

    def __init__(self, kinder: dict[str, list[str]]):
        super().__init__("https://cloud.test", BENUTZER, "geheim")
        self._kinder = kinder

    def _anfrage(self, methode: str, pfad: str, **kw):
        assert methode == "PROPFIND"
        eigen = "/" + pfad.strip("/") if pfad.strip("/") else ""
        if eigen not in self._kinder:
            return SimpleNamespace(status_code=404, text="")
        wurzel = self._wurzel  # bereits quote()-kodiert, wie beim echten Client
        hrefs = [f"{wurzel}{eigen}{k}" for k in self._kinder[eigen]]
        return SimpleNamespace(status_code=207,
                               text=_propfind_antwort(hrefs))


def test_ordner_liste_gibt_relative_pfade_trotz_at_im_benutzernamen():
    """Der eigentliche Fund: `pfad` eines Eintrags muss relativ zur Wurzel
    sein — NICHT der ganze absolute WebDAV-Pfad."""
    client = WolkeMitSonderzeichen({"": ["/Documents", "/Fotos"]})

    eintraege = client.liste("")

    namen = {e.name for e in eintraege}
    assert namen == {"Documents", "Fotos"}
    # `Eintrag.pfad` trägt konventionell einen führenden Schrägstrich (siehe
    # `test_gewoehnlicher_benutzername_bleibt_unveraendert`) — worauf es hier
    # ankommt, ist NICHT der Schrägstrich, sondern dass nichts vom absoluten
    # WebDAV-Pfad (`/remote.php/dav/files/…`) übrig bleibt.
    pfade = {e.pfad for e in eintraege}
    assert pfade == {"/Documents", "/Fotos"}, (
        f"der Wurzel-Pfad wurde nicht abgeschnitten: {pfade}")


def test_unterordner_ist_danach_wieder_anklickbar():
    """Der eigentliche Ausfall aus dem Bug-Report: nach dem ersten Klick
    (Ordnerliste holen) muss der zweite Klick (in den Unterordner hinein)
    denselben, weiterhin gültigen relativen Pfad benutzen."""
    client = WolkeMitSonderzeichen({
        "": ["/Documents"],
        "/Documents": ["/2026"],
    })

    obenliegend = client.liste("")
    documents = next(e for e in obenliegend if e.name == "Documents")

    # Genau das, was ordnerZeigen() im Frontend als nächstes tut: mit dem
    # zurückgegebenen `pfad` erneut anfragen.
    unterordner = client.liste(documents.pfad)
    assert {e.name for e in unterordner} == {"2026"}


def test_gewoehnlicher_benutzername_bleibt_unveraendert():
    """Gegenprobe: ein Benutzername ohne Sonderzeichen verhielt sich schon
    vorher richtig — das darf sich nicht ändern."""
    class WolkeOhneSonderzeichen(Nextcloud):
        def __init__(self):
            super().__init__("https://cloud.test", "nutzer", "geheim")

        def _anfrage(self, methode, pfad, **kw):
            wurzel = self._wurzel
            return SimpleNamespace(
                status_code=207,
                text=_propfind_antwort([f"{wurzel}/Rechnungen"]))

    eintraege = WolkeOhneSonderzeichen().liste("")
    assert eintraege[0].pfad == "/Rechnungen"
