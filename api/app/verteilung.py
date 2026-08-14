"""Verteilungsgewichte aus dem Schlüssel ableiten.

Die Rechen-Engine verteilt Kosten nach Gewichten (`Kostenposition.anteile`).
Woher diese Gewichte kommen, stand bisher nirgends: geschrieben hat sie nur der
Seed, und für jede selbst angelegte Immobilie blieb das Feld leer — die
Abrechnung lieferte dann keine Parteien und in der Summe 0,00 €.

Hier steht deshalb die Ableitung: aus den Stammdaten (Einheiten, laufende
Mietverhältnisse, Parteien) ergeben sich für die meisten Schlüssel die Gewichte
von selbst. Was sich nicht ableiten lässt — Zählerstände, Prozentsätze,
individuelle Zuordnung — bleibt Handarbeit und wird als solche gemeldet, statt
stillschweigend als Null durchzurutschen.

Die Partei-Namen stammen aus demselben Ort wie beim Versand
(`versand._empfaenger`): dem laufenden Mietverhältnis. Nur dann treffen
Verteilung, Vorauszahlung und Empfänger dieselbe Partei.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlmodel import Session, select

from .cashflow import monate_im_jahr
from .engine import Position
# N312 — die zweite Monatsregel: Zahlmonate für Vorauszahlungen.
from .zeit import zahlmonate
from .models import (ERLEDIGT, Einheit, Kostenart, Kostenposition, Miete,
                     Partei, Vorauszahlung, Zeitraum)
from .turnus import jahresbetrag

# Was jeder Schlüssel bedeutet und ob er sich aus den Stammdaten ergibt.
# `einheit` ist die Maßeinheit des Gewichts — ohne sie steht in der Oberfläche
# nur eine nackte Zahl („Büro 4.1398"), die niemand einordnen kann.
SCHLUESSEL: dict[str, dict] = {
    "flaeche": {
        "titel": "Fläche", "einheit": "m²", "ableitbar": True,
        "hinweis": "Wohn-/Nutzfläche je Einheit; Terrasse und Nebenfläche "
                   "zählen zur Hälfte. Bei einem Mieterwechsel teilen sich "
                   "Vor- und Nachmieter die Fläche nach Wohndauer; "
                   "Leerstandszeiten bleiben beim Eigentümer.",
    },
    "personen": {
        "titel": "Personen", "einheit": "Pers.", "ableitbar": True,
        "hinweis": "Personenzahl des Mietverhältnisses, gewichtet nach "
                   "Wohndauer im Zeitraum.",
    },
    "einheiten": {
        "titel": "Einheiten", "einheit": "Anteil", "ableitbar": True,
        "hinweis": "Alle Einheiten zu gleichen Teilen; bei einem Wechsel "
                   "teilen sich Vor- und Nachmieter den Anteil ihrer Einheit.",
    },
    "prozentual": {
        "titel": "Prozentual", "einheit": "%", "ableitbar": True,
        "hinweis": "Ein Prozentsatz je Einheit, Summe 100 %. Ohne eigene "
                   "Angabe gleichmäßig auf alle Einheiten verteilt; die Sätze "
                   "lassen sich je Einheit von Hand setzen. Verteilt wird "
                   "proportional zu den Gewichten — die Summe muss nicht exakt "
                   "100 sein, 30/30/40 geht genauso sauber auf wie 50/50.",
    },
    "bewohnermonate": {
        "titel": "Bewohnermonate", "einheit": "Pers.-Mon.", "ableitbar": True,
        "hinweis": "Personen × Monate im Zeitraum, taggenau — deckt den "
                   "Mieterwechsel mitten im Jahr ab.",
    },
    "verbrauch": {
        "titel": "Verbrauch", "einheit": "Zählerwert", "ableitbar": False,
        "hinweis": "Zählerstände lassen sich nicht ableiten — Werte je Partei "
                   "von Hand eintragen.",
    },
    "prozent": {
        "titel": "Prozent", "einheit": "%", "ableitbar": False,
        "hinweis": "Prozentsätze werden vereinbart, nicht berechnet.",
    },
    "individuell": {
        "titel": "Individuell", "einheit": "Anteil", "ableitbar": False,
        "hinweis": "Direkte Zuordnung — Gewichte von Hand setzen.",
    },
}

VORGABE = "flaeche"


class UnbekannterSchluessel(ValueError):
    """Ein Verteilungsschlüssel, den die Engine nicht kennt."""


@dataclass
class Bezug:
    """Eine Partei mit allem, woraus sich ihr Gewicht ergeben kann.

    `zugeordnet` sagt, ob sich die genannte Einheit im Objekt wiederfindet.
    `Miete.einheit` ist Freitext: steht dort nichts (bei mehreren Einheiten)
    oder eine abweichende Schreibweise, dann gibt es keine Fläche, die Partei
    fällt aus der Flächenverteilung — und bekäme ihre Vorauszahlung voll
    erstattet, ohne dass es jemandem auffällt.

    `zeiten` trägt die Spannen, in denen der Bezug im Zeitraum gilt. Für ein
    Mietverhältnis ist das genau `ab`–`bis`; ein Leerstand kann dagegen aus
    mehreren Stücken bestehen (Januar leer, dann vermietet, im Dezember wieder
    leer), die sich nicht als ein einzelnes ab/bis schreiben lassen."""
    partei: str
    einheit: str = ""
    flaeche: float | None = None
    personen: int = 1
    ab: date | None = None
    bis: date | None = None
    zugeordnet: bool = True
    leerstand: bool = False
    zeiten: list[tuple[date, date]] = field(default_factory=list)


def _gesamtflaeche(e: Einheit) -> float | None:
    """Die EINE massgebliche Fläche für alle Geld-Berechnungen (Nebenkosten
    „nach Fläche", Cashflow-Verteilung, Miete je m²) — Terrasse zählt zu ihrem
    einstellbaren Anteil (`Einheit.terrasse_anteil_pct`, N227), Nebenfläche
    weiter zur Hälfte. Ohne jede Angabe bleibt es None — eine 0 wäre gelogen
    und würde die Partei aus der Verteilung werfen, ohne dass es auffällt."""
    teile = [e.flaeche, e.terrasse, e.nebenflaeche]
    # CCCXXVII — anteilige Gemeinschaftsflächen zählen mit. Ohne erfasste
    # Gemeinschaftsflächen ist der Beitrag 0 und der Bestand bleibt unverändert.
    gemein = e.gemein_flaeche()
    # CCCXXIX — zusätzliche Nutzflächen zählen VOLL mit. Ohne erfasste
    # Nutzflächen ist der Beitrag 0 und der Bestand bleibt unverändert.
    nutz = e.nutz_flaeche()
    if all(t is None for t in teile) and gemein == 0 and nutz == 0:
        return None
    terrasse_pct = e.terrasse_anteil_pct if e.terrasse_anteil_pct is not None else 50.0
    return round((e.flaeche or 0) + (e.terrasse or 0) * terrasse_pct / 100
                 + (e.nebenflaeche or 0) * 0.5 + gemein + nutz, 2)


def _laufend(mieten: list[Miete], start: date, ende: date) -> list[Miete]:
    """Mietverhältnisse, die den Zeitraum berühren — auch die schon beendeten.
    Wer bis Juli gewohnt hat, gehört in die Abrechnung dieses Jahres."""
    return [m for m in mieten
            if m.ab_datum <= ende and (m.bis_datum is None or m.bis_datum >= start)]


def _luecken(belegt: list[tuple[date, date]],
             start: date, ende: date) -> list[tuple[date, date]]:
    """Die Zeitspannen, in denen eine Einheit im Zeitraum leer stand.

    Die belegten Spannen sind einschliesslich zu verstehen: endet ein
    Mietverhältnis am 30.06., beginnt der Leerstand am 01.07."""
    frei: list[tuple[date, date]] = []
    lauf = start
    for von, bis in sorted(belegt):
        if von > lauf:
            frei.append((lauf, von - timedelta(days=1)))
        lauf = max(lauf, bis + timedelta(days=1))
        if lauf > ende:
            return frei
    if lauf <= ende:
        frei.append((lauf, ende))
    return frei


def bezuege(einheiten: list[Einheit], mieten: list[Miete],
            parteien: list[Partei], start: date, ende: date) -> list[Bezug]:
    """Wer im Zeitraum abzurechnen ist — in dieser Reihenfolge:

    1. laufende Mietverhältnisse (dort steht auch die Mailadresse),
    2. die unbelegte Zeit jeder Einheit (Leerstand, Eigennutzung),
    3. ersatzweise die Partei-Liste des Objekts, falls es weder Einheiten
       noch Mietverhältnisse gibt.

    Punkt 2 gilt ausdrücklich auch für eine Einheit, die nur einen Teil des
    Zeitraums vermietet war. Vorher bekam nur die ganz leerstehende Einheit
    einen Bezug; endete ein Mietverhältnis mitten im Jahr ohne Nachmieter,
    galt die Einheit als belegt und trug — seit die Gewichte zeitanteilig sind
    — nur noch ihren halben Anteil. Der Rest verteilte sich auf die übrigen
    Mieter: bei 60 m² (halbes Jahr) und 90 m² zahlte das OG 75,2 % statt 60 %.
    Mit dem Leerstands-Bezug summiert sich jede Einheit wieder exakt auf ihre
    Fläche, und die unbelegte Zeit bleibt beim Eigentümer.

    CXCIII: eine Einheit mit `nk_abrechnung == False` ist gar nicht Teil dieser
    Abrechnung — selbstgenutzt, separat abgerechnet oder gewerblich mit eigenem
    Zähler. Sie taucht in keinem Schlüssel auf: weder ihr Mietverhältnis noch
    ein Leerstands-Bezug entsteht. Die Kosten verteilen sich allein auf die
    teilnehmenden Einheiten und gehen dort exakt auf — die ausgeschlossene
    Einheit verzerrt die Anteile der übrigen nicht.
    """
    teilnehmend = [e for e in einheiten if e.nk_abrechnung]
    ausgeschlossen = {e.bezeichnung for e in einheiten if not e.nk_abrechnung}
    flaechen = {e.bezeichnung: _gesamtflaeche(e) for e in teilnehmend}
    personen_je = {p.name: p.personen for p in parteien}
    treffer: list[Bezug] = []
    belegt: dict[str, list[tuple[date, date]]] = {}

    for m in sorted(_laufend(mieten, start, ende),
                    key=lambda m: (m.einheit, m.ab_datum)):
        if not m.partei:
            continue
        # Ein Mietverhältnis ohne Einheit gehört bei einer Einzelwohnung
        # eindeutig zu dieser — sonst stünde die Wohnung ein zweites Mal als
        # eigene Partei in der Verteilung und bekäme Kosten aufgebrummt.
        name = m.einheit or (einheiten[0].bezeichnung if len(einheiten) == 1 else "")
        # Zeigt das Mietverhältnis auf eine ausgeschlossene Einheit, gehört es
        # nicht in diese Abrechnung — der Mieter wird separat abgerechnet.
        if name in ausgeschlossen:
            continue
        von, bis = max(m.ab_datum, start), min(m.bis_datum or ende, ende)
        belegt.setdefault(name, []).append((von, bis))
        treffer.append(Bezug(
            partei=m.partei, einheit=name, flaeche=flaechen.get(name),
            personen=m.personen or personen_je.get(m.partei, 1),
            ab=von, bis=bis, zeiten=[(von, bis)],
            zugeordnet=not teilnehmend or name in flaechen))

    for e in teilnehmend:
        frei = _luecken(belegt.get(e.bezeichnung, []), start, ende)
        if not frei:
            continue
        treffer.append(Bezug(
            partei=e.bezeichnung, einheit=e.bezeichnung,
            flaeche=flaechen[e.bezeichnung],
            personen=personen_je.get(e.bezeichnung, 1),
            ab=frei[0][0], bis=frei[-1][1], zeiten=frei, leerstand=True))

    if not treffer:
        for p in parteien:
            treffer.append(Bezug(
                partei=p.name, personen=p.personen,
                ab=max(p.einzug or start, start), bis=min(p.auszug or ende, ende)))
    return treffer


def _monate(b: Bezug, start: date, ende: date) -> float:
    """Monate im Zeitraum, taggenau. `monate_im_jahr` rechnet je Kalenderjahr —
    ein Wirtschaftsjahr Oktober–September berührt zwei davon.

    Ein Leerstand besteht unter Umständen aus mehreren Stücken; sie werden
    zusammengezählt."""
    summe = 0.0
    for a, z in b.zeiten or [(b.ab or start, b.bis or ende)]:
        von, bis = max(a, start), min(z, ende)
        if bis < von:
            continue
        summe += sum(monate_im_jahr(von, bis, j)
                     for j in range(von.year, bis.year + 1))
    return round(summe, 4)


def _zahlmonate(b: Bezug, start: date, ende: date) -> float:
    """N312 — wie viele MONATSZAHLUNGEN in den Zeitraum fallen.

    Der Zwilling zu `_monate`, und der Unterschied ist der aus `zeit.py`:
    `_monate` misst den Anteil am Jahr (für Verteilungsschlüssel), diese
    Funktion zählt Zahlungen (für Vorauszahlungen). Ein voller Kalendermonat
    ist hier exakt 1,0 — wer im Februar wohnt, überweist seine 280 €, nicht
    280 × 28/365 × 12.

    Wie `_monate` verkraftet sie mehrere Stücke: ein Mietverhältnis kann
    unterbrochen sein."""
    summe = 0.0
    for a, z in b.zeiten or [(b.ab or start, b.bis or ende)]:
        von, bis = max(a, start), min(z, ende)
        if bis < von:
            continue
        summe += zahlmonate(von, bis)
    return round(summe, 4)


def _zeitraum_monate(start: date, ende: date) -> float:
    """Länge des Abrechnungszeitraums in Monaten, taggenau — die Bezugsgröße,
    an der die Wohndauer gemessen wird."""
    if ende < start:
        return 0.0
    return round(sum(monate_im_jahr(start, ende, j)
                     for j in range(start.year, ende.year + 1)), 4)


def _zeitanteil(b: Bezug, start: date, ende: date) -> float:
    """Welchen Teil des Zeitraums diese Partei bewohnt hat: 1.0 durchgehend,
    0.5 ein halbes Jahr."""
    gesamt = _zeitraum_monate(start, ende)
    if gesamt <= 0:
        return 0.0
    return _monate(b, start, ende) / gesamt


def auf_parteien(mengen: dict[str, float], bezuege_: list[Bezug],
                 start: date, ende: date) -> tuple[dict[str, float], list[str]]:
    """Mengen je EINHEIT in Gewichte je PARTEI übersetzen (N367).

    `engine.Position.anteile` ist von Partei-Name auf Gewicht geschlüsselt —
    `gewichte()` schreibt konsequent `out[b.partei]`. Wer Zählerverbräuche
    übernimmt, hat aber Einheiten-Bezeichnungen in der Hand („Wohnug 1.OG"),
    und die decken sich bei einem echten Objekt fast nie mit den Mieternamen.
    Wurde die Einheit ungeprüft als Schlüssel geschrieben, verteilte die
    Abrechnung ihren Anteil an eine Partei, die es nicht gibt: der Mieter
    bekam nichts, sein Saldo war um den vollen Betrag falsch — ohne Warnung.

    Wechselt der Mieter mitten im Zeitraum, tragen beide Parteien nach
    Wohndauer (`_zeitanteil`), wie überall sonst auch. Ein Leerstands-Bezug
    trägt legitim die Einheiten-Bezeichnung als `partei` und bleibt damit von
    selbst richtig.

    Zurück kommt zusätzlich, welche Labels sich keiner Partei zuordnen ließen —
    ihr Verbrauch fiele sonst lautlos aus der Abrechnung.
    """
    je_einheit: dict[str, list[Bezug]] = {}
    for b in bezuege_:
        if b.einheit:
            je_einheit.setdefault(b.einheit, []).append(b)
    bekannte_parteien = {b.partei for b in bezuege_}

    out: dict[str, float] = {}
    offen: list[str] = []
    for label, menge in mengen.items():
        if not menge:
            continue
        # Steht dort schon ein Partei-Name, bleibt er stehen — manche Zähler
        # sind historisch auf die Partei statt auf die Einheit gepflegt.
        if label in bekannte_parteien:
            out[label] = round(out.get(label, 0.0) + menge, 4)
            continue
        treffer = je_einheit.get(label) or []
        if not treffer:
            offen.append(label)
            continue
        anteile = [max(0.0, _zeitanteil(b, start, ende)) for b in treffer]
        summe = sum(anteile)
        if summe <= 0:                      # keine Wohndauer: gleiche Teile
            anteile = [1.0] * len(treffer)
            summe = float(len(treffer))
        for b, teil in zip(treffer, anteile):
            out[b.partei] = round(
                out.get(b.partei, 0.0) + menge * teil / summe, 4)
    return out, offen


def _gewicht(schluessel: str, b: Bezug, start: date, ende: date) -> float | None:
    """Gewicht einer Partei — None heißt: nimmt an diesem Schlüssel nicht teil.

    Alle Gewichte sind zeitanteilig. Ohne das bekam bei einem Mieterwechsel
    jede der beiden Parteien die volle Fläche ihrer Einheit angerechnet: eine
    Wohnung mit Wechsel zählte doppelt, und die Nachbarwohnung ohne Wechsel
    zahlte entsprechend zu wenig — beim Wechsel am 21.12. genauso viel wie bei
    einem Wechsel zur Jahresmitte. Mit dem Zeitanteil teilen sich Vor- und
    Nachmieter die 60 m² ihrer Einheit nach Wohndauer, und die Summe je
    Einheit stimmt wieder."""
    if schluessel == "bewohnermonate":
        # Schon in Personen-Monaten gemessen — dort steckt die Dauer im Wert.
        return round((b.personen or 0) * _monate(b, start, ende), 4) or None
    if schluessel == "flaeche":
        basis = b.flaeche or 0.0
    elif schluessel == "personen":
        basis = float(b.personen or 0)
    elif schluessel in ("einheiten", "prozentual"):
        # „prozentual" ohne gesetzte Anteile: jede Einheit zählt gleich, wie
        # bei „einheiten". `gewichte` skaliert das Ergebnis danach auf Summe
        # 100, sodass ein sinnvoller Vorgabe-Prozentsatz je Einheit entsteht.
        basis = 1.0
    else:
        return None
    return round(basis * _zeitanteil(b, start, ende), 4) or None


def gewichte(schluessel: str, bezuege_: list[Bezug],
             start: date, ende: date) -> dict[str, float]:
    """Gewichte je Partei für einen Schlüssel. Leeres dict heißt ehrlich:
    hier ist nichts abzuleiten — die Zahlen müssen von Hand kommen."""
    if schluessel not in SCHLUESSEL:
        raise UnbekannterSchluessel(
            f"Unbekannter Verteilungsschlüssel '{schluessel}'. Möglich: "
            + ", ".join(SCHLUESSEL))
    if not SCHLUESSEL[schluessel]["ableitbar"]:
        return {}
    out: dict[str, float] = {}
    for b in bezuege_:
        w = _gewicht(schluessel, b, start, ende)
        if w is None:
            continue
        # Zwei Mietverhältnisse derselben Partei (Wohnung und Garage) zählen
        # zusammen, statt sich gegenseitig zu überschreiben.
        out[b.partei] = round(out.get(b.partei, 0.0) + w, 4)
    gesamt = sum(out.values())
    if gesamt <= 0:
        return {}
    # Vorgabe für „prozentual": die gleichmäßigen Gewichte auf Summe 100
    # bringen, damit je Einheit ein echter Prozentsatz (100/n) gespeichert
    # wird — den der Nutzer anschließend von Hand anpassen kann.
    if schluessel == "prozentual":
        out = {k: round(v / gesamt * 100, 4) for k, v in out.items()}
    return out


def nur_einheit_gewichte(bezuege_: list[Bezug], einheit: str,
                         start: date, ende: date) -> dict[str, float]:
    """CXCIV: Gewichte für einen Sonderposten, der zu 100 % auf eine Einheit
    geht (Reparatur nur in Wohnung 2, eigener Warmwasserboiler).

    Nur die Bezüge dieser einen Einheit tragen — nach Wohndauer, genau wie beim
    Schlüssel „einheiten", bloß auf diese Einheit beschränkt. Zusammen ergeben
    sie 1,0, sodass der volle Betrag exakt bei dieser Einheit landet. Bei einem
    Mieterwechsel teilen Vor- und Nachmieter sich den Posten nach Dauer; stand
    die Einheit einen Teil des Jahres leer, bleibt dieser Anteil beim
    Eigentümer. Es steht immer die Partei/der Mieter der Einheit da, nie ein
    Pseudo-Name."""
    out: dict[str, float] = {}
    for b in bezuege_:
        if b.einheit != einheit:
            continue
        w = _gewicht("einheiten", b, start, ende)
        if w is None:
            continue
        out[b.partei] = round(out.get(b.partei, 0.0) + w, 4)
    return out if sum(out.values()) > 0 else {}


def stammdaten(session: Session, z: Zeitraum) -> list[Bezug]:
    """Bezüge eines Zeitraums aus der Datenbank."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    return bezuege(einheiten, mieten, parteien, z.start, z.ende)


def unbekannte_vorauszahlungen(session: Session, z: Zeitraum,
                               vzs: list[Vorauszahlung]) -> list[str]:
    """N314(g) — Vorauszahlungen, deren Partei zu KEINEM Bezug dieses Zeitraums
    gehört (Tippfehler im Namen, ausgezogener Mieter unter altem Namen).

    Die Engine kennt nur, was Kosten trägt (`kosten_je`) — eine solche
    Vorauszahlung fliesst zwar in `gesamt.abschlaege`/`saldo` ein, taucht aber
    in keiner Partei-Zeile auf und wäre sonst nur über die separate
    Schlüssel-Vorschau (`schluessel_vorschau`) sichtbar. Bislang schon dort
    berechnet, hier für Abrechnung und Versand wiederverwendet."""
    bekannt = {b.partei for b in stammdaten(session, z)}
    return sorted({v.partei for v in vzs} - bekannt)


def unbekannte_anteile(session: Session, z: Zeitraum) -> list[dict]:
    """N402 — das Gegenstück zu `unbekannte_vorauszahlungen`: von Hand gesetzte
    `Kostenposition.anteile`, deren Schlüssel auf KEINE Partei dieses Zeitraums
    zeigt.

    Live gefunden an der Laufer Str. 5: die Müll-Position trug als Gewicht den
    EINHEITEN-Namen „Wohnug 1.OG" statt des Partei-Namens „Alicia & Roman"
    (Altdatenrest aus einer Zeit, in der die Einheit selbst als Partei lief).
    Folge: die echte Partei bekam 0,00 € Müll, und ein Phantom-Empfänger, den
    es gar nicht gibt, bekam 85,45 € zugeteilt — Geld, das nie jemand
    bezahlt und das keine Abrechnung je erreicht.

    Angetastet wird nichts: `abgeleitet=False` heißt „von Hand gesetzt" und
    bleibt es (N5). Gemeldet wird trotzdem — ein Fund ohne Meldung ist ein
    vergessener Fund. Automatisch ableitbare Positionen prüft dieser Weg
    nicht: die schreibt `positionen_neu_ableiten` ohnehin bei jeder Änderung
    frisch aus den Stammdaten."""
    bekannt = {b.partei for b in stammdaten(session, z)}
    treffer: list[dict] = []
    for p in session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id == z.id)).all():
        fremd = sorted(k for k, w in (p.anteile or {}).items()
                       if k not in bekannt and (w or 0) > 0)
        if fremd:
            treffer.append({"kostenart": p.kostenart, "position_id": p.id,
                            "parteien": fremd})
    return treffer


def vorauszahlung_je_partei(session: Session, z: Zeitraum) -> dict[str, float]:
    """CCCLXIV — NK-Vorauszahlung je Partei aus der Miete abgeleitet: die
    monatliche Vorauszahlung × die im Zeitraum belegten Monate (taggenau,
    zeitanteilig ab Einzug/Auszug). So erscheinen die Vorauszahlungen ohne
    separate Erfassung. Erfasste Vorauszahlungs-Datensätze haben Vorrang und
    werden vom Aufrufer über dieses Ergebnis gelegt."""
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    ergebnis: dict[str, float] = {}
    for m in _laufend(mieten, z.start, z.ende):
        partei = (m.partei or "").strip()
        if not partei:
            continue
        monatlich = jahresbetrag(m.nebenkosten_vz, m.turnus) / 12
        if monatlich <= 0:
            continue
        # N312 — hier wird ein MONATSbetrag vervielfacht, also zählen
        # Zahlmonate, nicht Tagesanteile. Genau die Unterscheidung aus
        # `zeit.py` ([N291]), die `weg.py` befolgt und die hier verletzt war:
        # ein Mieter mit 280 €/Monat vom 01.01. bis 28.02. überweist 560,00 €,
        # angerechnet bekam er 543,12 € — 16,88 € zu wenig, direkt im Saldo.
        # Für den VERTEILUNGSSCHLÜSSEL (Wohndauer, Personenmonate) bleibt es
        # beim Tagesanteil; deshalb wird `_monate` hier nicht geändert, sondern
        # nur diese eine Stelle auf die richtige Frage umgestellt.
        monate = _zahlmonate(Bezug(partei=partei, ab=m.ab_datum,
                                   bis=m.bis_datum), z.start, z.ende)
        ergebnis[partei] = ergebnis.get(partei, 0.0) + monatlich * monate
    return {k: round(v, 2) for k, v in ergebnis.items() if round(v, 2)}


def _engine_positionen(session: Session, z: Zeitraum,
                       p: Kostenposition) -> list[Position]:
    """CCCLIX — eine Kostenposition in die zu rechnenden Engine-Positionen
    übersetzen. Trägt sie einen Vorab-Anteil direkt auf eine Einheit, entstehen
    zwei: der Vorab-Betrag zu 100 % auf diese Einheit (mit eigenem §35a) und der
    Rest (Betrag − Vorab) nach dem gewählten Schlüssel. Ohne Vorab bleibt es die
    eine Position wie bisher."""
    vorab = round(p.vorab_betrag or 0, 2)
    if vorab > 0 and (p.vorab_einheit or "").strip():
        aus = [Position(p.kostenart, vorab, "individuell",
                        ableiten_einheit(session, z, p.vorab_einheit), p.vorab_s35)]
        rest = round((p.betrag or 0) - vorab, 2)
        if rest > 0.005:
            aus.append(Position(p.kostenart, rest, p.schluessel, p.anteile or {}, p.s35))
        return aus
    return [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)]


def positionen_fuer_abrechnung(
        session: Session, z: Zeitraum
        ) -> tuple[list[Position], dict[str, float], list[Kostenposition],
                  list[Vorauszahlung], frozenset[str]]:
    """N274/N314(g) — die EINE Stelle, die aus den Rohdaten eines Zeitraums
    macht, was die Engine rechnen soll. Vorher gab es das zweimal: einmal
    hier (`objekt/abrechnung.py`s Vorschau-Endpunkt) und einmal — einfacher,
    ohne N125/CCCLIX/CCCLXIV — in `routers/versand.py` für den ECHTEN
    Versand. Der Versand-Pfad kannte weder die Vorauszahlung-aus-der-Miete-
    Ableitung noch den Vorab-Anteil-Split noch den §-N125-Filter für nicht
    umlagefähige Kostenarten — eine Partei ohne eigenen `Vorauszahlung`-
    Datensatz hätte 0,00 € Vorauszahlung angerechnet bekommen, obwohl die
    Vorschau (`GET .../abrechnung`) längst den korrekten, aus der Miete
    abgeleiteten Betrag zeigte. Gefunden beim Bau des Mieter-Onepagers
    (N274) an echten Daten (Laufer Str. 5, Zeitraum 15): alle fünf Parteien
    hätten beim Versand fälschlich 0,00 € Vorauszahlung und damit eine zu
    hohe Nachzahlung gesehen.

    Gibt zurück: die Engine-Positionen (nach N125-Filter und CCCLIX-Split),
    die Vorauszahlung je Partei (Miete-Ableitung, von echten Datensätzen
    überschrieben), die umlagefähigen Kostenpositionen (für
    `fehlende_angaben`), die rohen `Vorauszahlung`-Datensätze (für
    `unbekannte_vorauszahlungen`) und die Namen der optionalen Kostenarten
    (N404, für `fehlende_angaben` — mahnen nicht als „ohne Betrag")."""
    pos = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == z.id)).all()
    arten = session.exec(
        select(Kostenart).where(Kostenart.objekt_id == z.objekt_id)).all()
    # N125 — nicht umlagefähige Kostenarten (z. B. Einspeisevergütung) gehören
    # dem Eigentümer, nicht dem Mieter.
    nicht_umlegen = {k.name.strip().lower() for k in arten if not k.umlagefaehig}
    optionale_kostenarten = frozenset(k.name for k in arten if k.optional)
    umlegbar = [p for p in pos if p.kostenart.strip().lower() not in nicht_umlegen]
    positionen = [ep for p in umlegbar if p.status == ERLEDIGT
                  for ep in _engine_positionen(session, z, p)]
    # CCCLXIV — Vorauszahlungen aus der Miete ableiten (monatliche NK ×
    # belegte Monate); separat erfasste Vorauszahlungs-Datensätze haben Vorrang.
    vorausz = {**vorauszahlung_je_partei(session, z),
              **{v.partei: v.betrag for v in vzs}}
    return positionen, vorausz, umlegbar, vzs, optionale_kostenarten


def ableiten(session: Session, z: Zeitraum, schluessel: str) -> dict[str, float]:
    """Gewichte für eine neue oder umgestellte Position."""
    return gewichte(schluessel, stammdaten(session, z), z.start, z.ende)


def ableiten_einheit(session: Session, z: Zeitraum,
                     einheit: str) -> dict[str, float]:
    """CXCIV: Gewichte für einen Sonderposten, der zu 100 % auf eine Einheit
    geht — der Schlüssel spielt dabei keine Rolle."""
    return nur_einheit_gewichte(stammdaten(session, z), einheit,
                                z.start, z.ende)


def positionen_neu_ableiten(session: Session, objekt_id: int) -> int:
    """N5 — nach einer Stammdaten-Änderung (Mietverhältnis/Einheit) die
    ABGELEITETEN Gewichte offener Zeiträume neu berechnen.

    `Kostenposition.anteile` ist eine gespeicherte Momentaufnahme. Wird ein
    Mietverhältnis nachträglich korrigiert (z. B. Mietstart 2025 → 2026), lebt
    der alte, falsche Anteil sonst in der Position weiter und ein längst nicht
    mehr zum Zeitraum gehörender Mieter wird weiter belastet.

    Unangetastet bleiben: von Hand gesetzte Anteile (`abgeleitet=False`) und
    nicht ableitbare Schlüssel (Verbrauch/Prozent/individuell — deren Zahlen
    kommen von Hand; `gewichte` gäbe hier `{}` zurück und würde sie löschen).
    Nur Zeiträume „in Arbeit" — ein abgeschlossener Zeitraum ist ein Dokument
    und bleibt, wie er abgerechnet wurde.

    Gibt die Zahl der neu berechneten Positionen zurück."""
    zeitraeume = list(session.exec(select(Zeitraum).where(
        Zeitraum.objekt_id == objekt_id, Zeitraum.status == "in Arbeit")).all())
    geaendert = 0
    for z in zeitraeume:
        bez = stammdaten(session, z)                 # einmal je Zeitraum lesen
        posten = list(session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id == z.id)).all())
        for p in posten:
            if not getattr(p, "abgeleitet", True):
                continue
            einheit = (p.nur_einheit or "").strip()
            if einheit:
                neu = nur_einheit_gewichte(bez, einheit, z.start, z.ende)
            elif SCHLUESSEL.get(p.schluessel, {}).get("ableitbar"):
                neu = gewichte(p.schluessel, bez, z.start, z.ende)
            else:
                continue                             # manuelle Zahlen bleiben
            if neu != (p.anteile or {}):
                p.anteile = neu
                session.add(p)
                geaendert += 1
    if geaendert:
        session.commit()
    return geaendert


def ohne_einheit(bezuege_: list[Bezug]) -> list[str]:
    """Parteien, deren Mietverhältnis auf keine Einheit des Objekts zeigt."""
    return sorted({b.partei for b in bezuege_ if not b.zugeordnet})


def leerstaende(bezuege_: list[Bezug]) -> list[str]:
    """Bezüge, hinter denen keine Partei steht, sondern unbelegte Zeit.

    Sie tragen ihren Anteil an den Kosten — der bleibt beim Eigentümer — und
    bekommen weder Vorauszahlung noch Post."""
    return sorted({b.partei for b in bezuege_ if b.leerstand})


def anteil_details(bezuege_: list[Bezug], start: date,
                   ende: date) -> dict[str, dict]:
    """N29 — je Partei: Einheit, Mieter (bzw. Leerstand) und die im Zeitraum
    belegten Monate. So steht in der Aufteilung nicht nur „Meier", sondern
    „EG · Meier · 7 von 12 Monaten": man sieht, welche Einheit die Partei bewohnt
    und ob sie den Zeitraum ganz oder nur anteilig belegt.

    `zeitraum_monate` ist die Länge des Abrechnungszeitraums; liegt `monate`
    darunter, war die Partei nur einen Teil des Jahres da (Ein-/Auszug,
    Leerstands-Stück). Mehrere Bezüge derselben Partei (Wohnung + Garage) werden
    zusammengefasst: die Einheiten gesammelt, die längste Belegung als Maß."""
    zr = _zeitraum_monate(start, ende)
    out: dict[str, dict] = {}
    for b in bezuege_:
        mon = _monate(b, start, ende)
        d = out.get(b.partei)
        if d is None:
            out[b.partei] = {
                "partei": b.partei,
                "einheit": b.einheit or "",
                "mieter": None if b.leerstand else b.partei,
                "leerstand": b.leerstand,
                "monate": mon,
                "zeitraum_monate": zr,
            }
            continue
        if b.einheit and b.einheit not in d["einheit"].split(" · "):
            d["einheit"] = (d["einheit"] + " · " + b.einheit).strip(" · ")
        d["monate"] = max(d["monate"], mon)
        d["leerstand"] = d["leerstand"] and b.leerstand
        if not d["leerstand"] and d["mieter"] is None:
            d["mieter"] = b.partei
    return out


def vorschau(bezuege_: list[Bezug], start: date, ende: date) -> list[dict]:
    """Alle Schlüssel mit den Gewichten, die dabei herauskämen — damit man
    sieht, worauf man sich einlässt, bevor man sich festlegt.

    `parteien_ohne_einheit` nennt die Parteien, die bei diesem Schlüssel leer
    ausgingen, weil ihre Einheit nicht zu finden ist. Solange dort jemand
    steht, gilt der Schlüssel nicht als sauber ableitbar: er würde rechnen, als
    gäbe es die Partei nicht — sie bekäme keine Kosten und ihre Vorauszahlung
    voll erstattet."""
    fehlzuordnung = ohne_einheit(bezuege_)
    leer = leerstaende(bezuege_)
    out = []
    for wert, meta in SCHLUESSEL.items():
        g = gewichte(wert, bezuege_, start, ende)
        betroffen = [name for name in fehlzuordnung if name not in g]
        summe = round(sum(g.values()), 4)
        out.append({
            "wert": wert, "titel": meta["titel"], "einheit": meta["einheit"],
            "ableitbar": meta["ableitbar"] and not betroffen,
            "hinweis": meta["hinweis"],
            "gewichte": g, "summe": summe,
            "prozent": {k: round(v / summe * 100, 2) for k, v in g.items()}
            if summe > 0 else {},
            "moeglich": bool(g) and not betroffen,
            "parteien_ohne_einheit": betroffen,
            # Damit sich in der Vorschau erklärt, warum eine Einheit mit
            # halbjährigem Leerstand zweimal auftaucht.
            "leerstand": [name for name in leer if name in g],
        })
    return out


def fehlende_angaben(positionen: list[Kostenposition],
                     optionale_kostenarten: frozenset[str] = frozenset()) -> dict:
    """Was einen sauberen Abschluss noch verhindert.

    Zwei Fälle, die beide zu einer zu kleinen Abrechnung führen:
    *ohne Betrag* — die Position ist noch offen; und *ohne Verteilung* — sie
    gilt als erledigt, hat aber keine Gewichte. Der zweite Fall ist der
    tückische: der Betrag verschwindet lautlos aus der Abrechnung, weil
    `verteile_nach_wert` ein leeres dict bekommt und nichts zurückgibt.
    """
    # N403 — eine vom Nutzer ausdrücklich bestätigte Position zählt NICHT als
    # „ohne Betrag". „Heizöl & Lieferungen" ist genau so gebaut (N364): sie
    # legt selbst kein Geld um, ihr Öl fließt vollständig in Warmwasser und
    # Heizkörper-Wärme, und deshalb bleibt ihr eigener `betrag` dauerhaft 0
    # und ihr `status` „offen" — abgehakt wird sie über `bestaetigt`. Ohne
    # diese Ausnahme stand sie für immer unter „Noch offen" und verhinderte
    # den Abschluss einer fertigen Abrechnung.
    # N404 — eine `optional=True`-Kostenart (N189, z. B. Wartung Heizung)
    # mahnt in der Checkliste bewusst nicht; sie muss deshalb auch hier
    # rausfallen, sonst blockiert sie den Abschluss trotzdem.
    # N405 — dasselbe für eine einzelne Position, die der Nutzer per
    # „Position ohne Beleg schließen" ausdrücklich als „fällt nicht an"
    # markiert hat (`entfaellt`).
    ohne_betrag = [p.kostenart for p in positionen
                   if p.status != ERLEDIGT
                   and not getattr(p, "bestaetigt", False)
                   and not getattr(p, "entfaellt", False)
                   and p.kostenart not in optionale_kostenarten]
    ohne_verteilung = [p.kostenart for p in positionen
                       if p.status == ERLEDIGT and (p.betrag or 0) != 0
                       and sum((p.anteile or {}).values()) <= 0]
    return {"ohne_betrag": ohne_betrag, "ohne_verteilung": ohne_verteilung,
            "offen": ohne_betrag + ohne_verteilung}
