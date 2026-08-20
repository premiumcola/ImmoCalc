"""N340t/N340u — der Delta-t-Rechenweg (`waermesim.py`), gespeist aus echten
Zählern statt aus der Simulator-Konfiguration im Browser.

Ein Zähler trägt seinen Bewertungsfaktor jetzt selbst (`Zaehler.
bewertungsfaktor`) und braucht keinen kumulierten Stand mehr, wenn er als
fertiger Jahreswert geführt wird (`typ='direkt'`) — beides deckt `ablesung.
verbrauch_je_zaehler` bereits ab (dieselbe Funktion, die auch Wasser und Strom
verrechnet). Was fehlt, ist nur die Übersetzung „Zähler + Ablesung →
Nutzer-Zeile", die dieses Modul liefert. Die eigentliche Rechnung bleibt
`waermesim.rechne()` — eine reine Funktion, in `test_waermesim.py` gegen eine
echte Delta-t-Abrechnung geprüft.

Was weiterhin NICHT automatisch kommt (wie bei jeder anderen Kostenposition
aus einem Beleg): Brennstoff-Bestände, Restbestand, Kostenblöcke, Warmwasser-
volumen — die stehen auf der Öl-Rechnung, nicht am Zähler. Das liefert
`eingabe` beim Aufruf, wie in `waermesim.rechne()` selbst."""
from __future__ import annotations

from sqlmodel import Session, select

from . import verteilung, waermesim
from .ablesung import verbrauch_je_zaehler, verbrauchsreihe
from .einheitenzuordnung import karte as einheiten_karte
from .engine import verteile_nach_wert
from .einheitenzuordnung import parse_einheiten, schluessel
from .models import Ablesung, Einheit, Miete, Objekt, Partei, Zaehler, Zeitraum
from .routers.heizoel import bewertung as _heizoel_bewertung
from .routers.zaehler import _mit_vorlauf

# N340t — nur diese Kostenarten zählen zur Heizkosten-Verteilung; alles
# andere (Wasser, Strom, …) hat mit dem Rechenweg hier nichts zu tun.
HEIZKOSTEN_ARTEN = ("Heizung", "Warmwasser")


def _zaehler_mit_ablesungen(session: Session, objekt_id: int
                            ) -> list[tuple[Zaehler, list]]:
    zaehler = session.exec(select(Zaehler).where(
        Zaehler.objekt_id == objekt_id, Zaehler.aktiv,
        Zaehler.kostenart.in_(HEIZKOSTEN_ARTEN))).all()
    return [(z, session.exec(select(Ablesung)
                             .where(Ablesung.zaehler_id == z.id)).all())
            for z in zaehler]


def _bezugs_karte(session: Session, z: Zeitraum
                  ) -> tuple[list[Einheit], dict[str, str], dict[str, int]]:
    """Label → echte Einheit, dieselbe Abbildung wie Wasser/Strom/Übernahme
    (`einheitenzuordnung.karte`). Ein Zähler-`einheit_bezug` kann eine echte
    Einheit sein (zeigt auf sich selbst), ein Partei-Name („Roman & Alicia",
    zeigt auf deren Einheit im Zeitraum) oder etwas, das keins von beidem ist
    (z. B. das Alt-Label „WG") — dann bleibt der rohe Bezug stehen.

    N395 — liefert zusätzlich die Personenzahl je Einheit, für „Grundkosten
    nach Personen" (`waermesim.rechne`). Bei mehreren Bezügen derselben
    Einheit im Zeitraum (Mieterwechsel) gilt die zuletzt beginnende — dieselbe
    grobe Näherung wie bei `flaeche` hier: eine statische Zahl je Einheit,
    keine monatsgenaue Gewichtung (die kennt dieser Rechenweg auch bei der
    Fläche nicht, `zeitanteil` bleibt in der echten Zähler-Abrechnung
    ungenutzt — anders als im freien Wärmesimulator)."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    bezuege = verteilung.bezuege(einheiten, mieten, parteien, z.start, z.ende)
    personen: dict[str, int] = {}
    for b in sorted(bezuege, key=lambda b: b.ab or z.start):
        if b.einheit:
            personen[b.einheit] = b.personen or 1
    return einheiten, einheiten_karte(einheiten, bezuege), personen


def nutzer_aus_zaehlern(session: Session, z: Zeitraum) -> tuple[list[dict], list[str]]:
    """Baut die `nutzer`-Liste für `waermesim.rechne()`: eine Zeile je echter
    Einheit, plus eine Sammelzeile „WG" für gemeinsam genutzte Zähler (wie die
    Lane „Allgemein" im Simulator, und dieselbe Konvention wie die
    bestehenden Wasser-/Strom-Zähler dieses Objekts). Zwei Zähler, die
    dieselbe Einheit auf verschiedene Art benennen (Einheiten-Bezeichnung vs.
    Partei-Name), landen dadurch in DERSELBEN Zeile statt in zwei — sonst
    hätte „Studio 1.OG" (neuer WMZ) und „Roman & Alicia" (bestehender
    Warmwasserzähler) zwei nie zusammengeführte Spalten ergeben.

    Gibt zusätzlich zurück, welche Zähler keinen Einheiten-Bezug tragen —
    nichts wird stillschweigend verschluckt (N288-B4-Prinzip)."""
    einheiten, bezug_karte, personen_je = _bezugs_karte(session, z)
    flaeche = {e.bezeichnung: (e.flaeche or 0) for e in einheiten}

    zma = _zaehler_mit_ablesungen(session, z.objekt_id)
    if not zma:
        return [], []
    zeitraeume = list(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all())
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
    verbrauch = verbrauch_je_zaehler(zma, zeitraeume_i, z.id)

    lanes: dict[str, dict] = {}
    unzugeordnet: list[str] = []
    for zae, _ in zma:
        menge = verbrauch.get(zae.id)
        if not menge:
            continue
        # N341-Fix — dieselbe Quelle wie Wasser/Strom/Übernahme:
        # `parse_einheiten` nimmt zuerst die Mehrfachzuordnung `einheiten`
        # (dort steht die echte Einheit) und fällt nur ersatzweise auf das
        # Alt-Label `einheit_bezug` zurück. Vorher las dieses Modul allein
        # `einheit_bezug` — dadurch landete ein Zähler mit korrekt gesetztem
        # `einheiten`, aber altem Partei-Label („Roman & Alicia") in einer
        # eigenen Phantom-Zeile. Der Fehler lag hier, nicht in den Daten.
        ziele = parse_einheiten(zae)
        if not ziele:
            unzugeordnet.append(zae.name)
            continue
        # N343 — MEHRERE gewählte Einheiten (der gemeinschaftliche
        # Waschküchen-Heizkörper): der Wert verteilt sich zu gleichen Teilen
        # auf genau die im Konfigurator gewählten Einheiten — nicht auf eine
        # davon, nicht auf alle des Hauses.
        aufgeloest: list[str] = []
        for roh in ziele:
            bezug = bezug_karte.get(schluessel(roh), roh)
            if bezug not in aufgeloest:
                aufgeloest.append(bezug)
        anteil = menge / len(aufgeloest)
        for bezug in aufgeloest:
            # N395 — „einheiten" ist kein gemessener Wert, sondern IMMER 1: der
            # Schlüssel „nach Einheiten" heisst „jede Einheit gleich viel",
            # unabhängig von Fläche oder Personenzahl.
            lane = lanes.setdefault(bezug, {"name": bezug,
                                            "flaeche": flaeche.get(bezug, 0),
                                            "personen": personen_je.get(bezug, 1),
                                            "einheiten": 1.0,
                                            "ehkv": 0.0, "kwh": 0.0, "ww_m3": 0.0})
            # N340u — Wärmemengenzähler (kWh) und Warmwasserzähler (m³) sind
            # an der Kostenart/Messeinheit erkennbar; alles andere ist ein
            # Heizkörperverteiler und braucht seinen Bewertungsfaktor, sonst
            # sind seine Rohwerte gegen einen anderen HKV nicht vergleichbar.
            if zae.kostenart == "Warmwasser":
                lane["ww_m3"] += anteil
            elif zae.messeinheit == "kWh":
                lane["kwh"] += anteil
            else:
                lane["ehkv"] += anteil * (zae.bewertungsfaktor or 0.0)
    return list(lanes.values()), unzugeordnet


def _vergleichswert(zeile: dict) -> float | None:
    """Der Wert, mit dem ein Zähler INNERHALB seiner Art vergleichbar ist.

    Ein Wärmemengenzähler misst kWh direkt. Ein Heizkörper-Verteiler zählt
    Rohpunkte, die erst mal seinem Bewertungsfaktor mit einem anderen
    Heizkörper vergleichbar sind — genau der Schritt, den die Abrechnung
    „Punkte × Faktor" nennt. `None`, wenn der Wert (noch) fehlt."""
    if zeile.get("verbrauch") is None:
        return None
    faktor = zeile.get("bewertungsfaktor")
    ist_gemessen = zeile.get("messeinheit") in ("kWh", "m³")
    if ist_gemessen or not faktor:
        return zeile["verbrauch"]
    return zeile["verbrauch"] * faktor


def _zaehler_art(zeile: dict) -> str:
    """'kwh' (Wärmemengenzähler), 'hkv' (Heizkörper-Verteiler) oder 'm3'."""
    if zeile.get("messeinheit") == "kWh":
        return "kwh"
    if zeile.get("messeinheit") == "m³":
        return "m3"
    return "hkv"


def _zaehler_aufschluesseln(zeilen: list[dict], kosten_eigen: dict[str, float],
                            preis_je_liter: float | None) -> None:
    """N429 — den Weg vom Zählwert bis zu Euro und Liter Öl je Zähler, in
    place ergänzt (`bewertet`, `anteil_pct`, `eur`, `liter`).

    Die Kosten einer Kostenart werden auf ihre Zähler verteilt, proportional
    zum Vergleichswert — dieselbe Logik, mit der die Engine die Kosten auf die
    Einheiten verteilt hat, nur eine Ebene feiner. Kein neuer Rechenweg: die
    Summe über alle Zähler einer Kostenart ergibt exakt deren `kosten_eigen`.

    **Nicht** aufgeschlüsselt wird, wenn eine Kostenart Zähler VERSCHIEDENER
    Art trägt (ein Wärmemengenzähler in kWh neben Heizkörper-Punkten): die
    beiden Maße sind nicht ineinander umrechenbar, ein gemeinsamer Anteil wäre
    erfunden. Dann bleiben `eur`/`liter` leer und die PDF sagt es."""
    for kostenart, betrag in (kosten_eigen or {}).items():
        gruppe = [z for z in zeilen if z.get("kostenart") == kostenart]
        if not gruppe or not betrag:
            continue
        for z in gruppe:
            z["bewertet"] = _vergleichswert(z)
        if len({_zaehler_art(z) for z in gruppe}) > 1:
            continue                     # unvergleichbare Maße — nichts erfinden
        summe = sum(z["bewertet"] or 0 for z in gruppe)
        if summe <= 0:
            continue
        # Cent-genau über dieselbe Engine-Funktion wie jede andere Verteilung
        # (Größte-Reste-Verfahren): die Summe der Zeilen ergibt EXAKT den
        # Betrag der Kostenart. Von Hand gerundet fehlte sonst ein Cent —
        # und genau da schaut ein Mieter hin (siehe `verteile_nach_wert`).
        anteile = {str(i): (z["bewertet"] or 0) for i, z in enumerate(gruppe)}
        verteilt = verteile_nach_wert(betrag, anteile)
        for i, z in enumerate(gruppe):
            z["anteil_pct"] = round((z["bewertet"] or 0) / summe * 100, 1)
            z["eur"] = verteilt[str(i)]
            if preis_je_liter:
                z["liter"] = round(z["eur"] / preis_je_liter, 1)


def nachweis_fuer_einheit(session: Session, z: Zeitraum, einheit_bezeichnung: str,
                          partei: str, positionen: list[dict] | None) -> dict | None:
    """Der Heizkosten-Nachweis für EINE Einheit (Seite 2 der Abrechnungs-PDF,
    N419): eigene Zählerstände + der eigene, bereits verteilte €-Anteil,
    dazu die Gesamtmenge ALLER Einheiten zusammen zum Vergleich.

    Bewusst NICHT enthalten: die Zählerstände oder Anteile einzelner anderer
    Nutzer — nur die Summe über alle. `positionen` ist `res["positionen"]`
    aus `engine.abrechnung` (trägt je Kostenart schon die fertig verteilten
    €-Beträge); die €-Aufteilung wird hier nicht neu gerechnet, nur um die
    Zähler-Rohdaten ergänzt. Kein Liter-Öl-Preis: der Brennstoffpreis aus dem
    Heizkosten-Rechner (`waermesim.rechne`) wird nirgends gespeichert, nur
    das Ergebnis — eine erfundene Zahl wäre schlimmer als keine."""
    if not einheit_bezeichnung:
        return None
    nutzer, _ = nutzer_aus_zaehlern(session, z)
    eigene = next((n for n in nutzer if n["name"] == einheit_bezeichnung), None)
    if eigene is None:
        return None

    zma = _zaehler_mit_ablesungen(session, z.objekt_id)
    if not zma:
        return None
    zeitraeume = list(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all())
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
    verbrauch = verbrauch_je_zaehler(zma, zeitraeume_i, z.id)
    _, bezug_karte, _ = _bezugs_karte(session, z)

    zaehler_zeilen: list[dict] = []
    for zae, ablesungen in zma:
        ziele = parse_einheiten(zae)
        if not ziele:
            continue
        aufgeloest = {bezug_karte.get(schluessel(roh), roh) for roh in ziele}
        if einheit_bezeichnung not in aufgeloest:
            continue
        menge = verbrauch.get(zae.id)
        zeile = {"name": zae.name, "nummer": zae.zaehlernummer,
                "kostenart": zae.kostenart,
                "messeinheit": zae.messeinheit, "typ": zae.typ,
                "bewertungsfaktor": zae.bewertungsfaktor,
                "start": None, "ende": None,
                "verbrauch": round(menge / len(aufgeloest), 3)
                            if menge is not None else None}
        if zae.typ == "gemessen":
            eintrag = verbrauchsreihe(ablesungen, zeitraeume_i).get(z.id)
            if eintrag and eintrag["verbrauch"]:
                zeile["ende"] = round(eintrag["randwert"], 2)
                zeile["start"] = round(eintrag["randwert"] - eintrag["verbrauch"], 2)
        zaehler_zeilen.append(zeile)
    if not zaehler_zeilen:
        return None

    gesamt_kwh = round(sum(n["kwh"] for n in nutzer), 2)
    gesamt_ww = round(sum(n["ww_m3"] for n in nutzer), 3)

    kosten_eigen: dict[str, float] = {}
    kosten_haus: dict[str, float] = {}
    for eintrag in positionen or []:
        if eintrag.get("kostenart") not in HEIZKOSTEN_ARTEN:
            continue
        betrag = (eintrag.get("verteilung") or {}).get(partei)
        if betrag:
            kosten_eigen[eintrag["kostenart"]] = round(betrag, 2)
        kosten_haus[eintrag["kostenart"]] = round(
            kosten_haus.get(eintrag["kostenart"], 0.0) + (eintrag.get("kosten") or 0), 2)
    summe_eigen = round(sum(kosten_eigen.values()), 2)
    summe_haus = round(sum(kosten_haus.values()), 2)

    # N423 — Liter Öl je Nutzer: nicht aus einem angenommenen Heizwert
    # geschätzt, sondern aus der ECHTEN FIFO-Bewertung des Objekts
    # (`routers.heizoel.bewertung`, dieselbe Zahl wie im Öl-Bestand). Sie
    # liefert den tatsächlichen Verbrauch (Liter) UND den tatsächlich
    # gezahlten Ø-Einkaufspreis der Periode — der eigene Anteil ergibt sich
    # dann exakt aus dem €-Anteil an denselben Kosten, die die Engine schon
    # verteilt hat (`summe_eigen / verbrauch_kosten`), keine zweite Rechnung.
    oel_liter_eigen = None
    oel_preis_je_liter = None
    objekt = session.get(Objekt, z.objekt_id)
    if objekt:
        try:
            b = _heizoel_bewertung(objekt.slug, zeitraum_id=z.id,
                                   session=session, o=objekt)
        except Exception:
            b = None
        if b and b.get("verbrauch_liter") and b.get("verbrauch_kosten"):
            oel_preis_je_liter = b.get("preis_schnitt")
            if summe_eigen:
                oel_liter_eigen = round(
                    summe_eigen / b["verbrauch_kosten"] * b["verbrauch_liter"], 1)

    _zaehler_aufschluesseln(zaehler_zeilen, kosten_eigen, oel_preis_je_liter)

    return {
        "zaehler": zaehler_zeilen,
        "eigener_verbrauch_kwh": eigene["kwh"] or None,
        "gesamt_verbrauch_kwh": gesamt_kwh or None,
        "eigener_verbrauch_ww_m3": eigene["ww_m3"] or None,
        "gesamt_verbrauch_ww_m3": gesamt_ww or None,
        "kosten_je_kostenart": kosten_eigen,
        "kosten_gesamt_eigen": summe_eigen,
        "kosten_gesamt_haus": summe_haus,
        "kostenanteil_pct": (round(100 * summe_eigen / summe_haus, 1)
                             if summe_haus else None),
        "oel_liter_eigen": oel_liter_eigen,
        "oel_preis_je_liter": oel_preis_je_liter,
        "flaeche": eigene["flaeche"] or None,
        "personen": eigene["personen"] or None,
    }


def rechne_fuer_zeitraum(session: Session, z: Zeitraum, eingabe: dict) -> dict:
    """Wie `waermesim.rechne()`, nur dass die `nutzer`-Zeile aus echten
    Zählern kommt statt aus `eingabe` — alles andere (Brennstoff, Blöcke, …)
    bleibt wie gehabt von aussen gesetzt. Eine mitgegebene `nutzer`-Liste in
    `eingabe` wird überschrieben: die echten Zähler sind hier immer die
    Wahrheit, nicht ein Aufrufer-Wert."""
    nutzer, unzugeordnet = nutzer_aus_zaehlern(session, z)
    erg = waermesim.rechne({**eingabe, "nutzer": nutzer})
    erg["unzugeordnet"] = unzugeordnet
    return erg


__all__ = ["nutzer_aus_zaehlern", "rechne_fuer_zeitraum", "nachweis_fuer_einheit",
          "HEIZKOSTEN_ARTEN"]
