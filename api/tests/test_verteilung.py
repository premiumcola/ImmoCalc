"""Verteilungsgewichte — der Kern, an dem bisher jede eigene Immobilie scheiterte.

Ohne `Kostenposition.anteile` bekommt `verteile_nach_wert` ein leeres dict, die
Abrechnung liefert keine Parteien und in der Summe 0,00 €. Diese Tests belegen
den ganzen Weg: Objekt anlegen → Mieter → Position mit Schlüssel → echte
Beträge je Partei, deren Summe exakt den Gesamtkosten entspricht.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_verteilung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import verteilung  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.mailversand import MailFehler  # noqa: E402
from app.models import Einheit, Kostenposition, Miete, Partei  # noqa: E402
from app.routers import versand as versand_router  # noqa: E402

JAHR = date.today().year
START, ENDE = date(JAHR, 1, 1), date(JAHR, 12, 31)


# ---------------------------------------------------------------- Ableitung

def _einheit(bezeichnung: str, flaeche=None, terrasse=None, nebenflaeche=None,
             nk_abrechnung: bool = True):
    return Einheit(objekt_id=1, bezeichnung=bezeichnung, flaeche=flaeche,
                   terrasse=terrasse, nebenflaeche=nebenflaeche,
                   nk_abrechnung=nk_abrechnung)


def _miete(einheit: str, partei: str, personen: int = 1,
           ab: date = START, bis: date | None = None):
    return Miete(objekt_id=1, einheit=einheit, partei=partei,
                 personen=personen, ab_datum=ab, bis_datum=bis)


def test_flaeche_kommt_aus_den_einheiten():
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("EG", "Alpha"), _miete("OG", "Beta")],
                           [], START, ENDE)
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"Alpha": 60, "Beta": 90}


def test_terrasse_und_nebenflaeche_zaehlen_zur_haelfte():
    """Wie in cashflow.py — sonst zahlte eine Wohnung mit Balkon zu viel."""
    b = verteilung.bezuege([_einheit("EG", 60, terrasse=10, nebenflaeche=20)],
                           [], [], START, ENDE)
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"EG": 75.0}


def test_partei_ohne_flaeche_faellt_aus_der_flaechenverteilung():
    """Eine Garage ohne Flächenangabe darf nicht mit Gewicht 0 dastehen —
    sonst bekäme sie Vorauszahlungen komplett zurückerstattet."""
    b = verteilung.bezuege([_einheit("Wohnung", 80), _einheit("Garage")],
                           [], [], START, ENDE)
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"Wohnung": 80}


def test_personen_aus_dem_laufenden_mietverhaeltnis():
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 60)],
                           [_miete("EG", "Alpha", personen=3),
                            _miete("OG", "Beta", personen=1)], [], START, ENDE)
    assert verteilung.gewichte("personen", b, START, ENDE) == {"Alpha": 3, "Beta": 1}


def test_personen_ersatzweise_aus_der_parteiliste():
    b = verteilung.bezuege([], [], [Partei(objekt_id=1, name="Alpha", personen=4)],
                           START, ENDE)
    assert verteilung.gewichte("personen", b, START, ENDE) == {"Alpha": 4}


def test_einheiten_verteilt_zu_gleichen_teilen():
    b = verteilung.bezuege([_einheit("EG", 20), _einheit("OG", 200)], [], [],
                           START, ENDE)
    assert verteilung.gewichte("einheiten", b, START, ENDE) == {"EG": 1.0, "OG": 1.0}


def test_bewohnermonate_taggenau_beim_mieterwechsel():
    """Zwei lückenlos aufeinanderfolgende Mietverhältnisse ergeben zusammen
    genau zwölf Monate — nicht dreizehn wie beim Zählen ganzer Monate."""
    wechsel = date(JAHR, 7, 15)
    b = verteilung.bezuege(
        [_einheit("EG", 60)],
        [_miete("EG", "Vorher", personen=1, ab=START, bis=wechsel),
         _miete("EG", "Nachher", personen=1,
                ab=date(JAHR, 7, 16), bis=None)], [], START, ENDE)
    g = verteilung.gewichte("bewohnermonate", b, START, ENDE)
    assert sorted(g) == ["Nachher", "Vorher"]
    assert round(sum(g.values()), 2) == 12.0


def _wechsel_im_haus(wechsel: date) -> list[verteilung.Bezug]:
    """EG mit Mieterwechsel an diesem Tag, OG durchgehend bewohnt."""
    return verteilung.bezuege(
        [_einheit("EG", 60), _einheit("OG", 90)],
        [_miete("EG", "Vorher", personen=2, ab=START, bis=wechsel),
         _miete("EG", "Nachher", personen=2,
                ab=date(wechsel.year, wechsel.month, wechsel.day + 1)),
         _miete("OG", "Beta", personen=3)], [], START, ENDE)


def test_flaeche_beim_mieterwechsel_bleibt_bei_der_einheit():
    """Fund XCI: ohne Zeitanteil bekam jede der beiden EG-Parteien die vollen
    60 m² angerechnet. Aus 60 + 90 m² wurden 210, das OG trug nur noch 42,86 %
    statt 60 % — bei 500 € Wasser 214,29 € statt 300 €."""
    g = verteilung.gewichte("flaeche", _wechsel_im_haus(date(JAHR, 7, 15)),
                            START, ENDE)
    assert round(g["Vorher"] + g["Nachher"], 2) == 60.0
    assert g["Beta"] == 90.0
    assert round(sum(g.values()), 2) == 150.0
    assert g["Vorher"] > g["Nachher"], "wer länger wohnt, trägt mehr"


def test_flaeche_wechsel_kurz_vor_jahresende_verschiebt_die_last():
    """Ein Wechsel am 21.12. muss andere Zahlen ergeben als einer zur
    Jahresmitte — solange das Gewicht die volle Fläche war, kamen exakt
    dieselben heraus."""
    g = verteilung.gewichte("flaeche", _wechsel_im_haus(date(JAHR, 12, 20)),
                            START, ENDE)
    assert round(g["Vorher"] + g["Nachher"], 2) == 60.0
    assert round(sum(g.values()), 2) == 150.0
    assert g["Nachher"] < 2.0, "elf Tage von zwölf Monaten"
    zur_jahresmitte = verteilung.gewichte(
        "flaeche", _wechsel_im_haus(date(JAHR, 7, 15)), START, ENDE)
    assert g["Nachher"] != zur_jahresmitte["Nachher"]


def test_personen_beim_mieterwechsel_zaehlen_die_einheit_nicht_doppelt():
    """Zwei Personen im EG bleiben zwei — auch wenn sie mitten im Jahr
    ausgetauscht werden."""
    g = verteilung.gewichte("personen", _wechsel_im_haus(date(JAHR, 7, 15)),
                            START, ENDE)
    assert round(g["Vorher"] + g["Nachher"], 2) == 2.0
    assert g["Beta"] == 3.0
    assert round(sum(g.values()), 2) == 5.0


def test_einheiten_beim_mieterwechsel_teilen_sich_den_anteil():
    """Sonst zählte das Haus drei Einheiten statt zwei."""
    g = verteilung.gewichte("einheiten", _wechsel_im_haus(date(JAHR, 7, 15)),
                            START, ENDE)
    assert round(g["Vorher"] + g["Nachher"], 4) == 1.0
    assert g["Beta"] == 1.0
    assert round(sum(g.values()), 2) == 2.0


def _haus_mit_leerstand(bis: date | None, ab: date = START) -> list[verteilung.Bezug]:
    """EG nur von `ab` bis `bis` vermietet, OG durchgehend."""
    return verteilung.bezuege(
        [_einheit("EG", 60), _einheit("OG", 90)],
        [_miete("EG", "Vorher", personen=2, ab=ab, bis=bis),
         _miete("OG", "Beta", personen=3)], [], START, ENDE)


def test_leerstand_ab_jahresmitte_bleibt_bei_der_einheit():
    """Fund CXXI: endet ein Mietverhältnis mitten im Jahr ohne Nachmieter,
    galt die Einheit als belegt und bekam keinen Leerstands-Bezug. Ihr halber
    Anteil wanderte auf die übrigen Mieter — das OG trug 75,2 % statt 60 %."""
    g = verteilung.gewichte("flaeche", _haus_mit_leerstand(date(JAHR, 6, 30)),
                            START, ENDE)
    assert g["Beta"] == 90.0
    assert round(g["Vorher"] + g["EG"], 2) == 60.0, "die Einheit bleibt bei 60 m²"
    assert round(sum(g.values()), 2) == 150.0
    assert round(g["Vorher"] / 60 * 100) == 50, "ein halbes Jahr bewohnt"
    assert round(g["Beta"] / sum(g.values()) * 100, 1) == 60.0


def test_leerstand_vor_dem_mietbeginn_bleibt_bei_der_einheit():
    """Neukauf, Erstvermietung ab Juli: die leeren ersten Monate gehören dem
    Eigentümer, nicht dem Nachbarn."""
    g = verteilung.gewichte("flaeche",
                            _haus_mit_leerstand(None, ab=date(JAHR, 7, 1)),
                            START, ENDE)
    assert g["Beta"] == 90.0
    assert round(g["Vorher"] + g["EG"], 2) == 60.0
    assert round(sum(g.values()), 2) == 150.0


def test_leerstand_in_der_mitte_ergibt_zwei_stuecke():
    """Januar leer, Februar bis Juni vermietet, danach wieder leer — beide
    Stücke gehören zum selben Leerstands-Bezug."""
    b = verteilung.bezuege(
        [_einheit("EG", 60), _einheit("OG", 90)],
        [_miete("EG", "Zwischenzeit", ab=date(JAHR, 2, 1), bis=date(JAHR, 6, 30)),
         _miete("OG", "Beta")], [], START, ENDE)
    leer = next(x for x in b if x.leerstand)
    assert len(leer.zeiten) == 2
    assert leer.zeiten[0] == (START, date(JAHR, 1, 31))
    assert leer.zeiten[1] == (date(JAHR, 7, 1), ENDE)
    g = verteilung.gewichte("flaeche", b, START, ENDE)
    assert round(g["Zwischenzeit"] + g["EG"], 2) == 60.0
    assert g["Beta"] == 90.0
    assert verteilung.leerstaende(b) == ["EG"]


def test_voller_leerstand_bleibt_wie_bisher():
    """Regression: eine ganze Zeit lang leerstehende Einheit trägt ihre volle
    Fläche — daran ändert der neue Teil-Leerstand nichts."""
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("OG", "Beta")], [], START, ENDE)
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"EG": 60.0,
                                                              "Beta": 90.0}
    assert verteilung.leerstaende(b) == ["EG"]


def test_lueckenloser_mieterwechsel_erzeugt_keinen_leerstand():
    """Fund XCI darf nicht zurückkommen: zwei nahtlose Mietverhältnisse lassen
    keine unbelegte Zeit übrig, es entsteht kein dritter Bezug."""
    b = _wechsel_im_haus(date(JAHR, 7, 15))
    assert verteilung.leerstaende(b) == []
    g = verteilung.gewichte("flaeche", b, START, ENDE)
    assert sorted(g) == ["Beta", "Nachher", "Vorher"]
    assert round(g["Vorher"] + g["Nachher"], 2) == 60.0
    assert round(sum(g.values()), 2) == 150.0


def test_leerstand_traegt_auch_bei_personen_und_einheiten():
    """Auch die anderen ableitbaren Schlüssel dürfen die unbelegte Zeit nicht
    auf die Mieter schieben: die Einheit bleibt ein Anteil."""
    b = _haus_mit_leerstand(date(JAHR, 6, 30))
    einheiten = verteilung.gewichte("einheiten", b, START, ENDE)
    assert round(einheiten["Vorher"] + einheiten["EG"], 4) == 1.0
    assert einheiten["Beta"] == 1.0
    personen = verteilung.gewichte("personen", b, START, ENDE)
    assert personen["Beta"] == 3.0
    assert round(personen["Vorher"], 1) == 1.0, "zwei Personen, ein halbes Jahr"


def test_bewohnermonate_ueber_zwei_kalenderjahre():
    """Ein Wirtschaftsjahr Oktober–September berührt zwei Kalenderjahre."""
    start, ende = date(2024, 10, 1), date(2025, 9, 30)
    b = verteilung.bezuege([_einheit("EG", 60)],
                           [_miete("EG", "Alpha", personen=2, ab=date(2020, 1, 1))],
                           [], start, ende)
    g = verteilung.gewichte("bewohnermonate", b, start, ende)
    assert round(g["Alpha"] / 2, 1) == 12.0


def test_verbrauch_und_prozent_lassen_sich_nicht_ableiten():
    b = verteilung.bezuege([_einheit("EG", 60)], [], [], START, ENDE)
    for schluessel in ("verbrauch", "prozent", "individuell"):
        assert verteilung.gewichte(schluessel, b, START, ENDE) == {}


def test_unbekannter_schluessel_wird_abgelehnt():
    with pytest.raises(verteilung.UnbekannterSchluessel):
        verteilung.gewichte("mondphase", [], START, ENDE)


# ---------------------------------------------- CXCIII: Einheit ausschliessen

def test_ausgeschlossene_einheit_zaehlt_in_keinem_schluessel():
    """Fund CXCIII: eine Einheit mit nk_abrechnung=False (selbstgenutzt,
    separat abgerechnet) taucht in keinem Schlüssel auf — weder ihr Mieter noch
    ein Leerstand. Die übrigen Einheiten tragen exakt ihre eigene Fläche,
    nichts wird verzerrt."""
    einheiten = [_einheit("EG", 60), _einheit("OG", 90),
                 _einheit("Laden", 50, nk_abrechnung=False)]
    mieten = [_miete("EG", "Alpha", personen=2),
              _miete("OG", "Beta", personen=3),
              _miete("Laden", "Gamma", personen=1)]
    b = verteilung.bezuege(einheiten, mieten, [], START, ENDE)
    assert "Gamma" not in {x.partei for x in b}, "der Ladenmieter ist raus"

    flaeche = verteilung.gewichte("flaeche", b, START, ENDE)
    assert flaeche == {"Alpha": 60, "Beta": 90}, "ohne die 50 m² des Ladens"
    personen = verteilung.gewichte("personen", b, START, ENDE)
    assert personen == {"Alpha": 2, "Beta": 3}
    einh = verteilung.gewichte("einheiten", b, START, ENDE)
    assert einh == {"Alpha": 1.0, "Beta": 1.0}, "zwei Einheiten, nicht drei"


def test_ausgeschlossene_einheit_bekommt_keinen_leerstand():
    """Auch die leere Zeit einer ausgeschlossenen Einheit gehört nicht in diese
    Abrechnung — sie darf keinen Leerstands-Bezug erzeugen."""
    b = verteilung.bezuege(
        [_einheit("EG", 60), _einheit("DG", 50, nk_abrechnung=False)],
        [_miete("EG", "Alpha")], [], START, ENDE)
    assert verteilung.leerstaende(b) == [], "das leere DG bleibt draussen"
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"Alpha": 60}


def test_ausschluss_verzerrt_die_uebrigen_anteile_nicht():
    """Die Kernbedingung am Geld: 300 € nach Fläche auf drei Einheiten, eine
    davon ausgeschlossen. Die übrigen zwei (60 + 90 m²) tragen zusammen exakt
    300 €, als gäbe es die dritte nicht."""
    from app.engine import Position, abrechnung
    b = verteilung.bezuege(
        [_einheit("EG", 60), _einheit("OG", 90),
         _einheit("Laden", 50, nk_abrechnung=False)],
        [_miete("EG", "Alpha"), _miete("OG", "Beta"),
         _miete("Laden", "Gamma")], [], START, ENDE)
    anteile = verteilung.gewichte("flaeche", b, START, ENDE)
    res = abrechnung([Position("Wasser", 300.0, "flaeche", anteile, False)], {})
    kosten = {p: res["parteien"][p]["kosten"] for p in res["parteien"]}
    assert kosten == {"Alpha": 120.0, "Beta": 180.0}
    assert "Gamma" not in kosten
    assert round(sum(kosten.values()), 2) == 300.0, "die Summe geht exakt auf"


# ---------------------------------------------- CXCIV: Sonderposten je Einheit

def test_nur_einheit_gewicht_geht_ganz_an_die_partei():
    """Fund CXCIV: ein Sonderposten geht zu 100 % auf eine Einheit — ihre
    Partei trägt ihn allein, kein Pseudo-Name."""
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("EG", "Alpha"), _miete("OG", "Beta")],
                           [], START, ENDE)
    assert verteilung.nur_einheit_gewichte(b, "OG", START, ENDE) == {"Beta": 1.0}
    assert verteilung.nur_einheit_gewichte(b, "EG", START, ENDE) == {"Alpha": 1.0}


def test_nur_einheit_teilt_beim_mieterwechsel_nach_dauer():
    """Bei einem Mieterwechsel in der Einheit teilen Vor- und Nachmieter den
    Sonderposten nach Wohndauer — zusammen ergeben sie exakt 1,0."""
    b = _wechsel_im_haus(date(JAHR, 7, 15))
    g = verteilung.nur_einheit_gewichte(b, "EG", START, ENDE)
    assert sorted(g) == ["Nachher", "Vorher"]
    assert "Beta" not in g, "das OG trägt den Posten nicht mit"
    assert round(sum(g.values()), 4) == 1.0
    assert g["Vorher"] > g["Nachher"], "wer länger wohnt, trägt mehr"


def test_nur_einheit_selbstgenutzt_bleibt_beim_eigentuemer():
    """Eine ohne Mietverhältnis geführte Einheit (Eigennutzung) trägt den
    Sonderposten unter ihrem eigenen Namen — er bleibt beim Eigentümer."""
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("OG", "Beta")], [], START, ENDE)
    assert verteilung.nur_einheit_gewichte(b, "EG", START, ENDE) == {"EG": 1.0}


def test_einzelwohnung_ohne_einheitenzuordnung_bleibt_eine_partei():
    """Ein Mietverhältnis ohne gewählte Einheit gehört bei genau einer Einheit
    zu dieser — sonst stünde die Wohnung zweimal in der Verteilung."""
    b = verteilung.bezuege([_einheit("1. OG", 95)],
                           [_miete("", "Mieter Meier")], [], START, ENDE)
    assert verteilung.gewichte("flaeche", b, START, ENDE) == {"Mieter Meier": 95}
    assert verteilung.ohne_einheit(b) == [], "eindeutig zugeordnet"


def _schluessel(bezuege_, wert: str) -> dict:
    return next(s for s in verteilung.vorschau(bezuege_, START, ENDE)
                if s["wert"] == wert)


def test_partei_ohne_zuordenbare_einheit_wird_gemeldet():
    """Fund XCII: bei zwei Einheiten bleibt ein Mietverhältnis ohne Einheit
    ohne Fläche — die Partei fiel stumm aus der Flächenverteilung, bekam keine
    Kosten und ihre Vorauszahlung voll erstattet."""
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("", "Mieter Ohne")], [], START, ENDE)
    assert verteilung.ohne_einheit(b) == ["Mieter Ohne"]
    assert "Mieter Ohne" not in verteilung.gewichte("flaeche", b, START, ENDE)

    flaeche = _schluessel(b, "flaeche")
    assert flaeche["parteien_ohne_einheit"] == ["Mieter Ohne"]
    assert flaeche["moeglich"] is False
    assert flaeche["ableitbar"] is False

    # Personen trifft es nicht — dort ist die Partei mit dabei.
    personen = _schluessel(b, "personen")
    assert personen["parteien_ohne_einheit"] == []
    assert personen["moeglich"] is True


def test_abweichende_schreibweise_der_einheit_wird_gemeldet():
    """`Miete.einheit` ist Freitext: „eg" trifft die Einheit „EG" nicht."""
    b = verteilung.bezuege(
        [_einheit("EG", 60), _einheit("OG", 90)],
        [_miete("eg", "Mieter Klein"), _miete("OG", "Beta")], [], START, ENDE)
    assert verteilung.ohne_einheit(b) == ["Mieter Klein"]
    assert _schluessel(b, "flaeche")["parteien_ohne_einheit"] == ["Mieter Klein"]


def test_saubere_zuordnung_meldet_keine_fehlzuordnung():
    b = verteilung.bezuege([_einheit("EG", 60), _einheit("OG", 90)],
                           [_miete("EG", "Alpha"), _miete("OG", "Beta")],
                           [], START, ENDE)
    assert verteilung.ohne_einheit(b) == []
    for wert in verteilung.SCHLUESSEL:
        assert _schluessel(b, wert)["parteien_ohne_einheit"] == []
    assert _schluessel(b, "flaeche")["moeglich"] is True


# ------------------------------------------------------------------ Endpunkte

def _objekt_mit_zwei_wohnungen(c) -> tuple[str, int]:
    """Zwei Wohnungen, zwei Mieter mit Mailadresse, Vorauszahlungen.

    Die Partei-Namen kommen aus dem Mietverhältnis — genau wie beim Versand."""
    slug = c.post("/api/objekte", json={
        "name": "Verteilweg 3", "ort": "Prüfstadt",
        "kostenarten": ["Strom", "Wasser"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 60},
                      {"bezeichnung": "OG", "flaeche": 90}]}).json()["slug"]
    for einheit, partei, personen in [("EG", "Mieter Alpha", 1),
                                      ("OG", "Mieter Beta", 3)]:
        antwort = c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": einheit, "partei": partei, "personen": personen,
            "kaltmiete": 500.0, "email": f"{partei.split()[1].lower()}@example.org",
            "ab_datum": f"{JAHR}-01-01"})
        assert antwort.status_code == 201, antwort.text
    zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
    with Session(db_engine) as s:
        from app.models import Vorauszahlung
        s.add(Vorauszahlung(zeitraum_id=zid, partei="Mieter Alpha", betrag=300.0))
        s.add(Vorauszahlung(zeitraum_id=zid, partei="Mieter Beta", betrag=300.0))
        s.commit()
    return slug, zid


def test_kernfall_position_mit_flaeche_ergibt_echte_betraege():
    """Der Fund LXV: ohne Gewichte blieb hier alles 0,00 €."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        neu = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 500.0, "schluessel": "flaeche"})
        assert neu.status_code == 201, neu.text
        assert neu.json()["abgeleitet"] is True
        assert neu.json()["anteile"] == {"Mieter Alpha": 60, "Mieter Beta": 90}

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["gesamt"]["auslagen"] == 500.0
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 200.0
        assert a["parteien"]["Mieter Beta"]["kosten"] == 300.0
        # Invariante: die Summe der Anteile ist exakt die Gesamtsumme
        assert round(sum(p["kosten"] for p in a["parteien"].values()), 2) == 500.0
        # und die Vorauszahlungen treffen dieselben Parteien
        assert a["parteien"]["Mieter Alpha"]["saldo"] == 100.0


def _dritte_einheit_mit_mieter(c, slug: str, bezeichnung: str,
                               partei: str, flaeche: float) -> int:
    """Legt eine weitere Einheit samt Mieter an und gibt ihre id zurück."""
    eid = c.post(f"/api/objekte/{slug}/einheiten",
                 json={"bezeichnung": bezeichnung, "flaeche": flaeche}).json()["id"]
    antwort = c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": bezeichnung, "partei": partei, "personen": 1,
        "kaltmiete": 800.0, "email": "gewerbe@example.org",
        "ab_datum": f"{JAHR}-01-01"})
    assert antwort.status_code == 201, antwort.text
    return eid


def test_endpunkt_ausschluss_haelt_die_summe():
    """CXCIII über die API: eine dritte Einheit „Laden" wird ausgeschlossen.
    300 € Wasser nach Fläche verteilen sich exakt auf EG (60) und OG (90) —
    120 € und 180 € —, der Ladenmieter taucht in der Abrechnung nicht auf."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        eid = _dritte_einheit_mit_mieter(c, slug, "Laden", "Mieter Gamma", 50)
        aus = c.patch(f"/api/einheiten/{eid}", json={"nk_abrechnung": False})
        assert aus.status_code == 200, aus.text

        pos = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 300.0, "schluessel": "flaeche"})
        assert pos.status_code == 201, pos.text
        assert pos.json()["anteile"] == {"Mieter Alpha": 60, "Mieter Beta": 90}

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        parteien = a["parteien"]
        assert "Mieter Gamma" not in parteien, "der Laden wird separat abgerechnet"
        assert parteien["Mieter Alpha"]["kosten"] == 120.0
        assert parteien["Mieter Beta"]["kosten"] == 180.0
        assert round(sum(p["kosten"] for p in parteien.values()), 2) == 300.0


def test_endpunkt_sonderposten_geht_ganz_auf_eine_einheit():
    """CXCIV über die API: ein Sonderposten „Reparatur" nur für das OG geht zu
    100 % auf dessen Mieter — der Schlüssel spielt keine Rolle."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        pos = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Reparatur OG", "betrag": 200.0,
            "nur_einheit": "OG"})
        assert pos.status_code == 201, pos.text
        assert pos.json()["nur_einheit"] == "OG"
        assert pos.json()["anteile"] == {"Mieter Beta": 1.0}

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["parteien"]["Mieter Beta"]["kosten"] == 200.0
        # Der EG-Mieter trägt vom Sonderposten nichts — er kommt in dieser
        # einen Position gar nicht vor.
        assert "Mieter Alpha" not in a["parteien"]
        assert round(sum(p["kosten"] for p in a["parteien"].values()), 2) == 200.0

        # In der Checkliste ist die Einheit sichtbar hinterlegt.
        zeile = next(k for k in c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
                     if k["kostenart"] == "Reparatur OG")
        assert zeile["nur_einheit"] == "OG"


def test_sonderposten_laesst_sich_zum_normalen_posten_zuruecknehmen():
    """Wird die Einheit eines Sonderpostens geleert, verteilt er sich wieder
    über den Schlüssel auf alle Parteien."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 300.0,
            "nur_einheit": "EG"}).json()["id"]
        assert c.get(f"/api/zeitraeume/{zid}/abrechnung").json()[
            "parteien"]["Mieter Alpha"]["kosten"] == 300.0

        geaendert = c.patch(f"/api/positionen/{pid}",
                            json={"nur_einheit": "", "schluessel": "flaeche"})
        assert geaendert.status_code == 200, geaendert.text
        assert geaendert.json()["nur_einheit"] == ""
        assert geaendert.json()["anteile"] == {"Mieter Alpha": 60,
                                               "Mieter Beta": 90}
        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 120.0
        assert a["parteien"]["Mieter Beta"]["kosten"] == 180.0


def test_erledigte_position_ohne_gewichte_wird_gemeldet():
    """Der belegte Fall: „Strom" über 500 € mit leeren Anteilen — der Betrag
    verschwand lautlos aus der Abrechnung."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        with Session(db_engine) as s:
            s.add(Kostenposition(zeitraum_id=zid, kostenart="Strom", betrag=500.0,
                                 schluessel="verbrauch", status="erledigt",
                                 anteile={}))
            s.commit()

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["gesamt"]["auslagen"] == 0
        assert "Strom" in a["ohne_verteilung"]
        assert "Strom" in a["offen"], "der Abschluss würde die Position übergehen"

        zeile = next(k for k in c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
                     if k["kostenart"] == "Strom")
        assert zeile["ohne_verteilung"] is True

        blockiert = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                           json={"versenden": False})
        assert blockiert.status_code == 400
        assert "Strom" in blockiert.json()["detail"]


def test_schluessel_vorschau_zeigt_gewichte_und_fehlzuordnung():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        v = c.get(f"/api/zeitraeume/{zid}/schluessel").json()
        nach_wert = {s["wert"]: s for s in v["schluessel"]}
        assert nach_wert["flaeche"]["gewichte"] == {"Mieter Alpha": 60,
                                                    "Mieter Beta": 90}
        assert nach_wert["flaeche"]["prozent"]["Mieter Alpha"] == 40.0
        assert nach_wert["flaeche"]["einheit"] == "m²"
        assert nach_wert["personen"]["gewichte"] == {"Mieter Alpha": 1,
                                                     "Mieter Beta": 3}
        assert nach_wert["verbrauch"]["moeglich"] is False
        assert nach_wert["flaeche"]["parteien_ohne_einheit"] == []
        assert v["unbekannte_vorauszahlungen"] == []


def test_vorauszahlung_auf_unbekannten_namen_wird_aufgedeckt():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        with Session(db_engine) as s:
            from app.models import Vorauszahlung
            s.add(Vorauszahlung(zeitraum_id=zid, partei="Frau Gamma", betrag=99.0))
            s.commit()
        v = c.get(f"/api/zeitraeume/{zid}/schluessel").json()
        assert v["unbekannte_vorauszahlungen"] == ["Frau Gamma"]


def test_schluesselwechsel_leitet_die_gewichte_neu_ab():
    """Alte Flächen-Gewichte unter „Personen" stehen zu lassen wäre die
    unauffälligste Art, falsch abzurechnen."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 400.0,
            "schluessel": "flaeche"}).json()["id"]
        geaendert = c.patch(f"/api/positionen/{pid}",
                            json={"schluessel": "personen"}).json()
        assert geaendert["anteile"] == {"Mieter Alpha": 1, "Mieter Beta": 3}
        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 100.0


def test_einzelnes_gewicht_laesst_sich_ueberschreiben():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 300.0,
            "schluessel": "verbrauch",
            "anteile": {"Mieter Alpha": 2, "Mieter Beta": 1}}).json()["id"]
        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 200.0

        c.patch(f"/api/positionen/{pid}",
                json={"anteile": {"Mieter Alpha": 1, "Mieter Beta": 1}})
        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 150.0


def test_position_zweimal_anlegen_wird_abgelehnt():
    """CLXXXII: eine Kostenart, eine Zeile — sonst stünde „Wasser" zweimal in
    der Abrechnung und niemand wüsste, welche der beiden gilt.

    Dass trotzdem vier Abschlagsrechnungen auf dieselbe Zeile laufen, löst der
    Weg über den Beleg (`POST /api/dokumente/{id}/position`): dort addiert sich
    der Betrag in die vorhandene Position hinein. Die Abweisung sagt das auch,
    statt den Nutzer vor einer Sackgasse stehen zu lassen."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        c.post(f"/api/zeitraeume/{zid}/positionen", json={"kostenart": "Wasser"})
        zweite = c.post(f"/api/zeitraeume/{zid}/positionen",
                        json={"kostenart": "Wasser"})
        assert zweite.status_code == 409
        assert "Beleg" in zweite.json()["detail"]


def test_aus_belegen_gewachsene_position_verteilt_exakt():
    """Die Invariante gilt auch für eine Summe aus mehreren Belegen: die
    Anteile ergeben zusammen wieder exakt den Gesamtbetrag."""
    from app import belegposten
    from app.models import Dokument, Zeitraum

    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        with Session(db_engine) as s:
            objekt_id = s.get(Zeitraum, zid).objekt_id
            for i, betrag in enumerate([333.33, 333.33, 333.34], 1):
                d = Dokument(pfad=f"/x/{slug}/abschlag{i}.pdf",
                             dateiname=f"abschlag{i}.pdf", objekt_id=objekt_id,
                             kategorie="Nebenkosten", kostenart="Wasser",
                             betrag=betrag, zeitraum_id=zid,
                             belegdatum=date(JAHR, i, 1), status="zugeordnet")
                s.add(d)
                s.commit()
                s.refresh(d)
                belegposten.verbuche(s, d)
                s.commit()

        zeile = next(k for k in c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
                     if k["kostenart"] == "Wasser")
        assert zeile["betrag"] == 1000.0
        assert zeile["beleg_summe"] == 1000.0
        assert len(zeile["belege"]) == 3

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        assert a["gesamt"]["auslagen"] == 1000.0
        assert round(sum(p["kosten"] for p in a["parteien"].values()), 2) == 1000.0
        assert a["parteien"]["Mieter Alpha"]["kosten"] == 400.0


def test_position_loeschen_laesst_die_kostenart_stehen():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 100.0}).json()["id"]
        assert c.delete(f"/api/positionen/{pid}").status_code == 200
        zeile = next(k for k in c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
                     if k["kostenart"] == "Wasser")
        assert zeile["zustand"] == "fehlt"
        assert c.delete(f"/api/positionen/{pid}").status_code == 404


def test_unbekannter_schluessel_ueber_die_api():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        antwort = c.post(f"/api/zeitraeume/{zid}/positionen",
                         json={"kostenart": "Wasser", "schluessel": "mondphase"})
        assert antwort.status_code == 400


def test_unbekannter_schluessel_beim_aendern_wird_abgelehnt():
    """Beim Umstellen gilt derselbe Riegel wie beim Anlegen — sonst stünde in
    der Position ein Schlüssel, zu dem es keine Ableitung gibt, und die alten
    Gewichte blieben unter falschem Namen stehen."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        pid = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 400.0,
            "schluessel": "flaeche"}).json()["id"]

        antwort = c.patch(f"/api/positionen/{pid}", json={"schluessel": "mondphase"})
        assert antwort.status_code == 400
        assert "mondphase" in antwort.json()["detail"]

        zeile = next(k for k in c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
                     if k["kostenart"] == "Wasser")
        assert zeile["schluessel"] == "flaeche", "der alte Schlüssel bleibt stehen"


def test_geld_beim_mieterwechsel_trifft_die_richtige_wohnung():
    """Fund XCI am Geld: 500 € Wasser, EG 60 m² mit Wechsel, OG 90 m².
    Das OG trägt 60 % = 300 €, die beiden EG-Parteien zusammen 200 €.
    Vorher waren es 214,29 € für das OG — und dieselbe Zahl auch dann, wenn
    der Wechsel erst am 21.12. stattfand."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        # Der EG-Mieter zieht zur Jahresmitte aus, ein neuer kommt nach.
        mieten = c.get(f"/api/objekte/{slug}/mieten").json()
        eg = next(m for m in mieten if m["einheit"] == "EG")
        c.patch(f"/api/stammdaten/mieten/{eg['id']}",
                json={"bis_datum": f"{JAHR}-06-30"})
        neu = c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter Gamma", "personen": 1,
            "kaltmiete": 500.0, "email": "gamma@example.org",
            "ab_datum": f"{JAHR}-07-01"})
        assert neu.status_code == 201, neu.text

        pos = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 500.0, "schluessel": "flaeche"})
        assert pos.status_code == 201, pos.text

        a = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()
        parteien = a["parteien"]
        assert parteien["Mieter Beta"]["kosten"] == 300.0
        assert round(parteien["Mieter Alpha"]["kosten"]
                     + parteien["Mieter Gamma"]["kosten"], 2) == 200.0
        # Invariante: die Summe der Anteile ist exakt die Gesamtsumme
        assert round(sum(p["kosten"] for p in parteien.values()), 2) == 500.0


def test_geld_beim_leerstand_bleibt_beim_eigentuemer():
    """Fund CXXI am Geld: 500 € Wasser, EG 60 m² nur bis 30.06. vermietet,
    OG 90 m² durchgehend. Das OG trägt seine 60 % = 300,00 € — vorher waren es
    375,77 €, weil die leere Hälfte des EG auf die Mieter umgelegt wurde.
    Der Leerstand steht als eigene Zeile unter dem Namen der Einheit und
    bekommt keine Mail, weil dort kein Mietverhältnis mit Adresse hängt."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        mieten = c.get(f"/api/objekte/{slug}/mieten").json()
        eg = next(m for m in mieten if m["einheit"] == "EG")
        c.patch(f"/api/stammdaten/mieten/{eg['id']}",
                json={"bis_datum": f"{JAHR}-06-30"})

        pos = c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 500.0, "schluessel": "flaeche"})
        assert pos.status_code == 201, pos.text

        parteien = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()["parteien"]
        assert parteien["Mieter Beta"]["kosten"] == 300.00
        assert round(parteien["Mieter Alpha"]["kosten"]
                     + parteien["EG"]["kosten"], 2) == 200.0
        assert parteien["Mieter Alpha"]["kosten"] < 100.0, "nur ein halbes Jahr"
        # Invariante: die Summe der Anteile ist exakt die Gesamtsumme
        assert round(sum(p["kosten"] for p in parteien.values()), 2) == 500.0

        versand = c.get(f"/api/zeitraeume/{zid}/versand").json()
        leer = next(r for r in versand["parteien"] if r["partei"] == "EG")
        assert leer["versandbereit"] is False, "Leerstand bekommt keine Post"


def test_leerstand_bekommt_keine_mail(postfach):
    """Der Leerstand darf im Versand nicht als Empfänger auftauchen — es gibt
    niemanden, an den die Abrechnung ginge."""
    with TestClient(app) as c:
        slug, zid = _objekt_mit_zwei_wohnungen(c)
        mieten = c.get(f"/api/objekte/{slug}/mieten").json()
        eg = next(m for m in mieten if m["einheit"] == "EG")
        # EG zieht zur Jahresmitte aus und hinterlässt keine erreichbare
        # Adresse — ein echter Leerstand ohne Empfänger. (Ein ausgezogener
        # Mieter MIT Mail bekommt seine Abrechnung sehr wohl, siehe CCX.)
        c.patch(f"/api/stammdaten/mieten/{eg['id']}",
                json={"bis_datum": f"{JAHR}-06-30", "email": ""})
        c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 500.0, "schluessel": "flaeche"})

        fertig = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                        json={"versenden": True, "offene_uebergehen": True})
        assert fertig.status_code == 200, fertig.text
        assert "EG" in fertig.json()["ohne_mail"]
        assert postfach.gesendet == ["beta@example.org"], \
            "nur der laufende Mieter, nicht der ausgezogene und nicht der Leerstand"


# ------------------------------------------------------- Wieder öffnen (LXVI)

class Postfach:
    """Notiert statt zu senden."""

    def __init__(self):
        self.gesendet: list[str] = []
        self.absender_name = "Prüfstand"

    def sende(self, an, betreff, text, anhang=None):
        if an == "fehler@example.org":
            raise MailFehler("Prüfstand")
        self.gesendet.append(an)


@pytest.fixture
def postfach(monkeypatch):
    kasten = Postfach()
    monkeypatch.setattr(versand_router, "zugang", lambda session: kasten)
    return kasten


def test_zeitraum_laesst_sich_wieder_oeffnen_ohne_zweiten_versand(postfach):
    """Ein versehentlicher Abschluss war unumkehrbar. Beim Öffnen bleibt das
    Versandprotokoll stehen — wer die Abrechnung hat, bekommt sie nicht noch
    einmal."""
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Wasser", "betrag": 500.0, "schluessel": "flaeche"})

        erst = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                      json={"versenden": True, "offene_uebergehen": True})
        assert erst.status_code == 200, erst.text
        assert len(postfach.gesendet) == 2

        auf = c.post(f"/api/zeitraeume/{zid}/oeffnen")
        assert auf.status_code == 200
        assert auf.json()["status"] == "in Arbeit"
        assert auf.json()["bereits_versendet"] == ["Mieter Alpha", "Mieter Beta"]
        assert c.get(f"/api/zeitraeume/{zid}").json()["status"] == "in Arbeit"

        # Korrigieren und erneut abschliessen: niemand bekommt eine zweite Mail
        zweit = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                       json={"versenden": True, "offene_uebergehen": True})
        assert zweit.status_code == 200, zweit.text
        assert sorted(zweit.json()["schon_versendet"]) == ["Mieter Alpha",
                                                           "Mieter Beta"]
        assert len(postfach.gesendet) == 2, "zweiter Versand ist durchgerutscht"


def test_oeffnen_eines_offenen_zeitraums_aendert_nichts():
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        antwort = c.post(f"/api/zeitraeume/{zid}/oeffnen")
        assert antwort.status_code == 200
        assert antwort.json()["geaendert"] is False


def test_oeffnen_unbekannter_zeitraum():
    with TestClient(app) as c:
        assert c.post("/api/zeitraeume/999999/oeffnen").status_code == 404
