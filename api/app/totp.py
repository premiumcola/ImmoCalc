"""N472 — Zweiter Faktor per Authenticator-App (TOTP, RFC 6238).

Kein neues Paket: der komplette Algorithmus braucht nur `hmac`, `hashlib`,
`struct`, `base64`, `secrets`, `time` — allesamt Python-Standardbibliothek.
`pyotp` wäre die erste Fremdabhängigkeit für die Anmeldung gewesen; unnötig
bei ~15 Zeilen echtem Rechenkern.

HMAC-**SHA1** ist hier bewusst richtig, nicht unsicher: das ist der von
RFC 6238 vorgegebene und von praktisch jeder Authenticator-App (Google
Authenticator, Aegis, Authy, Microsoft Authenticator) fest erwartete
Algorithmus, mit fest erwarteten 30 Sekunden Schrittweite und 6 Ziffern.
SHA-256 wäre theoretisch stärker, aber viele Apps unterstützen nur den
Standardfall — eine "sicherere" Wahl hier würde nur die Kompatibilität
brechen, ohne den zeitlich ohnehin sehr kurzen Angriffszeitraum eines
6-stelligen Codes nennenswert zu verbessern.

Kein QR-Code-Bild: `CLAUDE.md` verbietet neue Frontend-Bibliotheken außer
Google Fonts, ein QR-Renderer wäre die erste Ausnahme. Der Base32-Schlüssel
als Text plus der `otpauth://`-Link decken denselben Zweck ab — "Setup-Key
manuell eingeben" ist in jeder Authenticator-App ein first-class
unterstützter Weg, keine Krücke."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# RFC-6238-Standardwerte — das, was jede Authenticator-App voraussetzt, ohne
# dass die App selbst Schrittweite/Ziffernzahl mitgeteilt bekommen müsste.
_SCHRITT_SEKUNDEN = 30
_ZIFFERN = 6
# ±1 Schritt Toleranz gegen leichte Uhr-Drift zwischen Handy und Server.
_FENSTER = 1


def geheimnis_neu() -> str:
    """Ein neues, zufälliges Base32-Geheimnis (160 Bit) — der Rohwert, der
    in `Familie.totp_geheimnis` liegt und in die Authenticator-App wandert."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_fuer(geheimnis: str, zeitfenster: int) -> str:
    """Der 6-stellige Code für ein bestimmtes 30-Sekunden-Fenster."""
    aufgefuellt = geheimnis + "=" * (-len(geheimnis) % 8)
    schluessel = base64.b32decode(aufgefuellt, casefold=True)
    nachricht = struct.pack(">Q", zeitfenster)
    digest = hmac.new(schluessel, nachricht, hashlib.sha1).digest()
    versatz = digest[-1] & 0x0F
    stueck = struct.unpack(">I", digest[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return str(stueck % 10 ** _ZIFFERN).zfill(_ZIFFERN)


def code_pruefen(geheimnis: str, eingabe: str, zeitpunkt: float | None = None) -> bool:
    """Zeitkonstanter Vergleich gegen das aktuelle Fenster ±`_FENSTER`
    Schritte — kein Rückschluss darauf, welcher Versuch am nächsten dran war."""
    eingabe = (eingabe or "").strip()
    if not eingabe:
        return False
    jetzt = int((zeitpunkt if zeitpunkt is not None else time.time())
                // _SCHRITT_SEKUNDEN)
    return any(hmac.compare_digest(_code_fuer(geheimnis, jetzt + versatz), eingabe)
               for versatz in range(-_FENSTER, _FENSTER + 1))


def otpauth_url(geheimnis: str, familienname: str) -> str:
    """Der `otpauth://`-Link für die Einrichtung — als Tap-Link UND als
    Grundlage für einen künftigen QR-Code, sollte der einmal dazukommen."""
    label = quote(f"ImmoCalc:{familienname}")
    return (f"otpauth://totp/{label}?secret={geheimnis}&issuer=ImmoCalc"
            f"&digits={_ZIFFERN}&period={_SCHRITT_SEKUNDEN}")


def wiederherstellungscodes_neu(anzahl: int = 8) -> list[str]:
    """Einmal-Codes für den Fall, dass das Handy mit der Authenticator-App
    weg ist. Nicht auswendig gelernt, nicht wiederverwendet — deshalb reicht
    ein einfacher Zufallswert ohne Passwort-KDF (siehe `code_hashen`)."""
    return [f"{secrets.token_hex(5)[:5]}-{secrets.token_hex(5)[5:]}"
            for _ in range(anzahl)]


def code_hashen(code: str) -> str:
    """SHA-256 reicht für einen Wiederherstellungscode — er ist bereits
    hochentropisch und einmalig, kein von Menschen gewähltes, wiederverwendetes
    Geheimnis wie ein Passwort. Groß-/Kleinschreibung und Bindestriche werden
    vor dem Hashen vereinheitlicht, damit ein Tippfehler bei der Schreibweise
    nicht an einem an sich richtigen Code scheitert."""
    bereinigt = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(bereinigt.encode("utf-8")).hexdigest()
