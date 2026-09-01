"""N436 — Passwort-Hashing und Sitzungs-Token für die Familien-Anmeldung.

Kein neues Paket: `hashlib.scrypt` ist Python-Standardbibliothek und ein
moderner, speicherharter KDF (RFC 7914) — geeigneter als bcrypt, ohne eine
weitere Abhängigkeit zu ziehen. Weder ein rohes Passwort noch ein roher
Sitzungs-Token wird je gespeichert, nur ihr Hash — ein Datenbank-Dump gibt
also keine gültige Sitzung und kein Passwort preis.

Die Brute-Force-Bremse (Zähler + Sperre direkt an `Familie`) ist bewusst
einfach gehalten: kein Redis, kein neues Paket — für eine Handvoll Familien
hinter einem VPN reicht das."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

SITZUNG_COOKIE = "immocalc_sitzung"
SITZUNG_GUELTIGKEIT = timedelta(days=30)
MAX_FEHLVERSUCHE = 8
SPERRDAUER = timedelta(minutes=5)

# scrypt-Parameter (RFC 7914, interaktive Anmeldung): N=2^14 kostet auf
# gewöhnlicher Server-Hardware ca. 20-40 ms — spürbar für einen
# Brute-Force-Versuch, unmerklich für eine einzelne Anmeldung.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def passwort_hashen(passwort: str) -> tuple[str, str]:
    """Gibt (hash_hex, salz_hex) zurück — beides in `Familie` zu speichern."""
    salz = secrets.token_hex(16)
    berechnet = hashlib.scrypt(
        passwort.encode("utf-8"), salt=bytes.fromhex(salz),
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return berechnet.hex(), salz


def passwort_pruefen(passwort: str, hash_hex: str, salz_hex: str) -> bool:
    """Zeitkonstanter Vergleich — kein Rückschluss auf die Trefferlänge."""
    berechnet = hashlib.scrypt(
        passwort.encode("utf-8"), salt=bytes.fromhex(salz_hex),
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return hmac.compare_digest(berechnet.hex(), hash_hex)


def token_hashen(token: str) -> str:
    """SHA-256 reicht hier — der Token selbst ist schon 32 zufällige Bytes
    (secrets.token_urlsafe), es geht nur ums Verschleiern beim Speichern,
    nicht um Brute-Force-Härte wie beim Passwort."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def neuer_sitzungstoken() -> tuple[str, str, datetime]:
    """Gibt (roher_token, token_hash, laeuft_ab) zurück. Der rohe Token geht
    nur ins Cookie — in der Datenbank landet ausschließlich sein Hash."""
    token = secrets.token_urlsafe(32)
    return token, token_hashen(token), datetime.utcnow() + SITZUNG_GUELTIGKEIT
