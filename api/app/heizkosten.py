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
from .ablesung import verbrauch_je_zaehler
from .einheitenzuordnung import karte as einheiten_karte
from .einheitenzuordnung import schluessel
from .models import Ablesung, Einheit, Miete, Partei, Zaehler, Zeitraum
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


def _bezugs_karte(session: Session, z: Zeitraum) -> tuple[list[Einheit], dict[str, str]]:
    """Label → echte Einheit, dieselbe Abbildung wie Wasser/Strom/Übernahme
    (`einheitenzuordnung.karte`). Ein Zähler-`einheit_bezug` kann eine echte
    Einheit sein (zeigt auf sich selbst), ein Partei-Name („Roman & Alicia",
    zeigt auf deren Einheit im Zeitraum) oder etwas, das keins von beidem ist
    (z. B. das Alt-Label „WG") — dann bleibt der rohe Bezug stehen."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    bezuege = verteilung.bezuege(einheiten, mieten, parteien, z.start, z.ende)
    return einheiten, einheiten_karte(einheiten, bezuege)


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
    einheiten, bezug_karte = _bezugs_karte(session, z)
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
        roh = zae.einheit_bezug
        if not roh:
            unzugeordnet.append(zae.name)
            continue
        bezug = bezug_karte.get(schluessel(roh), roh)
        lane = lanes.setdefault(bezug, {"name": bezug,
                                        "flaeche": flaeche.get(bezug, 0),
                                        "ehkv": 0.0, "kwh": 0.0, "ww_m3": 0.0})
        # N340u — Wärmemengenzähler (kWh) und Warmwasserzähler (m³) sind an
        # der Kostenart/Messeinheit erkennbar; alles andere ist ein
        # Heizkörperverteiler und braucht seinen Bewertungsfaktor, sonst sind
        # seine Rohwerte gegen einen anderen HKV nicht vergleichbar.
        if zae.kostenart == "Warmwasser":
            lane["ww_m3"] += menge
        elif zae.messeinheit == "kWh":
            lane["kwh"] += menge
        else:
            lane["ehkv"] += menge * (zae.bewertungsfaktor or 0.0)
    return list(lanes.values()), unzugeordnet


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


__all__ = ["nutzer_aus_zaehlern", "rechne_fuer_zeitraum", "HEIZKOSTEN_ARTEN"]
