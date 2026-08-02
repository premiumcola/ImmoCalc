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

Seit N148 wird der **Satz je kWh abgeleitet, nicht eingegeben**: Netzstrom zum
Durchschnittspreis des Netzbezugs (Betrag ÷ bezogene kWh, Grundgebühr
inbegriffen), eigener Strom `EIGEN_RABATT` darunter. Die beiden alten
Handeingaben — `Stromjahr.tanken_preis` und `Tankladung.preis` — bleiben als
Spalten stehen und dürfen die Rechnung **nicht mehr bewegen**; genau das prüft
`test_alter_handpreis_an_der_ladung_bewegt_nichts_mehr`. Fehlen die Kosten,
gibt es keinen Satz und keine 0,00 € — sondern einen Grund.

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
from app.models import (Einstellung, Kostenposition, Objekt,  # noqa: E402
                        Stromjahr, Tankladung, Tanknutzer, Zeitraum)
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


def test_abrechne_bewertet_jede_ladung_mit_dem_abgeleiteten_satz():
    """N148 — ein Satz für alle. Es gibt keinen Preis je Ladung mehr."""
    zeilen = t.abrechne([
        t.Buchung(date(2025, 7, 4), "Marvin", "", 30.0),
        t.Buchung(date(2025, 8, 9), "marvin", "", 20.0),   # gleicher Mensch
        t.Buchung(date(2025, 9, 1), "Alicia", "", 10.0),
    ], NUTZER, satz=0.32)

    marvin = next(z for z in zeilen if z["name"] == "Marvin")
    assert marvin["kwh"] == 50.0
    assert marvin["betrag"] == 16.0          # 50 × 0,32
    assert marvin["satz"] == 0.32
    assert marvin["anzahl"] == 2
    assert marvin["email"] == "marvin@example.invalid"

    alicia = next(z for z in zeilen if z["name"] == "Alicia")
    assert alicia["betrag"] == 3.2           # derselbe Satz, keine Ausnahme
    assert alicia["satz"] == 0.32


def test_abrechne_ohne_satz_zeigt_keine_null_sondern_nichts():
    """Steht kein Satz fest, gibt es keinen Betrag — auch keine 0,00 €.

    Eine Rechnung über null ohne erkennbaren Grund war hier schon einmal ein
    Problem; die Menge bleibt sichtbar, der Preis fehlt sichtbar."""
    zeilen = t.abrechne([t.Buchung(date(2025, 7, 4), "Marvin", "", 30.0)],
                        NUTZER, satz=None)
    marvin = next(z for z in zeilen if z["name"] == "Marvin")
    assert marvin["kwh"] == 30.0
    assert marvin["betrag"] is None and marvin["satz"] is None
    assert marvin["ladungen"][0]["betrag"] is None
    assert marvin["ladungen"][0]["kwh"] == 30.0


# --------------------------------------------------------------------------
# 3b) Der abgeleitete Satz: Netz · eigen · Mischung
# --------------------------------------------------------------------------

def test_eigener_strom_kostet_den_rabatt_weniger():
    assert t.EIGEN_RABATT == 0.10
    assert t.eigen_satz(0.32) == 0.288
    # Der Rabatt steht an einer Stelle — nicht als nackte 0,9 im Code.
    assert t.eigen_satz(0.5) == round(0.5 * (1 - t.EIGEN_RABATT), 5)


def test_mischsatz_gewichtet_nach_den_mengen_des_zeitraums():
    # Halb Netz, halb eigen: genau die Mitte zwischen 0,32 und 0,288.
    assert t.mischsatz(0.32, 0.288, 100.0, 100.0) == 0.304
    # Nur Netzbezug — kein Rabatt zu verteilen.
    assert t.mischsatz(0.32, 0.288, 100.0, 0.0) == 0.32
    assert t.mischsatz(0.32, 0.288, 0.0, 100.0) == 0.288
    # Aufteilung unbekannt: der Netzpreis gilt. Ein Rabatt auf Verdacht wäre
    # geschenktes Geld.
    assert t.mischsatz(0.32, 0.288, None, None) == 0.32
    assert t.mischsatz(0.32, 0.288, 0.0, 0.0) == 0.32


def test_passender_zeitraum_nimmt_die_groesste_ueberschneidung():
    """Die Nebenkostenperiode läuft nicht am Kalender entlang — gewählt wird
    der Zeitraum, der das Quartal am weitesten trägt."""
    alt = Zeitraum(objekt_id=1, start=date(2023, 10, 1), ende=date(2024, 9, 30))
    neu = Zeitraum(objekt_id=1, start=date(2024, 10, 1), ende=date(2025, 9, 30))
    # Q3 2025 (Jul–Sep) liegt ganz in der neuen Periode.
    assert t.passender_zeitraum([alt, neu], date(2025, 7, 1),
                                date(2025, 9, 30)) is neu
    # Q3 2024 liegt ganz in der alten.
    assert t.passender_zeitraum([alt, neu], date(2024, 7, 1),
                                date(2024, 9, 30)) is alt
    # Gar keine Überschneidung: lieber nichts als der falsche Preis.
    assert t.passender_zeitraum([alt, neu], date(2026, 1, 1),
                                date(2026, 3, 31)) is None
    assert t.passender_zeitraum([], date(2025, 1, 1), date(2025, 3, 31)) is None


def test_abrechne_zeigt_nutzer_ohne_ladung_und_ladung_ohne_nutzer():
    zeilen = t.abrechne([t.Buchung(date(2025, 7, 4), "Gast", "g@example.invalid",
                                   12.0)], NUTZER, satz=0.30)
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


def test_posten_als_buchungen_ordnet_bei_einem_nutzer_alles_zu():
    """N165 — genau ein Nutzer: alle Ladungen des Zeitraums gehören ihm,
    unabhängig davon, welchen Namen die Rohdaten tragen. Erkennbar automatisch."""
    posten = [t.Posten(date(2025, 7, 4), 30.0),
              t.Posten(date(2025, 8, 9), 20.0),
              t.Posten(date(2025, 9, 1), 0.0)]        # 0-kWh zählt nicht mit
    einer = [{"id": 7, "name": "Alicia", "email": "a@example.invalid"}]
    buchungen, automatisch = t.posten_als_buchungen(posten, einer)
    assert automatisch is True
    assert [b.person for b in buchungen] == ["Alicia", "Alicia"]
    assert sum(b.kwh for b in buchungen) == 50.0
    assert all(b.email == "a@example.invalid" for b in buchungen)

    # Mehrere (oder kein) Nutzer: keine automatische Zuordnung.
    assert t.posten_als_buchungen(posten, [])[1] is False
    assert t.posten_als_buchungen(
        posten, [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])[1] is False


def test_abrechnungstext_nennt_menge_betrag_und_eigenanteil():
    zeile = t.abrechne([t.Buchung(date(2025, 7, 4), "Marvin", "", 50.0)],
                       NUTZER, satz=0.32)[0]
    text = t.abrechnungstext("Laufer Str. 5", zeile, date(2025, 7, 1),
                             date(2025, 9, 30), "Q3 2025", 47.4,
                             "Rechnung 1.600,00 € (Position „Strom“) ÷ "
                             "5.000,00 kWh Netzbezug")
    assert "Hallo Marvin," in text
    assert "Q3 2025" in text and "01.07.2025 – 30.09.2025" in text
    assert "50,00 kWh" in text
    assert "16,00 €" in text
    assert "47,4 % des Stroms" in text
    assert "04.07.2025" in text
    # Der Empfänger soll den Satz nachrechnen können, nicht glauben müssen.
    assert "nicht gesetzt, sondern gerechnet" in text
    assert "Rechnung 1.600,00 €" in text
    assert "10 % weniger" in text


def test_abrechnungstext_ohne_bekannten_eigenanteil_behauptet_nichts():
    zeile = t.abrechne([t.Buchung(None, "Marvin", "", 10.0)],
                       NUTZER, satz=0.32)[0]
    text = t.abrechnungstext("Laufer Str. 5", zeile, date(2025, 7, 1),
                             date(2025, 9, 30), "Q3 2025", None)
    assert "Photovoltaik" not in text
    assert "ohne Datum" in text
    # Ohne Herkunft kein Herkunftssatz — nichts wird dazugedichtet.
    assert "gerechnet" not in text


def test_abrechnungstext_ohne_satz_stellt_keine_forderung():
    zeile = t.abrechne([t.Buchung(date(2025, 7, 4), "Marvin", "", 50.0)],
                       NUTZER, satz=None)[0]
    text = t.abrechnungstext("Laufer Str. 5", zeile, date(2025, 7, 1),
                             date(2025, 9, 30), "Q3 2025", None)
    assert "50,00 kWh" in text
    assert "steht noch nicht fest" in text
    assert "0,00 €" not in text


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


def _stromkosten(slug: str, jahr: int, betrag: float,
                 von: date | None = None, bis: date | None = None,
                 gesamt_kwh: float = 10000.0, netz_kwh: float = 5000.0,
                 solar_kwh: float = 3000.0, akku_kwh: float = 2000.0) -> None:
    """Die Stromkosten einer Abrechnungsperiode setzen — die Grundlage des
    abgeleiteten Satzes (N148).

    Direkt am Datensatz, wie schon `_jahresaufteilung`: geprüft wird die
    E-Tankstelle, nicht der Ausbaustand fremder Masken. Mit den Vorgaben
    entfallen 50 % des Verbrauchs auf den Netzbezug — 5.000 kWh, die den
    genannten Betrag gekostet haben."""
    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        start = von or date(jahr, 1, 1)
        ende = bis or date(jahr, 12, 31)
        z = session.exec(select(Zeitraum).where(
            Zeitraum.objekt_id == o.id, Zeitraum.start == start)).first()
        if z is None:
            z = Zeitraum(objekt_id=o.id, start=start, ende=ende)
            session.add(z)
            session.commit()
            session.refresh(z)
        sj = session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == o.id, Stromjahr.jahr == jahr)).first()
        if sj is None:
            sj = Stromjahr(objekt_id=o.id, jahr=jahr)
        sj.gesamt_kwh = gesamt_kwh
        sj.netz_kwh, sj.solar_kwh, sj.akku_kwh = netz_kwh, solar_kwh, akku_kwh
        session.add(sj)
        session.add(Kostenposition(zeitraum_id=z.id, kostenart="Strom",
                                   betrag=betrag, herkunft="extern",
                                   menge=netz_kwh, menge_einheit="kWh"))
        session.commit()


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
    # 1.600 € für 5.000 kWh Netzbezug → 0,32 € je kWh (N148).
    _stromkosten(slug, 2025, betrag=1600.0)
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
    _stromkosten(slug, 2025, betrag=1600.0)
    _nutzer(client, slug, "Marvin")
    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 1}).json()
    assert [z["name"] for z in d["nutzer"]] == ["Marvin"]
    assert d["betrag_gesamt"] == 0.0
    # Der Satz steht auch dann fest, wenn niemand geladen hat.
    assert d["satz"] == 0.32


def test_abrechnung_leitet_den_satz_aus_den_stromkosten_ab(client):
    """N148 — 1.600 € für 5.000 kWh Netzbezug ergeben 0,32 € je kWh; eigener
    Strom liegt 10 % darunter. Eingegeben wird nichts."""
    slug = _neues_objekt(client, "Satzhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-08-11")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["satz_netz"] == 0.32
    assert d["satz_eigen"] == 0.288
    assert d["satz_rabatt"] == 0.10
    # Ohne bekannte Aufteilung des Zeitraums gilt der Netzpreis.
    assert d["satz"] == 0.32
    assert d["satz_grund"] == ""
    # Die Herkunft nennt Betrag, Menge, Position und Zeitraum.
    assert "1.600,00 €" in d["satz_herkunft"]
    assert "5.000,00 kWh" in d["satz_herkunft"]
    assert "Strom" in d["satz_herkunft"]
    assert "01.01.2025 – 31.12.2025" in d["satz_herkunft"]
    assert next(z for z in d["nutzer"] if z["name"] == "Marvin")["betrag"] == 32.0


def test_abrechnung_mischt_netz_und_eigenen_strom_nach_den_mengen(client):
    """Eine Ladung speist sich aus beidem — der Satz folgt den Mengen.

    60 % Netz zu 0,32 € und 40 % eigen zu 0,288 € ergeben 0,3072 € je kWh."""
    slug = _neues_objekt(client, "Mischhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    _jahresaufteilung(slug, 2025, extern=60.0, eigen=40.0)
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-08-11")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["satz"] == 0.3072
    assert next(z for z in d["nutzer"] if z["name"] == "Marvin")["betrag"] == 30.72


def test_alter_handpreis_an_der_ladung_bewegt_nichts_mehr(client):
    """N148 — `Stromjahr.tanken_preis` und `Tankladung.preis` sind stillgelegt.

    Beide Spalten bleiben stehen (CLAUDE.md: nie entfernen) und tragen hier
    sogar einen Wert: 0,99 € je kWh, über den alten Weg erfasst. Gerechnet
    wird trotzdem mit dem abgeleiteten Satz — ein alter Handwert darf die
    Rechnung nicht mehr bewegen."""
    slug = _neues_objekt(client, "Handpreishaus")
    client.put(f"/api/objekte/{slug}/strom/2025", json={"tanken_preis": 0.99})
    _stromkosten(slug, 2025, betrag=1600.0)
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-08-11")

    # Der alte Wert steht wirklich an der Ladung — sonst prüfte der Test nichts.
    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        ladung = session.exec(select(Tankladung).where(
            Tankladung.objekt_id == o.id)).one()
        assert ladung.preis == 0.99

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["satz"] == 0.32
    marvin = next(z for z in d["nutzer"] if z["name"] == "Marvin")
    assert marvin["satz"] == 0.32 and marvin["betrag"] == 32.0
    assert marvin["ladungen"][0]["preis"] == 0.32


def test_abrechnung_ohne_stromkosten_nennt_den_grund_statt_null(client):
    """Keine Kosten erfasst → kein Satz und keine 0,00 €, sondern die Aussage,
    wodurch der Satz entsteht (N148)."""
    slug = _neues_objekt(client, "Ohnekostenhaus")
    n = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=40.0, datum="2025-08-11")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["satz"] is None and d["satz_netz"] is None
    assert d["betrag_gesamt"] is None
    marvin = next(z for z in d["nutzer"] if z["name"] == "Marvin")
    assert marvin["kwh"] == 40.0             # die Menge steht da
    assert marvin["betrag"] is None          # der Betrag nicht
    assert d["satz_grund"]                   # und es steht dabei, warum

    # Verschickt wird eine Rechnung ohne Preis nicht.
    antwort = client.post(f"/api/tankstelle/{slug}/versand",
                          json={"nutzer_id": n["id"], "jahr": 2025,
                                "quartal": 3})
    assert antwort.status_code == 400
    assert "kein Preis" in antwort.json()["detail"]


def test_ohne_bezogene_menge_nennt_die_luecke_beim_namen(client):
    """Der echte Stand beim Nutzer: der Betrag liegt vor (ein Beleg über
    543,00 €), die bezogene Menge nicht — die SolarEdge-Anteile sind noch
    nicht erfasst.

    Dann fehlt der Nenner, nicht der Zähler. „Die Stromkosten sind noch nicht
    erfasst" wäre an dieser Stelle schlicht falsch, und wer danach sucht,
    sucht am falschen Ort."""
    slug = _neues_objekt(client, "Ohnemengehaus")
    _stromkosten(slug, 2025, betrag=543.0, gesamt_kwh=0.0, netz_kwh=0.0,
                 solar_kwh=0.0, akku_kwh=0.0)
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["satz"] is None
    assert "nicht die bezogene Menge" in d["satz_grund"]
    assert "543,00 €" in d["satz_grund"]        # der Betrag wird genannt
    assert "SolarEdge" in d["satz_grund"]       # und wo die Menge herkommt


def test_satz_kommt_aus_der_periode_mit_der_groessten_ueberschneidung(client):
    """Die Nebenkostenperiode läuft vom 01.10. bis 30.09. — ein Quartal darin
    bekommt den Preis genau dieser Periode, nicht den des Kalenderjahres."""
    slug = _neues_objekt(client, "Periodenhaus")
    _stromkosten(slug, 2024, betrag=1600.0,
                 von=date(2023, 10, 1), bis=date(2024, 9, 30))
    _stromkosten(slug, 2025, betrag=2400.0,
                 von=date(2024, 10, 1), bis=date(2025, 9, 30))
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")

    # Q3 2025 (Jul–Sep) liegt ganz in der jüngeren Periode: 2.400 € / 5.000 kWh.
    neu = client.get(f"/api/tankstelle/{slug}/abrechnung",
                     params={"jahr": 2025, "quartal": 3}).json()
    assert neu["satz_netz"] == 0.48
    # Q3 2024 liegt ganz in der älteren.
    alt = client.get(f"/api/tankstelle/{slug}/abrechnung",
                     params={"jahr": 2024, "quartal": 3}).json()
    assert alt["satz_netz"] == 0.32


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
    _stromkosten(slug, 2025, betrag=1600.0)
    n = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-07-04")

    d = client.get(f"/api/tankstelle/{slug}/vorschau",
                   params={"jahr": 2025, "quartal": 3,
                           "nutzer_id": n["id"]}).json()
    assert d["an"] == "marvin@example.invalid"
    assert d["betrag"] == 16.0
    assert d["satz"] == 0.32
    assert "Hallo Marvin," in d["text"]
    assert "Q3 2025" in d["betreff"]
    # Die Vorschau nennt, woher der Satz kommt — nicht nur die Zahl.
    assert "5.000,00 kWh Netzbezug" in d["text"]

    # Unbekannter Nutzer → 404 statt einer leeren Rechnung.
    assert client.get(f"/api/tankstelle/{slug}/vorschau",
                      params={"jahr": 2025, "quartal": 3,
                              "nutzer_id": 999}).status_code == 404


class _Postfach:
    """Ein Postfach-Doppel: sammelt ein, was verschickt worden wäre — samt
    Anhang, damit sich das Quartals-PDF am Versand prüfen lässt."""

    def __init__(self):
        self.gesendet = []

    def sende(self, an, betreff, text, anhang=None):
        self.gesendet.append((an, betreff, text, anhang))


def test_versand_quartalsweise_geht_an_die_hinterlegte_adresse(client,
                                                               monkeypatch):
    slug = _neues_objekt(client, "Versandhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
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
    an, betreff, text, anhang = postfach.gesendet[0]
    assert an == "marvin@example.invalid"
    assert "Q3 2025" in betreff
    assert "16,00 €" in text
    # N165/2 — das Quartals-PDF hängt als Anhang mit.
    assert anhang is not None
    name, inhalt, subtyp = anhang
    assert subtyp == "pdf" and inhalt[:4] == b"%PDF"
    assert name.lower().endswith(".pdf")
    # Das PDF trägt die Zahlen, die der kurze Mailtext nicht mehr aufzählt.
    assert b"16,00 EUR" in inhalt and b"Q3 2025" in inhalt


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


# --------------------------------------------------------------------------
# 5) N165 — automatische Zuordnung, Übernahme, Quartals-PDF
# --------------------------------------------------------------------------

def test_ein_nutzer_bekommt_automatisch_alle_ladungen(client):
    """Der Kern von N165: ist genau ein Nutzer angelegt, gehören ihm alle
    Ladungen des Zeitraums — auch die, die unter einem anderen Namen erfasst
    wurden. Keine leere Abrechnung mehr trotz geladener kWh."""
    slug = _neues_objekt(client, "Autohaus")
    _stromkosten(slug, 2025, betrag=1600.0)         # 0,32 € je kWh
    _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    # Bewusst unter fremden Namen erfasst — trotzdem Alicias Ladungen.
    _ladung(client, slug, 2025, name="Unbekannt", kwh=30.0, datum="2025-07-04")
    _ladung(client, slug, 2025, name="Gast", kwh=20.0, datum="2025-08-09")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["automatisch"] is True
    assert [z["name"] for z in d["nutzer"]] == ["Alicia"]
    alicia = d["nutzer"][0]
    assert alicia["kwh"] == 50.0 and alicia["betrag"] == 16.0
    assert alicia["automatisch"] is True
    assert d["betrag_gesamt"] == 16.0
    # Keine „nicht angelegt"-Zeile, keine offene Lücke mehr.
    assert all(z["angelegt"] for z in d["nutzer"])
    assert d["offen_kwh"] in (None, 0.0)


def test_zwei_nutzer_bleiben_bei_der_zuordnung_ueber_den_namen(client):
    """Bei mehreren Nutzern greift die Automatik nicht — es bleibt bei der
    Zuordnung über den Namen (die feinere Regel kommt in Teil 2)."""
    slug = _neues_objekt(client, "Zweihaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=40.0, datum="2025-07-04")

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    assert d["automatisch"] is False
    marvin = next(z for z in d["nutzer"] if z["name"] == "Marvin")
    alicia = next(z for z in d["nutzer"] if z["name"] == "Alicia")
    assert marvin["kwh"] == 40.0 and alicia["kwh"] == 0.0


def test_alte_json_nutzerliste_wird_uebernommen(client):
    """Der Bestand lag als JSON in einer Einstellung (Name + E-Mail). Er wird
    einmalig in die Tabelle übernommen; der alte Schlüssel bleibt stehen."""
    import json as _json
    slug = _neues_objekt(client, "Altbestandhaus")
    with Session(db_modul.engine) as session:
        session.add(Einstellung(
            schluessel=f"tankstelle_nutzer:{slug}",
            wert=_json.dumps([{"id": 1, "name": "Alicia",
                               "email": "alicia@example.invalid",
                               "notiz": "Bestand"}])))
        session.commit()

    liste = client.get(f"/api/tankstelle/{slug}/nutzer").json()["nutzer"]
    assert [n["name"] for n in liste] == ["Alicia"]
    assert liste[0]["email"] == "alicia@example.invalid"

    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        tabelle = session.exec(select(Tanknutzer).where(
            Tanknutzer.objekt_id == o.id)).all()
        assert [tn.name for tn in tabelle] == ["Alicia"]
        # Der alte Schlüssel bleibt unangetastet stehen.
        alt = session.get(Einstellung, f"tankstelle_nutzer:{slug}")
        assert alt is not None and "Alicia" in alt.wert

    # Genau einmal: ein danach gelöschter Nutzer taucht nicht wieder auf.
    client.delete(f"/api/tankstelle/{slug}/nutzer/{liste[0]['id']}")
    assert client.get(f"/api/tankstelle/{slug}/nutzer").json()["nutzer"] == []


def test_nutzer_traegt_anschrift_und_bankverbindung(client):
    """N164/N165 — die Versand-Stammdaten (Anschrift, Bankverbindung) lassen
    sich pflegen. Ein nicht mitgeschicktes Feld bleibt bei der Änderung stehen."""
    slug = _neues_objekt(client, "Stammdatenhaus")
    n = client.post(f"/api/tankstelle/{slug}/nutzer", json={
        "name": "Alicia", "email": "alicia@example.invalid",
        "strasse": "Musterweg 3", "plz": "90000", "ort": "Nürnberg",
        "iban": "DE00 0000", "bic": "TESTDEFF", "kontoinhaber": "Alicia M."})
    assert n.status_code == 201, n.text
    d = n.json()
    assert d["strasse"] == "Musterweg 3" and d["ort"] == "Nürnberg"
    assert d["iban"] == "DE00 0000" and d["bic"] == "TESTDEFF"
    assert d["kontoinhaber"] == "Alicia M."

    g = client.put(f"/api/tankstelle/{slug}/nutzer/{d['id']}",
                   json={"ort": "Fürth"})
    assert g.status_code == 200
    assert g.json()["ort"] == "Fürth"
    assert g.json()["strasse"] == "Musterweg 3"     # unberührt
    assert g.json()["name"] == "Alicia"


def test_quartalsabrechnung_ueber_die_jahresgrenze(client):
    """Ein Zeitraum über 2025/2026, quartalsweise abgerechnet: Q4 2025 und
    Q1 2026 tragen je ihre eigenen Ladungen — sauber am Jahreswechsel getrennt."""
    slug = _neues_objekt(client, "Jahreswechselhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    _stromkosten(slug, 2026, betrag=1600.0)
    _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _ladung(client, slug, 2025, name="Alicia", kwh=40.0, datum="2025-12-20")
    _ladung(client, slug, 2026, name="Alicia", kwh=60.0, datum="2026-01-15")

    q4 = client.get(f"/api/tankstelle/{slug}/abrechnung",
                    params={"jahr": 2025, "quartal": 4}).json()
    assert q4["label"] == "Q4 2025"
    assert (q4["von"], q4["bis"]) == ("2025-10-01", "2025-12-31")
    assert q4["kwh_gesamt"] == 40.0

    q1 = client.get(f"/api/tankstelle/{slug}/abrechnung",
                    params={"jahr": 2026, "quartal": 1}).json()
    assert q1["label"] == "Q1 2026"
    assert (q1["von"], q1["bis"]) == ("2026-01-01", "2026-03-31")
    assert q1["kwh_gesamt"] == 60.0


def test_test_pdf_entsteht_und_nennt_die_zahlen(client):
    """Das Test-PDF ohne Versand: es entsteht, ist ein PDF und trägt die Zahlen,
    die den Nutzer angehen — Anschrift, Menge, Satz, Rechnungsbetrag."""
    slug = _neues_objekt(client, "PDFhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    n = client.post(f"/api/tankstelle/{slug}/nutzer", json={
        "name": "Alicia", "email": "alicia@example.invalid",
        "strasse": "Musterweg 3", "plz": "90000", "ort": "Nürnberg"}).json()
    _ladung(client, slug, 2025, name="Alicia", kwh=50.0, datum="2025-07-04")

    antwort = client.get(f"/api/tankstelle/{slug}/abrechnung.pdf",
                         params={"jahr": 2025, "quartal": 3,
                                 "nutzer_id": n["id"]})
    assert antwort.status_code == 200, antwort.text
    assert antwort.headers["content-type"] == "application/pdf"
    roh = antwort.content
    assert roh[:4] == b"%PDF"
    assert b"Alicia" in roh
    assert b"Musterweg 3" in roh
    assert "Nürnberg".encode("cp1252") in roh
    assert b"Q3 2025" in roh
    assert b"50,00 kWh" in roh              # geladene Menge
    assert b"0,3200 EUR je kWh" in roh      # der abgeleitete Satz
    assert b"16,00 EUR" in roh              # der Rechnungsbetrag


def test_kein_pdf_ohne_rechnungsbetrag(client):
    """Kein PDF über 0 €: wer nichts geladen hat oder ohne abgeleiteten Satz
    dasteht, bekommt eine Begründung statt eines leeren Blattes."""
    slug = _neues_objekt(client, "NullPDFhaus")
    n = _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _stromkosten(slug, 2025, betrag=1600.0)
    ohne = client.get(f"/api/tankstelle/{slug}/abrechnung.pdf",
                      params={"jahr": 2025, "quartal": 3, "nutzer_id": n["id"]})
    assert ohne.status_code == 400
    assert "nichts geladen" in ohne.json()["detail"]

    # Geladen, aber ohne Stromkosten → kein Satz → kein PDF.
    slug2 = _neues_objekt(client, "NullPDFhaus2")
    n2 = _nutzer(client, slug2, "Alicia", "alicia@example.invalid")
    _ladung(client, slug2, 2025, name="Alicia", kwh=10.0, datum="2025-07-04")
    ohne2 = client.get(f"/api/tankstelle/{slug2}/abrechnung.pdf",
                       params={"jahr": 2025, "quartal": 3, "nutzer_id": n2["id"]})
    assert ohne2.status_code == 400


def test_unbekanntes_objekt_meldet_404(client):
    assert client.get("/api/tankstelle/gibtsnicht/nutzer").status_code == 404
    assert client.get("/api/tankstelle/gibtsnicht/verlauf").status_code == 404


# --------------------------------------------------------------------------
# 6) N165 Teil 2 — Autoversand, doppelter Versand, Mehrnutzer-Zuordnung
# --------------------------------------------------------------------------

def test_faelliges_quartal_einen_tag_nach_quartalsende():
    """Ausgelöst wird einen Tag nach Quartalsende; danach nur noch im
    Nachhol-Fenster, nie mitten im Quartal."""
    assert t.faelliges_quartal(date(2025, 4, 1)) == (2025, 1)
    assert t.faelliges_quartal(date(2025, 7, 1)) == (2025, 2)
    assert t.faelliges_quartal(date(2025, 10, 1)) == (2025, 3)
    # Der Jahreswechsel: am 01.01. steht das Q4 des Vorjahres an.
    assert t.faelliges_quartal(date(2026, 1, 1)) == (2025, 4)
    # Im Nachhol-Fenster noch fällig …
    assert t.faelliges_quartal(date(2025, 7, 15)) == (2025, 2)
    # … danach nicht mehr, und mitten im Quartal ohnehin nicht.
    assert t.faelliges_quartal(date(2025, 7, 25)) is None
    assert t.faelliges_quartal(date(2025, 8, 15)) is None


def test_zuordnen_ueber_zeitraum_ohne_jede_ladung_anzuklicken():
    """Die reine Logik: eine Zeitraum-Regel je Nutzer verteilt alle Ladungen —
    keine Pflicht, jede einzeln zuzubuchen. Bei Überlappung gewinnt der spätere
    Beginn."""
    nutzer = [{"id": 1, "name": "Alicia", "email": "a@example.invalid"},
              {"id": 2, "name": "Marvin", "email": "m@example.invalid"}]
    rohe = [t.RohLadung(10, date(2025, 7, 10), "Unbekannt", "", 30.0),
            t.RohLadung(11, date(2025, 8, 20), "Unbekannt", "", 20.0),
            t.RohLadung(12, date(2025, 9, 25), "Unbekannt", "", 40.0)]
    regeln = [{"nutzer_id": 1, "von": date(2025, 7, 1), "bis": date(2025, 8, 31)},
              {"nutzer_id": 2, "von": date(2025, 9, 1), "bis": date(2025, 9, 30)}]
    buch = t.zuordnen(rohe, nutzer, regeln, set())
    je = {}
    for b in buch:
        je[b.person] = je.get(b.person, 0.0) + b.kwh
    assert je == {"Alicia": 50.0, "Marvin": 40.0}

    # Überlappung: die Regel mit dem späteren Beginn gewinnt.
    ueberlappend = [
        {"nutzer_id": 1, "von": date(2025, 7, 1), "bis": date(2025, 9, 30)},
        {"nutzer_id": 2, "von": date(2025, 8, 1), "bis": date(2025, 9, 30)}]
    buch2 = t.zuordnen([t.RohLadung(20, date(2025, 8, 15), "x", "", 5.0)],
                       nutzer, ueberlappend, set())
    assert buch2[0].person == "Marvin"

    # Ohne passende Regel bleibt es bei der Zuordnung über den Namen.
    buch3 = t.zuordnen([t.RohLadung(30, date(2025, 12, 1), "Alicia", "", 7.0)],
                       nutzer, regeln, set())
    assert buch3[0].person == "Alicia"


def test_zuordnen_schliesst_einzelne_ladung_aus():
    nutzer = [{"id": 1, "name": "Alicia", "email": "a@example.invalid"}]
    rohe = [t.RohLadung(10, date(2025, 7, 10), "Alicia", "", 30.0),
            t.RohLadung(11, date(2025, 8, 20), "Alicia", "", 20.0)]
    buch = t.zuordnen(rohe, nutzer, [], {11})
    assert len(buch) == 1 and buch[0].kwh == 30.0


def test_autoversand_schalter_ist_standardmaessig_aus(client):
    slug = _neues_objekt(client, "Schalterhaus")
    d = client.get(f"/api/tankstelle/{slug}/einstellungen").json()
    assert d["autoversand"] is False
    assert d["regeln"] == [] and d["ausschluss"] == []

    r = client.put(f"/api/tankstelle/{slug}/autoversand", json={"aktiv": True})
    assert r.status_code == 200 and r.json()["autoversand"] is True
    assert client.get(f"/api/tankstelle/{slug}/einstellungen"
                      ).json()["autoversand"] is True

    client.put(f"/api/tankstelle/{slug}/autoversand", json={"aktiv": False})
    assert client.get(f"/api/tankstelle/{slug}/einstellungen"
                      ).json()["autoversand"] is False


def test_autoversand_schickt_einmal_und_nie_erneut(client, monkeypatch):
    """Die wichtigste Zusicherung: der 15-Minuten-Wachdienst schickt ein
    bereits verschicktes Quartal beim zweiten Lauf nicht erneut."""
    slug = _neues_objekt(client, "Autoversandhaus")
    _stromkosten(slug, 2025, betrag=1600.0)                 # 0,32 € je kWh
    _nutzer(client, slug, "Marvin", "auto-marvin@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-08-11")
    assert client.put(f"/api/tankstelle/{slug}/autoversand",
                      json={"aktiv": True}).json()["autoversand"] is True

    postfach = _Postfach()
    monkeypatch.setattr(t, "zugang", lambda session: postfach)

    def _mails():
        return [g for g in postfach.gesendet
                if g[0] == "auto-marvin@example.invalid"]

    # Tag nach Q3-Ende (30.09.) → Q3 2025 ist fällig.
    with Session(db_modul.engine) as s:
        erg1 = t.versand_faellig_pruefen(s, heute=date(2025, 10, 1))
    assert erg1["faellig"] is True and (erg1["jahr"], erg1["quartal"]) == (2025, 3)
    assert len(_mails()) == 1
    an, betreff, text, anhang = _mails()[0]
    assert "Q3 2025" in betreff
    name, inhalt, subtyp = anhang
    assert subtyp == "pdf" and inhalt[:4] == b"%PDF"

    # Zweiter Wachdienst-Lauf im selben Fenster: kein erneuter Versand.
    with Session(db_modul.engine) as s:
        erg2 = t.versand_faellig_pruefen(s, heute=date(2025, 10, 1))
    assert erg2["versendet"] == 0
    assert len(_mails()) == 1


def test_autoversand_bleibt_bei_ausgeschaltetem_schalter_stumm(client,
                                                               monkeypatch):
    slug = _neues_objekt(client, "AutoStummhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    _nutzer(client, slug, "Marvin", "stumm@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-08-11")
    # Schalter NICHT eingeschaltet (Default aus).
    postfach = _Postfach()
    monkeypatch.setattr(t, "zugang", lambda session: postfach)
    with Session(db_modul.engine) as s:
        t.versand_faellig_pruefen(s, heute=date(2025, 10, 1))
    assert [g for g in postfach.gesendet if g[0] == "stumm@example.invalid"] == []


def test_autoversand_schickt_nichts_bei_null_euro_oder_ohne_satz(client,
                                                                 monkeypatch):
    """Lieber nichts als eine Rechnung über nichts: kein Satz (keine
    Stromkosten) und keine Ladung führen beide zu keinem Versand."""
    # a) Geladen, aber ohne Stromkosten → kein Satz → kein Versand.
    slug = _neues_objekt(client, "AutoOhnesatzhaus")
    _nutzer(client, slug, "Marvin", "ohnesatz@example.invalid")
    _ladung(client, slug, 2025, name="Marvin", kwh=50.0, datum="2025-08-11")
    client.put(f"/api/tankstelle/{slug}/autoversand", json={"aktiv": True})

    # b) Satz vorhanden, aber der Nutzer hat nichts geladen → 0 € → kein Versand.
    slug2 = _neues_objekt(client, "AutoNullhaus")
    _stromkosten(slug2, 2025, betrag=1600.0)
    _nutzer(client, slug2, "Leer", "leer@example.invalid")
    client.put(f"/api/tankstelle/{slug2}/autoversand", json={"aktiv": True})

    postfach = _Postfach()
    monkeypatch.setattr(t, "zugang", lambda session: postfach)
    with Session(db_modul.engine) as s:
        t.versand_faellig_pruefen(s, heute=date(2025, 10, 1))
    adressen = [g[0] for g in postfach.gesendet]
    assert "ohnesatz@example.invalid" not in adressen
    assert "leer@example.invalid" not in adressen


def test_mehrnutzer_zuordnung_ueber_zeitraum_in_der_abrechnung(client):
    """Bei mehreren Nutzern verteilt eine Zeitraum-Regel je Nutzer alle
    Ladungen — auch die unter fremdem Namen erfassten."""
    slug = _neues_objekt(client, "Zeitraumhaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    a = _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    m = _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    _ladung(client, slug, 2025, name="Unbekannt", kwh=30.0, datum="2025-07-10")
    _ladung(client, slug, 2025, name="Unbekannt", kwh=20.0, datum="2025-08-20")
    _ladung(client, slug, 2025, name="Unbekannt", kwh=40.0, datum="2025-09-25")

    r = client.put(f"/api/tankstelle/{slug}/zuordnung", json={"regeln": [
        {"nutzer_id": a["id"], "von": "2025-07-01", "bis": "2025-08-31"},
        {"nutzer_id": m["id"], "von": "2025-09-01", "bis": "2025-09-30"}]})
    assert r.status_code == 200, r.text

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    alicia = next(z for z in d["nutzer"] if z["name"] == "Alicia")
    marvin = next(z for z in d["nutzer"] if z["name"] == "Marvin")
    assert alicia["kwh"] == 50.0          # 30 + 20, ohne Einzelbuchung
    assert marvin["kwh"] == 40.0
    assert d["offen_kwh"] in (None, 0.0)  # nichts bleibt offen


def test_zuordnung_ladung_ausschliessen_in_der_abrechnung(client):
    slug = _neues_objekt(client, "Ausschlusshaus")
    _stromkosten(slug, 2025, betrag=1600.0)
    a = _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")   # zweiter Nutzer
    _ladung(client, slug, 2025, name="Unbekannt", kwh=30.0, datum="2025-07-10")
    l2 = _ladung(client, slug, 2025, name="Unbekannt", kwh=20.0,
                 datum="2025-08-20")

    r = client.put(f"/api/tankstelle/{slug}/zuordnung", json={
        "regeln": [{"nutzer_id": a["id"], "von": "2025-07-01",
                    "bis": "2025-09-30"}],
        "ausschluss": [l2["id"]]})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/tankstelle/{slug}/einstellungen"
                      ).json()["ausschluss"] == [l2["id"]]

    d = client.get(f"/api/tankstelle/{slug}/abrechnung",
                   params={"jahr": 2025, "quartal": 3}).json()
    alicia = next(z for z in d["nutzer"] if z["name"] == "Alicia")
    assert alicia["kwh"] == 30.0          # die ausgeschlossene Ladung fehlt
    assert d["geladen_kwh"] == 50.0
    assert d["offen_kwh"] == 20.0         # sie steht als offen da


def test_zuordnung_lehnt_kaputten_zeitraum_und_fremden_nutzer_ab(client):
    slug = _neues_objekt(client, "Regelpruefhaus")
    a = _nutzer(client, slug, "Alicia", "alicia@example.invalid")
    _nutzer(client, slug, "Marvin", "marvin@example.invalid")
    # Ende vor Beginn.
    schlecht = client.put(f"/api/tankstelle/{slug}/zuordnung", json={"regeln": [
        {"nutzer_id": a["id"], "von": "2025-09-30", "bis": "2025-07-01"}]})
    assert schlecht.status_code == 400
    # Unbekannter Nutzer.
    fremd = client.put(f"/api/tankstelle/{slug}/zuordnung", json={"regeln": [
        {"nutzer_id": 99999, "von": "2025-07-01", "bis": "2025-09-30"}]})
    assert fremd.status_code == 400
