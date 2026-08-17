"""Investment-Kennzahlen: NOI, Rendite, Finanzierung, Cashflow, Potenzial (N409).

Reine, seiteneffektfreie Rechen-Engine — keine Datenbank, keine Oberfläche.
Nimmt eine `KpiEingabe` (Momentaufnahme aller Eingaben, vom Aufrufer aus den
ORM-Modellen zusammengestellt) und liefert einen flachen Kennzahlen-Satz
zurück. Die Zuordnung „ist das Modul-Ergebnis grün/gelb/rot" (Bewertung/
Rating) gehört NICHT hierher — das ist ein eigener, noch zu bauender Layer
(N409 Aufgabe 2) auf diesen Zahlen.

**Roter Faden: fehlt eine Eingabe, ist das Ergebnis `None` — nie eine
erfundene 0.** 0 € Miete und „keine Angabe zur Miete" sind verschiedene
Aussagen; diese Engine verwechselt sie nirgends. Dieselbe Sprache wie
`vermoegen.wertzuwachs_kennzahlen`/`monatszins`, hier nur für das größere
Kennzahlen-Set eines Investments.

Amortisationsmathematik (Zins-/Tilgungsanteil je Monat) wird bewusst NICHT
neu geschrieben, sondern aus `vermoegen` übernommen (`_monatsschritt`) —
dieselbe Rechnung, die auch die Restschuld-Fortschreibung trägt. Zwei
Wahrheiten für dieselbe Zinsformel wären ein Risiko, kein Gewinn.

Die Kappungsgrenzen-Prüfung (§ 558 BGB, Sperr-/Wartefrist, angespannte
Wohnungsmärkte) lebt vollständig in `kappungsgrenze.py` und bleibt dort —
dieses Modul nimmt ihr Ergebnis nur entgegen (`kappungsgrenze_prozent`,
`basismiete_vor_3_jahren`), statt Datums- und Verordnungslogik ein zweites
Mal nachzubauen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .turnus import jahresbetrag
from .vermoegen import _monatsschritt

# Peters-Formel — verbreiteter Ansatz für die Instandhaltungsrücklage:
# 1,5 × Baukosten je m² Wohnfläche, über eine angenommene Nutzungsdauer von
# 80 Jahren linear verteilt. Nur ein Vorschlag; `ruecklage_jahr` in der
# Eingabe überschreibt ihn, sobald jemand einen eigenen Wert einträgt.
PETERS_FAKTOR = 1.5
PETERS_NUTZUNGSDAUER_JAHRE = 80


@dataclass
class KreditEingabe:
    """Ein Darlehen, so weit reduziert, wie diese Engine es braucht — kein
    ORM-Objekt, damit die Engine ohne Datenbank testbar bleibt."""
    restschuld: float | None = None
    zinssatz_pct: float | None = None       # Prozent p. a.
    rate_monatlich: float | None = None     # Annuität je Monat (Zins + Tilgung)
    zinsbindung_bis: date | None = None
    ist_bausparvertrag: bool = False        # keine Zinslast, kein Kapitaldienst


@dataclass
class KpiEingabe:
    """Alle Eingaben für eine KPI-Berechnung, zu einem Stichtag. Jedes Feld
    ist optional — was fehlt, lässt die davon abhängigen Kennzahlen `None`
    werden, blockiert aber nie die übrigen."""
    stichtag: date | None = None

    # ---- Kauf --------------------------------------------------------
    kaufpreis: float | None = None
    kaufdatum: date | None = None
    nebenkosten_grunderwerbsteuer: float | None = None
    nebenkosten_notar: float | None = None
    nebenkosten_makler: float | None = None

    # ---- Wert ----------------------------------------------------------
    verkehrswert: float | None = None

    # ---- Flächen / Einheiten -------------------------------------------
    grundstuecksflaeche_qm: float | None = None
    wohnflaeche_qm: float | None = None
    anzahl_einheiten: int | None = None

    # ---- Bodenrichtwert --------------------------------------------------
    bodenrichtwert_eur_qm: float | None = None
    bodenrichtwert_stichtag: date | None = None

    # ---- Gebäudeanteil / AfA -------------------------------------------
    gebaeudeanteil_pct_manuell: float | None = None   # Override
    afa_satz_pct: float | None = None                  # 2.0 / 2.5 / 3.33 / …
    restnutzungsdauer_jahre: float | None = None

    # ---- Steuer ----------------------------------------------------------
    grenzsteuersatz_pct: float | None = None

    # ---- Bewirtschaftung --------------------------------------------------
    ruecklage_jahr_manuell: float | None = None        # Override der Peters-Formel
    baukosten_eur_qm: float | None = None              # Basis der Peters-Formel
    verwaltung_jahr: float | None = None
    mietausfallwagnis_pct: float | None = None         # % der Ist-Kaltmiete
    nicht_umlagefaehige_kosten_jahr: float | None = None

    # ---- Miete -----------------------------------------------------------
    kaltmiete_jahr_ist: float | None = None            # nur vermietete Einheiten
    kaltmiete_jahr_leerstand_potenziell: float | None = None  # zu Marktmiete
    vergleichsmiete_eur_qm: float | None = None        # Mietspiegel
    hat_leerstand: bool = False

    # ---- Finanzierung ------------------------------------------------------
    kredite: list[KreditEingabe] = field(default_factory=list)

    # ---- Potenzial ---------------------------------------------------------
    opportunitaetszins_pct: float = 4.0
    kappungsgrenze_prozent: float | None = None        # aus kappungsgrenze.py
    basismiete_vor_3_jahren: float | None = None        # aus kappungsgrenze.py
    aktuelle_kaltmiete_gesamt: float | None = None
    bestehende_geschossflaeche_qm: float | None = None
    zulaessige_geschossflaeche_qm: float | None = None


def _rate_jahr(k: KreditEingabe) -> float:
    return jahresbetrag(k.rate_monatlich or 0.0, "monatlich")


def _zins_jahr(k: KreditEingabe) -> float | None:
    """Zinsanteil eines Kredits im Jahr — 12 Monatsschritte über
    `_monatsschritt` (dieselbe Amortisationsrechnung wie `vermoegen`).
    `None`, solange Restschuld oder Zinssatz fehlen."""
    if k.ist_bausparvertrag:
        return 0.0
    if not k.restschuld or k.restschuld <= 0 or k.zinssatz_pct is None:
        return None
    wert = float(k.restschuld)
    rate = float(k.rate_monatlich or 0.0)
    zins_summe = 0.0
    for _ in range(12):
        if wert <= 0:
            break
        neu, zins = _monatsschritt(wert, rate, k.zinssatz_pct)
        zins_summe += zins
        wert = neu
    return round(zins_summe, 2)


def tilgungsplan(k: KreditEingabe, jahre: int) -> list[dict] | None:
    """Zins-/Tilgungsanteil je Jahr über `jahre` Jahre, plus die Restschuld
    am Jahresende. `None` ohne Restschuld/Zinssatz — eine erfundene Kurve
    wäre schlimmer als keine."""
    if k.ist_bausparvertrag:
        return None
    if not k.restschuld or k.restschuld <= 0 or k.zinssatz_pct is None:
        return None
    wert = float(k.restschuld)
    rate = float(k.rate_monatlich or 0.0)
    plan = []
    for jahr in range(1, jahre + 1):
        start = wert
        zins_summe = 0.0
        for _ in range(12):
            if wert <= 0:
                break
            neu, zins = _monatsschritt(wert, rate, k.zinssatz_pct)
            zins_summe += zins
            wert = neu
        tilgung = round(start - wert, 2)
        plan.append({"jahr": jahr, "zins": round(zins_summe, 2),
                     "tilgung": tilgung, "restschuld_jahresende": round(wert, 2)})
        if wert <= 0:
            break
    return plan


def restschuld_bei_zinsbindungsende(k: KreditEingabe,
                                    stichtag: date) -> float | None:
    """Restschuld am Ende der Zinsbindung — `None` ohne Zinsbindung, Rate,
    Restschuld oder Zinssatz, oder wenn die Bindung schon vorbei ist."""
    if (k.ist_bausparvertrag or k.zinsbindung_bis is None
            or not k.restschuld or k.restschuld <= 0
            or k.zinssatz_pct is None):
        return None
    if k.zinsbindung_bis <= stichtag:
        return None
    monate = ((k.zinsbindung_bis.year - stichtag.year) * 12
             + (k.zinsbindung_bis.month - stichtag.month))
    wert = float(k.restschuld)
    rate = float(k.rate_monatlich or 0.0)
    for _ in range(max(0, monate)):
        if wert <= 0:
            break
        wert, _ = _monatsschritt(wert, rate, k.zinssatz_pct)
    return round(wert, 2)


def betriebsergebnis(e: KpiEingabe) -> dict:
    """NOI und was in sie eingeht.

    Mietausfallwagnis rechnet auf der IST-Miete (nicht dem Potenzial) — sie
    versichert das tatsächliche Ausfallrisiko der laufenden Mieten, nicht
    eine hypothetische Vollvermietung."""
    ruecklage = e.ruecklage_jahr_manuell
    if ruecklage is None and e.baukosten_eur_qm and e.wohnflaeche_qm:
        ruecklage = round(PETERS_FAKTOR * e.baukosten_eur_qm
                          / PETERS_NUTZUNGSDAUER_JAHRE * e.wohnflaeche_qm, 2)

    mietausfall = None
    if e.mietausfallwagnis_pct is not None and e.kaltmiete_jahr_ist is not None:
        mietausfall = round(e.kaltmiete_jahr_ist * e.mietausfallwagnis_pct / 100, 2)

    nicht_umlagefaehig = None
    posten = [e.verwaltung_jahr, ruecklage, mietausfall,
             e.nicht_umlagefaehige_kosten_jahr]
    if any(p is not None for p in posten):
        nicht_umlagefaehig = round(sum(p or 0.0 for p in posten), 2)

    noi = None
    if e.kaltmiete_jahr_ist is not None and nicht_umlagefaehig is not None:
        noi = round(e.kaltmiete_jahr_ist - nicht_umlagefaehig, 2)

    return {
        "ruecklage_jahr": ruecklage,
        "mietausfallwagnis_jahr": mietausfall,
        "nicht_umlagefaehige_kosten_gesamt": nicht_umlagefaehig,
        "noi": noi,
    }


def rendite(e: KpiEingabe, noi: float | None) -> dict:
    """Bruttorendite, Nettorendite, Kaufpreisfaktor, Miete/m² vs. Vergleich."""
    out: dict = {"brutto_rendite_pct": None, "netto_rendite_pct": None,
                "kaufpreisfaktor": None, "miete_pro_qm_ist": None,
                "miete_pro_qm_differenz": None}

    if e.kaltmiete_jahr_ist is not None and e.kaufpreis:
        out["brutto_rendite_pct"] = round(
            e.kaltmiete_jahr_ist / e.kaufpreis * 100, 2)
        out["kaufpreisfaktor"] = (round(e.kaufpreis / e.kaltmiete_jahr_ist, 1)
                                 if e.kaltmiete_jahr_ist > 0 else None)

    gesamtinvestition = _gesamtinvestition(e)
    if noi is not None and gesamtinvestition:
        out["netto_rendite_pct"] = round(noi / gesamtinvestition * 100, 2)

    if e.kaltmiete_jahr_ist is not None and e.wohnflaeche_qm:
        out["miete_pro_qm_ist"] = round(
            e.kaltmiete_jahr_ist / 12 / e.wohnflaeche_qm, 2)
        if e.vergleichsmiete_eur_qm is not None:
            out["miete_pro_qm_differenz"] = round(
                e.vergleichsmiete_eur_qm - out["miete_pro_qm_ist"], 2)
    return out


def _gesamtinvestition(e: KpiEingabe) -> float | None:
    if not e.kaufpreis:
        return None
    nk = [e.nebenkosten_grunderwerbsteuer, e.nebenkosten_notar,
         e.nebenkosten_makler]
    return round(e.kaufpreis + sum(n or 0.0 for n in nk), 2)


def finanzierung(e: KpiEingabe, noi: float | None, stichtag: date) -> dict:
    """LTV, DSCR, Leverage-Spread — die Leitkennzahl dieses Moduls.

    Ein Objekt ganz ohne Darlehen ist NICHT „unendlich gut": DSCR ist dann
    schlicht nicht anwendbar (`None`, eigens `dscr_anwendbar=False`), LTV
    ist 0 %. Der Leverage-Spread bleibt trotzdem berechenbar (der
    Fremdkapitalzins ist dann 0 %) — er zeigt in diesem Fall einfach genau
    die Nettorendite."""
    echte_darlehen = [k for k in e.kredite if not k.ist_bausparvertrag]
    restschuld_gesamt = round(sum(k.restschuld or 0.0
                                  for k in echte_darlehen), 2)

    ltv_pct = None
    if e.verkehrswert:
        ltv_pct = round(restschuld_gesamt / e.verkehrswert * 100, 2)

    kapitaldienst = None
    if echte_darlehen:
        raten = [_rate_jahr(k) for k in echte_darlehen if k.rate_monatlich]
        if raten:
            kapitaldienst = round(sum(raten), 2)

    dscr = None
    dscr_anwendbar = bool(echte_darlehen) and bool(restschuld_gesamt)
    if dscr_anwendbar and noi is not None and kapitaldienst:
        dscr = round(noi / kapitaldienst, 2)

    # Gewichteter Durchschnittszins über die Restschuld — Basis des Spreads.
    zins_gewichtet_pct = None
    gewichtssumme = sum(k.restschuld or 0.0 for k in echte_darlehen
                        if k.zinssatz_pct is not None)
    if gewichtssumme > 0:
        zins_gewichtet_pct = round(sum(
            (k.restschuld or 0.0) * (k.zinssatz_pct or 0.0)
            for k in echte_darlehen if k.zinssatz_pct is not None
        ) / gewichtssumme, 3)
    elif not echte_darlehen:
        zins_gewichtet_pct = 0.0     # schuldenfrei: kein Fremdkapitalzins

    netto_rendite = rendite(e, noi)["netto_rendite_pct"]
    leverage_spread_pp = None
    if netto_rendite is not None and zins_gewichtet_pct is not None:
        leverage_spread_pp = round(netto_rendite - zins_gewichtet_pct, 2)

    plaene = {}
    restschulden_bindungsende = {}
    for i, k in enumerate(echte_darlehen):
        plan = tilgungsplan(k, 30)
        if plan is not None:
            plaene[i] = plan
        rs = restschuld_bei_zinsbindungsende(k, stichtag)
        if rs is not None:
            restschulden_bindungsende[i] = rs

    # Die nächste auslaufende Zinsbindung unter allen echten Darlehen — für
    # die Countdown-Marke in der Eigentümer-Liste (< 36 Monate).
    kuenftige_bindungen = [k.zinsbindung_bis for k in echte_darlehen
                          if k.zinsbindung_bis and k.zinsbindung_bis > stichtag]
    naechste_zinsbindung_bis = min(kuenftige_bindungen) if kuenftige_bindungen else None

    return {
        "restschuld_gesamt": restschuld_gesamt,
        "ltv_pct": ltv_pct,
        "kapitaldienst_jahr": kapitaldienst,
        "dscr": dscr,
        "dscr_anwendbar": dscr_anwendbar,
        "zins_gewichtet_pct": zins_gewichtet_pct,
        "leverage_spread_pp": leverage_spread_pp,
        "tilgungsplaene_je_kredit": plaene,
        "restschuld_bei_zinsbindungsende_je_kredit": restschulden_bindungsende,
        "naechste_zinsbindung_bis": naechste_zinsbindung_bis,
    }


def cashflow(e: KpiEingabe, noi: float | None, fin: dict) -> dict:
    """Cashflow vor/nach Tilgung, steuerlich, „echtes Defizit".

    Das „echte Defizit" ist der Cashflow nach Steuer, aber OHNE den
    Tilgungsanteil — Tilgung ist Vermögensaufbau (sie fließt ins
    Eigenkapital), keine Ausgabe, die das Objekt „verliert". Das ist die
    Zahl, die Eigentümer am häufigsten falsch lesen: ein negativer Cashflow
    NACH Tilgung fühlt sich wie ein Verlust an, ist aber oft nur Sparen in
    Immobilienform."""
    echte_darlehen = [k for k in e.kredite if not k.ist_bausparvertrag]
    zins_jahr = None
    if echte_darlehen:
        zinsen = [_zins_jahr(k) for k in echte_darlehen]
        if all(z is not None for z in zinsen):
            zins_jahr = round(sum(zinsen), 2)
    elif not e.kredite:
        zins_jahr = 0.0

    cf_vor_tilgung = None
    if noi is not None and zins_jahr is not None:
        cf_vor_tilgung = round(noi - zins_jahr, 2)

    cf_nach_tilgung = None
    if noi is not None and fin["kapitaldienst_jahr"] is not None:
        cf_nach_tilgung = round(noi - fin["kapitaldienst_jahr"], 2)
    elif noi is not None and not echte_darlehen:
        cf_nach_tilgung = noi

    # AfA-Bemessungsgrundlage: Kaufpreis abzüglich Grundstücksanteil (der
    # Grund und Boden nutzt sich nicht ab und wird nicht abgeschrieben).
    afa_jahr = None
    if (e.afa_satz_pct is not None and e.kaufpreis
            and e.gebaeudeanteil_pct_manuell is not None):
        bemessung = e.kaufpreis * e.gebaeudeanteil_pct_manuell / 100
        afa_jahr = round(bemessung * e.afa_satz_pct / 100, 2)

    steuerpflichtiges_ergebnis = None
    if (e.kaltmiete_jahr_ist is not None and zins_jahr is not None
            and afa_jahr is not None
            and e.nicht_umlagefaehige_kosten_jahr is not None):
        steuerpflichtiges_ergebnis = round(
            e.kaltmiete_jahr_ist - zins_jahr - afa_jahr
            - e.nicht_umlagefaehige_kosten_jahr, 2)

    steuererstattung = None
    if (steuerpflichtiges_ergebnis is not None
            and e.grenzsteuersatz_pct is not None):
        steuererstattung = round(
            -steuerpflichtiges_ergebnis * e.grenzsteuersatz_pct / 100, 2)

    cf_nach_steuer = None
    if cf_nach_tilgung is not None and steuererstattung is not None:
        cf_nach_steuer = round(cf_nach_tilgung + steuererstattung, 2)

    echtes_defizit = None
    tilgung_jahr = None
    if fin["kapitaldienst_jahr"] is not None and zins_jahr is not None:
        tilgung_jahr = round(fin["kapitaldienst_jahr"] - zins_jahr, 2)
    elif not echte_darlehen:
        tilgung_jahr = 0.0
    if cf_nach_steuer is not None and tilgung_jahr is not None:
        echtes_defizit = round(cf_nach_steuer + tilgung_jahr, 2)

    return {
        "zins_jahr": zins_jahr,
        "tilgung_jahr": tilgung_jahr,
        "cashflow_vor_tilgung_vor_steuer": cf_vor_tilgung,
        "cashflow_nach_tilgung_vor_steuer": cf_nach_tilgung,
        "afa_jahr": afa_jahr,
        "steuerpflichtiges_ergebnis": steuerpflichtiges_ergebnis,
        "steuererstattung": steuererstattung,
        "cashflow_nach_steuer": cf_nach_steuer,
        "echtes_defizit_jahr": echtes_defizit,
        "echtes_defizit_monat": (round(echtes_defizit / 12, 2)
                                 if echtes_defizit is not None else None),
    }


def potenzial(e: KpiEingabe, cf: dict) -> dict:
    """Break-even-Wertsteigerung, Mietreserve, Kappungsgrenzen-Spielraum,
    GFZ-Auslastung — bewusst getrennt vom Cashflow-Risiko: ein Objekt mit
    schlechtem laufendem Cashflow kann trotzdem große Reserven haben."""
    eigenkapital = None
    if e.verkehrswert is not None:
        restschuld = sum(k.restschuld or 0.0 for k in e.kredite
                         if not k.ist_bausparvertrag)
        eigenkapital = round(e.verkehrswert - restschuld, 2)

    break_even_pct = None
    if (cf["echtes_defizit_jahr"] is not None and eigenkapital is not None
            and e.verkehrswert):
        chance_kosten = eigenkapital * e.opportunitaetszins_pct / 100
        break_even_pct = round(
            (cf["echtes_defizit_jahr"] + chance_kosten) / e.verkehrswert * 100, 2)

    mietreserve_jahr = None
    if (e.vergleichsmiete_eur_qm is not None and e.wohnflaeche_qm
            and e.kaltmiete_jahr_ist is not None):
        ist_pro_qm = e.kaltmiete_jahr_ist / 12 / e.wohnflaeche_qm
        mietreserve_jahr = round(
            (e.vergleichsmiete_eur_qm - ist_pro_qm) * e.wohnflaeche_qm * 12, 2)

    kappung_spielraum_jahr = None
    hoechstmiete_jahr = None
    if (e.kappungsgrenze_prozent is not None
            and e.basismiete_vor_3_jahren is not None
            and e.aktuelle_kaltmiete_gesamt is not None):
        hoechstmiete_monat = e.basismiete_vor_3_jahren * (
            1 + e.kappungsgrenze_prozent / 100)
        hoechstmiete_jahr = round(hoechstmiete_monat * 12, 2)
        kappung_spielraum_jahr = round(
            hoechstmiete_jahr - e.aktuelle_kaltmiete_gesamt, 2)

    gfz_auslastung_pct = None
    if e.bestehende_geschossflaeche_qm is not None and e.zulaessige_geschossflaeche_qm:
        gfz_auslastung_pct = round(
            e.bestehende_geschossflaeche_qm
            / e.zulaessige_geschossflaeche_qm * 100, 1)

    return {
        "eigenkapital": eigenkapital,
        "break_even_wertsteigerung_pct": break_even_pct,
        "mietreserve_jahr": mietreserve_jahr,
        "kappungsgrenze_hoechstmiete_jahr": hoechstmiete_jahr,
        "kappungsgrenze_spielraum_jahr": kappung_spielraum_jahr,
        "gfz_auslastung_pct": gfz_auslastung_pct,
    }


def bodenrichtwert_hinweis(e: KpiEingabe) -> dict:
    """N409-Randfall: Bodenrichtwert × Fläche kann bei großen Grundstücken
    über dem Kaufpreis liegen — real, nicht stillschweigend gekappt. Ein
    Warn-Flag statt eines gekappten Werts, weil das ein Signal ist: der
    AfA-Split (Gebäude/Grund) braucht dann ein echtes Wertgutachten."""
    if not (e.bodenrichtwert_eur_qm and e.grundstuecksflaeche_qm):
        return {"bodenwert": None, "warnung_ueber_kaufpreis": False}
    bodenwert = round(e.bodenrichtwert_eur_qm * e.grundstuecksflaeche_qm, 2)
    warnung = bool(e.kaufpreis and bodenwert > e.kaufpreis)
    return {"bodenwert": bodenwert, "warnung_ueber_kaufpreis": warnung}


def kennzahlen(e: KpiEingabe) -> dict:
    """Der eine Einstiegspunkt: alle Kennzahlen zu einer Eingabe.

    Reihenfolge ist wichtig — spätere Blöcke bauen auf `noi`/`fin`/`cf` der
    früheren auf, wie in der Spezifikation (Betriebsergebnis → Rendite →
    Finanzierung → Cashflow → Potenzial)."""
    stichtag = e.stichtag or date.today()
    be = betriebsergebnis(e)
    re = rendite(e, be["noi"])
    fin = finanzierung(e, be["noi"], stichtag)
    cf = cashflow(e, be["noi"], fin)
    pot = potenzial(e, cf)
    boden = bodenrichtwert_hinweis(e)
    return {
        "betriebsergebnis": be,
        "rendite": re,
        "finanzierung": fin,
        "cashflow": cf,
        "potenzial": pot,
        "bodenrichtwert": boden,
        "hat_leerstand": e.hat_leerstand,
    }
