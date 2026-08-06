"""Zeit- und Perioden-Helfer der E-Tankstelle.

Reine Rechenschritte um Quartale, Monatsfolgen und Abrechnungsüberschriften —
ohne Datenbank, ohne Netz. Grundlage für Verlauf und Abrechnung."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from .typen import Posten

# Wie viele Tage nach Quartalsende der automatische Versand noch nachholt. Der
# Auslöser ist „einen Tag nach dem Quartal" — dieses Fenster fängt ab, dass die
# App am Stichtag gerade aus war, ohne beim späteren Einschalten alte Quartale
# nachzublasen. Der Versendet-Marker verhindert Dopplungen innerhalb des
# Fensters.
GRACE_TAGE = 20

# Ein Verlauf über mehr als zehn Jahre ist eine Fehleingabe, kein Wunsch.
MAX_MONATE = 120

# Wie weit zurück nach Ladungen gesucht wird, wenn niemand einen Zeitraum
# nennt. Ein Jahr ohne Ladungen beantwortet die Box mit der blossen Kopfzeile —
# der Blick zurück kostet im Heimnetz Millisekunden.
RUECKBLICK_JAHRE = 9

MONATSKURZ = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


def quartal_zeitraum(jahr: int, quartal: int) -> tuple[date, date]:
    """Anfang und Ende eines Quartals — ``quartal=0`` meint das ganze Jahr.

    Beide Ränder zählen mit: Q3 läuft vom 01.07. bis zum 30.09."""
    if quartal == 0:
        return date(jahr, 1, 1), date(jahr, 12, 31)
    if quartal not in (1, 2, 3, 4):
        raise ValueError("Ein Quartal ist 1, 2, 3 oder 4 (0 = ganzes Jahr).")
    erster = 3 * (quartal - 1) + 1
    letzter = erster + 2
    return date(jahr, erster, 1), date(jahr, letzter,
                                       monthrange(jahr, letzter)[1])


def _monatsende(jahr: int, monat: int) -> date:
    """Der letzte Tag eines Monats — N214 (Zukunfts-Guard)."""
    return date(jahr, monat, monthrange(jahr, monat)[1])


def quartale_monate(quartale: list[int]) -> list[int]:
    """Die Monatsnummern (1–12) einer Quartalsauswahl — aufsteigend, ohne
    Dopplung.

    Mehrere Quartale lassen sich zusammen abrechnen (N169): Q2 + Q3 ergeben die
    Monate April bis September. Ist ``0`` (ganzes Jahr) dabei, sind es alle
    zwölf."""
    monate: set[int] = set()
    for q in quartale:
        if q == 0:
            return list(range(1, 13))
        if q not in (1, 2, 3, 4):
            raise ValueError("Ein Quartal ist 1, 2, 3 oder 4 (0 = ganzes Jahr).")
        erster = 3 * (q - 1) + 1
        monate.update({erster, erster + 1, erster + 2})
    return sorted(monate)


def aktive_monate(quartale: list[int], aus) -> list[int]:
    """Die Monate der gewählten Quartale ohne die einzeln abgewählten (N169).

    Der Umstieg von der 4-Monats- auf die Quartalsabrechnung lässt einen Monat
    doppelt erscheinen (der April war schon in der alten Weise abgerechnet):
    darum lassen sich einzelne Monate eines Quartals ausschließen. `aus` ist die
    Menge der Monatsnummern, die draußen bleiben."""
    aus = set(aus or ())
    return [m for m in quartale_monate(quartale) if m not in aus]


def abrechnungs_label(jahr: int, quartale: list[int], aus) -> str:
    """Die Überschrift der Abrechnung — trägt die Quartalsauswahl und die
    abgewählten Monate (N169).

    „Q3 2025" wie bisher; „Q2/Q3 2025" für mehrere; „Jahr 2025" für das ganze
    Jahr. Abgewählte Monate stehen als „(ohne Apr)" dahinter, damit die
    Ausnahme sichtbar bleibt."""
    gewaehlt = sorted(set(quartale))
    aus = sorted(set(aus or ()))
    if gewaehlt == [0] or {1, 2, 3, 4}.issubset(set(gewaehlt)):
        basis = f"Jahr {jahr}"
    elif len(gewaehlt) == 1:
        basis = f"Q{gewaehlt[0]} {jahr}"
    else:
        basis = "/".join(f"Q{q}" for q in gewaehlt if q) + f" {jahr}"
    if aus:
        basis += " (ohne " + ", ".join(MONATSKURZ[m - 1] for m in aus) + ")"
    return basis


def monatsfolge(von: date, bis: date) -> list[tuple[int, int]]:
    """Alle Monate von `von` bis `bis` — auch die ohne eine einzige Ladung.

    Ein Verlauf mit Lücken ist kein Verlauf: ein Monat ohne Ladung ist eine
    Aussage und gehört als leerer Balken in die Grafik."""
    if bis < von:
        raise ValueError("Das Ende des Zeitraums liegt vor seinem Beginn.")
    folge: list[tuple[int, int]] = []
    jahr, monat = von.year, von.month
    while (jahr, monat) <= (bis.year, bis.month):
        folge.append((jahr, monat))
        if len(folge) > MAX_MONATE:
            raise ValueError(
                f"Der Zeitraum umfasst mehr als {MAX_MONATE} Monate — "
                "bitte einen kürzeren wählen.")
        monat += 1
        if monat > 12:
            jahr, monat = jahr + 1, 1
    return folge


def faelliges_quartal(heute: date | None = None) -> tuple[int, int] | None:
    """Das Quartal, dessen Abrechnung jetzt automatisch fällig ist — oder
    ``None``.

    Ausgelöst wird **einen Tag nach Quartalsende**: am 01.07. steht Q2 an, am
    01.01. das Q4 des Vorjahres. Fällig bleibt es :data:`GRACE_TAGE` Tage lang,
    damit ein am Stichtag ausgeschalteter Rechner es nachholen kann; danach
    nicht mehr, damit ein spät eingeschalteter Autoversand nicht rückwirkend
    alte Quartale verschickt."""
    heute = heute or date.today()
    q = (heute.month - 1) // 3 + 1
    jahr, quartal = (heute.year - 1, 4) if q == 1 else (heute.year, q - 1)
    ende = quartal_zeitraum(jahr, quartal)[1]
    return (jahr, quartal) if 1 <= (heute - ende).days <= GRACE_TAGE else None


def suchfenster(heute: date | None = None) -> tuple[date, date]:
    """Das Fenster, in dem nach Ladungen gesucht wird, wenn niemand einen
    Zeitraum nennt.

    Bewusst grosszügig und trotzdem endlich: `RUECKBLICK_JAHRE` zurück bis zum
    Ende des laufenden Jahres. Die Wallbox beantwortet ein Jahr ohne Ladungen
    mit der blossen Kopfzeile — der Rückblick kostet fast nichts."""
    jetzt = heute or date.today()
    return date(jetzt.year - RUECKBLICK_JAHRE, 1, 1), date(jetzt.year, 12, 31)


def belegte_spanne(posten: list[Posten],
                   ersatz: tuple[date, date]) -> tuple[date, date]:
    """Vom ersten bis zum letzten Monat mit einer Ladung — volle Monate.

    Ohne eine einzige Ladung bleibt `ersatz` stehen: eine leere Grafik über
    zehn Jahre wäre keine Auskunft, das laufende Jahr schon."""
    tage = [p.tag for p in posten if p.tag and p.kwh > 0]
    if not tage:
        return ersatz
    erster, letzter = min(tage), max(tage)
    return (date(erster.year, erster.month, 1),
            date(letzter.year, letzter.month,
                 monthrange(letzter.year, letzter.month)[1]))


def jahre_mit_verbrauch(posten: list[Posten]) -> list[int]:
    """Die Jahre, in denen wirklich geladen wurde — aufsteigend.

    Grundlage der Jahresauswahl: ein Jahr ohne eine einzige Kilowattstunde
    gehört in keine Liste (N143)."""
    return sorted({p.tag.year for p in posten if p.tag and p.kwh > 0})
