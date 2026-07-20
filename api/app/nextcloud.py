"""WebDAV-Zugriff auf Nextcloud.

Bewusst ohne Zusatzbibliothek: WebDAV ist HTTP mit den Methoden PROPFIND
(auflisten), MKCOL (Ordner anlegen), PUT/GET (Datei) und MOVE (verschieben
bzw. umbenennen).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

import httpx

log = logging.getLogger("immocalc")

DAV = "{DAV:}"
PROPFIND_RUMPF = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"><d:prop>
  <d:resourcetype/><d:getcontentlength/><d:getlastmodified/>
</d:prop></d:propfind>"""


@dataclass
class Eintrag:
    name: str
    pfad: str
    ordner: bool
    groesse: int = 0


class NextcloudFehler(RuntimeError):
    pass


# Pfade, die beim Kopieren aus der Adresszeile mitkommen. Nextcloud darf in
# einem Unterverzeichnis liegen (https://host/nextcloud), deshalb wird nur ab
# diesen Markern abgeschnitten statt der Pfad pauschal verworfen.
_ANHAENGSEL = ("/login", "/index.php", "/apps/", "/settings/", "/remote.php")


def normalisiere_url(url: str) -> str:
    """Macht aus einer kopierten Browser-Adresse die Server-Basisadresse."""
    roh = (url or "").strip()
    if not roh:
        return ""
    if "://" not in roh:
        roh = "https://" + roh
    teile = urlparse(roh)
    pfad = teile.path or ""
    for marker in _ANHAENGSEL:
        stelle = pfad.find(marker)
        if stelle >= 0:
            pfad = pfad[:stelle]
            break
    return f"{teile.scheme}://{teile.netloc}{pfad.rstrip('/')}"


class AussenhalbHome(NextcloudFehler):
    """Ein Schreibzugriff sollte ausserhalb des freigegebenen Ordners landen."""


def _normpfad(pfad: str) -> str:
    return "/" + "/".join(t for t in (pfad or "").split("/") if t and t != ".")


class Nextcloud:
    def __init__(self, url: str, benutzer: str, passwort: str,
                 zertifikat_pruefen: bool = False, timeout: float = 15.0,
                 heimat: str = ""):
        self.basis = normalisiere_url(url)
        self.benutzer = benutzer
        self._auth = (benutzer, passwort)
        self._pruefen = zertifikat_pruefen
        self._timeout = timeout
        # Schreibzugriffe sind auf diesen Ordner begrenzt. Leer = nur Lesen.
        self.heimat = _normpfad(heimat) if heimat else ""

    def _pruefe_schreibrecht(self, pfad: str) -> None:
        """Riegel vor jedem verändernden Zugriff.

        Ein '..' im Pfad oder ein Ziel ausserhalb des Home-Ordners bricht ab,
        bevor irgendetwas gesendet wird."""
        if ".." in (pfad or "").split("/"):
            raise AussenhalbHome(f"Unzulässiger Pfad: {pfad}")
        if not self.heimat:
            raise AussenhalbHome(
                "Kein Home-Ordner festgelegt — es wird nichts geschrieben.")
        ziel = _normpfad(pfad)
        if ziel != self.heimat and not ziel.startswith(self.heimat + "/"):
            raise AussenhalbHome(
                f"'{ziel}' liegt ausserhalb von '{self.heimat}' — "
                "ImmoCalc verändert dort nichts.")

    @property
    def _wurzel(self) -> str:
        return f"{self.basis}/remote.php/dav/files/{quote(self.benutzer)}"

    def _url(self, pfad: str) -> str:
        teile = [quote(t) for t in pfad.strip("/").split("/") if t]
        return self._wurzel + ("/" + "/".join(teile) if teile else "")

    def _anfrage(self, methode: str, pfad: str, **kw) -> httpx.Response:
        try:
            with httpx.Client(verify=self._pruefen, timeout=self._timeout,
                              follow_redirects=True) as client:
                return client.request(methode, self._url(pfad), auth=self._auth, **kw)
        except httpx.HTTPError as e:
            raise NextcloudFehler(f"Nextcloud nicht erreichbar: {e}") from e

    def pruefe(self) -> dict:
        """Verbindungstest — liefert eine kurze Rückmeldung für die Oberfläche."""
        antwort = self._anfrage("PROPFIND", "", headers={"Depth": "0"},
                                content=PROPFIND_RUMPF)
        if antwort.status_code == 401:
            raise NextcloudFehler("Anmeldung fehlgeschlagen — Benutzer oder App-Passwort falsch")
        if antwort.status_code in (404, 405):
            raise NextcloudFehler(
                f"Unter {self.basis} liegt kein WebDAV-Zugang. Bitte nur die "
                "Server-Adresse angeben, z. B. https://192.168.178.10:444 "
                "— ohne /login oder weitere Pfade.")
        if antwort.status_code >= 400:
            raise NextcloudFehler(f"Unerwartete Antwort {antwort.status_code}")
        return {"ok": True, "benutzer": self.benutzer, "url": self.basis}

    def liste(self, pfad: str = "") -> list[Eintrag]:
        """Direkte Kinder eines Ordners, Ordner zuerst."""
        antwort = self._anfrage("PROPFIND", pfad, headers={"Depth": "1"},
                                content=PROPFIND_RUMPF)
        if antwort.status_code == 404:
            raise NextcloudFehler(f"Ordner nicht gefunden: /{pfad.strip('/')}")
        if antwort.status_code >= 400:
            raise NextcloudFehler(f"Auflisten fehlgeschlagen ({antwort.status_code})")

        wurzel_pfad = urlparse(self._wurzel).path.rstrip("/")
        eigener = "/" + pfad.strip("/") if pfad.strip("/") else ""
        eintraege: list[Eintrag] = []

        for response in ElementTree.fromstring(antwort.text).findall(f"{DAV}response"):
            href = response.findtext(f"{DAV}href") or ""
            relativ = unquote(urlparse(href).path)
            if relativ.startswith(wurzel_pfad):
                relativ = relativ[len(wurzel_pfad):]
            relativ = "/" + relativ.strip("/") if relativ.strip("/") else ""
            if relativ == eigener:
                continue  # der Ordner selbst

            props = response.find(f"{DAV}propstat/{DAV}prop")
            ist_ordner = props is not None and \
                props.find(f"{DAV}resourcetype/{DAV}collection") is not None
            groesse = props.findtext(f"{DAV}getcontentlength") if props is not None else None
            eintraege.append(Eintrag(
                name=relativ.rstrip("/").split("/")[-1],
                pfad=relativ.rstrip("/"),
                ordner=ist_ordner,
                groesse=int(groesse) if groesse and groesse.isdigit() else 0,
            ))

        eintraege.sort(key=lambda e: (not e.ordner, e.name.lower()))
        return eintraege

    def ordner_anlegen(self, pfad: str) -> bool:
        """Legt einen Ordner an. Bestehende bleiben unangetastet."""
        self._pruefe_schreibrecht(pfad)
        antwort = self._anfrage("MKCOL", pfad)
        if antwort.status_code in (201, 405):   # 405 = existiert bereits
            return antwort.status_code == 201
        raise NextcloudFehler(
            f"Ordner '{pfad}' konnte nicht angelegt werden ({antwort.status_code})")

    def ordner_baum_anlegen(self, wurzel: str, unterordner: list[str]) -> list[str]:
        """Legt Wurzel und Unterordner an; gibt die neu erstellten zurück."""
        neu = []
        pfad = ""
        for teil in wurzel.strip("/").split("/"):
            pfad = f"{pfad}/{teil}" if pfad else teil
            # Ebenen oberhalb des Home-Ordners existieren bereits und werden
            # bewusst nicht angefasst.
            if self.heimat and not _normpfad(pfad).startswith(self.heimat):
                continue
            if self.ordner_anlegen(pfad):
                neu.append("/" + pfad)
        for unter in unterordner:
            if self.ordner_anlegen(f"{wurzel.strip('/')}/{unter}"):
                neu.append(f"/{wurzel.strip('/')}/{unter}")
        return neu

    def lege_ab(self, pfad: str, inhalt: bytes,
                typ: str = "application/pdf") -> None:
        """Datei hochladen. Ueberschreibt eine gleichnamige Datei nicht —
        der Aufrufer sorgt fuer einen freien Namen."""
        self._pruefe_schreibrecht(pfad)
        antwort = self._anfrage("PUT", pfad, content=inhalt,
                                headers={"Content-Type": typ})
        if antwort.status_code >= 400:
            raise NextcloudFehler(
                f"Hochladen fehlgeschlagen ({antwort.status_code}): {pfad}")

    def existiert(self, pfad: str) -> bool:
        antwort = self._anfrage("PROPFIND", pfad, headers={"Depth": "0"},
                                content=PROPFIND_RUMPF)
        return antwort.status_code < 400

    def verschiebe(self, von: str, nach: str) -> None:
        # beide Seiten pruefen: weder Quelle noch Ziel duerfen ausserhalb liegen
        self._pruefe_schreibrecht(von)
        self._pruefe_schreibrecht(nach)
        antwort = self._anfrage("MOVE", von, headers={
            "Destination": self._url(nach), "Overwrite": "F"})
        if antwort.status_code >= 400:
            raise NextcloudFehler(
                f"Verschieben fehlgeschlagen ({antwort.status_code}): {von} -> {nach}")
