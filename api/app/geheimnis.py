"""N475 — Zugangsdaten verschlüsselt in der Datenbank ablegen.

Bis hierher lagen Nextcloud-Passwort, Postfach-Passwort, KI-Schlüssel, das
WebDAV-Passwort fürs Backup und das TOTP-Geheimnis im KLARTEXT in
`immocalc.db` (N469 Punkt 11). Wer die Datei in die Hand bekam, hatte damit
zugleich den Zugang zur Cloud des Nutzers, zu seinem Postfach und die
Möglichkeit, gültige Zwei-Faktor-Codes zu erzeugen.

**Was das hier löst und was nicht.** Der Schlüssel kommt aus der Umgebung
(`GEHEIMNIS_SCHLUESSEL`, Server-env-Datei) und nicht aus einem Nutzer-
Passwort — anders ginge es nicht: der nächtliche Backup-Lauf und der
Wachdienst müssen um drei Uhr morgens ohne Zutun an die Zugangsdaten. Damit
gilt:

* Wer NUR die Datenbank hat (eine kopierte Sicherung, ein weggeworfenes
  Laufwerk, eine Datei-Lücke in der App), bekommt nichts mehr.
* Wer Datenbank UND env-Datei hat, bekommt alles — der steht dann aber
  ohnehin schon im Container und hat die laufende App.

Das ist der ehrliche Gewinn: von „eine Datei genügt" auf „zwei Dinge an zwei
Orten". Ein Hardware-Schlüssel wäre die nächste Stufe und ist auf einem
Heimserver nicht zu haben.

**Verfahren.** AES-256-GCM (authentifiziert: ein verändertes Byte fällt auf,
statt Datenmüll zu liefern), Schlüssel per scrypt aus der Umgebungsvariable.
Bewusst mit FESTEM Salz, damit derselbe Wert in der Umgebung immer denselben
Schlüssel ergibt — das Salz schützt gegen vorberechnete Tabellen auf
schwache, von Menschen gewählte Passwörter; hier steht ein langer Zufallswert
aus der env-Datei, und gebraucht wird Wiederholbarkeit.

**Format.** `gcm1:<base64(nonce|ciphertext+siegel)>`. Das Präfix ist der
ganze Trick beim Umstieg: `lesen()` erkennt daran, ob ein Wert überhaupt
verschlüsselt ist, und reicht alles andere unverändert durch. Deshalb
funktioniert die App mit gemischtem Bestand, mit oder ohne gesetzten
Schlüssel — und der Umstieg (`migrate.geheimnisse_schuetzen`) ist ein
gewöhnliches Lesen-und-Zurückschreiben."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import String, TypeDecorator

log = logging.getLogger("immocalc")

PRAEFIX = "gcm1:"
_NONCE_LAENGE = 12
_SALZ = b"immocalc-geheimnis-v1"
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1

# Die Einstellungs-Schlüssel, deren Wert ein Geheimnis ist. Alles andere
# (Adressen, Ordnernamen, Vorlagen, Versand-Marker) bleibt lesbar — sonst
# liesse sich die Datenbank nicht mehr von Hand prüfen, ohne dass es dem
# Schutz etwas brächte.
GEHEIME_SCHLUESSEL = frozenset({
    "nc_passwort",          # Nextcloud (cloudkern.S_PASSWORT)
    "mail_passwort",        # Postfach (routers/mail.S_PASSWORT)
    "ki_api_key",           # Anthropic (routers/ki.S_KI_KEY)
})

_schluessel_zwischenspeicher: tuple[str, bytes] | None = None
_gewarnt = False


def _umgebungswert() -> str:
    return os.environ.get("GEHEIMNIS_SCHLUESSEL", "").strip()


def aktiv() -> bool:
    """Ob überhaupt verschlüsselt wird. Ohne gesetzte Umgebungsvariable
    verhält sich alles wie vor N475 — bewusst, damit eine bestehende
    Installation ohne Zutun weiterläuft."""
    return bool(_umgebungswert())


def _schluessel() -> bytes:
    """scrypt ist teuer (20-40 ms); `_lies` läuft aber im Wachdienst-Takt und
    an jeder Cloud-Anfrage. Deshalb einmal ableiten und behalten — neu
    abgeleitet nur, wenn sich die Umgebungsvariable ändert (Tests)."""
    global _schluessel_zwischenspeicher
    roh = _umgebungswert()
    if _schluessel_zwischenspeicher and _schluessel_zwischenspeicher[0] == roh:
        return _schluessel_zwischenspeicher[1]
    abgeleitet = hashlib.scrypt(roh.encode("utf-8"), salt=_SALZ, n=_SCRYPT_N,
                                r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    _schluessel_zwischenspeicher = (roh, abgeleitet)
    return abgeleitet


def ist_geschuetzt(wert: str | None) -> bool:
    return bool(wert) and wert.startswith(PRAEFIX)


def schuetzen(wert: str | None) -> str | None:
    """Verschlüsselt einen Wert. Ohne gesetzten Schlüssel, bei leerem Wert
    oder bei einem bereits geschützten Wert bleibt er, wie er ist."""
    if not wert or not aktiv() or ist_geschuetzt(wert):
        return wert
    nonce = secrets.token_bytes(_NONCE_LAENGE)
    roh = AESGCM(_schluessel()).encrypt(nonce, wert.encode("utf-8"), None)
    return PRAEFIX + base64.b64encode(nonce + roh).decode("ascii")


def lesen(wert: str | None) -> str | None:
    """Entschlüsselt einen Wert — oder gibt ihn unverändert zurück, wenn er
    gar nicht verschlüsselt ist (Bestand vor N475, nicht geheime Werte).

    Bei falschem Schlüssel wird NICHT geworfen: sonst käme die App bei einer
    vertauschten env-Datei nicht einmal mehr hoch, und ein Zugang, den man
    nicht mehr lesen kann, ist genau so gut wie ein leerer. Stattdessen laut
    ins Log und "" zurück — die Oberfläche sagt dann „noch nicht
    eingerichtet", und der Nutzer trägt es neu ein."""
    global _gewarnt
    if not ist_geschuetzt(wert):
        return wert
    if not aktiv():
        if not _gewarnt:
            log.error("In der Datenbank liegen verschlüsselte Zugangsdaten, "
                      "aber GEHEIMNIS_SCHLUESSEL ist nicht gesetzt — sie "
                      "bleiben unlesbar, bis die Variable wieder da ist.")
            _gewarnt = True
        return ""
    roh = base64.b64decode(wert[len(PRAEFIX):])
    try:
        klar = AESGCM(_schluessel()).decrypt(roh[:_NONCE_LAENGE],
                                             roh[_NONCE_LAENGE:], None)
    except (InvalidTag, ValueError):
        if not _gewarnt:
            log.error("Zugangsdaten lassen sich nicht entschlüsseln — passt "
                      "GEHEIMNIS_SCHLUESSEL noch zu dieser Datenbank? Bis "
                      "dahin gelten sie als nicht eingerichtet.")
            _gewarnt = True
        return ""
    return klar.decode("utf-8")


class Geheim(TypeDecorator):
    """Spaltentyp für ein Geheimnis: verschlüsselt beim Schreiben,
    entschlüsselt beim Lesen — für jeden Aufrufer unsichtbar.

    Damit sind die betroffenen Spalten an EINER Stelle geschützt statt an
    jedem Zugriff einzeln, und der Familien-Export (`model_dump`) bekommt
    automatisch den Klartext: eine Sicherung muss sich auf einer frischen
    Instanz mit ANDEREM `GEHEIMNIS_SCHLUESSEL` wiederherstellen lassen. Sie
    ist ja bereits als Ganzes mit dem Backup-Passwort verschlüsselt."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return schuetzen(value)

    def process_result_value(self, value, dialect):
        return lesen(value)
