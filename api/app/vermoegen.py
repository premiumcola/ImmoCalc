"""Vermögensübersicht: was gehört mir, was schulde ich, was ist es wert.

Rechnet je Objekt und in Summe:
  Wert        — Verkehrswert, ersatzweise Kaufpreis
  Restschuld  — Summe der offenen Darlehen
  Eigenkapital = Wert − Restschuld
  Volumen     — investiertes Volumen (Kaufpreis)
  Beleihung   — Restschuld / Wert in Prozent

Fehlen Angaben, wird die Zeile trotzdem gezeigt — mit dem, was da ist. Ein
Objekt ohne Kredit hat schlicht keine Restschuld, das ist kein Fehler.

Die Restschuld eines Kredits wird nicht geraten: eingetragen wird der Stand
zum 31.12. eines Jahres — wie ein Zählerstand —, dazwischen schreibt
`stand_fortschreiben` monatlich fort.
"""
from __future__ import annotations

from datetime import date

from .models import ist_grundstueck
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


def _reihe(staende: list | None) -> list:
    """Jahresstände, aufsteigend nach Jahr."""
    return sorted((s for s in (staende or []) if s.jahr), key=lambda s: s.jahr)


def kreditstand(kredit, staende: list | None = None,
                stichtag: date | None = None) -> dict:
    """Restschuld eines Kredits zum Stichtag.

    Ohne Jahresstände gilt weiter das Feld `Kredit.restschuld` — so bleibt
    jeder gewachsene Bestand unverändert richtig. Mit Jahresständen wird vom
    letzten Stand vor dem Stichtag monatlich fortgeschrieben."""
    heute = stichtag or date.today()
    reihe = _reihe(staende)
    rate = monatsrate(kredit)
    if not reihe:
        rest = round(float(kredit.restschuld or 0), 2)
        return {"restschuld": rest,
                "quelle": "eingetragen", "stand_jahr": None, "stand_wert": None,
                "monate": 0, "rate_monat": rate,
                "zins_monat": monatszins(rest, kredit.zinssatz)}

    vergangen = [s for s in reihe if date(s.jahr, 12, 31) <= heute]
    basis = vergangen[-1] if vergangen else reihe[0]
    monate = monate_seit_jahresende(basis.jahr, heute)
    rest = stand_fortschreiben(basis.restschuld, rate, kredit.zinssatz, monate)
    return {
        "restschuld": rest,
        "quelle": "jahresstand" if monate == 0 else "fortgeschrieben",
        "stand_jahr": basis.jahr,
        "stand_wert": round(float(basis.restschuld or 0), 2),
        "monate": monate,
        "rate_monat": rate,
        # Was von der Rate an Zinsen weggeht — je kleiner die Restschuld
        # wird, desto weniger.
        "zins_monat": monatszins(rest, kredit.zinssatz),
    }


def verlauf(kredit, staende: list | None = None,
            bis_jahr: int | None = None) -> list[dict]:
    """Restschuld zum 31.12. je Jahr — eingetragene Stände und die Rechnung
    dazwischen. Zeigt in der Oberfläche, wo gemessen und wo gerechnet wurde."""
    reihe = _reihe(staende)
    if not reihe:
        return []
    ende = max(bis_jahr or date.today().year, reihe[-1].jahr)
    eingetragen = {s.jahr: round(float(s.restschuld or 0), 2) for s in reihe}
    rate = monatsrate(kredit)
    zeilen: list[dict] = []
    wert = eingetragen[reihe[0].jahr]
    for jahr in range(reihe[0].jahr, ende + 1):
        if jahr in eingetragen:
            wert = eingetragen[jahr]
            zeilen.append({"jahr": jahr, "restschuld": wert, "eingetragen": True})
            continue
        wert = stand_fortschreiben(wert, rate, kredit.zinssatz, 12)
        zeilen.append({"jahr": jahr, "restschuld": wert, "eingetragen": False})
    return zeilen


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
    restschuld = round(sum(lage["restschuld"] for _, lage in lagen), 2)
    annuitaet = round(sum(jahresbetrag(k.rate_monatlich, k.turnus) for k in kredite), 2)
    zinsen = round(sum(lage["restschuld"] * float(k.zinssatz or 0) / 100
                       for k, lage in lagen), 2)
    eigen = round(wert - restschuld, 2) if wert is not None else None
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
        "eigenkapital": eigen,
        "beleihung": quote,
        "annuitaet_jahr": annuitaet,
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
    return {
        "objekte": len(zeilen),
        "wert": wert,
        "kaufpreis": summe("kaufpreis"),
        "restschuld": restschuld,
        "eigenkapital": round(wert - restschuld, 2) if bekannt else None,
        "eigenkapital_anteilig": summe("eigenkapital_anteilig") if bekannt else None,
        "beleihung": round(restschuld / wert * 100, 1) if wert else None,
        "annuitaet_jahr": summe("annuitaet_jahr"),
        "zinslast_jahr": summe("zinslast_jahr"),
        "tilgung_jahr": summe("tilgung_jahr"),
        "ohne_wert": sum(1 for z in zeilen if z["wert"] is None),
    }
