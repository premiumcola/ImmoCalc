"""Aus einem Beleg wird eine Kostenposition.

Bisher endete ein Beleg in der Ablage: er trug Kostenart, Belegdatum und
Zeitraum, aber in der Abrechnung stand deshalb keine Zeile. Wörtlich vom
Nutzer: „Wir wollen ja nicht irgendeinen Beleg ohne eine Position in der
jeweiligen Immobilie."

Hier steht die Regel dafür — nicht im Endpunkt, denn sie ist Rechenlogik:

* **Eine Position je Kostenart und Zeitraum bleibt die Regel** (CLXXXII).
  Auf dieselbe Zeile laufen aber vier Abschlagsrechnungen zu. Ein zweiter
  Beleg legt deshalb keine zweite Position an, sondern erhöht die vorhandene.
* **Der Betrag setzt sich sichtbar zusammen.** `Kostenposition.betrag` bleibt
  die Zahl, mit der gerechnet wird. `beleg_summe` sagt, welcher Teil davon aus
  Belegen stammt; die Differenz ist der Handeintrag. Nur mit dieser Trennung
  lässt sich ein weiterer Beleg addieren, ohne den Handeintrag zu verlieren.
* **Zweimal „Übernehmen" zählt einmal.** Der Beleg merkt sich seine Position
  (`Dokument.position_id`), und die Summe wird jedes Mal aus allen verknüpften
  Belegen neu gebildet — nie durch Draufrechnen. Ein zweiter Klick, ein
  korrigierter Betrag, ein gelöschter Beleg: die Zahl stimmt danach immer.

`vorschau` und `verbuche` sind dieselbe Rechnung, einmal ohne und einmal mit
Schreiben. So kann die Oberfläche vorher zeigen, was passieren wird — der
Nutzer soll es bestätigen können, nicht ertragen müssen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from .models import Dokument, Kostenart, Kostenposition, Zeitraum
from .verteilung import VORGABE, ableiten

log = logging.getLogger("immocalc")

# Belege ohne Datum sortieren sich vor die datierten, statt den Vergleich zu
# sprengen.
FRUEH = date.min


class BelegFehler(ValueError):
    """Diesem Beleg fehlt etwas, das eine Kostenposition braucht."""


@dataclass
class Buchung:
    """Was aus einem Beleg wird — vor oder nach dem Übernehmen.

    Dieselben Felder für Vorschau und Ergebnis: was der Nutzer bestätigt, ist
    danach auch das, was dasteht."""
    kostenart: str
    zeitraum_id: int
    position_id: Optional[int] = None
    neu: bool = True                  # die Position entsteht erst dadurch
    schon_verbucht: bool = False      # dieser Beleg zählte bereits mit
    vorher: float = 0.0               # Betrag der Position vor dem Übernehmen
    betrag: float = 0.0               # Betrag der Position danach
    beleg_summe: float = 0.0          # davon aus Belegen
    handanteil: float = 0.0           # davon von Hand eingetragen
    belege: list[dict] = field(default_factory=list)

    def als_dict(self) -> dict:
        return {
            "kostenart": self.kostenart, "zeitraum_id": self.zeitraum_id,
            "position_id": self.position_id, "neu": self.neu,
            "schon_verbucht": self.schon_verbucht,
            "vorher": self.vorher, "betrag": self.betrag,
            "beleg_summe": self.beleg_summe, "handanteil": self.handanteil,
            "belege": self.belege,
        }


def _geld(wert: float) -> float:
    return round(wert or 0.0, 2)


def kurz(d: Dokument) -> dict:
    """Ein Beleg, so knapp wie ihn eine Position anzeigen muss."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "betrag": d.betrag,
            "belegdatum": d.belegdatum.isoformat() if d.belegdatum else None}


def belege_der_position(session: Session, position_id: int) -> list[Dokument]:
    """Alle Belege, die in diese Position eingerechnet sind."""
    return list(session.exec(
        select(Dokument).where(Dokument.position_id == position_id)
        .order_by(Dokument.belegdatum, Dokument.id)).all())


def belege_je_position(session: Session, positionen: list[Kostenposition]
                       ) -> dict[int, list[Dokument]]:
    """Der Rückweg für eine ganze Zeitraumseite — in einer Abfrage.

    Je Position einzeln zu fragen wären bei zwanzig Kostenarten zwanzig
    Abfragen für eine einzige Ansicht."""
    ids = [p.id for p in positionen if p.id is not None]
    if not ids:
        return {}
    eimer: dict[int, list[Dokument]] = {i: [] for i in ids}
    for d in session.exec(select(Dokument)
                          .where(Dokument.position_id.in_(ids))
                          .order_by(Dokument.belegdatum, Dokument.id)).all():
        eimer.setdefault(d.position_id, []).append(d)
    return eimer


def handanteil(p: Kostenposition) -> float:
    """Was an dieser Position von Hand eingetragen wurde.

    Nie negativ: eine gewachsene Datenbank hat `beleg_summe` als 0, und ein
    Betrag, der kleiner ist als die Belegsumme, wäre eine Korrektur nach unten
    — sie darf den nächsten Beleg nicht ins Minus ziehen."""
    return max(0.0, _geld((p.betrag or 0.0) - (p.beleg_summe or 0.0)))


def finde(session: Session, zeitraum_id: int, kostenart: str
          ) -> Optional[Kostenposition]:
    """Die Position dieser Kostenart in diesem Zeitraum — falls es sie gibt."""
    name = (kostenart or "").strip()
    if not name:
        return None
    for p in session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id == zeitraum_id)).all():
        if p.kostenart == name:
            return p
    return None


def anlegen(session: Session, z: Zeitraum, kostenart: str, *,
            betrag: float = 0.0, schluessel: str = VORGABE,
            wertquelle: str = "manuell", status: Optional[str] = None,
            s35: Optional[bool] = None,
            anteile: Optional[dict[str, float]] = None,
            beleg_summe: float = 0.0) -> Kostenposition:
    """Legt eine Kostenposition an — mit Gewichten, nicht ohne.

    Ohne `anteile` werden sie aus dem Schlüssel abgeleitet; ohne `s35` erbt die
    Position den Vermerk aus dem Katalog des Objekts. Die Stelle steht hier und
    nicht im Endpunkt, weil sie zwei Aufrufer hat: die Handanlage aus der
    Checkliste und den Beleg."""
    gewichte = anteile if anteile is not None else ableiten(session, z, schluessel)
    if s35 is None:
        art = session.exec(select(Kostenart).where(
            Kostenart.objekt_id == z.objekt_id,
            Kostenart.name == kostenart)).first()
        s35 = bool(art and art.s35)
    p = Kostenposition(
        zeitraum_id=z.id, kostenart=kostenart, betrag=_geld(betrag),
        schluessel=schluessel, wertquelle=wertquelle, s35=s35,
        status=status or ("erledigt" if betrag else "offen"),
        anteile=gewichte, beleg_summe=_geld(beleg_summe))
    session.add(p)
    return p


def _pruefe(d: Dokument) -> None:
    """Was ein Beleg mitbringen muss, damit eine Position daraus wird.

    Alle drei Angaben stehen im Prüfblatt; fehlt eine, wird gesagt welche —
    „geht nicht" allein schickt den Nutzer auf die Suche."""
    if not (d.kostenart or "").strip():
        raise BelegFehler("Diesem Beleg fehlt die Kostenposition — "
                          "wähle zuerst, auf welche Zeile der Abrechnung er "
                          "zeigt.")
    if not d.zeitraum_id:
        raise BelegFehler("Diesem Beleg fehlt der Abrechnungszeitraum.")
    if not d.betrag:
        raise BelegFehler("Diesem Beleg fehlt der Betrag — ohne ihn hätte die "
                          "Kostenposition keine Zahl.")


def _rechne(session: Session, d: Dokument, p: Optional[Kostenposition]
            ) -> Buchung:
    """Die Zusammensetzung, wie sie mit diesem Beleg aussähe.

    Gerechnet wird immer aus der ganzen Belegliste, nie durch Draufrechnen —
    darum zählt ein zweites „Übernehmen" nicht doppelt."""
    schon = bool(p and d.position_id == p.id)
    andere = [b for b in (belege_der_position(session, p.id) if p else [])
              if b.id != d.id]
    belege = sorted(andere + [d], key=lambda b: (b.belegdatum or FRUEH, b.id or 0))
    beleg_summe = _geld(sum(b.betrag or 0.0 for b in belege))
    hand = handanteil(p) if p else 0.0
    return Buchung(
        kostenart=(d.kostenart or "").strip(), zeitraum_id=d.zeitraum_id,
        position_id=p.id if p else None, neu=p is None, schon_verbucht=schon,
        vorher=_geld(p.betrag) if p else 0.0,
        betrag=_geld(hand + beleg_summe), beleg_summe=beleg_summe,
        handanteil=hand, belege=[kurz(b) for b in belege])


def vorschau(session: Session, d: Dokument) -> Buchung:
    """Was das Übernehmen ergäbe. Ändert nichts."""
    _pruefe(d)
    return _rechne(session, d, _position_fuer(session, d))


def _position_fuer(session: Session, d: Dokument) -> Optional[Kostenposition]:
    """Die Position dieses Belegs: erst die gemerkte, dann die des Namens.

    Die gemerkte zuerst — sie überlebt eine umbenannte Kostenart (CLXXXIV).
    Sie gilt aber nur, solange sie noch zu diesem Zeitraum gehört; hängt der
    Beleg inzwischen an einer anderen Abrechnung, wäre sie die falsche."""
    if d.position_id:
        p = session.get(Kostenposition, d.position_id)
        if p and p.zeitraum_id == d.zeitraum_id:
            return p
    return finde(session, d.zeitraum_id, d.kostenart)


def verbuche(session: Session, d: Dokument) -> Buchung:
    """Trägt den Beleg in seine Kostenposition ein — und legt sie an, wenn es
    sie noch nicht gibt.

    Committet nicht: der Aufrufer entscheidet, wann der Stand steht."""
    _pruefe(d)
    p = _position_fuer(session, d)
    # Beides vor der Änderung festhalten: danach zeigt der Beleg auf die
    # Position, und die Antwort könnte nicht mehr sagen, ob sie gerade erst
    # entstanden ist oder ob der Beleg schon mitzählte.
    war_neu = p is None
    zaehlte_schon = bool(p and d.position_id == p.id)
    if p is None:
        z = session.get(Zeitraum, d.zeitraum_id)
        if not z:
            raise BelegFehler("Der Abrechnungszeitraum dieses Belegs "
                              "existiert nicht mehr.")
        p = anlegen(session, z, (d.kostenart or "").strip(),
                    betrag=0.0, wertquelle="Scan")
        session.flush()                    # die id wird gleich gebraucht
    d.position_id = p.id
    session.add(d)
    ergebnis = _rechne(session, d, p)
    ergebnis.neu = war_neu
    ergebnis.schon_verbucht = zaehlte_schon
    _schreibe(session, p, ergebnis)
    log.info("Beleg %s verbucht auf Position %s (%s): %.2f €",
             d.id, p.id, p.kostenart, ergebnis.betrag)
    return ergebnis


def _schreibe(session: Session, p: Kostenposition, b: Buchung) -> None:
    """Setzt Betrag und Belegsumme — und den Zustand, der dazu passt."""
    p.betrag = b.betrag
    p.beleg_summe = b.beleg_summe
    if b.betrag:
        # Ein Betrag heisst: der Beleg liegt vor. Genau wie beim Nachtragen
        # von Hand (`position_aendern`).
        p.status = "erledigt"
    if p.wertquelle == "manuell":
        p.wertquelle = "Scan"
    session.add(p)


def nachrechnen(session: Session, p: Kostenposition) -> float:
    """Bildet Betrag und Belegsumme aus den verknüpften Belegen neu.

    Gebraucht, wenn ein Beleg wegfällt oder sich löst: die Position darf nicht
    auf einer Summe sitzenbleiben, zu der es keine Belege mehr gibt. Der
    Handanteil bleibt stehen — er war nie an einen Beleg gebunden."""
    hand = handanteil(p)
    beleg_summe = _geld(sum(b.betrag or 0.0
                            for b in belege_der_position(session, p.id)))
    p.beleg_summe = beleg_summe
    p.betrag = _geld(hand + beleg_summe)
    session.add(p)
    return p.betrag


def loese(session: Session, d: Dokument) -> Optional[Kostenposition]:
    """Nimmt den Beleg aus seiner Position heraus.

    Die Position bleibt stehen — sie kann von Hand eingetragene Anteile und
    eine gepflegte Verteilung tragen. Nur ihr Betrag schrumpft um das, was der
    Beleg beigesteuert hat."""
    if not d.position_id:
        return None
    p = session.get(Kostenposition, d.position_id)
    d.position_id = None
    session.add(d)
    if p is None:
        return None
    session.flush()
    nachrechnen(session, p)
    return p


def nachziehen(session: Session, d: Dokument) -> str:
    """Hält eine bestehende Buchung ehrlich, nachdem der Beleg geändert wurde.

    Angelegt wird hier nie etwas — das bleibt der bestätigte Schritt (CLXXX).
    Aber ein Beleg, der einmal in eine Position eingerechnet wurde und dann
    einen anderen Betrag, eine andere Kostenart oder einen anderen Zeitraum
    bekommt, darf die Summe dort nicht verfälscht stehen lassen.

    Gibt zurück, was geschehen ist: '' (nichts), 'aktualisiert' oder 'geloest'.
    """
    if not d.position_id:
        return ""
    p = session.get(Kostenposition, d.position_id)
    if p is None:
        d.position_id = None
        session.add(d)
        return "geloest"
    passt = (p.zeitraum_id == d.zeitraum_id
             and p.kostenart == (d.kostenart or "").strip()
             and bool(d.betrag))
    if not passt:
        loese(session, d)
        return "geloest"
    session.flush()
    nachrechnen(session, p)
    return "aktualisiert"


def zusammensetzung(session: Session, p: Kostenposition,
                    belege: Optional[list[Dokument]] = None) -> dict:
    """Woraus der Betrag dieser Position besteht — für die Anzeige."""
    liste = belege if belege is not None else belege_der_position(session, p.id)
    return {
        "beleg_summe": _geld(p.beleg_summe),
        "handanteil": handanteil(p),
        "belege": [kurz(b) for b in liste],
    }
