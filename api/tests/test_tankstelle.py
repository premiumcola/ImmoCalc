"""N132 — die E-Tankstelle als eigener Bereich.

Drei Ebenen, wie in den übrigen Prüfungen: die reine Logik (Quartalszuschnitt,
Monatsverlauf, Abrechnung je Nutzer), dann die Endpunkte (Nutzer anlegen,
Verlauf, Abrechnung, Vorschau, Versand) und zuletzt der Leerzustand — der Fall,
den es in der echten Anwendung am Anfang immer gibt.

Kontrollzahlen des Nutzers aus der echten Wallbox für 2025:

    111 Ladungen · 1991,03 kWh
      Netz (extern)   1024,82 kWh   51,5 %
      Akku (Speicher)  450,09 kWh   22,6 %
      PV (inkl. 23,31 kWh Rest)  516,13 kWh   25,9 %
      => Netz + PV + Akku == 1991,03 kWh

Die Aufteilung wird hier an genau diesen Zahlen gemessen
(`test_verlauf_trifft_die_kontrollzahlen`). Seit N143 zählt der von der
Wallbox nicht zugeordnete Rest zum PV-Block; es bleibt nichts übrig.

**Kein Test geht ins Netz und kein Test verschickt eine Mail.** Die Wallbox
steht im Heimnetz; der Versand wird durch ein Postfach-Doppel ersetzt, das die
Nachricht nur einsammelt.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_tankstelle.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db as db_modul  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Objekt, Stromjahr  # noqa: E402
from app.routers import tankstelle as t  # noqa: E402


# --------------------------------------------------------------------------
# 1) Quartalszuschnitt
# --------------------------------------------------------------------------

def test_quartal_zeitraum_alle_vier_und_ganzes_jahr():
    assert t.quartal_zeitraum(2025, 1) == (date(2025, 1, 1), date(2025, 3, 31))
    assert t.quartal_zeitraum(2025, 2) == (date(2025, 4, 1), date(2025, 6, 30))
    assert t.quartal_zeitraum(2025, 3) == (date(2025, 7, 1), date(2025, 9, 30))
    assert t.quartal_zeitraum(2025, 4) == (date(2025, 10, 1), date(2025, 12, 31))
    # 0 = das ganze Jahr, nicht „kein Quartal".
    assert t.quartal_zeitraum(2025, 0) == (date(2025, 1, 1), date(2025, 12, 31))


def test_quartal_zeitraum_schaltjahr_und_fehleingabe():
    # Februar 2024 hat 29 Tage — das Quartalsende wird gerechnet, nicht geraten.
    assert t.quartal_zeitraum(2024, 1)[1] == date(2024, 3, 31)
    with pytest.raises(ValueError):
        t.quartal_zeitraum(2025, 5)


def test_zeitraum_label():
    assert t.zeitraum_label(2025, 3) == "Q3 2025"
    assert t.zeitraum_label(2025, 0) == "Jahr 2025"


# --------------------------------------------------------------------------
# 2) Monatsverlauf — auch über eine Jahresgrenze
# --------------------------------------------------------------------------

def test_monatsfolge_ueber_die_jahresgrenze():
    folge = t.monatsfolge(date(2024, 11, 15), date(2025, 2, 3))
    assert folge == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_monatsfolge_lehnt_rueckwaerts_und_uferloses_ab():
    with pytest.raises(ValueError):
        t.monatsfolge(date(2025, 3, 1), date(2025, 1, 1))
    with pytest.raises(ValueError):
        t.monatsfolge(date(1900, 1, 1), date(2025, 1, 1))


def test_verlauf_ueber_die_jahresgrenze_mit_anteilen():
    """Ein Abrechnungszeitraum läuft nicht am Kalender entlang: 01.11.2024 bis
    28.02.2025 sind vier Monate, zwei davon im nächsten Jahr."""
    posten = [
        t.Posten(date(2024, 11, 5), 100.0, extern_kwh=60.0, eigen_kwh=40.0),
        t.Posten(date(2024, 11, 20), 50.0, extern_kwh=10.0, eigen_kwh=40.0),
        # Dezember: keine Ladung — der Monat gehört trotzdem in den Verlauf.
        t.Posten(date(2025, 1, 9), 80.0, extern_kwh=20.0, eigen_kwh=60.0),
        t.Posten(date(2025, 2, 14), 40.0, extern_kwh=40.0, eigen_kwh=0.0),
        # Ausserhalb — darf nicht mitzählen.
        t.Posten(date(2025, 3, 1), 999.0, extern_kwh=999.0, eigen_kwh=0.0),
    ]
    zeilen = t.verlauf(posten, date(2024, 11, 1), date(2025, 2, 28))
    assert [(z["jahr"], z["monat"]) for z in zeilen] == \
        [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]

    november = zeilen[0]
    assert november["anzahl"] == 2
    assert november["kwh"] == 150.0
    assert november["extern_kwh"] == 70.0
    assert november["eigen_kwh"] == 80.0
    # 70/150 = 46,7 % · 80/150 = 53,3 %
    assert november["extern_prozent"] == 46.7
    assert november["eigen_prozent"] == 53.3

    dezember = zeilen[1]
    assert dezember["kwh"] == 0.0 and dezember["anzahl"] == 0
    # Kein Strom, keine Prozentzahl — 0 % wäre eine Behauptung.
    assert dezember["extern_prozent"] is None

    summe = t.verlauf_summe(zeilen)
    assert summe["kwh"] == 270.0
    assert summe["extern_kwh"] == 130.0 and summe["eigen_kwh"] == 140.0
    assert summe["anzahl"] == 4


def test_verlauf_ohne_bekannte_aufteilung_erfindet_keine_null():
    """Weiß niemand, woher der Strom kam, steht die Menge da — aber keine
    Aufteilung. Eine 0 sähe aus wie eine Messung."""
    zeilen = t.verlauf([t.Posten(date(2025, 5, 3), 42.0)],
                       date(2025, 5, 1), date(2025, 5, 31))
    assert zeilen[0]["kwh"] == 42.0
    assert zeilen[0]["aufteilung"] is False
    assert zeilen[0]["extern_kwh"] is None
    assert zeilen[0]["eigen_prozent"] is None
    assert t.verlauf_summe(zeilen)["aufteilung"] is False


def test_verlauf_trifft_die_kontrollzahlen():
    """Die echten Jahreszahlen der Box (2025) — auf zwölf Monate verteilt.

    Geprüft wird, dass die Aufteilung über die Monate hinweg genau die
    Kontrollwerte ergibt: 1991,03 kWh, davon 1024,82 Netz, 450,09 Akku und
    516,13 PV (492,82 direkt + 23,31 Rest). Die drei Blöcke ergeben zusammen
    wieder die volle Menge — es bleibt nichts liegen."""
    monatlich = [
        (1, 180.11, 92.70, 40.72, 46.69), (2, 210.42, 108.30, 47.57, 54.55),
        (3, 165.00, 84.90, 37.30, 42.80), (4, 140.55, 72.30, 31.77, 36.48),
        (5, 155.20, 79.90, 35.09, 40.21), (6, 148.30, 76.30, 33.51, 38.49),
        (7, 172.40, 88.70, 38.96, 44.74), (8, 168.90, 86.90, 38.17, 43.83),
        (9, 159.75, 82.20, 36.11, 41.44), (10, 175.60, 90.40, 39.69, 45.51),
        (11, 158.40, 81.50, 35.79, 41.11), (12, 156.40, 80.72, 35.41, 40.27),
    ]
    posten = [t.Posten(date(2025, m, 15), kwh, extern_kwh=extern,
                       speicher_kwh=speicher, pv_kwh=pv)
              for m, kwh, extern, speicher, pv in monatlich]
    summe = t.verlauf_summe(t.verlauf(posten, date(2025, 1, 1),
                                      date(2025, 12, 31)))
    assert summe["kwh"] == 1991.03
    assert summe["extern_kwh"] == 1024.82
    assert summe["speicher_kwh"] == 450.09
    assert summe["pv_kwh"] == 516.12
    assert summe["eigen_kwh"] == 966.21
    assert summe["extern_prozent"] == 51.5
    # Netz + PV + Akku ergeben wieder die volle Energiemenge.
    assert round(summe["extern_kwh"] + summe["pv_kwh"]
                 + summe["speicher_kwh"], 2) == 1991.03


def test_verlauf_schlaegt_den_nicht_zugeordneten_rest_dem_eigenen_strom_zu():
    """Am 12.07.2026 schrieb die Wallbox in alle vier Anteile 0 %.

    Die 49,88 kWh dieses Monats zählen seit N143 zum PV-Block und damit zum
    eigenen Strom — so hat der Nutzer entschieden. Landeten sie beim Netz,
    sähe ein Monat mit 0,3 % Netzbezug zu drei Vierteln nach Zukauf aus; als
    eigener grauer Topf verwirrten sie nur. Nachvollziehbar bleiben sie über
    `rest_kwh`."""
    posten = [
        t.Posten(date(2026, 7, 3), 18.31, extern_kwh=0.20, pv_kwh=12.11,
                 speicher_kwh=6.0),
        t.Posten(date(2026, 7, 12), 49.88, extern_kwh=0.0, pv_kwh=49.88,
                 speicher_kwh=0.0, rest_kwh=49.88),
    ]
    juli = t.verlauf(posten, date(2026, 7, 1), date(2026, 7, 31))[0]
    assert juli["kwh"] == 68.19
    assert juli["extern_kwh"] == 0.20 and juli["extern_prozent"] == 0.3
    assert juli["eigen_kwh"] == 67.99 and juli["eigen_prozent"] == 99.7
    assert juli["pv_kwh"] == 61.99 and juli["speicher_kwh"] == 6.0
    # Netz + eigen ergeben wieder die geladene Menge — kein Rest daneben.
    assert round(juli["extern_kwh"] + juli["eigen_kwh"], 2) == juli["kwh"]
    # Wie viel auf diesem Weg dazukam, bleibt einzeln nachvollziehbar.
    assert juli["rest_kwh"] == 49.88
    assert juli["rest_prozent"] == 73.1
    assert t.verlauf_summe([juli])["rest_kwh"] == 49.88


def test_verlauf_ohne_rest_meldet_keinen():
    zeilen = t.verlauf([t.Posten(date(2025, 5, 3), 10.0, extern_kwh=6.0,
                                 pv_kwh=3.0, speicher_kwh=1.0)],
                       date(2025, 5, 1), date(2025, 5, 31))
    assert zeilen[0]["rest_kwh"] == 0.0
    assert zeilen[0]["eigen_kwh"] == 4.0
    assert t.verlauf_summe(zeilen)["rest_kwh"] == 0.0


def test_verlauf_ohne_pv_akku_trennung_erfindet_keine():
    """Die aus Jahreswerten übertragene Schätzung kennt nur Netz und eigen.

    Dann steht `dreiteilig` auf ``false`` und PV/Akku bleiben leer — eine 0
    sähe aus wie „nichts vom Dach"."""
    zeilen = t.verlauf([t.Posten(date(2025, 5, 3), 10.0, extern_kwh=6.0,
                                 eigen_kwh=4.0)],
                       date(2025, 5, 1), date(2025, 5, 31))
    assert zeilen[0]["aufteilung"] is True
    assert zeilen[0]["dreiteilig"] is False
    assert zeilen[0]["eigen_kwh"] == 4.0
    assert zeilen[0]["pv_kwh"] is None and zeilen[0]["speicher_kwh"] is None
    summe = t.verlauf_summe(zeilen)
    assert summe["dreiteilig"] is False and summe["pv_kwh"] is None


def test_belegte_spanne_und_jahre_mit_verbrauch():
    """Der Verlauf läuft über alles, die Jahresauswahl nur über Jahre mit
    Verbrauch (N143)."""
    posten = [t.Posten(date(2025, 3, 17), 12.0),
              t.Posten(date(2026, 8, 2), 30.0),
              t.Posten(date(2024, 6, 1), 0.0)]      # angesteckt, nichts geflossen
    ersatz = (date(2030, 1, 1), date(2030, 12, 31))
    assert t.belegte_spanne(posten, ersatz) == (date(2025, 3, 1),
                                                date(2026, 8, 31))
    # 2024 hat keine Kilowattstunde gesehen und gehört in keine Auswahl.
    assert t.jahre_mit_verbrauch(posten) == [2025, 2026]
    # Ohne jede Ladung bleibt der Ersatzzeitraum stehen.
    assert t.belegte_spanne([], ersatz) == ersatz
    assert t.jahre_mit_verbrauch([]) == []


def test_suchfenster_ist_grosszuegig_aber_endlich():
    von, bis = t.suchfenster(date(2026, 8, 2))
    assert (von, bis) == (date(2017, 1, 1), date(2026, 12, 31))
    # Es muss in den Verlauf passen, sonst wäre der Rückblick nutzlos.
    assert len(t.monatsfolge(von, bis)) <= t.MAX_MONATE


# --------------------------------------------------------------------------
# 3) Abrechnung je Nutzer
# --------------------------------------------------------------------------

NUTZER = [{"id": 1, "name": "Marvin", "email": "marvin@example.invalid"},
          {"id": 2, "name": "Alicia", "email": ""}]


def test_abrechne_je_nutzer_mit_gepflegtem_satz():
    zeilen = t.abrechne([
        t.Buchung(date(2025, 7, 4), "Marvin", "", 30.0, 0.0),
        t.Buchung(date(2025, 8, 9), "marvin", "", 20.0, 0.0),   # gleicher Mensch
        t.Buchung(date(2025, 9, 1), "Alicia", "", 10.0, 0.45),  # eigener Satz
    ], NUTZER, satz=0.32)

    marvin = next(z for z in zeilen if z["name"] == "Marvin")
    assert marvin["kwh"] == 50.0
    assert marvin["betrag"] == 16.0          # 50 × 0,32
    assert marvin["satz"] == 0.32
    assert marvin["anzahl"] == 2
    assert marvin["email"] == "marvin@example.invalid"

    alicia = next(z for z in zeilen if z["name"] == "Alicia")
    assert alicia["betrag"] == 4.5           # eigener Satz hat Vorrang
    assert alicia["satz"] == 0.45


def test_abrechne_zeigt_nutzer_ohne_ladung_und_ladung_ohne_nutzer():
    zeilen = t.abrechne([t.Buchung(date(2025, 7, 4), "Gast", "g@example.invalid",
                                   12.0, 0.0)], NUTZER, satz=0.30)
    namen = {z["name"]: z for z in zeilen}
    # Wer nichts geladen hat, verschwindet nicht aus der Liste.
    assert namen["Alicia"]["kwh"] == 0.0 and namen["Alicia"]["betrag"] == 0.0
    assert namen["Alicia"]["angelegt"] is True
    # Wer geladen hat, ohne angelegt zu sein, wird trotzdem abgerechnet.
    assert namen["Gast"]["angelegt"] is False
    assert namen["Gast"]["betrag"] == 3.6
    assert namen["Gast"]["email"] == "g@example.invalid"
    # Wer geladen hat, steht oben.
    assert zeilen[0]["name"] == "Gast"


def test_abrechnungstext_nennt_menge_betrag_und_eigenanteil():
    zeile = t.abrechne([t.Buchung(date(2025, 7, 4), "Marvin", "", 50.0, 0.0)],
                       NUTZER, satz=0.32)[0]
    text = t.abrechnungstext("Laufer Str. 5", zeile, date(2025, 7, 1),
                             date(2025, 9, 30), "Q3 2025", 47.4)
    assert "Hallo Marvin," in text
    assert "Q3 2025" in text and "01.07.2025 – 30.09.2025" in text
    assert "50,00 kWh" in text
    assert "16,00 €" in text
    assert "47,4 % des Stroms" in text
    assert "04.07.2025" in text


def test_abrechnungstext_ohne_bekannten_eigenanteil_behauptet_nichts():
    zeile = t.abrechne([t.Buchung(None, "Marvin", "", 10.0, 0.0)],
                       NUTZER, satz=0.32)[0]
    text = t.abrechnungstext("Laufer Str. 5", zeile, date(2025, 7, 1),
                             date(2025, 9, 30), "Q3 2025", None)
    assert "Photovoltaik" not in text
    assert "ohne Datum" in text


def test_deutsche_zahlen():
    assert t.deutsch(1234.5) == "1.234,50"
    assert t.deutsch(0.32, 4) == "0,3200"


# --------------------------------------------------------------------------
# 4) Endpunkte
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c, name: str = "Tankhaus") -> str:
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def _nutzer(c, slug: str, name: str, email: str = "") -> dict:
    antwort = c.post(f"/api/tankstelle/{slug}/nutzer",
                     json={"name": name, "email": email})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _jahresaufteilung(slug: str, jahr: int, extern: float, eigen: float) -> None:
    """Die von Hand gepflegte Aufteilung Netz/eigen eines Jahres setzen (N124).

    Direkt am Datensatz und nicht über den Strom-Endpunkt: dessen Feldliste
    führt die beiden Mengen (noch) nicht — dieser Test soll die E-Tankstelle
    prüfen, nicht den Ausbaustand einer fremden Maske."""
    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        sj = session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == o.id, Stromjahr.jahr == jahr)).first()
        if sj is None:
            sj = Stromjahr(objekt_id=o.id, jahr=jahr)
        sj.eauto_extern_kwh = extern
        sj.eauto_eigen_kwh = eigen
        session.add(sj)
        session.commit()


def _ladung(c, slug: str, jahr: int, **werte) -> dict:
    """Eine Ladung über den bestehenden Weg erfassen (N112)."""
    antwort = c.post(f"/api/objekte/{slug}/tankstelle/{jahr}", json=werte)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_nutzer_dynamisch_anlegen_aendern_entfernen(client):
    slug = _neues_objekt(client, "Nutzerhaus")
    assert client.get(f"/api/tankstelle/{slug}/nutzer").json()["nutzer"] == []

    a = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    b = _nutzer(client, slug, "Alicia")
    assert a["id"] != b["id"]

    liste = client.get(f"/api/tankstelle/{slug}/nutzer").json()["nutzer"]
    assert [n["name"] for n in liste] == ["Marvin", "Alicia"]

    # Derselbe Name zweimal wäre in der Abrechnung nicht auflösbar.
    doppelt = client.post(f"/api/tankstelle/{slug}/nutzer",
                          json={"name": " marvin "})
    assert doppelt.status_code == 400

    # Ein Nutzer ohne Namen ist keiner.
    assert client.post(f"/api/tankstelle/{slug}/nutzer",
                       json={"name": "  "}).status_code == 400
    # Eine Adresse ohne @ ist keine.
    assert client.post(f"/api/tankstelle/{slug}/nutzer",
                       json={"name": "Kai", "email": "kai"}).status_code == 400

    geaendert = client.put(f"/api/tankstelle/{slug}/nutzer/{b['id']}",
                           json={"email": "alicia@example.invalid"})
    assert geaendert.status_code == 200
    assert geaendert.json()["name"] == "Alicia"          # Name bleibt stehen
    assert geaendert.json()["email"] == "alicia@example.invalid"

    assert client.delete(f"/api/tankstelle/{slug}/nutzer/{b['id']}"
                         ).status_code == 200
    assert [n["name"] for n in client.get(
        f"/api/tankstelle/{slug}/nutzer").json()["nutzer"]] == ["Marvin"]
    assert client.delete(f"/api/tankstelle/{slug}/nutzer/{b['id']}"
                         ).status_code == 404


def test_nutzer_zweier_objekte_bleiben_getrennt(client):
    eins = _neues_objekt(client, "Tank A")
    zwei = _neues_objekt(client, "Tank B")
    _nutzer(client, eins, "Nur bei A")
    assert client.get(f"/api/tankstelle/{zwei}/nutzer").json()["nutzer"] == []


def test_verlauf_leer_zeigt_zwoelf_monate_ohne_erfundene_zahlen(client):
    """Der Leerzustand: noch kein Nutzer, keine Ladung. Der Verlauf ist
    trotzdem eine sinnvolle Antwort — zwölf Monate mit 0, keine Prozentzahl."""
    slug = _neues_objekt(client, "Leerhaus")
    d = client.get(f"/api/tankstelle/{slug}/verlauf", params={"jahr": 2025}).json()
    assert len(d["monate"]) == 12
    assert d["quelle"] == "leer"
    assert d["summe"]["kwh"] == 0.0
    assert d["summe"]["extern_prozent"] is None
    assert all(m["kwh"] == 0.0 for m in d["monate"])


def test_verlauf_aus_erfassten_ladungen_mit_jahresverhaeltnis(client):
    """Ohne Wallbox tragen die erfassten Ladungen den Verlauf. Die Aufteilung
    Netz/eigen kommt dann aus den Jahreswerten (N124) — als Übertragung
    gekennzeichnet, nicht als Messung."""
    slug = _neues_objekt(client, "Verlaufhaus")
    client.put(f"/api/objekte/{slug}/strom/2025", json={"tanken_preis": 0.32})
    _jahresaufteilung(slug, 2025, extern=60.0, eigen=40.0)
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-03-05")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-07-11")

    d = client.get(f"/api/tankstelle/{slug}/verlauf", params={"jahr": 2025}).json()
    assert d["quelle"] == "erfasst"
    assert d["summe"]["kwh"] == 150.0
    assert d["summe"]["extern_kwh"] == 90.0     # 60 % von 150
    assert d["summe"]["eigen_kwh"] == 60.0
    assert d["summe"]["eigen_prozent"] == 40.0
    maerz = next(m for m in d["monate"] if m["monat"] == 3)
    assert maerz["kwh"] == 100.0 and maerz["extern_prozent"] == 60.0
    assert "Aufteilung" in d["hinweis"]


def test_verlauf_ueber_freien_zeitraum_geht_ueber_die_jahresgrenze(client):
    slug = _neues_objekt(client, "Grenzhaus")
    _ladung(client, slug, 2024, name="Marvin", kwh=20.0, datum="2024-11-02")
    _ladung(client, slug, 2025, name="Marvin", kwh=30.0, datum="2025-01-20")
    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"von": "2024-10-01", "bis": "2025-02-28"}).json()
    assert [(m["jahr"], m["monat"]) for m in d["monate"]] == \
        [(2024, 10), (2024, 11), (2024, 12), (2025, 1), (2025, 2)]
    assert d["summe"]["kwh"] == 50.0


def test_verlauf_ueber_alles_geht_ueber_die_jahre_und_nennt_sie(client):
    """N143 — ohne Zeitraum läuft der Verlauf vom ersten bis zum letzten Monat
    mit Verbrauch, und `jahre` nennt nur Jahre, in denen geladen wurde."""
    slug = _neues_objekt(client, "Gesamthaus")
    _ladung(client, slug, 2025, name="Marvin", kwh=20.0, datum="2025-03-14")
    _ladung(client, slug, 2026, name="Marvin", kwh=30.0, datum="2026-05-09")

    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"alles": 1}).json()
    assert d["von"] == "2025-03-01" and d["bis"] == "2026-05-31"
    assert [(m["jahr"], m["monat"]) for m in d["monate"]][0] == (2025, 3)
    assert [(m["jahr"], m["monat"]) for m in d["monate"]][-1] == (2026, 5)
    assert len(d["monate"]) == 15               # März 2025 bis Mai 2026
    assert d["summe"]["kwh"] == 50.0
    # Die Jahresauswahl kennt nur Jahre mit Verbrauch.
    assert d["jahre"] == [2025, 2026]


def test_verlauf_ueber_alles_ohne_eine_einzige_ladung(client):
    """Kein Verbrauch, keine erfundene Spanne: das laufende Jahr und eine
    leere Jahresliste — die Oberfläche sagt dann etwas Ruhiges statt einer
    leeren Auswahl."""
    slug = _neues_objekt(client, "Gesamtleerhaus")
    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"alles": 1}).json()
    assert d["jahre"] == []
    assert d["quelle"] == "leer"
    assert len(d["monate"]) == 12
    assert d["summe"]["kwh"] == 0.0


def test_verlauf_lehnt_rueckwaerts_laufenden_zeitraum_ab(client):
    slug = _neues_objekt(client, "Ruecklaufhaus")
    antwort = client.get(f"/api/tankstelle/{slug}/verlauf",
                         params={"von": "2025-06-01", "bis": "2025-01-01"})
    assert antwort.status_code == 400


def test_abrechnung_je_nutzer_und_quartalszuschnitt(client):
    slug = _neues_objekt(client, "Abrechnungshaus")
    client.put(f"/api/objekte/{slug}/strom/2025", json={"tanken_preis": 0.32})
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=30.0, datum="2025-07-04")
    _ladung(client, slug, 2025, name="Marvin", kwh=20.0, datum="2025-08-09")
    _ladung(client, slug, 2025, name="Alicia", kwh=10.0, datum="2025-02-02")

    q3 = client.get(f"/api/tankstelle/{slug}/abrechnung",
                    params={"jahr": 2025, "quartal": 3}).json()
    assert q3["label"] == "Q3 2025"
    assert q3["satz"] == 0.32
    marvin = next(z for z in q3["nutzer"] if z["name"] == "Marvin")
    assert marvin["kwh"] == 50.0 and marvin["betrag"] == 16.0
    # Alicias Ladung lag im Februar — im dritten Quartal steht sie mit 0 da.
    alicia = next(z for z in q3["nutzer"] if z["name"] == "Alicia")
    assert alicia["kwh"] == 0.0
    assert q3["betrag_gesamt"] == 16.0

    ganz = client.get(f"/api/tankstelle/{slug}/abrechnung",
                      params={"jahr": 2025, "quartal": 0}).json()
    assert ganz["label"] == "Jahr 2025"
    assert ganz["kwh_gesamt"] == 60.0
    assert ganz["betrag_gesamt"] == 19.2


def test_abrechnung_leer_liefert_die_angelegten_nutzer_mit_null(client):
    slug = _neues_objekt(client, "Nullhaus")
    _nutzer(client, slug, "Marvin")
    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 1}).json()
    assert [z["name"] for z in d["nutzer"]] == ["Marvin"]
    assert d["betrag_gesamt"] == 0.0


def test_abrechnung_nennt_die_luecke_zwischen_geladen_und_zugeordnet(client):
    """N143 — die Abrechnung rechnet nur ab, was einer Person zugeordnet ist.

    Wer nichts zugeordnet hat, sieht sonst überall 0,00 € und weiss nicht,
    wieso: darum steht daneben, wie viel im Zeitraum überhaupt geladen wurde.
    Diese Lücke ist die Antwort auf „wieso passiert da nichts"."""
    slug = _neues_objekt(client, "Rueckfragehaus")
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=40.0, datum="2025-08-11")

    # Q3: die Ladung ist zugeordnet — keine Lücke.
    q3 = client.get(f"/api/tankstelle/{slug}/abrechnung",
                    params={"jahr": 2025, "quartal": 3}).json()
    assert q3["geladen_kwh"] == 40.0
    assert q3["kwh_gesamt"] == 40.0
    assert q3["offen_kwh"] == 0.0

    # Q1: nichts geladen, nichts zugeordnet — auch keine Lücke.
    q1 = client.get(f"/api/tankstelle/{slug}/abrechnung",
                    params={"jahr": 2025, "quartal": 1}).json()
    assert q1["kwh_gesamt"] == 0.0
    assert q1["offen_kwh"] in (None, 0.0)


def test_vorschau_zeigt_die_mail_ohne_sie_zu_verschicken(client):
    slug = _neues_objekt(client, "Vorschauhaus")
    client.put(f"/api/objekte/{slug}/strom/2025", json={"tanken_preis": 0.32})
    n = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-07-04")

    d = client.get(f"/api/tankstelle/{slug}/vorschau",
                   params={"jahr": 2025, "quartal": 3,
                           "nutzer_id": n["id"]}).json()
    assert d["an"] == "marvin@example.invalid"
    assert d["betrag"] == 16.0
    assert "Hallo Marvin," in d["text"]
    assert "Q3 2025" in d["betreff"]

    # Unbekannter Nutzer → 404 statt einer leeren Rechnung.
    assert client.get(f"/api/tankstelle/{slug}/vorschau",
                      params={"jahr": 2025, "quartal": 3,
                              "nutzer_id": 999}).status_code == 404


class _Postfach:
    """Ein Postfach-Doppel: sammelt ein, was verschickt worden wäre."""

    def __init__(self):
        self.gesendet = []

    def sende(self, an, betreff, text, anhang=None):
        self.gesendet.append((an, betreff, text))


def test_versand_quartalsweise_geht_an_die_hinterlegte_adresse(client,
                                                               monkeypatch):
    slug = _neues_objekt(client, "Versandhaus")
    client.put(f"/api/objekte/{slug}/strom/2025", json={"tanken_preis": 0.32})
    n = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-07-04")

    postfach = _Postfach()
    monkeypatch.setattr(t, "zugang", lambda session: postfach)

    antwort = client.post(f"/api/tankstelle/{slug}/versand",
                          json={"nutzer_id": n["id"], "jahr": 2025,
                                "quartal": 3})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["an"] == "marvin@example.invalid"
    assert antwort.json()["betrag"] == 16.0
    assert len(postfach.gesendet) == 1
    an, betreff, text = postfach.gesendet[0]
    assert an == "marvin@example.invalid"
    assert "Q3 2025" in betreff
    assert "16,00 €" in text


def test_versand_ohne_ladung_und_ohne_adresse_wird_abgelehnt(client,
                                                             monkeypatch):
    slug = _neues_objekt(client, "Absagehaus")
    ohne_mail = _nutzer(client, slug, "Ohne Adresse")
    mit_mail = _nutzer(client, slug, "Mit Adresse", "mit@example.invalid")
    _ladung(client, slug, 2025, name="Ohne Adresse", kwh=5.0,
            datum="2025-07-04")

    postfach = _Postfach()
    monkeypatch.setattr(t, "zugang", lambda session: postfach)

    ohne = client.post(f"/api/tankstelle/{slug}/versand",
                       json={"nutzer_id": ohne_mail["id"], "jahr": 2025,
                             "quartal": 3})
    assert ohne.status_code == 400 and "Adresse" in ohne.json()["detail"]

    leer = client.post(f"/api/tankstelle/{slug}/versand",
                       json={"nutzer_id": mit_mail["id"], "jahr": 2025,
                             "quartal": 3})
    assert leer.status_code == 400 and "nichts geladen" in leer.json()["detail"]
    assert postfach.gesendet == []


def test_unbekanntes_objekt_meldet_404(client):
    assert client.get("/api/tankstelle/gibtsnicht/nutzer").status_code == 404
    assert client.get("/api/tankstelle/gibtsnicht/verlauf").status_code == 404
