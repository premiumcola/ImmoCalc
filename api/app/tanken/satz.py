"""Der Satz je kWh — abgeleitet, nicht eingegeben (N148).

Netzstrom kostet den Durchschnittspreis des Netzbezugs, eigener Strom
:data:`EIGEN_RABATT` darunter, der Mischsatz gewichtet nach den Mengen des
Zeitraums. Grundlage ist die Stromkette der passenden Abrechnungsperiode."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from ..models import Zeitraum

log = logging.getLogger("immocalc")

# Eigener Strom (PV und Akku) kostet an der Ladestation 10 % weniger als
# zugekaufter. Feste Vorgabe des Betreibers — keine gerechnete Größe, deshalb
# hier einmal benannt statt als nackte 0,9 im Code verstreut.
EIGEN_RABATT = 0.10


@dataclass
class Satz:
    """Der abgeleitete Preis je kWh — mit seiner Herkunft (N148).

    `netz` ist der Durchschnittspreis des Netzbezugs, `eigen` liegt
    :data:`EIGEN_RABATT` darunter, `misch` ist der, den der Nutzer zahlt: eine
    Ladung speist sich aus beidem, gewichtet nach den Mengen des Zeitraums.

    Steht kein Satz fest, sind alle drei ``None`` und `grund` sagt, was dafür
    fehlt. **Keine 0,00 € als Notnagel** — eine Rechnung über null ohne
    erkennbaren Grund war hier schon einmal ein Problem."""
    netz: float | None = None
    eigen: float | None = None
    misch: float | None = None
    herkunft: str = ""
    grund: str = ""


def eigen_satz(netz_preis: float) -> float:
    """Was eigener Strom (PV und Akku) an der Ladestation kostet."""
    return round(netz_preis * (1.0 - EIGEN_RABATT), 5)


def mischsatz(netz_preis: float, eigen_preis: float, extern_kwh: float | None,
              eigen_kwh: float | None) -> float:
    """Der Satz einer Ladung: Netz und eigener Strom nach ihren Mengen.

    Ist die Aufteilung des Zeitraums nicht bekannt (`extern_kwh`/`eigen_kwh`
    sind dann ``None``), gilt der **Netzpreis**. Den günstigeren eigenen Satz
    zu unterstellen, ohne zu wissen, ob eigener Strom geflossen ist, wäre ein
    Rabatt auf Verdacht."""
    if extern_kwh is None or eigen_kwh is None:
        return netz_preis
    ganz = max(0.0, extern_kwh) + max(0.0, eigen_kwh)
    if ganz <= 0:
        return netz_preis
    return round((max(0.0, extern_kwh) * netz_preis
                  + max(0.0, eigen_kwh) * eigen_preis) / ganz, 5)


def deutsch(wert: float, stellen: int = 2) -> str:
    """Eine Zahl in deutscher Schreibweise: „1.234,56".

    Python setzt Komma und Punkt genau andersherum; `translate` tauscht
    beide in einem Durchgang — nacheinander ersetzen würde die eigene
    Arbeit wieder einsammeln."""
    return f"{wert:,.{stellen}f}".translate(str.maketrans(",.", ".,"))


def _ueberlappung(a_von: date, a_bis: date, b_von: date, b_bis: date) -> int:
    """Wie viele Tage zwei Zeitspannen gemeinsam haben (beide Ränder zählen)."""
    return max(0, (min(a_bis, b_bis) - max(a_von, b_von)).days + 1)


def passender_zeitraum(zeitraeume: list[Zeitraum], von: date,
                       bis: date) -> Zeitraum | None:
    """Der Abrechnungszeitraum, der ein Quartal am weitesten trägt.

    Die Nebenkostenperiode läuft z. B. vom 01.10.2024 bis 30.09.2025, ein
    Quartal aber am Kalender entlang. Gewählt wird der Zeitraum mit der
    größten Überschneidung; bei Gleichstand der spätere — die jüngere Rechnung
    beschreibt den Preis besser. Ohne jede Überschneidung: ``None``."""
    treffer = [(_ueberlappung(z.start, z.ende, von, bis), z.start, z)
               for z in zeitraeume]
    treffer = [t for t in treffer if t[0] > 0]
    if not treffer:
        return None
    return max(treffer, key=lambda t: (t[0], t[1]))[2]


def _stromkette_holen(session: Session, zid: int) -> dict:
    """Die Stromkette eines Zeitraums — erst beim Aufruf importiert.

    **Bewusst hier drin und nicht oben:** `routers/stromkette` importiert
    seinerseits `erfasste_ladungen` aus diesem Modul. Ein Import auf Modulebene
    liefe deshalb im Kreis und schlüge — je nach Ladereihenfolge — mit einem
    `ImportError` fehl, den ein `try/except` still zu „die Stromkette gibt es
    nicht" verharmlosen würde. Zur Aufrufzeit sind beide Module fertig
    geladen, und der Kreis löst sich auf."""
    from ..routers.stromkette import stromkette
    return stromkette(zid, session)


def satz_ableiten(session: Session, objekt_id: int, von: date, bis: date,
                  extern_kwh: float | None = None,
                  eigen_kwh: float | None = None) -> Satz:
    """Der Preis je kWh für einen Abrechnungszeitraum — aus der Stromkette.

    Netzstrom kostet den Durchschnittspreis des Netzbezugs: den Gesamtbetrag
    der Strom-Positionen geteilt durch die bezogenen kWh. Die Grundgebühr
    steckt im Betrag und wird **nicht** getrennt umgelegt — genau deshalb ist
    es ein Durchschnitt. Eigener Strom liegt :data:`EIGEN_RABATT` darunter.

    Eingegeben wird nichts: `Stromjahr.tanken_preis` und `Tankladung.preis`
    bleiben ungelesen. Fehlt die Rechnung, kommt ein leerer :class:`Satz` mit
    `grund` zurück — nicht 0,00 €."""
    zeitraeume = list(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all())
    z = passender_zeitraum(zeitraeume, von, bis)
    if z is None:
        return Satz(grund="Für diesen Zeitraum gibt es noch keine "
                          "Abrechnungsperiode. Der Satz entsteht aus den "
                          "Stromkosten einer Periode — ohne sie lässt er sich "
                          "nicht ermitteln.")
    try:
        kette = _stromkette_holen(session, z.id)
    except Exception as fehler:            # noqa: BLE001 - fremde Kette
        log.info("E-Tankstelle: Stromkette %s nicht rechenbar — %s", z.id,
                 fehler)
        return Satz(grund=f"Die Stromkosten des Zeitraums "
                          f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y} lassen sich "
                          f"gerade nicht ermitteln ({fehler}).")

    schritt1 = kette.get("schritt1") or {}
    netz = schritt1.get("netz") or {}
    betrag, menge = netz.get("betrag") or 0.0, netz.get("kwh") or 0.0
    # N173 — der Fahrer zahlt den GEEICHTEN Netzsatz (Betrag ÷ geeichte
    # Rechnungsmenge), nicht den Verteilungssatz der Mieter (Betrag ÷
    # SolarEdge-Menge). Fehlt die geeichte Menge, hat die Kette bereits auf den
    # Verteilungssatz zurückgestellt — dann ist `netz_preis_geeicht` == diesem.
    netz_preis = schritt1.get("netz_preis_geeicht")
    geeichte_menge = schritt1.get("geeichte_menge") or 0.0
    label = (kette.get("zeitraum") or {}).get("label", "")
    quelle = schritt1.get("quelle_betrag") or ""
    # Zwei Hälften, zwei verschiedene Lücken. Welche fehlt, gehört benannt —
    # „die Stromkosten fehlen" wäre falsch, wenn nur die Menge fehlt.
    if betrag <= 0:
        return Satz(grund=(
            f"Für den Zeitraum {label} ist noch kein Betrag für den Netzbezug "
            "erfasst. Der Satz entsteht aus diesem Betrag geteilt durch die "
            "bezogenen kWh — sobald die Stromkosten in den Nebenkosten "
            "stehen, rechnet er sich von selbst."))
    if netz_preis is None:
        # Weder die geeichte Rechnungsmenge noch die SolarEdge-Menge ist da —
        # ohne Nenner kein Durchschnittspreis.
        # Die Quellenangabe bringt selbst schon Klammern mit (Belegname) —
        # noch ein Klammerpaar drumherum liest sich wie ein Tippfehler.
        return Satz(grund=(
            f"Für den Zeitraum {label} steht der Betrag — "
            f"{quelle or f'{deutsch(betrag)} €'} —, aber nicht die bezogene "
            "Menge: ohne die kWh des Netzbezugs gibt es keinen "
            "Durchschnittspreis. Die Menge ergibt sich aus dem "
            "Gesamtverbrauch und den SolarEdge-Anteilen am Strom-Jahr."))

    # Die Menge, die den Satz trägt: die geeichte Rechnungsmenge, sonst
    # (Rückfall) die SolarEdge-Netzmenge — dieselbe, auf die die Kette dann auch
    # zurückgestellt hat.
    satz_menge = geeichte_menge if geeichte_menge > 0 else menge
    geeicht_hinweis = ("geeichte Rechnungsmenge" if geeichte_menge > 0
                       else "SolarEdge-Menge, geeichte Menge fehlt")
    eigen_preis = eigen_satz(netz_preis)
    return Satz(
        netz=netz_preis, eigen=eigen_preis,
        misch=mischsatz(netz_preis, eigen_preis, extern_kwh, eigen_kwh),
        herkunft=(f"{quelle or f'{deutsch(betrag)} € Netzbezug'} ÷ "
                  f"{deutsch(satz_menge)} kWh Netzbezug "
                  f"({geeicht_hinweis}, {label})"))
