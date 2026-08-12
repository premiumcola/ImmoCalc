"""N273 — WEG-Modus: die fertige Einzelabrechnung der Messfirma übernehmen.

Prüfsteine sind die Zahlen des echten Belegs (Delta-t Messdienst Wenzel GmbH,
Liegenschaft Unterschöllenbacher Hauptstr. 6a, Nutzer-Nr. 0004-001,
01.01.2025–31.12.2025):

    Heizkosten            730,60
    Warmwasserkosten      205,67
    Betriebskosten      2.008,28
    ------------------------------
    Rechnungsbetrag     2.944,55
    Vorauszahlung      −2.928,00
    Nachzahlung            16,55

Die wichtigste fachliche Regel steht in `test_nicht_umlagefaehige_werden_nie_
kostenposition`: der Block „Nicht umlagefähig" (Anschaffungen 22,54 · Reparatur
27,13 · Schädlingsbekämpfung 164,22) gehört der Eigentümergemeinschaft und darf
den Mieter nie erreichen.

Aus dem Papier stammen die fünf im Auftrag genannten Zeilen (Wasser 103,24 ·
Müll 138,18 · Versicherungen 442,18 · Verwalter 205,63 · Rauchwarnmelder 4,17);
die übrigen sieben sind so gesetzt, dass die Summe exakt die 2.008,28 des
Deckblatts trifft — der Maßstab bleibt damit die echte Deckblattsumme.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_weg.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db, kiauslese, ocr, weg  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Einheit, Kostenposition, Miete, Objekt,  # noqa: E402
                        WegVorauszahlung, Zeitraum)

EINHEIT = "Wohnung 6a"
PARTEI = "Mieter 6a"

# --------------------------------------------------------------------------
# Der Beleg, wie ihn die Auslese liefert.
# --------------------------------------------------------------------------
UMLAGEFAEHIG = [
    ("Wasserkosten", 788.80, 103.24, "Wasser gesamt"),
    ("Abwasserkosten", 1806.00, 236.58, "Wasser gesamt"),
    ("Niederschlagswasser", 1083.20, 141.89, "m2 Betriebsk."),
    ("Müllgebühren", 690.78, 138.18, "Personen"),
    ("Versicherungen", 1824.55, 442.18, "m2 Betriebsk."),
    ("Hausmeister", 1633.99, 396.00, "m2 Betriebsk."),
    ("Verwalter", 1028.16, 205.63, "Anzahl WE"),
    ("Bankspesen", 63.00, 12.60, "Anzahl WE"),
    ("Abrechn. Kaltwasserzähler", 107.25, 21.45, "Anzahl WE"),
    ("Miete Kaltwasserzähler", 91.80, 18.36, "Anzahl WE"),
    ("Prüfung Rauchwarnmelder", 20.83, 4.17, "Anzahl RWM"),
    ("1&1 Gebühren", 1440.00, 288.00, "Anzahl WE"),
]
NICHT_UMLAGEFAEHIG = [
    ("Anschaffungen", 112.69, 22.54),
    ("Reparatur", 135.66, 27.13),
    ("Schädlingsbekämpfung", 821.10, 164.22),
]

HEIZKOSTEN = 730.60
WARMWASSER = 205.67
BETRIEBSKOSTEN = 2008.28
RECHNUNGSBETRAG = 2944.55
VORAUSZAHLUNG = 2928.00
NACHZAHLUNG = 16.55


def _beleg() -> dict:
    """Das Leseergebnis des echten Belegs — frisch je Test, damit kein Test die
    Vorlage eines anderen verändert."""
    positionen = [{"bezeichnung": b, "gesamtkosten": g, "ihre_kosten": i,
                   "schluessel": s, "umlagefaehig": True}
                  for b, g, i, s in UMLAGEFAEHIG]
    positionen += [{"bezeichnung": b, "gesamtkosten": g, "ihre_kosten": i,
                    "schluessel": "", "umlagefaehig": False}
                   for b, g, i in NICHT_UMLAGEFAEHIG]
    return {
        "firma": "Delta-t Messdienst Wenzel GmbH",
        "liegenschaft": "Unterschöllenbacher Hauptstr. 6a",
        "nutzer_nr": "0004-001",
        "von": "2025-01-01", "bis": "2025-12-31", "datum": "2026-03-16",
        "positionen": positionen,
        "heizkosten": HEIZKOSTEN, "warmwasserkosten": WARMWASSER,
        "betriebskosten": BETRIEBSKOSTEN, "rechnungsbetrag": RECHNUNGSBETRAG,
        "vorauszahlung": VORAUSZAHLUNG, "nachzahlung": NACHZAHLUNG,
        "warnung": "",
    }


# --------------------------------------------------------------------------
# Aufbau: ein Objekt mit genau einer Einheit — der WEG-Regelfall.
# --------------------------------------------------------------------------
def _objekt_id() -> int:
    with Session(db.engine) as s:
        vorhanden = s.exec(select(Objekt).where(Objekt.slug == "weg-6a")).first()
        if vorhanden:
            return vorhanden.id
        o = Objekt(slug="weg-6a", name="Unterschöllenbacher Hauptstr. 6a",
                   start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        s.add(Einheit(objekt_id=o.id, bezeichnung=EINHEIT, flaeche=99.0))
        s.add(Miete(objekt_id=o.id, einheit=EINHEIT, partei=PARTEI,
                    ab_datum=date(2020, 1, 1)))
        s.commit()
        return o.id


def _zeitraum(jahr: int) -> int:
    """Ein eigener Zeitraum je Test — die Modul-Datenbank ist geteilt."""
    oid = _objekt_id()
    with Session(db.engine) as s:
        z = Zeitraum(objekt_id=oid, start=date(jahr, 1, 1), ende=date(jahr, 12, 31),
                     typ="regulär", status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        return z.id


def _positionen(zid: int) -> list[Kostenposition]:
    with Session(db.engine) as s:
        return list(s.exec(select(Kostenposition)
                           .where(Kostenposition.zeitraum_id == zid)).all())


def _uebernehmen(zid: int, beleg: dict | None = None) -> dict:
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        return weg.uebernehmen(s, z, beleg or _beleg(), einheit=EINHEIT)


def _stand(zid: int) -> dict:
    with Session(db.engine) as s:
        return weg.stand(s, s.get(Zeitraum, zid))


# --------------------------------------------------------------------------
# 1) Der Beleg selbst
# --------------------------------------------------------------------------
def test_beleg_hat_zwoelf_umlagefaehige_und_drei_nicht():
    beleg = _beleg()
    assert len(weg.umlagefaehige(beleg)) == 12 + 2   # + Heizung + Warmwasser
    assert len([p for p in beleg["positionen"] if p["umlagefaehig"]]) == 12
    assert len(weg.nicht_umlagefaehige(beleg)) == 3


def test_summe_der_umlagefaehigen_trifft_das_deckblatt():
    """Die Spalte „Ihre Kosten" der Betriebskosten muss die 2.008,28 des
    Deckblatts ergeben — wer stattdessen die Gesamtkosten der Liegenschaft
    liest, landet bei 9.686,49 und damit um ein Vielfaches daneben."""
    summe = round(sum(i for _b, _g, i, _s in UMLAGEFAEHIG), 2)
    assert abs(summe - BETRIEBSKOSTEN) <= BETRIEBSKOSTEN * 0.01
    assert summe == BETRIEBSKOSTEN


# --------------------------------------------------------------------------
# 2) Übernahme
# --------------------------------------------------------------------------
def test_uebernahme_legt_alle_umlagefaehigen_positionen_an():
    zid = _zeitraum(2031)
    stand = _uebernehmen(zid)
    # 12 Betriebskostenzeilen + Heizkosten + Warmwasser
    assert len(stand["positionen"]) == 14
    assert stand["umlagefaehig_summe"] == RECHNUNGSBETRAG
    namen = {p["kostenart"] for p in stand["positionen"]}
    assert weg.HEIZKOSTEN in namen and weg.WARMWASSER in namen
    # Alle tragen die Marke, damit die Oberfläche sie als fremd erkennt.
    assert all(p["wertquelle"] == weg.QUELLE for p in stand["positionen"])
    # Und sie gehen zu 100 % auf die eine Wohnung.
    for p in _positionen(zid):
        assert p.nur_einheit == EINHEIT
        assert p.anteile == {PARTEI: 1.0}


def test_nicht_umlagefaehige_werden_nie_kostenposition():
    """Die wichtigste Regel: Anschaffungen (22,54), Reparatur (27,13) und
    Schädlingsbekämpfung (164,22) trägt die Eigentümergemeinschaft."""
    zid = _zeitraum(2032)
    stand = _uebernehmen(zid)
    namen = {p.kostenart for p in _positionen(zid)}
    betraege = {round(p.betrag, 2) for p in _positionen(zid)}
    for bezeichnung, _gesamt, ihre in NICHT_UMLAGEFAEHIG:
        assert bezeichnung not in namen
        assert ihre not in betraege
    # Sichtbar bleiben sie trotzdem — nur eben als Information.
    assert stand["nicht_umlagefaehig_summe"] == 213.89
    assert {p["kostenart"] for p in stand["nicht_umlagefaehig"]} == {
        b for b, _g, _i in NICHT_UMLAGEFAEHIG}
    # Und sie zählen nirgends in die Summe, die der Mieter trägt.
    assert stand["umlagefaehig_summe"] == RECHNUNGSBETRAG


def test_zweimal_uebernehmen_verdoppelt_nichts():
    zid = _zeitraum(2033)
    erst = _uebernehmen(zid)
    zweit = _uebernehmen(zid)
    assert len(erst["positionen"]) == len(zweit["positionen"]) == 14
    assert zweit["umlagefaehig_summe"] == RECHNUNGSBETRAG
    # Dieselben Zeilen, nicht neu angelegte: die ids bleiben.
    assert ([p["id"] for p in erst["positionen"]]
            == [p["id"] for p in zweit["positionen"]])


def test_handgepflegte_position_ueberlebt_die_uebernahme():
    """Eine Übernahme fasst nur ihre eigenen WEG-Zeilen an."""
    zid = _zeitraum(2034)
    with Session(db.engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Gartenpflege",
                             betrag=180.0, schluessel="individuell",
                             wertquelle="manuell", status="erledigt",
                             anteile={PARTEI: 1.0}))
        s.commit()
    _uebernehmen(zid)
    _uebernehmen(zid)
    hand = [p for p in _positionen(zid) if p.kostenart == "Gartenpflege"]
    assert len(hand) == 1
    assert hand[0].betrag == 180.0
    assert hand[0].wertquelle == "manuell"


def test_handeingabe_gewinnt_gegen_gleichnamige_weg_zeile():
    """Eine Kostenart, eine Zeile — sonst stünde derselbe Posten zweimal in
    der Abrechnung. Der Nutzer erfährt das über `uebersprungen`."""
    zid = _zeitraum(2035)
    with Session(db.engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Verwalter",
                             betrag=199.0, schluessel="individuell",
                             wertquelle="manuell", status="erledigt",
                             anteile={PARTEI: 1.0}))
        s.commit()
    stand = _uebernehmen(zid)
    assert stand["uebersprungen"] == ["Verwalter"]
    verwalter = [p for p in _positionen(zid) if p.kostenart == "Verwalter"]
    assert len(verwalter) == 1
    assert verwalter[0].betrag == 199.0


def test_entfallene_weg_zeile_verschwindet_beim_zweiten_lauf():
    zid = _zeitraum(2036)
    _uebernehmen(zid)
    schmaler = _beleg()
    schmaler["positionen"] = [p for p in schmaler["positionen"]
                              if p["bezeichnung"] != "Bankspesen"]
    stand = _uebernehmen(zid, schmaler)
    assert stand["entfernt"] == ["Bankspesen"]
    assert "Bankspesen" not in {p["kostenart"] for p in stand["positionen"]}


# --------------------------------------------------------------------------
# N315(a) — zwei Einheiten derselben WEG im selben Zeitraum
# --------------------------------------------------------------------------

def _zweite_einheit(oid: int, bezeichnung: str) -> None:
    with Session(db.engine) as s:
        vorhanden = s.exec(select(Einheit).where(
            Einheit.objekt_id == oid, Einheit.bezeichnung == bezeichnung)).first()
        if not vorhanden:
            s.add(Einheit(objekt_id=oid, bezeichnung=bezeichnung, flaeche=60.0))
            s.commit()


def test_zweite_einheit_ueberschreibt_nicht_die_zeilen_der_ersten():
    """Beide Wohnungen einer WEG haben eine Zeile "Hausmeister". Vor dem Fix
    schlüsselte `weg_alt` nur nach Kostenart — die zweite Übernahme fand die
    Zeile der ersten Wohnung wieder und schrieb ihren Betrag und ihre
    `nur_einheit` einfach um, statt eine eigene Zeile anzulegen. Die erste
    Wohnung verlor ihre 396,00 € ersatzlos."""
    zid = _zeitraum(2038)
    oid = _objekt_id()
    _zweite_einheit(oid, "Wohnung 6b")

    _uebernehmen(zid)                                  # Wohnung 6a, Regelbeleg

    beleg_b = _beleg()
    for p in beleg_b["positionen"]:
        if p["bezeichnung"] == "Hausmeister":
            p["ihre_kosten"] = 308.87
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        stand_b = weg.uebernehmen(s, z, beleg_b, einheit="Wohnung 6b")

    hausmeister = [p for p in stand_b["positionen"]
                  if p["kostenart"] == "Hausmeister"]
    assert len(hausmeister) == 2
    a = next(p for p in hausmeister if p["nur_einheit"] == EINHEIT)
    b = next(p for p in hausmeister if p["nur_einheit"] == "Wohnung 6b")
    assert a["betrag"] == 396.00                        # Wohnung 6a unangetastet
    assert b["betrag"] == 308.87


# --------------------------------------------------------------------------
# 3) Vorauszahlung und Saldo
# --------------------------------------------------------------------------
def test_saldo_ist_die_nachzahlung_des_belegs():
    """2.928,00 vorausgezahlt gegen 2.944,55 Rechnungsbetrag = 16,55
    Nachzahlung. Negativ = Nachzahlung, genau wie auf dem Beleg."""
    zid = _zeitraum(2037)
    _uebernehmen(zid)
    with Session(db.engine) as s:
        s.add(WegVorauszahlung(zeitraum_id=zid, einheit=EINHEIT,
                               betrag_monat=244.0))
        s.commit()
    stand = _stand(zid)
    assert stand["vorauszahlung_summe"] == VORAUSZAHLUNG
    assert stand["umlagefaehig_summe"] == RECHNUNGSBETRAG
    assert stand["saldo"] == -NACHZAHLUNG


def test_gestueckelte_vorauszahlung_rechnet_monatsgenau():
    """Ein halbes Jahr kann höher gezahlt worden sein als das andere:
    6 × 220 + 6 × 235 = 2.730."""
    zid = _zeitraum(2038)
    with Session(db.engine) as s:
        s.add(WegVorauszahlung(zeitraum_id=zid, einheit=EINHEIT,
                               von=date(2038, 1, 1), bis=date(2038, 6, 30),
                               betrag_monat=220.0))
        s.add(WegVorauszahlung(zeitraum_id=zid, einheit=EINHEIT,
                               von=date(2038, 7, 1), bis=date(2038, 12, 31),
                               betrag_monat=235.0))
        s.commit()
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        assert weg.vorauszahlung(s, z) == 2730.0
        teile = weg.abschnitte(s, z)
    assert [t["monate"] for t in teile] == [6.0, 6.0]
    assert [t["summe"] for t in teile] == [1320.0, 1410.0]


def test_abschnitt_ohne_grenzen_gilt_fuer_den_ganzen_zeitraum():
    zid = _zeitraum(2039)
    with Session(db.engine) as s:
        s.add(WegVorauszahlung(zeitraum_id=zid, betrag_monat=100.0))
        s.commit()
        assert weg.vorauszahlung(s, s.get(Zeitraum, zid)) == 1200.0


# --------------------------------------------------------------------------
# 4) Ein unstimmiger Beleg wird gemeldet, nicht verworfen
# --------------------------------------------------------------------------
def test_unstimmiger_beleg_setzt_warnung_und_wird_trotzdem_uebernommen():
    """Weicht die Summe der Positionen um mehr als 1 % vom Deckblatt ab, sagt
    das die Warnung — verworfen wird nichts, der Nutzer hat das Papier."""
    roh = _beleg()
    roh["positionen"][0]["ihre_kosten"] = 788.80      # Gesamtkosten verlesen
    gelesen = kiauslese.weg_ergebnis(roh)
    assert "2008.28" in gelesen["warnung"]     # das Deckblatt wird genannt

    zid = _zeitraum(2040)
    stand = _uebernehmen(zid, gelesen)
    assert len(stand["positionen"]) == 14
    assert stand["warnung"] == gelesen["warnung"]


def test_stimmiger_beleg_bleibt_ohne_warnung():
    assert kiauslese.weg_ergebnis(_beleg())["warnung"] == ""


# --------------------------------------------------------------------------
# 5) Additiv: ohne WEG-Modus ändert sich nichts
# --------------------------------------------------------------------------
def test_ohne_weg_modus_bleibt_alles_wie_bisher():
    zid = _zeitraum(2041)
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        assert z.weg_modus is False
        assert z.weg_beleg == {}
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=500.0,
                             schluessel="flaeche", wertquelle="manuell",
                             status="erledigt", anteile={PARTEI: 99.0}))
        s.commit()
    stand = _stand(zid)
    # Der Stand kennt keine WEG-Positionen und rührt die Handeingabe nicht an.
    assert stand["positionen"] == []
    assert stand["umlagefaehig_summe"] == 0.0
    assert stand["nicht_umlagefaehig_summe"] == 0.0
    assert [p.kostenart for p in _positionen(zid)] == ["Wasser"]


# --------------------------------------------------------------------------
# 6) Die Endpunkte
# --------------------------------------------------------------------------
def test_endpunkte_schalten_lesen_uebernehmen_und_vorauszahlen():
    zid = _zeitraum(2042)
    with TestClient(app) as c:
        r = c.get(f"/api/zeitraeume/{zid}/weg")
        assert r.status_code == 200
        assert r.json()["aktiv"] is False

        r = c.patch(f"/api/zeitraeume/{zid}/weg", json={"aktiv": True})
        assert r.status_code == 200 and r.json()["aktiv"] is True

        beleg = _beleg()
        beleg["einheit"] = EINHEIT
        r = c.post(f"/api/zeitraeume/{zid}/weg/uebernehmen", json=beleg)
        assert r.status_code == 200
        stand = r.json()["stand"]
        assert len(stand["positionen"]) == 14
        assert stand["umlagefaehig_summe"] == RECHNUNGSBETRAG
        assert stand["nicht_umlagefaehig_summe"] == 213.89

        r = c.post(f"/api/zeitraeume/{zid}/weg/vorauszahlung",
                   json={"einheit": EINHEIT, "betrag_monat": 244.0})
        assert r.status_code == 201
        vid = r.json()["id"]
        assert r.json()["summe"] == VORAUSZAHLUNG

        assert c.get(f"/api/zeitraeume/{zid}/weg").json()["stand"]["saldo"] \
            == -NACHZAHLUNG

        r = c.patch(f"/api/zeitraeume/{zid}/weg/vorauszahlung/{vid}",
                    json={"einheit": EINHEIT, "von": "2042-01-01",
                          "bis": "2042-06-30", "betrag_monat": 220.0})
        assert r.status_code == 200 and r.json()["summe"] == 1320.0

        assert c.delete(
            f"/api/zeitraeume/{zid}/weg/vorauszahlung/{vid}").json()["summe"] == 0.0

        # Unbekannter Zeitraum bleibt ein sauberer 404, kein 500.
        assert c.get("/api/zeitraeume/999999/weg").status_code == 404


def test_lesen_ohne_ki_meldet_ruhig_statt_zu_scheitern(monkeypatch):
    """Ohne eingerichtete Erkennung ist die Antwort ein Hinweis, kein Fehler."""
    zid = _zeitraum(2043)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: False)
    with TestClient(app) as c:
        r = c.post(f"/api/zeitraeume/{zid}/weg/lesen",
                   files={"datei": ("abrechnung.pdf", b"%PDF-1.4 test",
                                    "application/pdf")})
    assert r.status_code == 200
    assert r.json()["gelesen"] is None
    assert "von Hand" in r.json()["hinweis"]


def test_lesen_gibt_die_gerasterten_seitenbilder_an_die_auslese_weiter(monkeypatch):
    """N330 — die Verdrahtung Ende zu Ende: der Router rastert den Beleg zu
    PNG-Seiten und reicht sie an `lies_weg_abrechnung` weiter, statt sich
    allein auf den (bei dieser Tabelle unzuverlässigen) PDF-Text zu
    verlassen."""
    zid = _zeitraum(2044)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(ocr, "text_aus_beleg", lambda *_a, **_k: "etwas Text")
    monkeypatch.setattr(ocr, "seiten_als_png",
                        lambda *_a, **_k: [b"seite-1-png", b"seite-2-png"])

    gerufen = {}

    def gestellt(text, dateiname="", schluessel="", modell="", bilder=None):
        gerufen["bilder"] = bilder
        return {"positionen": [], "heizkosten": 1.0, "warmwasserkosten": 1.0}

    monkeypatch.setattr(kiauslese, "lies_weg_abrechnung", gestellt)

    with TestClient(app) as c:
        r = c.post(f"/api/zeitraeume/{zid}/weg/lesen",
                   files={"datei": ("abrechnung.pdf", b"%PDF-1.4 test",
                                    "application/pdf")})
    assert r.status_code == 200
    assert gerufen["bilder"] == [b"seite-1-png", b"seite-2-png"]


# --------------------------------------------------------------------------
# N351 — § 35a wandert vom Beleg bis in den Stand
# --------------------------------------------------------------------------
def test_s35a_wandert_vom_beleg_in_position_und_stand():
    """Eine als haushaltsnah markierte Zeile (KI-Feld `s35a`) wird zur
    Kostenposition MIT § 35a-Vermerk; der Stand weist die Summe separat aus
    und kennzeichnet die Zeile — der Mieter braucht das für die
    Steuererklärung."""
    zid = _zeitraum(2045)
    beleg = _beleg()
    for p in beleg["positionen"]:
        if p["bezeichnung"] in ("Hausmeister", "Prüfung Rauchwarnmelder"):
            p["s35a"] = True
    _uebernehmen(zid, beleg)

    nach_name = {p.kostenart: p for p in _positionen(zid)}
    assert nach_name["Hausmeister"].s35 is True
    assert nach_name["Prüfung Rauchwarnmelder"].s35 is True
    assert nach_name["Versicherungen"].s35 is False

    stand = _stand(zid)
    assert stand["s35_summe"] == round(396.00 + 4.17, 2)
    flags = {p["kostenart"]: p["s35"] for p in stand["positionen"]}
    assert flags["Hausmeister"] is True
    assert flags["Versicherungen"] is False


def test_s35a_wird_beim_zweiten_lauf_fortgeschrieben():
    """Idempotenz auch für den Vermerk: nimmt der korrigierte Beleg das
    Kennzeichen zurück, verschwindet es an der bestehenden Position — die
    Zeile wird fortgeschrieben, nicht verdoppelt."""
    zid = _zeitraum(2046)
    beleg = _beleg()
    beleg["positionen"][5]["s35a"] = True          # Hausmeister
    _uebernehmen(zid, beleg)
    assert _stand(zid)["s35_summe"] > 0

    _uebernehmen(zid, _beleg())                    # ohne Kennzeichen
    stand = _stand(zid)
    assert stand["s35_summe"] == 0
    assert len(_positionen(zid)) == len(UMLAGEFAEHIG) + 2   # + Heiz/WW, nichts doppelt
