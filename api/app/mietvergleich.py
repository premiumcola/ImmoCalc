"""Orientierungswert für die Quadratmetermiete — ist meine Miete in Ordnung?

Der Nutzer kennt seine Miete. Was ihm fehlt, ist der Vergleich: Liegt sie im
Rahmen dessen, was in seiner Lage gezahlt wird, oder deutlich darunter oder
darüber? Dieses Modul liefert dazu eine Spanne und ordnet die tatsächliche
Miete darin ein.

**Der Wert heißt „Orientierungswert", nicht „ortsübliche Vergleichsmiete".**
Letzteres ist ein Rechtsbegriff nach § 558 BGB mit vier abschließenden
Begründungsmitteln (Mietspiegel, Sachverständigengutachten, Auskunft aus einer
Mietdatenbank, drei Vergleichswohnungen). Ein Zensus-Mittelwert ist keines
davon. Er taugt zur Einordnung, nicht als Begründung einer Mieterhöhung.
Näheres in `docs/mietvergleich-recherche.md`.

Datengrundlage
--------------
Zensus 2022, durchschnittliche Nettokaltmiete je Quadratmeter und Anzahl der
vermieteten Wohnungen je 1-km-Gitterzelle — die einzige bundesweit
flächendeckende, frei nutzbare Quelle. Sie liegt als `daten/…csv.gz` im Repo;
zur Laufzeit wird nichts nachgeladen.

Rechenweg
---------
1. Koordinate (WGS84) → Gitterzelle (ETRS89-LAEA, EPSG:3035)
2. Zelle und Nachbarzellen einsammeln, bis genug vermietete Wohnungen
   zusammenkommen — sonst schlägt ein einzelnes Mehrfamilienhaus durch
3. Quartile und Median, **gewichtet mit der Zahl der Wohnungen** je Zelle
4. Fortschreibung vom Zensus-Stichtag 15.05.2022 auf heute über den
   Verbraucherpreisindex für Nettokaltmieten
5. Einordnung der tatsächlichen Miete in die fortgeschriebene Spanne

Jede Rückgabe nennt ihre Herkunft: Quelle, Stichtag, Zahl der Zellen, Radius,
Anteil unsicherer Werte. Ein Wert ohne Herkunft wäre in dieser App wertlos.

Die Adresse → Koordinate (Geokodierung) gehört nicht hierher: sie braucht einen
Netzdienst. Wer die Oberfläche baut, liefert Breite und Länge.
"""
from __future__ import annotations

import gzip
import logging
import math
import os
from datetime import date

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Quellenangabe — gehört an jede Ausgabe
# --------------------------------------------------------------------------

QUELLE = ("Statistische Ämter des Bundes und der Länder, Ergebnisse des "
          "Zensus 2022, durchschnittliche Nettokaltmiete je m² in "
          "1-km-Gitterzellen")
LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)"
LIZENZ_URL = "http://www.govdata.de/dl-de/by-2-0"
STICHTAG = date(2022, 5, 15)

DATEI = os.path.join(os.path.dirname(__file__), "daten",
                     "zensus2022_nettokaltmiete_1km.csv.gz")


# --------------------------------------------------------------------------
# WGS84 → ETRS89-LAEA (EPSG:3035)
# --------------------------------------------------------------------------
#
# Lambert-azimutal-flächentreu auf dem Ellipsoid GRS80, EPSG-Methode 9820.
# Formeln nach Snyder, "Map Projections — A Working Manual" (USGS PP 1395),
# Kapitel 24, in der Fassung der IOGP Geomatics Guidance Note 7-2.
# Geprüft gegen das amtliche Rechenbeispiel der Guidance Note:
#   50° N / 5° O  →  E 3.962.799,45 m / N 2.999.718,85 m  (Abweichung < 1 mm)
#
# Absichtlich von Hand gerechnet: das Projekt hat keine externen Bibliotheken,
# und pyproj wäre für zwei Formeln ein schweres Geschütz.

_A = 6378137.0                       # große Halbachse GRS80
_F = 1 / 298.257222101               # Abplattung GRS80
_E2 = _F * (2 - _F)                  # erste numerische Exzentrizität, quadriert
_E = math.sqrt(_E2)
_LAT0 = math.radians(52.0)           # Breite des Ursprungs
_LON0 = math.radians(10.0)           # Länge des Ursprungs
_OSTWERT = 4321000.0                 # False Easting
_NORDWERT = 3210000.0                # False Northing


def _q(sin_breite: float) -> float:
    """Flächentreue Hilfsgröße q (Snyder 3-12) — Fläche statt Winkel."""
    return (1 - _E2) * (sin_breite / (1 - _E2 * sin_breite ** 2)
                        - math.log((1 - _E * sin_breite) / (1 + _E * sin_breite))
                        / (2 * _E))


_QP = _q(1.0)                                    # q am Pol
_RQ = _A * math.sqrt(_QP / 2)                    # Radius der flächengleichen Kugel
_BETA0 = math.asin(_q(math.sin(_LAT0)) / _QP)    # authalische Breite des Ursprungs
_D = ((_A * math.cos(_LAT0) / math.sqrt(1 - _E2 * math.sin(_LAT0) ** 2))
      / (_RQ * math.cos(_BETA0)))


def nach_laea(breite: float, laenge: float) -> tuple[float, float]:
    """WGS84-Koordinate in Meter-Koordinaten der Projektion EPSG:3035."""
    lat = math.radians(breite)
    lon = math.radians(laenge)
    beta = math.asin(_q(math.sin(lat)) / _QP)
    d_lon = lon - _LON0
    nenner = (1 + math.sin(_BETA0) * math.sin(beta)
              + math.cos(_BETA0) * math.cos(beta) * math.cos(d_lon))
    if nenner <= 0:
        raise ValueError("Punkt liegt dem Projektionsursprung gegenüber")
    b = _RQ * math.sqrt(2 / nenner)
    x = _OSTWERT + b * _D * math.cos(beta) * math.sin(d_lon)
    y = _NORDWERT + (b / _D) * (math.cos(_BETA0) * math.sin(beta)
                                - math.sin(_BETA0) * math.cos(beta) * math.cos(d_lon))
    return x, y


def nach_wgs84(x: float, y: float) -> tuple[float, float]:
    """Rückweg aus EPSG:3035 — für Prüfungen und um eine Zelle zu verorten.

    Die Breite wird über die übliche Reihenentwicklung aus der authalischen
    Breite gewonnen; das bleibt millimetergenau und damit weit unterhalb der
    Kantenlänge einer Gitterzelle."""
    dx = x - _OSTWERT
    dy = y - _NORDWERT
    rho = math.hypot(dx / _D, _D * dy)
    if rho == 0:
        return math.degrees(_LAT0), math.degrees(_LON0)
    c = 2 * math.asin(rho / (2 * _RQ))
    beta = math.asin(math.cos(c) * math.sin(_BETA0)
                     + _D * dy * math.sin(c) * math.cos(_BETA0) / rho)
    laenge = _LON0 + math.atan2(
        dx * math.sin(c),
        _D * rho * math.cos(_BETA0) * math.cos(c)
        - _D * _D * dy * math.sin(_BETA0) * math.sin(c))
    breite = (beta
              + (_E2 / 3 + 31 * _E2 ** 2 / 180 + 517 * _E2 ** 3 / 5040)
              * math.sin(2 * beta)
              + (23 * _E2 ** 2 / 360 + 251 * _E2 ** 3 / 3780) * math.sin(4 * beta)
              + (761 * _E2 ** 3 / 45360) * math.sin(6 * beta))
    return math.degrees(breite), math.degrees(laenge)


def gitterzelle(breite: float, laenge: float) -> tuple[int, int]:
    """Koordinate → Kennung der 1-km-Gitterzelle als (Ost, Nord) in Kilometern.

    Das ist die linke untere Ecke der Zelle, genau wie in der INSPIRE-Kennung
    des Zensus (`CRS3035RES1000mN2943000E4409000` → (4409, 2943))."""
    x, y = nach_laea(breite, laenge)
    return math.floor(x / 1000), math.floor(y / 1000)


def gitter_id(ost: int, nord: int) -> str:
    """INSPIRE-Kennung der Zelle — so steht sie in den Zensus-Rohdaten."""
    return f"CRS3035RES1000mN{nord * 1000}E{ost * 1000}"


# --------------------------------------------------------------------------
# Datengrundlage
# --------------------------------------------------------------------------

# (Ost, Nord) -> (Miete in Cent, Zahl der vermieteten Wohnungen, unsicher)
_zellen: dict[tuple[int, int], tuple[int, int, bool]] | None = None


def _lies_datei(pfad: str) -> dict[tuple[int, int], tuple[int, int, bool]]:
    """Liest das kompakte Gitter. Aufbau steht im Kopf der Datei selbst."""
    zellen: dict[tuple[int, int], tuple[int, int, bool]] = {}
    with gzip.open(pfad, "rt", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#"):
                continue
            kopf, _, rest = zeile.partition("|")
            nord = int(kopf)
            ost = 0
            for eintrag in rest.split(";"):
                unsicher = eintrag.endswith("*")
                abstand, cent, wohnungen = (eintrag[:-1] if unsicher
                                            else eintrag).split(",")
                ost += int(abstand)
                zellen[(ost, nord)] = (int(cent), int(wohnungen), unsicher)
    return zellen


def lade(pfad: str | None = None) -> dict[tuple[int, int], tuple[int, int, bool]]:
    """Gitter aus der Datei, beim ersten Zugriff geladen und dann behalten.

    Rund 136.000 Zellen — das einmal im Speicher zu halten ist billiger, als
    für jede Anfrage 450 KB zu entpacken."""
    global _zellen
    if pfad is not None:
        return _lies_datei(pfad)
    if _zellen is None:
        _zellen = _lies_datei(DATEI)
        logger.info("Mietvergleich: %d Gitterzellen geladen", len(_zellen))
    return _zellen


def _als_zelle(ost: int, nord: int,
               treffer: tuple[int, int, bool]) -> dict:
    """Rohtripel der Datei in die nach außen sichtbare Form bringen."""
    cent, wohnungen, unsicher = treffer
    return {"ost": ost, "nord": nord, "gitter_id": gitter_id(ost, nord),
            "miete_qm": round(cent / 100, 2), "wohnungen": wohnungen,
            "unsicher": unsicher}


def zelle(ost: int, nord: int) -> dict | None:
    """Eine einzelne Gitterzelle, oder None, wenn dort keine Wohnungen sind.

    Zellen ohne vermietete Wohnungen kommen in den Zensus-Daten nicht vor —
    Wald, Acker, Gewerbegebiet, oder vom Geheimhaltungsverfahren entfernt."""
    treffer = lade().get((ost, nord))
    return _als_zelle(ost, nord, treffer) if treffer else None


def umgebung(ost: int, nord: int, radius: int) -> list[dict]:
    """Alle belegten Zellen im Quadrat mit `radius` Kilometern Rand.

    Ein Quadrat statt eines Kreises: bei Kantenlänge 1 km ist der Unterschied
    zur Genauigkeit der Datenbasis bedeutungslos, und es bleibt nachvollziehbar,
    welche Zellen eingeflossen sind."""
    gitter = lade()
    return [_als_zelle(ost + dx, nord + dy, gitter[(ost + dx, nord + dy)])
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if (ost + dx, nord + dy) in gitter]


# --------------------------------------------------------------------------
# Fortschreibung auf heute
# --------------------------------------------------------------------------
#
# Der Zensus bildet den 15.05.2022 ab. Ohne Fortschreibung wäre jeder
# Orientierungswert systematisch zu niedrig — Mieten steigen.
#
# Reihe: Verbraucherpreisindex für Deutschland, Teilindex „Tatsächliche
# Nettokaltmiete" (COICOP 04.1.1, Wägungsanteil 68,30 ‰), Jahresdurchschnitte,
# Basis 2020 = 100. Genau dieser Teilindex passt zum Zensus-Merkmal: was Mieter
# tatsächlich kalt zahlen. Die daneben veröffentlichte „unterstellte
# Nettokaltmiete" ist die rechnerische Miete von Selbstnutzern und gehört hier
# nicht hinein.
#
# Quelle: GENESIS-Online Tabelle 61111-0003 (Verbraucherpreisindex Deutschland,
# Jahre, COICOP), Merkmal CC13-0411, abgerufen am 21.07.2026 — alle Werte
# endgültig. Gegengeprüft an den Jahresmeldungen des Bundesamtes:
#   2024  107,7 (+2,2 %)  PD25_020_611     2025  110,0 (+2,1 %)  PD26_019_611
#   Juni 2026  112,4 (+2,2 % zum Vorjahresmonat)  PD26_243_611
# https://genesis.destatis.de/datenbank/online/statistic/61111/table/61111-0003
# https://www.destatis.de/DE/Presse/Pressemitteilungen/
#
# Neue Jahre einfach unten anfügen — die Rechnung zieht sie von selbst heran.

MIETINDEX: dict[int, float] = {
    2020: 100.0,     # Basisjahr
    2021: 101.4,
    2022: 103.2,
    2023: 105.4,
    2024: 107.7,
    2025: 110.0,
}

# Für Jahre nach dem letzten Eintrag wird mit dieser Jahresrate weitergerechnet
# und das Ergebnis als geschätzt gekennzeichnet. Stand: Veränderung Juni 2026
# gegenüber Juni 2025 (+2,2 %). Zur Probe: 110,0 × 1,022 = 112,4 — genau der
# für Juni 2026 veröffentlichte Indexstand.
MIETINDEX_FORTSCHREIBUNG = 0.022

# Veröffentlichter Monatswert für den Zensus-Stichtag, aus derselben Reihe
# (GENESIS 61111-0004, Mai 2022). Wird nicht gerechnet, sondern dient als
# Prüfstein: die Interpolation aus den Jahresdurchschnitten muss ihn treffen.
MIETINDEX_MAI_2022 = 103.0


def _index_am(zeitpunkt: date) -> tuple[float, bool]:
    """Indexstand zu einem Tag, plus Kennzeichen „über die Reihe hinaus".

    Ein Jahresdurchschnitt gilt als Wert der Jahresmitte; dazwischen wird
    linear interpoliert. Die Probe zeigt, dass das reicht: für Mai 2022 trifft
    die Interpolation den veröffentlichten Monatswert auf 0,1 Punkte genau."""
    if not MIETINDEX:
        raise ValueError("keine Indexreihe hinterlegt")
    jahre = sorted(MIETINDEX)
    # Bruchteil des Jahres, gemessen von Jahresmitte zu Jahresmitte
    stelle = zeitpunkt.year + (zeitpunkt.timetuple().tm_yday - 182.5) / 365.0
    if stelle <= jahre[0]:
        return MIETINDEX[jahre[0]], stelle < jahre[0]
    if stelle >= jahre[-1]:
        ueber = stelle - jahre[-1]
        return (MIETINDEX[jahre[-1]] * (1 + MIETINDEX_FORTSCHREIBUNG) ** ueber,
                ueber > 0)
    unten = max(j for j in jahre if j <= stelle)
    oben = min(j for j in jahre if j > stelle)
    anteil = (stelle - unten) / (oben - unten)
    return MIETINDEX[unten] + anteil * (MIETINDEX[oben] - MIETINDEX[unten]), False


def fortschreibungsfaktor(bis: date | None = None,
                          von: date | None = None) -> dict:
    """Um welchen Faktor die Miete seit dem Zensus-Stichtag gestiegen ist.

    Gibt den Faktor mit seiner Herleitung zurück — wer ihn anzweifelt, soll
    nachrechnen können, statt eine nackte Zahl glauben zu müssen."""
    von = von or STICHTAG
    bis = bis or date.today()
    basis, _ = _index_am(von)
    aktuell, geschaetzt = _index_am(bis)
    return {
        "faktor": round(aktuell / basis, 4),
        "von": von.isoformat(),
        "bis": bis.isoformat(),
        "index_von": round(basis, 1),
        "index_bis": round(aktuell, 1),
        "geschaetzt": geschaetzt,
        "reihe": ("Verbraucherpreisindex, Teilindex Tatsächliche "
                  "Nettokaltmiete, 2020 = 100"),
        "reihe_quelle": ("Statistisches Bundesamt, Verbraucherpreisindex für "
                         "Deutschland, Jahresdurchschnitte, GENESIS-Online "
                         "61111-0003 (CC13-0411)"),
        "reihe_bis_jahr": max(MIETINDEX) if MIETINDEX else None,
    }


# --------------------------------------------------------------------------
# Spanne aus dem Gitter
# --------------------------------------------------------------------------

# Ab wann eine Aussage trägt. Eine einzelne Zelle mit sechs Wohnungen sagt
# nichts: Zensuswerte sind zur Geheimhaltung leicht verrauscht, und ein einziges
# günstiges Haus zieht den Schnitt weit nach unten. Erst mit einigen hundert
# Wohnungen aus mehreren Zellen wird daraus eine Größenordnung.
MINDEST_WOHNUNGEN = 500
MINDEST_ZELLEN = 5
MAX_RADIUS = 10          # Kilometer; darüber ist es nicht mehr dieselbe Lage


def gewichtetes_quantil(werte: list[tuple[float, float]], q: float) -> float:
    """Quantil einer nach Häufigkeit gewichteten Verteilung.

    `werte` sind Paare (Miete, Gewicht). Gewichtet wird mit der Zahl der
    vermieteten Wohnungen: eine Zelle mit 4000 Wohnungen beschreibt die Lage
    besser als eine mit dreien. Ungewichtet wäre der Median der Median der
    *Zellen*, nicht der der Wohnungen — auf dem Land wären das lauter kaum
    besiedelte Zellen."""
    if not werte:
        raise ValueError("keine Werte")
    geordnet = sorted(werte)
    gesamt = sum(g for _, g in geordnet)
    if gesamt <= 0:
        return geordnet[len(geordnet) // 2][0]
    ziel = q * gesamt
    laufend = 0.0
    for wert, gewicht in geordnet:
        laufend += gewicht
        if laufend >= ziel:
            return wert
    return geordnet[-1][0]


def _sammle(ost: int, nord: int) -> tuple[list[dict], int]:
    """Nachbarschaft so weit ausdehnen, bis sie trägt. Radius wird mitgemeldet."""
    gefunden: list[dict] = []
    for radius in range(1, MAX_RADIUS + 1):
        gefunden = umgebung(ost, nord, radius)
        genug = (len(gefunden) >= MINDEST_ZELLEN
                 and sum(z["wohnungen"] for z in gefunden) >= MINDEST_WOHNUNGEN)
        if genug:
            return gefunden, radius
    return gefunden, MAX_RADIUS


def spanne(breite: float, laenge: float, stichtag: date | None = None) -> dict:
    """Orientierungsspanne für eine Koordinate — Quartile und Median.

    Trägt die Umgebung keine Aussage, wird das gesagt und nicht gerechnet.
    Lieber „weiß ich nicht" als eine Zahl, auf die sich niemand stützen kann."""
    ost, nord = gitterzelle(breite, laenge)
    eigene = zelle(ost, nord)
    nachbarn, radius = _sammle(ost, nord)
    wohnungen = sum(z["wohnungen"] for z in nachbarn)

    herkunft = {
        "quelle": QUELLE,
        "lizenz": LIZENZ,
        "lizenz_url": LIZENZ_URL,
        "stichtag": STICHTAG.isoformat(),
        "gitter": "1 km (ETRS89-LAEA, EPSG:3035)",
        "gitter_id": gitter_id(ost, nord),
        "radius_km": radius,
        "zellen": len(nachbarn),
        "wohnungen": wohnungen,
        "zelle_belegt": eigene is not None,
        "unsichere_zellen": sum(1 for z in nachbarn if z["unsicher"]),
    }

    if (len(nachbarn) < MINDEST_ZELLEN or wohnungen < MINDEST_WOHNUNGEN):
        logger.info("Mietvergleich: zu dünne Datenlage bei %s (%d Zellen, "
                    "%d Wohnungen)", herkunft["gitter_id"], len(nachbarn), wohnungen)
        return {"tragfaehig": False,
                "grund": ("In dieser Lage sind zu wenige vermietete Wohnungen "
                          "erfasst, um eine Spanne zu bilden."),
                "herkunft": herkunft}

    paare = [(z["miete_qm"], float(z["wohnungen"])) for z in nachbarn]
    unten = gewichtetes_quantil(paare, 0.25)
    mitte = gewichtetes_quantil(paare, 0.50)
    oben = gewichtetes_quantil(paare, 0.75)

    fort = fortschreibungsfaktor(bis=stichtag)
    f = fort["faktor"]
    anteil_unsicher = herkunft["unsichere_zellen"] / len(nachbarn)

    return {
        "tragfaehig": True,
        # Stand Zensus-Stichtag — unverändert, so wie veröffentlicht
        "zensus": {"unten": unten, "mitte": mitte, "oben": oben},
        # Auf den Stichtag der Anfrage fortgeschrieben; das ist der Wert für die
        # Oberfläche
        "unten": round(unten * f, 2),
        "mitte": round(mitte * f, 2),
        "oben": round(oben * f, 2),
        "fortschreibung": fort,
        "guete": _guete(len(nachbarn), wohnungen, anteil_unsicher, radius),
        "herkunft": herkunft,
    }


def _guete(zellen: int, wohnungen: int, anteil_unsicher: float,
           radius: int) -> str:
    """Wie belastbar die Spanne ist: gut, mittel oder grob.

    Viele Wohnungen aus einer engen Umgebung sind gut. Musste weit ausgeholt
    werden oder sind viele Zellen als unsicher gekennzeichnet, ist es grob."""
    if radius >= 5 or anteil_unsicher > 0.3:
        return "grob"
    if wohnungen >= 3000 and zellen >= 9 and radius <= 2 and anteil_unsicher <= 0.1:
        return "gut"
    return "mittel"


# --------------------------------------------------------------------------
# Einordnung der tatsächlichen Miete
# --------------------------------------------------------------------------

EINORDNUNG = {
    "zu_niedrig": "unter der Spanne",
    "fair": "in der Spanne",
    "zu_hoch": "über der Spanne",
}


def einordnung(miete_qm: float, unten: float, oben: float) -> str:
    """`zu_niedrig`, `fair` oder `zu_hoch` — allein an der Spanne gemessen.

    Die Grenzen gehören zur Spanne: genau auf dem unteren Quartil ist noch
    fair, nicht zu niedrig."""
    if miete_qm < unten:
        return "zu_niedrig"
    if miete_qm > oben:
        return "zu_hoch"
    return "fair"


def bewerte(breite: float, laenge: float, kaltmiete: float, wohnflaeche: float,
            stichtag: date | None = None) -> dict:
    """Vollständige Auskunft zu einer konkreten Wohnung.

    `kaltmiete` ist die Nettokaltmiete im Monat, `wohnflaeche` in m² — der
    Zensus misst genau das, also muss auch der Vergleichswert so gebildet
    werden. Nebenkosten gehören nicht hinein."""
    if wohnflaeche is None or wohnflaeche <= 0:
        raise ValueError("Wohnfläche muss größer als null sein")
    miete_qm = round(float(kaltmiete) / float(wohnflaeche), 2)
    ergebnis = spanne(breite, laenge, stichtag)
    ergebnis["miete_qm"] = miete_qm
    ergebnis["kaltmiete"] = round(float(kaltmiete), 2)
    ergebnis["wohnflaeche"] = round(float(wohnflaeche), 2)

    if not ergebnis["tragfaehig"]:
        ergebnis["einordnung"] = None
        ergebnis["text"] = ("Für diese Lage liegt kein Orientierungswert vor.")
        return ergebnis

    lage = einordnung(miete_qm, ergebnis["unten"], ergebnis["oben"])
    mitte = ergebnis["mitte"]
    ergebnis["einordnung"] = lage
    ergebnis["abweichung_prozent"] = round((miete_qm / mitte - 1) * 100, 1) if mitte else None
    ergebnis["spielraum_bis_oben"] = round(
        (ergebnis["oben"] - miete_qm) * float(wohnflaeche), 2)
    ergebnis["text"] = (
        f"{miete_qm:.2f} €/m² — {EINORDNUNG[lage]} von {ergebnis['unten']:.2f} "
        f"bis {ergebnis['oben']:.2f} €/m² (Mitte {mitte:.2f} €/m²)")
    return ergebnis


def quellenvermerk() -> str:
    """Der Nachweis, der nach der Datenlizenz sichtbar mitlaufen muss."""
    return (f"{QUELLE}. {LIZENZ}, {LIZENZ_URL}. Stichtag "
            f"{STICHTAG.strftime('%d.%m.%Y')}, fortgeschrieben mit dem "
            f"Verbraucherpreisindex für Nettokaltmieten des Statistischen "
            f"Bundesamtes.")
