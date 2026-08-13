"""Zähler-Ablesungen → interpolierter Verbrauch je Abrechnungszeitraum (CCXCIII).

Verdrahtet die reinen, getesteten Engine-Funktionen (`interpoliere_verbrauch`,
`rest_verbrauch`, `tage`) mit den gespeicherten Ablesungen. `engine.py` bleibt
unberührt — die 142.577-Referenz läuft hier nur durch.

Modell wie in der Muster-Excel: je Abrechnungszeitraum eine Ablesung (nahe dem
Periodenende). Der interpolierte Stand zum Soll-Stichtag (`Zeitraum.ende`) wird
als Randwert in die nächste Periode fortgeschrieben; der Verbrauch einer Periode
ist die Differenz der beiden Randwerte — linear auf Tagesbasis hochgerechnet.
"""
from datetime import date, timedelta
from typing import Optional

from . import engine

# N381 — eine rein informative Altangabe. Wird gesetzt, wenn ein Zähler von
# einem Jahreswert (fertiger Verbrauch, `typ='direkt'`) auf echte Zählerstände
# (`typ='gemessen'`) umgestellt wird und seine Historie aus einer fremden
# Abrechnung (z. B. dem Delta-t-Messdienst) stammt: dort sind die Altwerte
# JAHRESVERBRÄUCHE, keine Gerätestände. Ein Wärmemengenzähler etwa lieferte
# über Jahre nur den fertigen Verbrauch je Saison; sein realer, kumulierter
# Zählerstand ist davon unabhängig und wurde nie erfasst.
#
# Ohne diese Markierung griff sich `_ablesung_fuer` die ALTEN Verbrauchszahlen
# als vermeintliche Stände heraus (sie liegen oft zufällig nahe an echten
# Periodengrenzen) und differenzierte sie wie echte Ablesungen — das ergab
# sinkende, teils negative "Verbrauchswerte" für vergangene Perioden UND einen
# falschen, nur zufällig plausibel aussehenden Wert für die laufende Periode.
# Verifiziert an echten Daten (Laufer Str. 5, Wärmemengenzähler Studio/Büro):
# Verbrauch 2022/23 wäre mit −1.930 kWh (Studio) bzw. −952 kWh (Büro)
# berechnet worden, 2024/25 mit einem unauffällig falschen Wert.
#
# Die Werte selbst bleiben erhalten und weiter sichtbar (`_verlauf_verbrauch`
# in `routers/zaehler.py` zeigt sie jahrweise) — nur die Interpolation lässt
# sie links liegen.
HISTORISCH_PRAEFIX = "Delta-t-Historie"


def _ist_historisch(a) -> bool:
    return (getattr(a, "notiz", "") or "").startswith(HISTORISCH_PRAEFIX)


def _ablesung_fuer(ablesungen: list, z, alle_zeitraeume: list = ()) -> Optional[object]:
    """Die Ablesung, die diesen Zeitraum abschließt: bevorzugt die ausdrücklich
    diesem Zeitraum zugeordnete (`zeitraum_id`), sonst die mit dem zum
    Periodenende nächstgelegenen Datum.

    N352 — eine ungetaggte Ablesung gilt aber NUR, wenn ihr kein anderer
    Zeitraum näher liegt. Ohne diese Schranke griff sich eine Altperiode, für
    die nie abgelesen wurde, den Stand einer ganz anderen Periode: bei der
    Laufer Str. 5 nahm der Zeitraum 2018/19 den Anfangsstand vom 1.10.2024 als
    „seine" Ablesung, 2022/23 schrieb den Randwert-Anker auf den 30.9.2023
    fort — und die eigentliche Periode 2024/25 rechnete ihre 3.431 Liter
    danach über 731 statt 364 Ist-Tage, also auf 1.708 Liter halbiert.
    """
    getaggt = [a for a in ablesungen if getattr(a, "zeitraum_id", None) == z.id]
    if getaggt:
        # N109 - bei mehreren Ablesungen desselben Zeitraums zaehlt die, die der
        # Periodengrenze am naechsten liegt, NICHT die spaeteste. Nach einem
        # Perioden-Split bleiben Altablesungen mit derselben `zeitraum_id`, aber
        # weit spaeterem Datum stehen; die spaeteste zu nehmen streckte die
        # Interpolation auf den alten, laengeren Zeitraum (28,1 m3 wurden so zu
        # 17,758 m3).
        return min(getaggt, key=lambda a: abs(engine.tage(z.ende, a.datum)))
    frei = [a for a in ablesungen
            if getattr(a, "zeitraum_id", None) is None and not _ist_historisch(a)]
    if not frei:
        return None
    kandidat = min(frei, key=lambda a: abs(engine.tage(z.ende, a.datum)))
    # Liegt ein anderer Zeitraum näher an dieser Ablesung, gehört sie dorthin.
    eigener = abs(engine.tage(z.ende, kandidat.datum))
    for andere in alle_zeitraeume:
        if getattr(andere, "id", None) == getattr(z, "id", None):
            continue
        if abs(engine.tage(andere.ende, kandidat.datum)) < eigener:
            return None
    return kandidat


def verbrauchsreihe(ablesungen: list, zeitraeume: list) -> dict:
    """{zeitraum_id: {"verbrauch", "randwert", "datum", "stand"}} über alle
    Zeiträume (nach Ende sortiert). Die erste Periode mit Ablesung ist die
    Startablesung — ihr Verbrauch ist 0, ihr Stand wird zum Randwert."""
    geordnet = sorted(zeitraeume, key=lambda z: z.ende)
    randwert: Optional[float] = None
    randdatum: Optional[date] = None
    out: dict = {}
    for z in geordnet:
        a = _ablesung_fuer(ablesungen, z, geordnet)
        if a is None:
            out[z.id] = None
            continue
        if randwert is None:
            # N352 — bevor diese Periode zur blossen Startablesung wird: gibt
            # es einen FRÜHEREN Stand, der zu keiner Periode gehört (der
            # Anfangsstand vor der ersten Abrechnung), ist er der Randwert und
            # diese Periode rechnet ihren echten Verbrauch. Ohne das verlor ein
            # Zähler, dessen Erfassung nach dem ersten Objekt-Zeitraum beginnt,
            # sein erstes Jahr — die Vorlauf-Periode (`_mit_vorlauf`) greift
            # nur, wenn der Anfangsstand vor der ALLERERSTEN Periode liegt.
            frueher = [v for v in ablesungen
                       if v is not a and v.datum <= z.start
                       and getattr(v, "zeitraum_id", None) is None
                       and not _ist_historisch(v)]
            if not frueher:
                # N315(j) - der Anker fuer die naechste Periode muss das TATSAECH-
                # LICHE Ablesedatum sein, nicht z.ende: die Startablesung ist ein
                # roher Zaehlerstand, nicht auf den Soll-Stichtag interpoliert. Mit
                # z.ende als Anker zaehlte die Folgeperiode einen Tag zu wenig
                # Ist-Tage, sobald die Ablesung nicht exakt auf die Periodengrenze
                # fiel (z.B. Periodenende 30.09., Ablesung am 01.10.) - das ergab
                # einen systematischen 364/365-Streckfaktor statt 1,0 und damit
                # rund -0,27 % Fehler im interpolierten Verbrauch.
                randwert, randdatum = a.stand, a.datum
                out[z.id] = {"verbrauch": 0.0, "randwert": randwert,
                             "datum": a.datum, "stand": a.stand, "start": True}
                continue
            anker = max(frueher, key=lambda v: v.datum)
            randwert, randdatum = anker.stand, anker.datum
        tage_ist = engine.tage(randdatum, a.datum)
        tage_soll = engine.tage(z.start, z.ende)
        verb = engine.interpoliere_verbrauch(randwert, a.stand, tage_ist, tage_soll)
        randwert = randwert + verb
        # N368 — der Anker für die NÄCHSTE Periode ist deren erster Tag, nicht
        # der letzte dieser. `engine.tage` misst exklusiv: `tage_soll` einer
        # lückenlos anschließenden Periode zählt von ihrem `start`, der Anker
        # zählte aber schon ab dem Vortag. Die Ist-Spanne war damit systematisch
        # einen Tag länger als die Soll-Spanne — Faktor 364/365, also −0,27 % in
        # JEDER Folgeperiode. Das ist derselbe Fehler, den N315(j) für die
        # Startperiode behoben hat; dort war er nur sichtbar, weil kein Test die
        # zweite Periode prüfte. Bei 3.431 L Heizöl fehlten so gut 9 Liter, und
        # die Summe aller Perioden ging nie auf die echte Zählerdifferenz auf.
        randdatum = z.ende + timedelta(days=1)
        out[z.id] = {"verbrauch": verb, "randwert": randwert,
                     "datum": a.datum, "stand": a.stand, "start": False}
    return out


def verbrauch_je_zaehler(zaehler_mit_ablesungen: list, zeitraeume: list,
                         zid: int) -> dict:
    """Verbrauch aller Zähler für einen Zeitraum. `zaehler_mit_ablesungen` ist
    eine Liste von (zaehler, [ablesungen]). Rest-Zähler (`typ='rest'`) ergeben
    sich als Gesamt (ihr `hauptzaehler_id`) minus die gemessenen Geschwister."""
    verb: dict[int, Optional[float]] = {}
    reihen: dict[int, dict] = {}
    for zaehler, ablesungen in zaehler_mit_ablesungen:
        # N120 — `direkt`: für manche Verbräuche gibt es keine Zählerstände,
        # sondern nur den fertigen Jahreswert (E-Auto-Ladestrom, Jahres-
        # abrechnung des Versorgers). Der eingetragene Wert IST der Verbrauch;
        # interpoliert wird nichts. Erkennbar an der Ablesung, die auf diesen
        # Zeitraum getaggt ist.
        if getattr(zaehler, "typ", "") == "direkt":
            treffer = [a for a in ablesungen if a.zeitraum_id == zid]
            verb[zaehler.id] = treffer[-1].stand if treffer else None
            continue
        reihe = verbrauchsreihe(ablesungen, zeitraeume)
        reihen[zaehler.id] = reihe
        eintrag = reihe.get(zid)
        verb[zaehler.id] = eintrag["verbrauch"] if eintrag else None

    # Rest-Zähler: Gesamt minus die gemessenen Unterzähler desselben Hauptzählers
    for zaehler, _ in zaehler_mit_ablesungen:
        if zaehler.typ != "rest" or not zaehler.hauptzaehler_id:
            continue
        gesamt = verb.get(zaehler.hauptzaehler_id)
        if gesamt is None:
            continue
        # Direkt erfasste Geschwister zaehlen genauso ab wie gemessene — sonst
        # bliebe der E-Auto-Strom im Rest des Hauses haengen.
        gemessen = [verb[z.id] for z, _ in zaehler_mit_ablesungen
                    if z.hauptzaehler_id == zaehler.hauptzaehler_id
                    and z.typ in ("gemessen", "direkt")
                    and verb.get(z.id) is not None]
        verb[zaehler.id] = engine.rest_verbrauch(gesamt, gemessen)
    return verb
