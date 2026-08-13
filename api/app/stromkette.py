"""N378 — die Rechnung der Stromkette, ohne Datenbank und ohne Endpunkt.

`routers/stromkette.py` war auf 869 Zeilen mit genau zwei Endpunkten gewachsen:
alles dazwischen war Domänenrechnung. Die Projektregel sagt dazu klar
„Rechenlogik gehört in die Engine, nicht in Endpunkte; Endpunkte bleiben dünn"
— und der Kopfkommentar des Routers behauptete es sogar von sich selbst
(„Gerechnet wird nicht hier"), während direkt darunter die Verteilung stand.

Hier liegt jetzt, was ohne `Session` auskommt: die Aufteilung der Zählerwerte
auf die Einheiten, die Ableitung der Netz-/PV-/Akku-Anteile aus der
SolarEdge-Auswertung, die Blockverteilung und die kleinen Formatierer für die
Quellenangaben. Alles rein — gleiche Eingabe, gleiche Ausgabe, keine Seiten-
wirkung. Damit ist es einzeln prüfbar, ohne ein Objekt, einen Zeitraum und
eine Datenbank aufbauen zu müssen.

Im Router bleibt, was Daten holt: `_verbrauch`, `_gewichte`, `_netz_betrag`,
`_eigen_betraege`, `_eauto` und ihre Geschwister. Sie ließen sich nur um den
Preis einer Verrenkung trennen — sie sind das Einsammeln selbst.

Dasselbe Muster wie `strom.py`/`routers/strom.py` und
`waerme.py`/`routers/waerme.py`.
"""
from __future__ import annotations

from . import strombloecke
from .einheitenzuordnung import zuordne_zaehler
from .zahlen import geschrieben
# N313/N378 — der Rabattsatz gilt für Mieterabrechnung UND Fahrer-
# rechnung; beides sind versendete Dokumente. Deshalb die eine Fassung
# aus `tanken.satz`. Hier auf Modulebene möglich, weil dieses Modul
# keinen Router lädt — im Router selbst musste der Import verzögert
# werden, weil `tanken.satz` seinerseits den Endpunkt braucht.
from .tanken.satz import eigen_satz

# Herkunft an einer Kostenposition (N122).
H_EXTERN, H_EIGEN = "extern", "eigen"

# Zähler in dieser Messeinheit tragen die Stromverteilung.
KWH = "kWh"


# Trägt das Strom-Jahr keine Einheit für die Ladungen, bekommt der Abzug diesen
# Namen. Er ist keine Wohnung — er hält die geladene Menge sichtbar aus der
# Verteilung heraus.
EAUTO_VORGABE = "E-Tankstelle"


# Ein zuordnungsloser Zähler, dessen Menge ungefähr der E-Auto-Menge entspricht,
# IST die Ladestation — dafür braucht es keine Warnung.
EAUTO_TOLERANZ = 0.05


def _zahl(wert: float) -> str:
    """Eine Zahl deutsch geschrieben — die Quellenangaben in den Antworten
    werden gelesen, nicht weitergerechnet."""
    return geschrieben(wert)


def _ct(preis: float) -> str:
    """Ein Preis je kWh in Cent, deutsch geschrieben."""
    return f"{preis * 100:.2f}".replace(".", ",")


def _gesamtzaehler(kwh_zaehler: list[Zaehler]) -> Zaehler | None:
    """Der Zähler, der den Gesamtverbrauch trägt: der, auf den die anderen
    zeigen, sonst der erste ohne eigenen Hauptzähler (wie in der Maske)."""
    haupt_ids = {zae.hauptzaehler_id for zae in kwh_zaehler if zae.hauptzaehler_id}
    return (next((zae for zae in kwh_zaehler
                  if zae.typ != "rest" and zae.id in haupt_ids), None)
            or next((zae for zae in kwh_zaehler
                     if zae.typ != "rest" and not zae.hauptzaehler_id), None))


def _je_einheit(kwh_zaehler: list[Zaehler], verb: dict[int, float | None],
                gesamt_id: int | None, karte: dict[str, str],
                haupthaus: list[str],
                gewichte: dict[str, float]) -> tuple[dict[str, float],
                                                     list[dict], list[str]]:
    """Der kWh-Verbrauch je Einheit — plus die Zähler ohne Zuordnung und die
    einzelnen Labels, die zu keiner Einheit passen.

    Der Gesamtzähler zählt nicht mit (er ist die Summe der übrigen). Ein Zähler
    mit mehreren Einheiten teilt seine Menge nach Person·Mietdauer, ersatzweise
    zu gleichen Teilen — dieselbe Regel wie beim Wasser.

    N288-B4 — trug ein Zähler mehrere Ziele und war nur EINES davon unbekannt,
    blieb das bisher unsichtbar: die Menge ging vollständig an die übrigen
    Einheiten. Erst wenn ALLE Ziele fehlten, kam der Zähler in `ohne`. Jetzt
    wird beides genannt — die Wasser-Kette macht es seit N101/6 so."""
    verbrauch: dict[str, float] = {}
    ohne: list[dict] = []
    unbekannt: list[str] = []
    for zae in kwh_zaehler:
        menge = verb.get(zae.id)
        if zae.id == gesamt_id or menge is None or menge <= 0:
            continue
        treffer = zuordne_zaehler(zae, karte, haupthaus)
        if not treffer.ziele:
            # Gar kein Ziel: der Zähler selbst ist der Fund (mit seiner Menge).
            ohne.append({"zaehler": zae.name, "kwh": round(menge, 3)})
            continue
        for name in treffer.unbekannt:
            if name not in unbekannt:
                unbekannt.append(name)
        teil = {name: max(0.0, gewichte.get(name, 0.0)) for name in treffer.ziele}
        if sum(teil.values()) <= 0:
            teil = {name: 1.0 for name in treffer.ziele}
        summe = sum(teil.values())
        for name, gew in teil.items():
            verbrauch[name] = round(verbrauch.get(name, 0.0)
                                    + menge * gew / summe, 3)
    return verbrauch, ohne, unbekannt


def _mengen(sj: Stromjahr) -> tuple[float, float, float]:
    """Die drei erfassten SolarEdge-Mengen (Netz · PV · Speicher)."""
    return (sj.netz_kwh or 0.0, sj.solar_kwh or 0.0, sj.akku_kwh or 0.0)


def _anteile(sj: Stromjahr) -> tuple[float, float, float, str]:
    """Die drei SolarEdge-Anteile in Prozent — die, mit denen gerechnet wird.

    Ein eigenes Prozentfeld gibt es im Datenmodell nicht — wohl aber die drei
    Mengen `netz_kwh`, `solar_kwh` und `akku_kwh`. Genau sie sind die Anteile;
    die Prozente ergeben sich daraus.

    Bezugsgröße ist ihre Summe, nicht der Gesamtverbrauch: nur so decken die
    drei Blöcke die ganze Menge ab und es bleibt kein Strom ohne Preis. Decken
    sich beide nicht, sagt das :func:`_anteile_pruefen`."""
    mengen = _mengen(sj)
    summe = sum(mengen)
    if summe <= 0:
        return 0.0, 0.0, 0.0, ""
    netz, pv, akku = (round(m / summe * 100.0, 2) for m in mengen)
    return netz, pv, akku, (f"aus den erfassten Mengen "
                            f"({mengen[0]:.0f} · {mengen[1]:.0f} · "
                            f"{mengen[2]:.0f} kWh)")


def _erfasste_anteile(sj: Stromjahr,
                      gesamt_kwh: float) -> tuple[float, float, float]:
    """Die Anteile, wie der Nutzer sie eingetragen hat — Menge am Gesamt-
    verbrauch. Sie stehen in den Eingabefeldern und gehen deshalb unverändert
    wieder hinein; die gerechneten Anteile (`_anteile`) können davon abweichen,
    wenn die drei zusammen nicht 100 % ergeben."""
    if gesamt_kwh <= 0:
        return 0.0, 0.0, 0.0
    netz, pv, akku = (round(m / gesamt_kwh * 100.0, 2) for m in _mengen(sj))
    return netz, pv, akku


def _anteile_pruefen(sj: Stromjahr, gesamt_kwh: float) -> list[str]:
    """Decken die drei erfassten Mengen den Gesamtverbrauch?

    Ein eigenes Prozentfeld gibt es nicht — ob die SolarEdge-Anteile 100 %
    ergeben, zeigt sich daran, ob ihre Mengen zusammen den Gesamtverbrauch
    treffen. Verteilt wird trotzdem auf 100 %, sonst fehlte Geld."""
    erfasst = ((sj.netz_kwh or 0.0) + (sj.solar_kwh or 0.0)
               + (sj.akku_kwh or 0.0))
    if erfasst <= 0 or gesamt_kwh <= 0:
        return []
    prozent = erfasst / gesamt_kwh * 100.0
    if abs(prozent - 100.0) <= 0.5:
        return []
    return [f"Die erfassten Anteile ergeben zusammen {prozent:.0f} % des "
            f"Gesamtverbrauchs ({_zahl(erfasst)} von {_zahl(gesamt_kwh)} kWh) — "
            "bitte die SolarEdge-Werte prüfen. Verteilt wird trotzdem auf "
            "den vollen Verbrauch."]


def _herkunft(kostenart: str = "", beleg: str = "", text: str = "") -> dict:
    """Woher der Betrag eines Blocks stammt — die Kostenart, der angehängte
    Beleg und ein lesbarer Satz dazu.

    Der Nutzer will die Herkunft jeder Zahl sehen: welche Kostenposition welchen
    Zeitraums den Betrag getragen hat und welcher Beleg daran hängt."""
    return {"kostenart": kostenart, "beleg": beleg, "text": text}


def _beleg_karte(d: Dokument) -> dict:
    """Das Wenige, das die Stromkette zu einem Netz-Beleg zeigt: genug, um ihn
    anzusehen und — wenn er doppelt oder irrelevant ist — herauszunehmen (N192).
    Die Datei bleibt in der Cloud; entfernt wird nur die App-Zuordnung."""
    return {"id": d.id, "dateiname": d.dateiname or "",
            "betrag": d.betrag, "pfad": d.pfad or "",
            "belegdatum": d.belegdatum.isoformat() if d.belegdatum else "",
            "position_id": d.position_id,
            "aus_position": d.position_id is not None}


def _block(b: strombloecke.Block, betrag: float | None,
           herkunft: dict) -> dict:
    """Ein Block für die Antwort: Menge, Betrag, Preis und die Herkunft.

    Fehlt der Betrag noch, stehen `betrag` und `preis` auf ``null`` statt auf
    0.0 — eine Null läse sich wie „dieser Strom kostet nichts". Gerechnet wird
    intern trotzdem weiter (mit 0 €), damit die Kette nicht abreißt; dass etwas
    fehlt, sagen die Warnungen."""
    kein_preis = betrag is None or b.kwh <= 0
    return {"kwh": round(b.kwh, 3),
            "betrag": None if betrag is None else round(betrag, 2),
            "preis": None if kein_preis else round(b.preis, 5),
            "herkunft": herkunft}


def _gesamtmenge(gesamt: Zaehler | None, verb: dict[int, float | None],
                 sj: Stromjahr) -> tuple[float, str]:
    """Der Gesamtverbrauch der Periode — aus dem Zähler, sonst aus dem Jahr."""
    if gesamt is not None and verb.get(gesamt.id):
        return round(verb[gesamt.id], 3), f"Zähler „{gesamt.name}“"
    if sj.gesamt_kwh:
        return round(sj.gesamt_kwh, 3), "Jahreswert am Strom-Jahr"
    # N167 — kein Gesamtwert, aber die drei SolarEdge-Mengen sind erfasst: ihre
    # Summe IST der Gesamtverbrauch. Sonst blieben alle Blöcke bei 0 kWh und die
    # Kette meldete „kein Durchschnittspreis", obwohl Menge und Betrag längst da
    # sind — der Gesamtverbrauch ist einfach die Summe von Netz, PV und Speicher.
    summe = sum(_mengen(sj))
    if summe > 0:
        return round(summe, 3), "Summe der erfassten Netz-/PV-/Speicher-Mengen"
    return 0.0, ""


def _geeichte_menge(positionen: list[Kostenposition]) -> float:
    """Die geeichte Rechnungsmenge des Netzbezugs — die `menge`, die der Nutzer
    an der externen Strom-Position im Feld „Verbrauch & Herkunft" einträgt.

    Sie kommt vom Zähler des Versorgers und weicht bewusst von der
    SolarEdge-gemessenen Netzmenge ab: SolarEdge misst am Wechselrichter, die
    Rechnung am geeichten Zähler. Der Unterschied wird mit dem Versorger
    geklärt; für den E-Auto-Satz zählt die geeichte Menge (N173). 0.0, wenn
    keine gepflegt ist — dann fällt der geeichte Satz auf den Verteilungssatz."""
    return round(sum((p.menge or 0.0) for p in positionen
                     if (p.herkunft or "").strip().lower() == H_EXTERN
                     and p.menge), 3)


def _quote_setzen(e: strombloecke.Ergebnis, bloecke: strombloecke.Bloecke) -> None:
    """Die Eigenverbrauchsquote aus den VOLLEN Blöcken — nicht aus dem um das
    E-Auto verkleinerten Rest, sonst zählte das Auto aus der Quote heraus."""
    gesamt_kwh = bloecke.kwh
    e.eigenverbrauchsquote = (round(bloecke.eigen_kwh / gesamt_kwh, 4)
                              if gesamt_kwh else 0.0)


def _verteile(bloecke: strombloecke.Bloecke, verbrauch: dict[str, float],
              eauto_einheit: str, eauto_netz_kwh: float, eauto_pv_kwh: float,
              eauto_akku_kwh: float,
              netz_preis_geeicht: float | None) -> strombloecke.Ergebnis:
    """Die drei Blöcke auf die Einheiten verteilen — das E-Auto vorab zum
    GEEICHTEN Satz (N173).

    `strombloecke.verteile` bepreist die E-Auto-Menge mit dem Durchschnitts-
    preis des Blocks (dem Verteilungssatz der Mieter, auf SolarEdge-Menge). Der
    Nutzer will das E-Auto aber mit dem geeichten Netzpreis abrechnen — genau so
    rechnet auch `tankstelle.py` die Fahrer ab, damit Kette und Fahrer-Abrechnung
    dieselbe Summe ergeben: Netz-Anteil × `netz_preis_geeicht`, PV/Akku 10 %
    darunter.

    Deshalb wird das E-Auto hier vorab bepreist und mit seinen kWh **und** seinen
    geeichten Kosten aus jedem Block herausgenommen; der Rest — voller Blockbetrag
    minus E-Auto-Kosten, über die restlichen kWh — geht über
    `strombloecke.verteile` an die Einheiten und trägt weiter den
    Verteilungssatz auf SolarEdge-Basis. Cent-genau: E-Auto-Kosten +
    verteilte Rest-Kosten == der volle Strombetrag, weil der Rest schlicht die
    Differenz ist.

    Fehlt eine E-Auto-Menge oder der geeichte Satz, verteilt es ganz normal
    (ohne Vorab-Abzug)."""
    vorab = {"netz": max(0.0, eauto_netz_kwh), "pv": max(0.0, eauto_pv_kwh),
             "akku": max(0.0, eauto_akku_kwh)}
    eauto_gesamt = round(sum(vorab.values()), 3)
    macht_abzug = (bool(eauto_einheit) and eauto_gesamt > 0
                   and netz_preis_geeicht is not None)
    zu_viel = macht_abzug and any(vorab[name] > b.kwh + 1e-9
                                  for name, b in bloecke.paare())
    if not macht_abzug or zu_viel:
        e = strombloecke.verteile(bloecke, verbrauch)
        if zu_viel:
            e.warnungen.append(
                f"Die Ladungen von „{eauto_einheit}“ übersteigen die erfasste "
                "Strommenge — die Vorab-Verrechnung wurde ausgelassen.")
        _quote_setzen(e, bloecke)
        return e

    # Der geeichte Satz für Netz, 10 % darunter für den eigenen Strom — dieselbe
    # Regel wie in tankstelle.eigen_satz, damit die Zahlen zusammenpassen.
    eigen_geeicht = eigen_satz(netz_preis_geeicht)
    preis = {"netz": netz_preis_geeicht, "pv": eigen_geeicht, "akku": eigen_geeicht}
    eauto_kosten = {name: round(vorab[name] * preis[name], 2) for name in vorab}
    eauto_betrag = round(sum(eauto_kosten.values()), 2)

    # Der Rest je Block: kWh und Kosten des E-Autos abgezogen. Über diesen Rest
    # verteilt der bewährte Verteiler die Mieter-Anteile — auf SolarEdge-Basis.
    def rest(name: str, b: strombloecke.Block) -> strombloecke.Block:
        return strombloecke.Block(kwh=round(b.kwh - vorab[name], 6),
                                  betrag=round(b.betrag - eauto_kosten[name], 2))

    reduziert = strombloecke.Bloecke(
        netz=rest("netz", bloecke.netz), pv=rest("pv", bloecke.pv),
        akku=rest("akku", bloecke.akku))
    e = strombloecke.verteile(reduziert, verbrauch)

    # Die E-Auto-Zeile in das Ergebnis zurücklegen — Kosten und Mengen je Block,
    # damit die Antwort sie wie bisher ausweisen kann.
    e.kosten[eauto_einheit] = eauto_betrag
    for name, _ in bloecke.paare():
        e.mengen[name][eauto_einheit] = round(vorab[name], 3)
    e.eauto = {"einheit": eauto_einheit, "betrag": eauto_betrag,
               "kwh": eauto_gesamt,
               **{f"{name}_kwh": round(vorab[name], 3) for name in vorab}}
    e.gesamt = round(sum(e.kosten.values()), 2)
    _quote_setzen(e, bloecke)
    return e
