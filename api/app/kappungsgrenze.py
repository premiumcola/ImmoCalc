"""Kappungsgrenze nach § 558 Abs. 3 BGB — 20 %, in angespannten Märkten 15 %.

Wer die Miete auf die ortsübliche Vergleichsmiete anhebt, darf sie binnen drei
Jahren um höchstens 20 % erhöhen. In Gemeinden mit angespanntem Wohnungsmarkt
senkt eine Landesverordnung diese Grenze auf 15 % (§ 558 Abs. 3 Satz 2 und 3
BGB). Welche Gemeinden das sind, steht in `GEBIETE`.

**Gewarnt, nicht verboten.** Die Grenze kennt Ausnahmen — eine Erhöhung nach
Modernisierung (§ 559 BGB) fällt gar nicht darunter, und ob eine Erhöhung
formell wirksam ist, entscheidet nicht diese Datei. Die App rechnet vor, was
sie sieht, und nennt die Fundstelle; entscheiden muss der Vermieter.

**Warum AGS statt Name.** Die Anlage zur Bayerischen Mieterschutzverordnung
schreibt Eckental als „Eckenthal" — ein Namensabgleich läuft ins Leere.
Eindeutig ist allein der amtliche Gemeindeschlüssel (AGS). Er ist deshalb der
Schlüssel der Liste; Postleitzahl und Ortsteilnamen dienen nur dazu, ein
Objekt der richtigen Gemeinde zuzuordnen.

Quellen:
  § 558 BGB — https://www.gesetze-im-internet.de/bgb/__558.html
  Bayerische Mieterschutzverordnung vom 16.12.2025, GVBl. S. 718,
  BayRS 400-6-J, gültig 01.01.2026 bis 31.12.2029
  https://www.gesetze-bayern.de/Content/Document/BayMiSchuV2025
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Die allgemeine Grenze des § 558 Abs. 3 Satz 1 BGB.
ALLGEMEIN = 20.0
# Die abgesenkte Grenze in Gebieten mit angespanntem Wohnungsmarkt.
ANGESPANNT = 15.0
# Der Betrachtungszeitraum: drei Jahre vor Wirksamwerden der Erhöhung.
JAHRE = 3


@dataclass(frozen=True)
class Gebiet:
    """Eine Gemeinde mit angespanntem Wohnungsmarkt.

    `plz` sind Postleitzahlen oder deren Anfänge (Nürnberg hat über achtzig);
    `orte` sind Gemeinde- und Ortsteilnamen samt der Schreibweise, die in der
    Verordnung steht. Beides dient nur der Zuordnung — verbindlich ist `ags`.
    """
    ags: str
    name: str
    plz: tuple[str, ...]
    orte: tuple[str, ...]
    ab: date
    bis: date
    fundstelle: str
    grenze: float = ANGESPANNT
    ortsteile: tuple[str, ...] = field(default=())


# Klein und änderbar gehalten: die Verordnung läuft am 31.12.2029 aus, und
# ihre Anlage listet 285 Gemeinden. Hier stehen nur die, in denen tatsächlich
# Objekte liegen — eine weitere kommt mit vier Zeilen dazu.
BAYMISCHUV = ("Bayerische Mieterschutzverordnung vom 16.12.2025 "
              "(GVBl. S. 718), gültig bis 31.12.2029")

GEBIETE: tuple[Gebiet, ...] = (
    Gebiet(
        ags="09572121",
        name="Eckental",
        plz=("90542",),
        # „Eckenthal" mit „th" ist die Schreibweise der rechtsverbindlichen
        # Anlage; in der Begründung steht sie richtig. Beide zählen.
        orte=("eckental", "eckenthal"),
        ortsteile=("eschenau", "eckenhaid", "unterschöllenbach",
                   "unterschoellenbach", "forth", "brand", "herpersdorf",
                   "benzendorf", "oberschöllenbach", "oberschoellenbach"),
        ab=date(2026, 1, 1), bis=date(2029, 12, 31),
        fundstelle=f"{BAYMISCHUV}, Anlage Nr. 5.3.5",
    ),
    Gebiet(
        ags="09564000",
        name="Nürnberg",
        plz=("904",),
        orte=("nürnberg", "nuernberg"),
        ab=date(2026, 1, 1), bis=date(2029, 12, 31),
        fundstelle=f"{BAYMISCHUV}, Anlage Nr. 5.1.3",
    ),
)


def _schlicht(text: str) -> str:
    """Ortsnamen vergleichbar machen: klein, ohne Zusätze wie „b.Nürnberg"."""
    roh = str(text or "").strip().lower()
    for trenner in (",", "/", " b.", " bei ", " (", " -"):
        stelle = roh.find(trenner)
        if stelle > 0:
            roh = roh[:stelle]
    return roh.strip()


def gemeinde_fuer(objekt) -> Gebiet | None:
    """Welches Gebiet gilt für dieses Objekt — oder keines.

    Drei Wege, in dieser Reihenfolge: der am Objekt hinterlegte amtliche
    Gemeindeschlüssel, die Postleitzahl, der Ortsname (auch der eines
    Ortsteils — Eschenau steht nirgends in der Verordnung, gehört aber zu
    Eckental)."""
    ags = str(getattr(objekt, "ags", "") or "").strip()
    if ags:
        for g in GEBIETE:
            if g.ags == ags:
                return g
        return None
    plz = str(getattr(objekt, "plz", "") or "").strip()
    if plz:
        for g in GEBIETE:
            if any(plz.startswith(p) for p in g.plz):
                return g
    ort = _schlicht(getattr(objekt, "ort", ""))
    if ort:
        for g in GEBIETE:
            if ort in g.orte or ort in g.ortsteile:
                return g
    return None


def grenze_fuer(objekt, stichtag: date | None = None) -> dict:
    """Die Kappungsgrenze, die für dieses Objekt an diesem Tag gilt.

    Ausserhalb der Geltungsdauer der Verordnung gilt wieder die allgemeine
    Grenze — die App rechnet dann von selbst richtig weiter, ohne dass jemand
    ein Datum pflegen muss."""
    tag = stichtag or date.today()
    g = gemeinde_fuer(objekt)
    if g is None or not (g.ab <= tag <= g.bis):
        return {"prozent": ALLGEMEIN, "angespannt": False, "gemeinde": None,
                "ags": None, "gueltig_bis": None,
                "fundstelle": "§ 558 Abs. 3 Satz 1 BGB",
                "grund": "Höchstens 20 % in drei Jahren (§ 558 Abs. 3 BGB)."}
    return {
        "prozent": g.grenze,
        "angespannt": True,
        "gemeinde": g.name,
        "ags": g.ags,
        "gueltig_bis": g.bis.isoformat(),
        "fundstelle": g.fundstelle,
        "grund": f"{g.name} ist Gebiet mit angespanntem Wohnungsmarkt — "
                 f"höchstens {g.grenze:.0f} % in drei Jahren "
                 f"(§ 558 Abs. 3 Satz 2 BGB).",
    }


def _vor_jahren(tag: date, jahre: int) -> date:
    """Derselbe Tag vor `jahre` Jahren — der 29.02. wird zum 28.02."""
    try:
        return tag.replace(year=tag.year - jahre)
    except ValueError:
        return tag.replace(year=tag.year - jahre, day=28)


def basismiete(staende: list, stichtag: date) -> dict | None:
    """Die Kaltmiete, die drei Jahre vor dem Stichtag geschuldet war.

    `staende` sind die Mietstände derselben Partei (`Miete`), in beliebiger
    Reihenfolge. Gesucht ist der Stand, der am Stichtag minus drei Jahre galt.
    Gibt es keinen so alten — das Mietverhältnis läuft noch keine drei Jahre —,
    zählt der älteste: die Kappungsgrenze bemisst sich dann an der
    Ausgangsmiete.

    `None`, wenn gar kein Stand mit Kaltmiete vorliegt.
    """
    reihe = sorted((s for s in staende if getattr(s, "ab_datum", None)),
                   key=lambda s: s.ab_datum)
    if not reihe:
        return None
    schwelle = _vor_jahren(stichtag, JAHRE)
    frueher = [s for s in reihe if s.ab_datum <= schwelle]
    gewaehlt = frueher[-1] if frueher else reihe[0]
    return {"kaltmiete": round(float(getattr(gewaehlt, "kaltmiete", 0) or 0), 2),
            "ab_datum": gewaehlt.ab_datum.isoformat(),
            "stichtag": schwelle.isoformat(),
            "vollstaendig": bool(frueher)}


def pruefe(objekt, staende: list, neue_kaltmiete: float | None,
           ab_datum: date | None) -> dict:
    """Prüft eine geplante Erhöhung gegen die Kappungsgrenze.

    Verglichen wird die Nettokaltmiete — Betriebskosten, Stellplatz und
    sonstige Einnahmen bleiben aussen vor, sie gehören nicht in die Rechnung
    des § 558 BGB.

    Ohne neue Miete wird nur die Lage beschrieben (Grenze, Basismiete,
    Höchstmiete); das genügt der Oberfläche, um den Rahmen zu nennen, bevor
    etwas eingetippt ist.
    """
    tag = ab_datum or date.today()
    lage = grenze_fuer(objekt, tag)
    basis = basismiete(staende, tag)
    ergebnis: dict = {
        "grenze_prozent": lage["prozent"],
        "angespannt": lage["angespannt"],
        "gemeinde": lage["gemeinde"],
        "ags": lage["ags"],
        "gueltig_bis": lage["gueltig_bis"],
        "fundstelle": lage["fundstelle"],
        "grund": lage["grund"],
        "basis": basis,
        "hoechstmiete": None,
        "neue_kaltmiete": None,
        "erhoehung_prozent": None,
        "ueberschritten": False,
        # `titel` trägt die Überschrift der Warnung, `text` die Erklärung —
        # getrennt, damit die Oberfläche nicht beides ineinander schachtelt
        # und dieselbe Zahl zweimal dasteht.
        "titel": "",
        "text": lage["grund"],
    }
    if not basis or basis["kaltmiete"] <= 0:
        ergebnis["text"] = (f"{lage['grund']} Ohne eine frühere Kaltmiete lässt "
                            f"sich nicht ausrechnen, wie viel Luft bleibt.")
        return ergebnis

    alt = basis["kaltmiete"]
    hoechst = round(alt * (1 + lage["prozent"] / 100), 2)
    ergebnis["hoechstmiete"] = hoechst
    if neue_kaltmiete is None:
        ergebnis["text"] = (
            f"{lage['grund']} Gemessen an {_geld(alt)} vom "
            f"{_tag(basis['ab_datum'])} sind höchstens {_geld(hoechst)} "
            f"kalt möglich.")
        return ergebnis

    neu = round(float(neue_kaltmiete), 2)
    zuwachs = round((neu - alt) / alt * 100, 1)
    ergebnis["neue_kaltmiete"] = neu
    ergebnis["erhoehung_prozent"] = zuwachs
    ergebnis["ueberschritten"] = neu > hoechst + 0.005
    if ergebnis["ueberschritten"]:
        ergebnis["titel"] = (f"Über der Kappungsgrenze von "
                             f"{lage['prozent']:.0f} %")
        ergebnis["text"] = (
            f"{_geld(neu)} sind {_zuwachs(zuwachs)} mehr als die "
            f"{_geld(alt)} vom {_tag(basis['ab_datum'])}. Ohne besonderen "
            f"Grund sind höchstens {_geld(hoechst)} kalt möglich.")
    else:
        ergebnis["text"] = (
            f"{_zuwachs(zuwachs)} gegenüber {_geld(alt)} vom "
            f"{_tag(basis['ab_datum'])} — innerhalb der Kappungsgrenze von "
            f"{lage['prozent']:.0f} % (bis {_geld(hoechst)}).")
    return ergebnis


def _geld(betrag: float) -> str:
    """Ein Betrag, wie er in einem deutschen Satz steht: 1.234,50 €."""
    return f"{betrag:,.2f} €".replace(",", "#").replace(".", ",").replace("#", ".")


def _zuwachs(wert: float) -> str:
    """Ein Zuwachs in Prozent: 16,7 % — das Minus einer Senkung bleibt stehen."""
    return f"{wert:.1f} %".replace(".", ",")


def _tag(iso: str) -> str:
    jahr, monat, tag = iso.split("-")
    return f"{tag}.{monat}.{jahr}"
