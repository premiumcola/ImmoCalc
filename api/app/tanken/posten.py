"""Datenquellen und Zuordnung der E-Tankstelle.

Erst die Wallbox, dann die erfassten Ladungen — nie eine stille Null: welche
Quelle gesprochen hat, wird immer beantwortet. Dazu die Zuordnung von
erfassten Ladungen zu Nutzern (über Zeitraum-Regeln oder namentlich)."""
from __future__ import annotations

import logging
from datetime import date

from sqlmodel import Session, select

from ..cloudkern import _lies
from ..models import Eigentuemer, Objekt, Stromjahr, Tankladung
from .typen import Buchung, Posten, RohLadung

# Die Wallbox-Anbindung entsteht parallel (N130). Fehlt sie, arbeitet dieser
# Bereich auf den erfassten Ladungen weiter — eine harte Abhängigkeit auf
# fremde, noch entstehende Arbeit wäre hier fehl am Platz.
try:                                        # pragma: no cover - Importzweig
    from .. import openwb
except ImportError:                         # pragma: no cover - Importzweig
    openwb = None                           # type: ignore[assignment]

try:                                        # pragma: no cover - Importzweig
    import httpx
except ImportError:                         # pragma: no cover - Importzweig
    httpx = None                            # type: ignore[assignment]

log = logging.getLogger("immocalc")

# Adresse der Wallbox, gesetzt in `routers/openwb.py`. Hier nur gelesen.
S_OPENWB_URL = "openwb_url"

# Die Box steht im Heimnetz und ist mal aus. Kurz genug, dass die Seite nicht
# hängt.
TIMEOUT = 8.0


def _wallbox_bereit() -> bool:
    """Ist die Wallbox-Anbindung da und hat sie die Form, die hier gebraucht
    wird? Fehlt sie, wird nicht geraten, sondern zurückgefallen."""
    return httpx is not None and openwb is not None and all(
        hasattr(openwb, name) for name in
        ("normalisiere_basis", "protokoll_url", "jahre", "lies",
         "zusammenfuehren", "OpenwbFehler"))


def _protokoll(basis: str, jahr: int) -> str:
    """Das Ladeprotokoll eines Jahres holen — nur GET, knapper Timeout."""
    adresse = openwb.protokoll_url(basis, jahr)
    try:
        antwort = httpx.get(adresse, timeout=TIMEOUT, follow_redirects=True)
    except Exception as fehler:            # noqa: BLE001 - httpx-Fehlerbaum
        raise openwb.OpenwbFehler(
            f"Die Wallbox ist unter {basis} nicht erreichbar ({fehler}).") \
            from fehler
    if antwort.status_code != 200:
        raise openwb.OpenwbFehler(
            f"Die Wallbox antwortete für {jahr} mit HTTP "
            f"{antwort.status_code}. Stimmt die Adresse?")
    return antwort.text


def wallbox_posten(session: Session, von: date,
                   bis: date) -> tuple[list[Posten], str]:
    """Die Ladungen aus der Wallbox — ``([], Grund)``, wenn sie nichts sagt."""
    if not _wallbox_bereit():
        return [], ("Die Anbindung an die Wallbox ist auf diesem Stand noch "
                    "nicht verfügbar.")
    basis = openwb.normalisiere_basis(_lies(session, S_OPENWB_URL))
    if not basis:
        return [], ("Für die Wallbox ist noch keine Adresse hinterlegt "
                    "(Einstellungen → openWB).")
    try:
        # Auch das Folgejahr holen: openWB legt eine Ladung nach ihrem **Ende**
        # ab. Die Ladung vom 31.12.2025 steht in der Datei 2026 — wer nur 2025
        # holt, verliert sie lautlos. Ein leeres Jahr kostet die Box nichts.
        alle: list = []
        for jahr in [*openwb.jahre(von, bis), bis.year + 1]:
            alle = openwb.zusammenfuehren(alle,
                                          openwb.lies(_protokoll(basis, jahr)).ladungen)
    except openwb.OpenwbFehler as fehler:
        log.info("E-Tankstelle: Wallbox nicht auswertbar — %s", fehler)
        return [], str(fehler)
    return [Posten(tag=l.tag, kwh=l.kwh, extern_kwh=l.extern_kwh,
                   pv_kwh=l.pv_kwh, speicher_kwh=l.speicher_kwh,
                   rest_kwh=l.rest_kwh)
            for l in alle if von <= l.tag <= bis], ""


def _jahresverhaeltnis(session: Session, objekt_id: int,
                       jahr: int) -> tuple[float, float] | None:
    """Die von Hand gepflegte Aufteilung Netz/eigen eines Jahres (N124).

    Ohne Wallbox ist das die einzige Aussage darüber, woher der Ladestrom kam.
    Sie gilt fürs ganze Jahr und wird auf die Monate übertragen — als Schätzung
    gekennzeichnet, nicht als Messung."""
    sj = session.exec(select(Stromjahr).where(
        Stromjahr.objekt_id == objekt_id, Stromjahr.jahr == jahr)).first()
    if not sj:
        return None
    extern = getattr(sj, "eauto_extern_kwh", 0.0) or 0.0
    eigen = getattr(sj, "eauto_eigen_kwh", 0.0) or 0.0
    return (extern, eigen) if extern + eigen > 0 else None


def erfasste_ladungen(session: Session, objekt_id: int, von: date,
                      bis: date) -> list[Tankladung]:
    """Die erfassten Ladungen eines Zeitraums.

    Gefiltert wird über das Datum. Ladungen ohne Datum lassen sich keinem Monat
    zuordnen; sie zählen über ihr `jahr` mit, sobald dieses ganz im Zeitraum
    liegt — sonst bliebe eine bezahlte Ladung unsichtbar."""
    liste = session.exec(
        select(Tankladung).where(Tankladung.objekt_id == objekt_id)
        .order_by(Tankladung.datum, Tankladung.id)).all()
    passend = []
    for l in liste:
        if l.datum is not None:
            if von <= l.datum <= bis:
                passend.append(l)
        elif von <= date(l.jahr, 1, 1) and date(l.jahr, 12, 31) <= bis:
            passend.append(l)
    return passend


def erfasste_posten(session: Session, objekt_id: int, von: date,
                    bis: date) -> tuple[list[Posten], bool]:
    """Die erfassten Ladungen als Verlaufs-Posten — plus die Angabe, ob die
    Aufteilung Netz/eigen dabei geschätzt wurde."""
    verhaeltnisse: dict[int, tuple[float, float] | None] = {}
    posten, geschaetzt = [], False
    for l in erfasste_ladungen(session, objekt_id, von, bis):
        tag = l.datum or date(l.jahr, 1, 1)
        if l.jahr not in verhaeltnisse:
            verhaeltnisse[l.jahr] = _jahresverhaeltnis(session, objekt_id, l.jahr)
        anteil = verhaeltnisse[l.jahr]
        # N315(e) — `l.kwh` als Wahrheitswert prüfte auf „ungleich 0", nicht
        # auf „bekannt": eine Ladung mit genau 0 kWh (z. B. ein Ladevorgang
        # ohne Energiefluss) fiel dadurch auf den Zweig ohne Netz/eigen-
        # Aufteilung — und ein einziger solcher Posten kippte `aufteilung`
        # für den ganzen Monat auf falsch, worauf die Abrechnung auf den
        # vollen Netzpreis zurückfiel, obwohl das Verhältnis bekannt war.
        if anteil:
            extern, eigen = anteil
            quote = extern / (extern + eigen)
            posten.append(Posten(tag=tag, kwh=l.kwh,
                                 extern_kwh=l.kwh * quote,
                                 eigen_kwh=l.kwh * (1 - quote)))
            geschaetzt = True
        else:
            posten.append(Posten(tag=tag, kwh=l.kwh))
    return posten, geschaetzt


def _person(l: Tankladung, namen: dict[int, str]) -> str:
    """Wer geladen hat: die verknüpfte Person, sonst der freie Name."""
    return namen.get(l.person_id or 0, "") or l.name or "—"


def _regel_treffer(regeln: list[dict], tag: date | None) -> dict | None:
    """Die Zeitraum-Regel, die einen Ladetag enthält (beide Ränder zählen).

    Ohne Datum lässt sich keine Regel anwenden — dann ``None``. Treffen mehrere
    Regeln denselben Tag (überlappende Zeiträume), gewinnt die mit dem
    **späteren Beginn**: die jüngere, engere Zuordnung überschreibt die ältere,
    breite. Bei gleichem Beginn entscheidet das spätere Ende. So ist die
    Auswahl deterministisch und für den Nutzer nachvollziehbar."""
    if tag is None:
        return None
    passend = [r for r in regeln if r["von"] <= tag <= r["bis"]]
    if not passend:
        return None
    return max(passend, key=lambda r: (r["von"], r["bis"]))


def zuordnen(rohe: list[RohLadung], nutzer: list[dict], regeln: list[dict],
             ausschluss: set[int]) -> list[Buchung]:
    """Erfasste Ladungen einer Person zuschlagen — über einen Zeitraum, nicht
    Ladung für Ladung (N165 Teil 2).

    Für jede Ladung: liegt ihr Tag in einer Zeitraum-Regel, gehört sie dem
    Nutzer dieser Regel; sonst bleibt es bei der bisherigen Zuordnung über den
    Namen (`RohLadung.name`) — so geht keine Ladung verloren, nur weil (noch)
    keine Regel sie trägt. Ausgeschlossene Ladungen (`ausschluss`, Menge von
    Ladungs-Ids) fallen ganz heraus; das ist der Korrekturweg für eine falsch
    zugeordnete Ladung. `regeln` trägt bereits geprüfte Regeln mit
    ``date``-Rändern und einer `nutzer_id`, die in `nutzer` steht."""
    nach_id = {n["id"]: n for n in nutzer}
    gueltig = [r for r in regeln if r.get("nutzer_id") in nach_id]
    ergebnis: list[Buchung] = []
    for l in rohe:
        if l.id is not None and l.id in ausschluss:
            continue
        treffer = _regel_treffer(gueltig, l.tag) if gueltig else None
        if treffer is not None:
            n = nach_id[treffer["nutzer_id"]]
            ergebnis.append(Buchung(tag=l.tag, person=n["name"],
                                    email=n.get("email", ""), kwh=l.kwh))
        else:
            ergebnis.append(Buchung(tag=l.tag, person=l.name, email=l.email,
                                    kwh=l.kwh))
    return ergebnis


def buchungen(session: Session, objekt_id: int, von: date, bis: date,
              nutzer: list[dict] | None = None,
              regeln: list[dict] | None = None,
              ausschluss: set[int] | None = None,
              aktive_monate: set[int] | None = None) -> list[Buchung]:
    """Die erfassten Ladungen als Abrechnungszeilen.

    `Tankladung.preis` wird bewusst **nicht** übernommen (N148): der Satz ist
    abgeleitet und für alle Ladungen des Zeitraums derselbe.

    Ohne Zeitraum-Regeln bleibt es bei der Zuordnung über den Namen (der alte
    Weg). Mit Regeln greift die Mehrnutzer-Zuordnung über den Zeitraum
    (N165/2): jede Ladung geht an den Nutzer, dessen Zeitraum ihren Tag enthält;
    ausgeschlossene Ladungen fallen heraus.

    `aktive_monate` grenzt zusätzlich auf einzelne Monate der Spanne ein (N169):
    ein aus dem Quartal abgewählter Monat fällt aus Menge und Betrag heraus.
    Ladungen ohne Datum bleiben, weil sie keinem Monat zugeordnet werden
    können."""
    namen = {e.id: e.name for e in session.exec(select(Eigentuemer)).all()}
    rohe = [RohLadung(id=l.id, tag=l.datum, name=_person(l, namen),
                      email=l.email or "", kwh=l.kwh or 0.0)
            for l in erfasste_ladungen(session, objekt_id, von, bis)
            if aktive_monate is None or l.datum is None
            or l.datum.month in aktive_monate]
    return zuordnen(rohe, nutzer or [], regeln or [], ausschluss or set())


def posten_als_buchungen(posten: list[Posten],
                         nutzer: list[dict]) -> tuple[list[Buchung], bool]:
    """N165 — die automatische Zuordnung bei **genau einem** Nutzer.

    Solange nur eine Person an der Station lädt, gibt es nichts zu entscheiden:
    ihr gehören alle Ladungen des Zeitraums, ohne dass jede von Hand zugebucht
    werden müsste. Grundlage sind die tatsächlich geladenen Mengen (`posten` —
    aus der Wallbox oder den erfassten Ladungen), nicht die per Namen erfassten
    `Tankladung`-Sätze: sonst bliebe die Abrechnung leer, obwohl kWh geflossen
    sind.

    Rückgabe ``(buchungen, automatisch)``. `automatisch` ist ``True``, wenn die
    Zuordnung so entstanden ist — damit die Oberfläche sie als das ausweisen
    kann, was sie ist, statt sie wie eine Handeingabe aussehen zu lassen. Bei
    mehreren (oder keinem) Nutzer bleibt es bei der Zuordnung über den Namen;
    die feinere Mehrnutzer-Regel kommt in einem zweiten Schritt."""
    if len(nutzer) != 1:
        return [], False
    n = nutzer[0]
    return ([Buchung(tag=p.tag, person=n["name"], email=n.get("email", ""),
                     kwh=p.kwh) for p in posten if p.kwh], True)


def _stations_verbrauch(nutzer: list[dict]) -> float | None:
    """Der mittlere Verbrauch (kWh/100km) über alle Nutzer der Station, die
    einen Wert gepflegt haben (N188).

    Für die Reichweite eines Monats braucht es einen typischen Verbrauch der
    Station — der Durchschnitt der Nutzer mit einem Wert > 0. Hat niemand einen
    Verbrauch hinterlegt, kommt ``None`` zurück: dann bleibt die Reichweite
    leer, statt sie aus dem Nichts zu erfinden."""
    werte = [n.get("verbrauch_kwh_100km") or 0.0 for n in nutzer]
    werte = [w for w in werte if w > 0]
    return sum(werte) / len(werte) if werte else None


def _posten_holen(session: Session, o: Objekt, von: date,
                  bis: date) -> tuple[list[Posten], str, str]:
    """Die Ladungen eines Zeitraums — Wallbox zuerst, sonst die erfassten.

    Liefert ``(posten, quelle, hinweis)``. `quelle` ist „wallbox", „erfasst"
    oder „leer"; der Hinweis sagt, warum die Box nicht sprach. Nie eine stille
    Null."""
    posten, grund = wallbox_posten(session, von, bis)
    if posten:
        return posten, "wallbox", ""
    ersatz, geschaetzt = erfasste_posten(session, o.id, von, bis)
    hinweis = ""
    if grund:
        hinweis = (f"{grund} Gezeigt werden die erfassten Ladungen."
                   if ersatz else grund)
    if geschaetzt:
        hinweis = (hinweis + " Die Aufteilung Netz/eigen ist aus den "
                   "Jahreswerten übertragen; PV und Akku lassen sich daraus "
                   "nicht trennen.").strip()
    return ersatz, ("erfasst" if ersatz else "leer"), hinweis
