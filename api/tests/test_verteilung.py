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

def _einheit(bezeichnung: str, flaeche=None, terrasse=None, nebenflaeche=None):
    return Einheit(objekt_id=1, bezeichnung=bezeichnung, flaeche=flaeche,
                   terrasse=terrasse, nebenflaeche=nebenflaeche)


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
    with TestClient(app) as c:
        _, zid = _objekt_mit_zwei_wohnungen(c)
        c.post(f"/api/zeitraeume/{zid}/positionen", json={"kostenart": "Wasser"})
        zweite = c.post(f"/api/zeitraeume/{zid}/positionen",
                        json={"kostenart": "Wasser"})
        assert zweite.status_code == 409


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
