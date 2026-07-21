"""Vermögensübersicht: was gehört mir, was schulde ich, was ist es wert.

Rechnet je Objekt und in Summe:
  Wert        — Verkehrswert, ersatzweise Kaufpreis
  Restschuld  — Summe der offenen Darlehen
  Guthaben    — Summe der Bausparguthaben
  Eigenkapital = Wert − Restschuld + Bausparguthaben
  Volumen     — investiertes Volumen (Kaufpreis)
  Beleihung   — Restschuld / Wert in Prozent

Fehlen Angaben, wird die Zeile trotzdem gezeigt — mit dem, was da ist. Ein
Objekt ohne Kredit hat schlicht keine Restschuld, das ist kein Fehler.

Der Stand eines Vertrags wird nicht geraten: eingetragen wird er zum 31.12.
eines Jahres — wie ein Zählerstand —, dazwischen schreibt
`stand_fortschreiben` bzw. `spar_fortschreiben` monatlich fort.

**Ein Bausparvertrag ist kein Darlehen** (CXLIX). Er läuft unter derselben
Überschrift, weil er an derselben Immobilie hängt und dieselbe Rate im Monat
kostet — gerechnet wird er aber umgekehrt:

  Darlehen         Restschuld sinkt · mindert das Eigenkapital · Zinslast
  Bausparvertrag   Guthaben wächst · erhöht das Eigenkapital · keine Zinslast

Ein Bausparguthaben in der Beleihungsquote aufzurechnen wäre falsch: die
Quote misst, wie stark das Objekt belastet ist, und das Guthaben liegt
daneben, nicht darin.
"""
from __future__ import annotations

from datetime import date

from .models import ist_bausparer, ist_grundstueck
from .turnus import jahresbetrag


def _wert(objekt) -> float | None:
    """Verkehrswert schlägt Kaufpreis — er ist die aktuellere Angabe."""
    if objekt.verkehrswert:
        return float(objekt.verkehrswert)
    if objekt.kaufpreis:
        return float(objekt.kaufpreis)
    return None


# --------------------------------------------------------------------------
# Restschuld fortschreiben
# --------------------------------------------------------------------------

def monatsrate(kredit) -> float:
    """Was monatlich an die Bank geht — unabhängig vom eingetragenen Turnus.

    Eine vierteljährlich gezahlte Rate von 3000 € tilgt im Monat wie 1000 €."""
    return round(jahresbetrag(kredit.rate_monatlich, kredit.turnus) / 12, 2)


def monatszinssatz(zinssatz: float | None) -> float:
    """Der Jahreszinssatz als Faktor je Monat: 1,28 % → 0,001066…"""
    return float(zinssatz or 0) / 100 / 12


def monatszins(restschuld: float | None, zinssatz: float | None) -> float | None:
    """Zinsanteil einer Monatsrate: Restschuld × Zinssatz ÷ 12.

    Bei 140.000 € und 1,28 % sind das 149,33 € im Monat. Gerundet wird erst
    zum Schluss — die Rechnung selbst läuft ungerundet.

    `None`, solange die Restschuld fehlt oder null ist: ohne sie gibt es
    nichts umzurechnen, und 0,00 € wäre eine Behauptung statt einer Auskunft."""
    rest = float(restschuld or 0)
    if rest <= 0 or zinssatz is None:
        return None
    return round(rest * monatszinssatz(zinssatz), 2)


def zinssatz_aus_monatszins(restschuld: float | None,
                            zins_monat: float | None) -> float | None:
    """Der umgekehrte Weg: aus dem monatlichen Zinsanteil der Jahreszinssatz.

    Wer seine Rate kennt und den Satz nicht, liest den Zinsanteil aus dem
    Kontoauszug ab — 149,33 € auf 140.000 € sind 1,28 % im Jahr. Zwei
    Nachkommastellen, wie sie eine Bank auch ausweist."""
    rest = float(restschuld or 0)
    if rest <= 0 or zins_monat is None:
        return None
    return round(float(zins_monat) * 12 / rest * 100, 2)


def monate_seit_jahresende(jahr: int, stichtag: date) -> int:
    """Volle Monatsraten zwischen dem 31.12. eines Jahres und dem Stichtag.

    Negativ, wenn der Stichtag davor liegt — dann wird zurückgerechnet."""
    return (stichtag.year - jahr) * 12 + (stichtag.month - 12)


def stand_fortschreiben(rest: float, rate_monat: float, zinssatz: float | None,
                        monate: int) -> float:
    """Restschuld um `monate` Monate fortschreiben (negativ: zurückrechnen).

    Je Monat: Zins = Restschuld × Zinssatz / 12, Tilgung = Rate − Zins. Weil
    die Restschuld sinkt, sinkt auch der Zinsanteil und die Tilgung wächst —
    genau das macht eine Annuität aus.

    Deckt die Rate den Zins nicht (oder ist keine Rate erfasst), bleibt die
    Restschuld stehen. Lieber der letzte bekannte Wert als eine erfundene
    Kurve."""
    zins_monat = monatszinssatz(zinssatz)
    rate = float(rate_monat or 0)
    wert = float(rest or 0)
    if rate <= 0 or wert <= 0:
        return round(wert, 2)
    for _ in range(abs(monate)):
        if monate > 0:
            tilgung = rate - wert * zins_monat
            if tilgung <= 0:
                break               # Rate deckt nicht einmal die Zinsen
            wert = max(wert - tilgung, 0.0)
            if wert <= 0:
                break
        else:
            # Rückwärts: aus rest_neu = rest_alt × (1 + z) − Rate folgt
            wert = (wert + rate) / (1 + zins_monat)
    return round(wert, 2)


def spar_fortschreiben(stand: float, rate_monat: float, zinssatz: float | None,
                       monate: int, ziel: float | None = None) -> float:
    """Sparstand eines Bausparvertrags fortschreiben (negativ: zurückrechnen).

    Dieselbe Mechanik wie `stand_fortschreiben`, nur andersherum: je Monat
    kommt die Rate hinzu, und das vorhandene Guthaben verzinst sich mit dem
    Habenzins. Über die Bausparsumme hinaus wächst nichts — ist sie erreicht,
    ist die Ansparphase zu Ende und der Vertrag zuteilungsreif.

    Ohne Rate bleibt der Stand stehen (bis auf die Verzinsung). Lieber der
    letzte bekannte Wert als eine erfundene Kurve — wie beim Darlehen.
    """
    zins_monat = monatszinssatz(zinssatz)
    rate = float(rate_monat or 0)
    wert = float(stand or 0)
    grenze = float(ziel) if ziel else None
    for _ in range(abs(monate)):
        if monate > 0:
            wert = wert * (1 + zins_monat) + rate
            if grenze is not None and wert >= grenze:
                return round(grenze, 2)
        else:
            # Rückwärts: aus stand_neu = stand_alt × (1 + z) + Rate folgt
            wert = max((wert - rate) / (1 + zins_monat), 0.0)
    return round(max(wert, 0.0), 2)


def _reihe(staende: list | None) -> list:
    """Jahresstände, aufsteigend nach Jahr."""
    return sorted((s for s in (staende or []) if s.jahr), key=lambda s: s.jahr)


def _basis(reihe: list, heute: date):
    """Der Jahresstand, von dem aus gerechnet wird — der letzte vergangene."""
    vergangen = [s for s in reihe if date(s.jahr, 12, 31) <= heute]
    return vergangen[-1] if vergangen else reihe[0]


def _lage(art: str, stand: float, quelle: str, jahr: int | None,
          stand_wert: float | None, monate: int, rate: float,
          kredit) -> dict:
    """Ein Vertragsstand in der Form, die Oberfläche und Übersicht lesen.

    `restschuld` und `guthaben` schliessen sich aus: was kein Darlehen ist,
    hat keine Restschuld, und was kein Bausparvertrag ist, kein Guthaben. So
    kann keine Auswertung ein Guthaben versehentlich als Schuld addieren."""
    bausparer = ist_bausparer(kredit)
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None
    return {
        "art": art,
        "restschuld": 0.0 if bausparer else stand,
        "guthaben": stand if bausparer else 0.0,
        "stand": stand,
        "bausparsumme": ziel,
        "noch_zu_sparen": round(max(ziel - stand, 0.0), 2) if ziel else None,
        "zuteilungsreif": bool(ziel) and stand >= ziel,
        "quelle": quelle,
        "stand_jahr": jahr,
        "stand_wert": stand_wert,
        "monate": monate,
        "rate_monat": rate,
        # Was von der Rate an Zinsen weggeht — je kleiner die Restschuld wird,
        # desto weniger. Ein Bausparer in der Ansparphase zahlt keine Zinsen,
        # er bekommt welche: dort steht `None` und daneben der Habenzins.
        "zins_monat": None if bausparer else monatszins(stand, kredit.zinssatz),
        "habenzins_monat": monatszins(stand, kredit.zinssatz) if bausparer else None,
    }


def kreditstand(kredit, staende: list | None = None,
                stichtag: date | None = None) -> dict:
    """Der Stand eines Vertrags zum Stichtag — Restschuld oder Guthaben.

    Ohne Jahresstände gilt weiter das eingetragene Feld (`Kredit.restschuld`
    beim Darlehen, `Kredit.angespart` beim Bausparvertrag) — so bleibt jeder
    gewachsene Bestand unverändert richtig. Mit Jahresständen wird vom letzten
    Stand vor dem Stichtag monatlich fortgeschrieben."""
    heute = stichtag or date.today()
    reihe = _reihe(staende)
    rate = monatsrate(kredit)
    bausparer = ist_bausparer(kredit)
    art = "bausparvertrag" if bausparer else "darlehen"
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None

    if not reihe:
        roh = kredit.angespart if bausparer else kredit.restschuld
        stand = round(float(roh or 0), 2)
        if ziel:
            stand = min(stand, round(ziel, 2))
        return _lage(art, stand, "eingetragen", None, None, 0, rate, kredit)

    basis = _basis(reihe, heute)
    monate = monate_seit_jahresende(basis.jahr, heute)
    stand = (spar_fortschreiben(basis.restschuld, rate, kredit.zinssatz, monate, ziel)
             if bausparer
             else stand_fortschreiben(basis.restschuld, rate, kredit.zinssatz, monate))
    return _lage(art, stand, "jahresstand" if monate == 0 else "fortgeschrieben",
                 basis.jahr, round(float(basis.restschuld or 0), 2),
                 monate, rate, kredit)


def verlauf(kredit, staende: list | None = None,
            bis_jahr: int | None = None) -> list[dict]:
    """Der Stand zum 31.12. je Jahr — eingetragene Stände und die Rechnung
    dazwischen. Zeigt in der Oberfläche, wo gemessen und wo gerechnet wurde.

    Der Schlüssel heisst weiter `restschuld`, damit bestehende Aufrufer
    unverändert lesen; beim Bausparvertrag steht dort der Sparstand, und
    `stand` nennt denselben Wert unter neutralem Namen."""
    reihe = _reihe(staende)
    if not reihe:
        return []
    bausparer = ist_bausparer(kredit)
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None
    ende = max(bis_jahr or date.today().year, reihe[-1].jahr)
    eingetragen = {s.jahr: round(float(s.restschuld or 0), 2) for s in reihe}
    rate = monatsrate(kredit)
    zeilen: list[dict] = []
    wert = eingetragen[reihe[0].jahr]
    for jahr in range(reihe[0].jahr, ende + 1):
        if jahr in eingetragen:
            wert = eingetragen[jahr]
            zeilen.append({"jahr": jahr, "restschuld": wert, "stand": wert,
                           "eingetragen": True})
            continue
        wert = (spar_fortschreiben(wert, rate, kredit.zinssatz, 12, ziel) if bausparer
                else stand_fortschreiben(wert, rate, kredit.zinssatz, 12))
        zeilen.append({"jahr": jahr, "restschuld": wert, "stand": wert,
                       "eingetragen": False})
    return zeilen


def kapitaldienst_jahr(kredite: list) -> float:
    """Was im Jahr an die Banken geht — ohne Sparraten.

    Für jede Auswertung, die Kreditkosten als Ausgabe zeigt: die Rate eines
    Bausparvertrags ist keine Ausgabe, sondern eine Umschichtung in eigenes
    Vermögen. Sie hier mitzuzählen machte den Cashflow schlechter, als er
    ist."""
    return round(sum(jahresbetrag(k.rate_monatlich, k.turnus)
                     for k in kredite if not ist_bausparer(k)), 2)


def sparrate_jahr(kredite: list) -> float:
    """Was im Jahr in Bausparverträge fliesst — Gegenstück zum Kapitaldienst."""
    return round(sum(jahresbetrag(k.rate_monatlich, k.turnus)
                     for k in kredite if ist_bausparer(k)), 2)


def objekt_vermoegen(objekt, kredite: list, anteile: list | None = None,
                     staende: dict[int, list] | None = None,
                     stichtag: date | None = None) -> dict:
    """Vermögenslage eines Objekts. `anteile` sind Tausendstel je Eigentümer.

    `staende` sind die Jahresstände je Kredit-id. Ohne sie zählt weiter das
    Feld `Kredit.restschuld` — die Übersicht bleibt damit unverändert
    richtig, auch wenn noch niemand einen Jahresstand gepflegt hat."""
    wert = _wert(objekt)
    lagen = [(k, kreditstand(k, (staende or {}).get(getattr(k, "id", None)),
                             stichtag)) for k in kredite]
    darlehen = [(k, lage) for k, lage in lagen if not ist_bausparer(k)]
    bausparer = [(k, lage) for k, lage in lagen if ist_bausparer(k)]

    restschuld = round(sum(lage["restschuld"] for _, lage in darlehen), 2)
    guthaben = round(sum(lage["guthaben"] for _, lage in bausparer), 2)
    # Annuität ist Kapitaldienst — Zins und Tilgung. Eine Sparrate gehört
    # nicht dazu: sie verlässt zwar das Konto, wird aber zu eigenem Vermögen.
    annuitaet = kapitaldienst_jahr(kredite)
    sparrate = sparrate_jahr(kredite)
    zinsen = round(sum(lage["restschuld"] * float(k.zinssatz or 0) / 100
                       for k, lage in darlehen), 2)
    # Das Guthaben liegt neben der Immobilie, nicht in ihr: es erhöht das
    # Eigenkapital, mindert aber die Beleihung nicht.
    eigen = round(wert - restschuld + guthaben, 2) if wert is not None else None
    quote = round(restschuld / wert * 100, 1) if wert else None
    gehalten = sum(int(a.tausendstel or 0) for a in (anteile or [])) or None

    return {
        "slug": objekt.slug,
        "name": objekt.name,
        "wert": wert,
        # Beim Grundstueck ist derselbe Wert der Grundstueckswert — das Wort
        # „Verkehrswert" passt dort nicht zu dem, was der Nutzer eingetragen
        # hat. Der Wert selbst ist unveraendert, nur seine Bezeichnung folgt
        # dem Objekttyp.
        "wertquelle": ("Grundstückswert" if ist_grundstueck(objekt) else
                       "Verkehrswert") if objekt.verkehrswert else (
            "Kaufpreis" if objekt.kaufpreis else None),
        "kaufpreis": float(objekt.kaufpreis) if objekt.kaufpreis else None,
        "restschuld": restschuld,
        "bauspar_guthaben": guthaben,
        "bausparvertraege": len(bausparer),
        "eigenkapital": eigen,
        "beleihung": quote,
        "annuitaet_jahr": annuitaet,
        "sparrate_jahr": sparrate,
        "zinslast_jahr": zinsen,
        "tilgung_jahr": round(max(annuitaet - zinsen, 0.0), 2),
        "kredite": len(kredite),
        "tausendstel": gehalten,
        # Anteilig bewertet — bei Alleineigentum identisch mit eigenkapital
        "eigenkapital_anteilig": round(eigen * gehalten / 1000, 2)
        if eigen is not None and gehalten else eigen,
    }


def gesamt(zeilen: list[dict]) -> dict:
    """Summenzeile. `None` zählt als nicht vorhanden, nicht als Null."""
    def summe(feld: str) -> float:
        return round(sum(z[feld] or 0 for z in zeilen), 2)

    # Kennt kein einziges Objekt seinen Wert, ist die Summe nicht null, sondern
    # unbekannt — sonst stuende oben "0 €" und darunter ein rotes Eigenkapital
    # in Hoehe der gesamten Restschuld.
    bekannt = any(z["wert"] is not None for z in zeilen)
    wert = summe("wert") if bekannt else None
    restschuld = summe("restschuld")
    guthaben = summe("bauspar_guthaben")
    return {
        "objekte": len(zeilen),
        "wert": wert,
        "kaufpreis": summe("kaufpreis"),
        "restschuld": restschuld,
        "bauspar_guthaben": guthaben,
        "eigenkapital": round(wert - restschuld + guthaben, 2) if bekannt else None,
        "eigenkapital_anteilig": summe("eigenkapital_anteilig") if bekannt else None,
        "beleihung": round(restschuld / wert * 100, 1) if wert else None,
        "annuitaet_jahr": summe("annuitaet_jahr"),
        "sparrate_jahr": summe("sparrate_jahr"),
        "zinslast_jahr": summe("zinslast_jahr"),
        "tilgung_jahr": summe("tilgung_jahr"),
        "ohne_wert": sum(1 for z in zeilen if z["wert"] is None),
    }
