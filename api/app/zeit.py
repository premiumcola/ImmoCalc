"""Zeitrechnung — die beiden Arten, „ein Monat" zu zählen, an einer Stelle.

N291. Es gab sie zweimal im Repo, in `cashflow.py` und in `weg.py`, mit
unterschiedlichem Ergebnis: für den Februar 2025 einmal 0,9205 und einmal
1,0000 — knapp **8 % Unterschied** in derselben Abrechnung. Das sah nach einer
Doppelung aus, die man zusammenlegt. Es ist keine.

Die beiden beantworten verschiedene Fragen, und beide Antworten sind richtig:

**`jahresanteil_monate` — welchen Anteil des Jahres deckt dieser Zeitraum ab?**
Gebraucht überall dort, wo ein JAHRESbetrag über die Zeit verteilt wird: der
Verteilungsschlüssel Wohndauer/Personenmonate in der Nebenkostenabrechnung, die
Jahresmiete in der Auswertung. Hier ist der Tagesanteil richtig — wer die 28
Tage des Februars bewohnt, trägt weniger Personentage als wer die 31 Tage des
Juli bewohnt. Genau so stehen die Referenzzahlen in den Excel-Dateien.

**`zahlmonate` — wie viele Monatszahlungen fallen an?**
Gebraucht dort, wo ein MONATSbetrag vervielfacht wird: die WEG-Vorauszahlung
„244 € im Monat". Hier muss ein voller Kalendermonat exakt 1,0 zählen — wer im
Februar wohnt, überweist 244 €, nicht 224,60 €. Der Tagesanteil wäre hier ein
echter Rechenfehler.

Beide erfüllen dieselbe Invariante: über ein volles Jahr ergeben sie exakt 12,
und zwei lückenlos aufeinanderfolgende Zeiträume summieren sich exakt auf die
Länge des Ganzen — ein Mieterwechsel erzeugt in keiner der beiden Regeln einen
dreizehnten Monat.

`test_zeit.py` hält den Unterschied fest, damit die nächste
Modularisierungsrunde ihn nicht als Doppelung „aufräumt" und dabei entweder die
Verteilung oder die Vorauszahlung verfälscht.
"""
from __future__ import annotations

import calendar
from datetime import date


def jahresanteil_monate(ab: date, bis: date | None, jahr: int) -> float:
    """Wie viele Monate des Jahres deckt dieser Zeitraum ab — taggenau.

    Für die Verteilung eines JAHRESbetrags. Die Gegenfrage beantwortet
    `zahlmonate`; der Unterschied ist gewollt, siehe Modulkopf.

    Bewusst keine ganzen Monate: gezählt wurden früher angebrochene Monate an
    beiden Enden voll. Bei einem Mieterwechsel am 15. Juli ergab das für den
    Vorgänger 7 und für den Nachfolger 6 Monate — zusammen 13 Monate Miete in
    einem Jahr, also gut 8 % zu viel Einnahmen. Taggenau summieren sich zwei
    lückenlos aufeinanderfolgende Mietverhältnisse wieder exakt auf 12.

    Das Ende ist einschliesslich zu verstehen: wer am 31.12. auszieht, hat
    diesen Tag noch gewohnt.
    """
    von = max(ab, date(jahr, 1, 1))
    ende = min(bis or date(jahr, 12, 31), date(jahr, 12, 31))
    if ende < von:
        return 0.0
    tage = (ende - von).days + 1
    im_jahr = (date(jahr, 12, 31) - date(jahr, 1, 1)).days + 1   # 365 oder 366
    return round(tage / im_jahr * 12, 6)


def zahlmonate(von: date, bis: date) -> float:
    """Wie viele Monatszahlungen zwischen zwei Tagen anfallen — anteilig.

    Für die Vervielfachung eines MONATSbetrags. Die Gegenfrage beantwortet
    `jahresanteil_monate`; der Unterschied ist gewollt, siehe Modulkopf.

    Ein voller Kalendermonat zählt exakt 1,0 (auch der Februar mit 28 Tagen),
    ein angebrochener nach seinem Tagesanteil. So ergeben 01.01.–30.06. genau
    6,0 Monate, und ein Mietbeginn zur Monatsmitte kippt die Summe nicht."""
    if bis < von:
        return 0.0
    summe = 0.0
    jahr, monat = von.year, von.month
    while (jahr, monat) <= (bis.year, bis.month):
        tage = calendar.monthrange(jahr, monat)[1]
        anfang = max(von, date(jahr, monat, 1))
        ende = min(bis, date(jahr, monat, tage))
        if ende >= anfang:
            summe += ((ende - anfang).days + 1) / tage
        monat += 1
        if monat > 12:
            jahr, monat = jahr + 1, 1
    return summe
