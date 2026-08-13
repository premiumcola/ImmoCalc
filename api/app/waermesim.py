"""N340 — der Rechenweg einer Heizkostenabrechnung, nachgebaut und nachprüfbar.

Für die Laufer Str. 5 rechnet bisher ein Messdienst (Delta-t Wenzel) die
Heizkosten ab. Damit ImmoCalc das übernehmen kann, muss sein Rechenweg erst
Zahl für Zahl reproduziert werden — an mehreren echten Jahren, bis nichts mehr
abweicht. Genau dafür ist dieses Modul da: **eine reine Funktion**, die aus den
Eingaben eines Jahres dieselbe Aufstellung erzeugt, die auf der Abrechnung
steht, und sie den tatsächlichen Beträgen gegenüberstellt.

Der Weg, abgelesen an der Abrechnung 01.10.2018 – 30.09.2019 (Objekt 103536-002):

  1. **Brennstoff** — Anfangsbestand + Anlieferungen − Restbestand ergibt die
     verbrauchten Liter und ihren Wert (4.446,000 l / 3.328,15 €). Mal Heizwert
     (10 kWh/l) sind das 44.460 kWh.
  2. **Warmwasser-Abzug (§9 HeizkostenV)** — aus dem gemessenen Warmwasser-
     volumen (30,110 m³) die Wärmemenge Qtw = 2,5 · V · (t − 10) = 3.764 kWh,
     daraus Btw = Qtw / Heizwert = 376,4 l. Sein Anteil an den Gesamtlitern ist
     der Warmwasseranteil: 8,47 % — der Rest (91,53 %) ist Heizung.
  3. **Kostenblöcke** — Brennstoff, „Nebenkosten Heizung" (Betriebsstrom,
     Verbrauchserfassung, Kaminkehrer, Wartung) und „Zusatzkosten Heizung"
     (Miete der Zähler). Jeder wird in diesem Verhältnis geteilt; die
     Zusatzkosten ausdrücklich NICHT — sie gehören ganz zur Heizung.
  4. **Heizung: fest und verbrauchsabhängig** — 30 % Festkosten auf die
     Wohnfläche, 70 % nach Verbrauch. Die Verbrauchskosten teilen sich noch
     einmal auf zwei Erfassungsarten: H1 sind die Heizkostenverteiler an den
     Heizkörpern, H2 ist der Wärmezähler des Anbaus.
  5. **Warmwasser** — der Warmwasseranteil aller Blöcke, verteilt nach m³.
  6. **Je Nutzer** — Verbrauch (H1 oder H2) + Festkosten (m² × Preis, bei
     unterjährigem Wechsel zeitanteilig) + Warmwasser.

Die lange offene Größe — **wie sich die Verbrauchskosten auf H1 und H2
aufteilen** — ist inzwischen gefunden (N340b): der Wärmezähler bekommt seinen
Anteil an der HEIZenergie, also an der Ölenergie nach Abzug des Warmwassers,
und zwar als Anteil an den gesamten Heizkosten. An drei von vier echten
Abrechnungen stimmt das auf die zweite Nachkommastelle; 2023/24 weicht um
0,11 Prozentpunkte ab. Deshalb bleibt `h2_anteil` überschreibbar und die
Simulation zeigt die Abweichung, statt sie zu glätten.

Bewusst ohne Datenbank und ohne eigene Tabelle: das ist ein Werkzeug auf Zeit.
Steht der Rechenweg, wandert er in die Engine und dieses Modul fällt weg.
"""
from __future__ import annotations

from .engine import verteile_nach_wert
from .waerme import HEIZWERT_OEL, oel_kwh, warmwasser_kwh

# Der gesetzliche Regelfall der HeizkostenV: 30 % Grundkosten nach Fläche,
# 70 % nach erfasstem Verbrauch. Delta-t rechnet genau so.
FEST_ANTEIL = 0.30

# N395 — wonach die Grundkosten (der `fest_anteil`) auf die Nutzer verteilt
# werden. „flaeche" ist der gesetzliche Regelfall und bleibt die Vorgabe;
# „personen" und „einheiten" sind zulässige Alternativen nach § 7 HeizkostenV,
# die der Nutzer über die Oberfläche wählen kann. Das Feld muss in jeder
# `nutzer`-Zeile stehen — bei den echten Zählern trägt `heizkosten.
# nutzer_aus_zaehlern` es ein, im freien Wärmesimulator die Eingabe selbst.
FEST_SCHLUESSEL = ("flaeche", "personen", "einheiten")


def _zahl(wert, vorgabe: float = 0.0) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return vorgabe


def brennstoff(eingabe: dict) -> dict:
    """Verbrauchte Liter und ihr Wert — entweder direkt oder aus den Beständen.

    Die Abrechnung führt Anfangsbestand, Anlieferungen und Restbestand
    getrennt auf; wer nur die Summe kennt, gibt sie direkt an. Beides ergibt
    dieselben zwei Zahlen."""
    if eingabe.get("liter") is not None:
        return {"liter": round(_zahl(eingabe.get("liter")), 3),
                "eur": round(_zahl(eingabe.get("eur")), 2),
                "aus_bestaenden": False}
    zugang = [{"liter": _zahl(p.get("liter")), "eur": _zahl(p.get("eur"))}
              for p in (eingabe.get("bestaende") or [])]
    rest_l = _zahl((eingabe.get("rest") or {}).get("liter"))
    rest_e = _zahl((eingabe.get("rest") or {}).get("eur"))
    return {"liter": round(sum(p["liter"] for p in zugang) - rest_l, 3),
            "eur": round(sum(p["eur"] for p in zugang) - rest_e, 2),
            "aus_bestaenden": True}


def _bloecke_teilen(bloecke: list[dict], heiz_anteil: float) -> list[dict]:
    """Jeden Kostenblock in Heizungs- und Warmwasseranteil zerlegen.

    `nur_heizung` bleibt ungeteilt — die Miete für Heizkostenverteiler und
    Wärmezähler hat mit dem Warmwasser nichts zu tun."""
    geteilt = []
    for b in bloecke:
        betrag = round(_zahl(b.get("betrag")), 2)
        if b.get("nur_heizung"):
            heiz, ww = betrag, 0.0
        else:
            heiz = round(betrag * heiz_anteil, 2)
            ww = round(betrag - heiz, 2)
        geteilt.append({"name": b.get("name") or "Kosten", "betrag": betrag,
                        "heizung": heiz, "warmwasser": ww,
                        "nur_heizung": bool(b.get("nur_heizung"))})
    return geteilt


def _verteile_wie_deltat(betrag: float, gewichte: dict[str, float]) -> dict:
    """Einen Kostentopf so aufteilen, wie es auf der Delta-t-Abrechnung steht.

    Jede Zeile kaufmännisch gerundet, und der Rest, der dabei zur Summe fehlt
    (oder zu viel ist), geht **an die größte Zeile**. Nachgewiesen an genau
    einer Stelle der Abrechnung 2018/19: acht Heizkostenverteiler-Zeilen
    treffen alle auf den Cent, nur die größte steht mit 568,44 € statt der
    gerechneten 568,42 € da — und exakt diese 2 Cent fehlen der Summe der
    gerundeten Zeilen zu den ausgewiesenen 1.747,30 €.

    Das ist bewusst NICHT das Größte-Reste-Verfahren der Engine
    (`verteile_nach_wert`), das den Rest an die größte abgeschnittene
    Nachkommastelle gibt — damit wanderten dieselben Cent auf zwei andere
    Zeilen. Beide Verfahren halten die Summe exakt ein; sie legen den Rest nur
    woanders hin. Welches Delta-t wirklich verwendet, muss ein zweites
    Abrechnungsjahr bestätigen — bis dahin ist das hier eine begründete
    Annahme, keine gesicherte Regel (umschaltbar über `rundung: "engine"`).
    """
    summe = sum(gewichte.values())
    if summe <= 0:
        return {k: 0.0 for k in gewichte}
    ziel = round(betrag, 2)
    zeilen = {k: round(betrag * v / summe, 2) for k, v in gewichte.items()}
    rest = round(ziel - sum(zeilen.values()), 2)
    if rest:
        groesste = max(gewichte, key=lambda k: gewichte[k])
        zeilen[groesste] = round(zeilen[groesste] + rest, 2)
    return zeilen


def rechne(eingabe: dict) -> dict:
    """Die vollständige Aufstellung eines Abrechnungsjahres.

    `eingabe` (alles optional, sinnvolle Vorgaben):
      * `heizwert`      — kWh je Liter (Vorgabe 10,0)
      * `liter`/`eur` ODER `bestaende`/`rest` — der Brennstoff (s. `brennstoff`)
      * `ww_m3`, `ww_temp` — Warmwasservolumen und -temperatur (§9)
      * `ww_kwh`        — statt dessen die Wärmemenge direkt, wenn bekannt
      * `bloecke`       — weitere Kostenblöcke [{name, betrag, nur_heizung}]
      * `fest_anteil`   — Grundkostenanteil (Vorgabe 0,30)
      * `fest_schluessel` — wonach die Grundkosten verteilt werden: "flaeche"
                          (Vorgabe, gesetzlicher Regelfall), "personen" oder
                          "einheiten" (§7 HeizkostenV)
      * `h2_anteil`     — Anteil des Wärmezählers an den VERBRAUCHSkosten
                          (0…1). Ohne Angabe aus der Heizenergie abgeleitet
                          (siehe unten) — das ist der Regelfall.
      * `nutzer`        — [{name, flaeche, zeitanteil, ehkv, kwh, ww_m3}]
      * `soll`          — {name: Euro} die tatsächlichen Beträge von Delta-t

    Rückgabe: `brennstoff`, `energie`, `anteile`, `bloecke`, `heizung`,
    `warmwasser`, `preise`, `nutzer` (je Zeile mit Teilbeträgen, Summe und —
    wo ein Soll vorliegt — `soll` und `abweichung`) und `abgleich`.
    """
    # N373 — der Heizwert kommt aus `waerme`, nicht als eigene Zahl.
    heizwert = _zahl(eingabe.get("heizwert"), HEIZWERT_OEL) or HEIZWERT_OEL
    stoff = brennstoff(eingabe)
    gesamt_kwh = oel_kwh(stoff["liter"], heizwert)

    # Warmwasser: gemessene Wärmemenge oder aus dem Volumen nach §9.
    ww_kwh = (_zahl(eingabe.get("ww_kwh")) if eingabe.get("ww_kwh") is not None
              else warmwasser_kwh(_zahl(eingabe.get("ww_m3")),
                                  _zahl(eingabe.get("ww_temp"), 60.0)))
    ww_liter = round(ww_kwh / heizwert, 3) if heizwert else 0.0
    ww_anteil = (min(1.0, ww_liter / stoff["liter"]) if stoff["liter"] > 0
                 else 0.0)
    heiz_anteil = round(1.0 - ww_anteil, 6)

    bloecke = _bloecke_teilen(
        [{"name": "Brennstoffkosten", "betrag": stoff["eur"]}]
        + list(eingabe.get("bloecke") or []), heiz_anteil)
    heiz_gesamt = round(sum(b["heizung"] for b in bloecke), 2)
    ww_gesamt = round(sum(b["warmwasser"] for b in bloecke), 2)

    fest_anteil = _zahl(eingabe.get("fest_anteil"), FEST_ANTEIL)
    fest_eur = round(heiz_gesamt * fest_anteil, 2)
    verbrauch_eur = round(heiz_gesamt - fest_eur, 2)
    # N395 — der Umschalter „Grundkosten verteilen nach" (Fläche/Personen/
    # Einheiten) griff bisher ins Leere: die Verteilung war unten hart auf
    # das Feld "flaeche" codiert. Unbekannte Werte fallen auf den
    # gesetzlichen Regelfall zurück, statt eine Ausnahme zu werfen — eine
    # falsche Kleinschreibung soll die Rechnung nicht abbrechen.
    fest_schluessel = eingabe.get("fest_schluessel") or "flaeche"
    if fest_schluessel not in FEST_SCHLUESSEL:
        fest_schluessel = "flaeche"

    nutzer = list(eingabe.get("nutzer") or [])
    summe_ehkv = round(sum(_zahl(n.get("ehkv")) for n in nutzer), 3)
    summe_kwh = round(sum(_zahl(n.get("kwh")) for n in nutzer), 3)
    summe_ww = round(sum(_zahl(n.get("ww_m3")) for n in nutzer), 3)
    # Fläche zeitanteilig — ein unterjähriger Wechsel teilt dieselbe Wohnung
    # unter zwei Nutzern auf (Delta-t schreibt das als „× 360,0/1000,0").
    summe_flaeche = round(
        sum(_zahl(n.get("flaeche")) * _zahl(n.get("zeitanteil"), 1.0)
            for n in nutzer), 3)

    # N340b — der gesuchte Schlüssel, gefunden: der Wärmezähler bekommt seinen
    # Anteil an der **Heizenergie**, also an der Ölenergie NACH Abzug des
    # Warmwassers — nicht an der Rohenergie. Und zwar als Anteil an den
    # GESAMTEN Heizkosten (die 30 % Grundkosten eingeschlossen), weshalb auf
    # der Abrechnung H01 und H02 zusammen 70 % ergeben.
    #
    #   H02-Prozent = kWh Wärmezähler / (Ölenergie × Heizungsanteil)
    #
    # An vier echten Abrechnungen geprüft: 2018/19 24,80 % (Abrechnung 24,80),
    # 2020/21 30,03 % (30,03), 2022/23 24,72 % (24,71) — und 2023/24 23,34 %
    # gegen ausgewiesene 23,23 %. Drei Jahre auf die zweite Nachkommastelle,
    # das vierte um 0,11 Prozentpunkte daneben; woran das liegt, muss die
    # Simulation zeigen. Deshalb bleibt `h2_anteil` überschreibbar.
    heiz_kwh = round(gesamt_kwh * heiz_anteil, 3)
    if eingabe.get("h2_anteil") is not None:
        h2_anteil = max(0.0, min(1.0, _zahl(eingabe.get("h2_anteil"))))
    else:
        von_gesamt = (summe_kwh / heiz_kwh) if heiz_kwh > 0 else 0.0
        rest = 1.0 - fest_anteil
        h2_anteil = min(1.0, von_gesamt / rest) if rest > 0 else 0.0
    verbrauch_h2 = round(verbrauch_eur * h2_anteil, 2)
    verbrauch_h1 = round(verbrauch_eur - verbrauch_h2, 2)

    teile = lambda betrag, menge: round(betrag / menge, 6) if menge > 0 else 0.0
    preise = {
        "fest_je_m2": teile(fest_eur, summe_flaeche),
        "h1_je_einheit": teile(verbrauch_h1, summe_ehkv),
        "h2_je_kwh": teile(verbrauch_h2, summe_kwh),
        "ww_je_m3": teile(ww_gesamt, summe_ww),
    }

    # N368 — der Schlüssel trägt den Index, der Name bleibt zur Anzeige. Zwei
    # Zeilen gleichen Namens (zwei gleich benannte Einheiten, ein zweites
    # „Allgemein") wurden vorher in EINEN Topf gebündelt, danach aber
    # positionsweise wieder ausgelesen — beide bekamen den zusammengelegten
    # Betrag, und die Summe der Zeilen überschritt die eingesetzten Liter und
    # Euro. `vermoegen.pv_zurechnung` schlüsselt aus demselben Grund nach Index.
    namen = [n.get("name") or f"Nutzer {i + 1}" for i, n in enumerate(nutzer)]
    schluessel = [f"{i}:{name}" for i, name in enumerate(namen)]
    rundung = eingabe.get("rundung") or "deltat"

    def topf(betrag: float, feld: str, mit_zeit: bool = False) -> dict:
        gewichte = {}
        for name, n in zip(schluessel, nutzer):
            wert = _zahl(n.get(feld))
            if mit_zeit:
                wert *= _zahl(n.get("zeitanteil"), 1.0)
            gewichte[name] = gewichte.get(name, 0.0) + wert
        if rundung == "engine":
            return verteile_nach_wert(betrag, gewichte)
        return _verteile_wie_deltat(betrag, gewichte)

    t_h1 = topf(verbrauch_h1, "ehkv")
    t_h2 = topf(verbrauch_h2, "kwh")
    t_fest = topf(fest_eur, fest_schluessel, mit_zeit=True)
    t_ww = topf(ww_gesamt, "ww_m3")

    # N340c — dieselbe Verteilung noch einmal in LITERN. Der Nutzer will für
    # seine eigene Abrechnung nicht Euro-Töpfe umlegen, sondern schlicht die
    # verbrauchten Liter Öl auf die abgelesenen Werte verteilen. Die Menge
    # folgt denselben Gewichten wie das Geld — Liter und Euro bleiben so
    # zueinander stimmig, egal welche Kostenblöcke sonst mitlaufen.
    def menge(gesamt: float, feld: str, mit_zeit: bool = False) -> dict:
        gewichte = {}
        for name, n in zip(schluessel, nutzer):
            wert = _zahl(n.get(feld))
            if mit_zeit:
                wert *= _zahl(n.get("zeitanteil"), 1.0)
            gewichte[name] = gewichte.get(name, 0.0) + wert
        summe = sum(gewichte.values())
        if summe <= 0:
            return {k: 0.0 for k in gewichte}
        return {k: round(gesamt * v / summe, 3) for k, v in gewichte.items()}

    liter_heiz = round(stoff["liter"] * heiz_anteil, 3)
    l_fest = menge(liter_heiz * fest_anteil, fest_schluessel, mit_zeit=True)
    l_h1 = menge(liter_heiz * (1 - fest_anteil) * (1 - h2_anteil), "ehkv")
    l_h2 = menge(liter_heiz * (1 - fest_anteil) * h2_anteil, "kwh")
    l_ww = menge(ww_liter, "ww_m3")

    soll = eingabe.get("soll") or {}
    zeilen = []
    for schl, name, n in zip(schluessel, namen, nutzer):
        p_h1, p_h2 = t_h1.get(schl, 0.0), t_h2.get(schl, 0.0)
        p_fest, p_ww = t_fest.get(schl, 0.0), t_ww.get(schl, 0.0)
        liter_heizung = round(l_fest.get(schl, 0.0) + l_h1.get(schl, 0.0)
                              + l_h2.get(schl, 0.0), 3)
        zeile = {"name": name, "verbrauch_h1": p_h1, "verbrauch_h2": p_h2,
                 "festkosten": p_fest, "warmwasser": p_ww,
                 "liter": liter_heizung,
                 "liter_warmwasser": l_ww.get(schl, 0.0),
                 "kwh": round(liter_heizung * heizwert, 1),
                 "heizkosten": round(p_h1 + p_h2 + p_fest, 2),
                 "summe": round(p_h1 + p_h2 + p_fest + p_ww, 2)}
        if name in soll:
            zeile["soll"] = round(_zahl(soll[name]), 2)
            zeile["abweichung"] = round(zeile["heizkosten"] - zeile["soll"], 2)
        zeilen.append(zeile)

    verglichen = [z for z in zeilen if "abweichung" in z]
    return {
        "brennstoff": stoff,
        "energie": {"gesamt_kwh": gesamt_kwh, "ww_kwh": round(ww_kwh, 3),
                    "ww_liter": ww_liter, "heizwert": heizwert,
                    "heiz_kwh": heiz_kwh},
        "anteile": {"warmwasser": round(ww_anteil, 6),
                    "heizung": heiz_anteil,
                    "fest": fest_anteil,
                    "fest_schluessel": fest_schluessel,
                    "h2_von_verbrauch": round(h2_anteil, 6),
                    # So steht es auf der Abrechnung: H01 und H02 als Anteile
                    # an den gesamten Heizkosten, zusammen die 70 %.
                    "h2_von_gesamt": round(h2_anteil * (1 - fest_anteil), 6),
                    "h1_von_gesamt": round((1 - h2_anteil) * (1 - fest_anteil), 6)},
        "bloecke": bloecke,
        "heizung": {"gesamt": heiz_gesamt, "fest": fest_eur,
                    "verbrauch": verbrauch_eur,
                    "verbrauch_h1": verbrauch_h1, "verbrauch_h2": verbrauch_h2},
        "warmwasser": {"gesamt": ww_gesamt},
        "mengen": {"flaeche": summe_flaeche, "ehkv": summe_ehkv,
                   "kwh": summe_kwh, "ww_m3": summe_ww},
        "preise": preise,
        "nutzer": zeilen,
        "abgleich": {
            "verglichen": len(verglichen),
            "groesste_abweichung": (max((abs(z["abweichung"]) for z in verglichen),
                                        default=0.0)),
            "summe_abweichung": round(sum(z["abweichung"] for z in verglichen), 2),
            "summe_ist": round(sum(z["heizkosten"] for z in zeilen), 2),
            "summe_soll": round(sum(z["soll"] for z in verglichen), 2),
        },
    }


def nur_oel(eingabe: dict, fest_anteil: float = 0.0,
            warmwasser_abziehen: bool = True) -> dict:
    """N340c — nur das Öl verteilen, sonst nichts.

    Der Messdienst legt jede Menge mit um: Betriebsstrom, Kaminkehrer,
    Wartung, Abrechnungsgebühren, Miete der Zähler. Für die eigene Abrechnung
    will der Nutzer genau das nicht — nur die verbrauchten Liter Öl, verteilt
    über die abgelesenen Werte an Heizkörpern und Wärmezähler.

    Deshalb hier: alle Kostenblöcke fallen weg, es bleibt der Brennstoff.

    * `fest_anteil=0.0` (Vorgabe) heisst **rein nach Verbrauch** — wer nicht
      heizt, zahlt nichts. Wer den gesetzlichen Regelfall will, gibt 0,30 an;
      dann gehen 30 % nach Fläche wie bei Delta-t.
    * `warmwasser_abziehen=True` nimmt die Warmwasser-Wärmemenge nach §9
      vorweg heraus (sie hat mit den Heizkörpern nichts zu tun). Mit `False`
      wandert alles Öl in die Heizung — sinnvoll, wenn das Warmwasser separat
      abgerechnet wird oder es keines gibt.

    Der Rest ist derselbe Rechenweg wie sonst, also auch dieselbe Prüfung: die
    Summe der Zeilen ergibt exakt die eingesetzten Liter und Euro.
    """
    ohne = {k: v for k, v in eingabe.items()
            if k not in ("bloecke", "fest_anteil", "soll")}
    if not warmwasser_abziehen:
        ohne["ww_m3"] = 0.0
        ohne["ww_kwh"] = 0.0
    return rechne({**ohne, "bloecke": [], "fest_anteil": fest_anteil})


def h2_anteil_aus_soll(eingabe: dict) -> float | None:
    """Welcher H2-Anteil träfe die vorgegebenen Soll-Beträge am besten?

    Der Nutzer sucht genau diese Zahl. Statt sie von Hand zu suchen, wird sie
    hier eingegabelt: 0 bis 1 in feinen Schritten, das Minimum der Summe der
    Abweichungsquadrate gewinnt. Ohne Soll-Werte gibt es nichts zu treffen."""
    if not (eingabe.get("soll") or {}):
        return None
    bester, bestwert = None, None
    for schritt in range(0, 1001):
        anteil = schritt / 1000
        erg = rechne({**eingabe, "h2_anteil": anteil})
        abw = sum(z["abweichung"] ** 2 for z in erg["nutzer"]
                  if "abweichung" in z)
        if bestwert is None or abw < bestwert:
            bester, bestwert = anteil, abw
    return bester


__all__ = ["rechne", "brennstoff", "nur_oel", "h2_anteil_aus_soll",
           "FEST_ANTEIL", "verteile_nach_wert"]
