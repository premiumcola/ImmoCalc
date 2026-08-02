"""N130 — das openWB-Ladeprotokoll lesen und auswerten.

Geprüft wird die reine Logik (`app/openwb.py`) an **echten Zeilen** aus dem
Protokoll der Wallbox — als Text hier eingebettet. **Kein Test geht ins Netz**:
die Box steht im Heimnetz, ein Testlauf darf nicht davon abhängen, ob sie
gerade an ist.

Kontrollzahlen des Nutzers für das Kalenderjahr 2025 (gegen die echte Datei
nachgerechnet, hier im Ausschnitt nachgebildet):

    111 Ladungen · 1991,03 kWh · 580,70 €
      Netz (extern)  1024,82 kWh  51,5 %
      Speicher        450,09 kWh  22,6 %
      PV direkt       492,82 kWh  24,8 %  + 23,31 Rest = 516,13 kWh
      => Netz + PV + Speicher == 1991,03 kWh

Seit N143 sind **Netz, PV und Speicher drei eigene Blöcke** — der Nutzer
rechnet seine Stromkosten über genau diese drei. Und was die Wallbox keinem
Anteil zuordnet, zählt zum PV-Block: die drei Blöcke ergeben wieder die volle
Energiemenge, und `rest_kwh` sagt, wie viel auf diesem Weg dazukam.

Wichtig ist der Zuschnitt nach **Abrechnungszeitraum** (z. B. 01.10.2024 bis
30.09.2025), nicht nach Kalenderjahr — deshalb der Filter über das Datum.
"""
import os
import sys
import tempfile
from datetime import date, datetime

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_openwb.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import openwb  # noqa: E402
from app.main import app  # noqa: E402

# Der Kopf, wie ihn die Wallbox schreibt — alle 27 Spalten, damit belegt ist,
# dass die vielen ungenutzten Spalten nicht stören.
KOPF = ('"Beginn";"Ende";"Zeitstempel Beginn";"Zeitstempel Ende";"Dauer";'
        '"Kosten";"Energieanteil Netz";"Energieanteil Ladepunkte";'
        '"Energieanteil Speicher";"Energieanteil PV";"Fahrzeug";"Fahrzeug-ID";'
        '"Lademodus";"Priorität";"ID-Tag";"SoC Beginn";"SoC Ende";'
        '"Reichweite Beginn";"Reichweite Ende";"Ladepunkt";"Ladepunkt-ID";'
        '"Zähler Seriennummer";"Energie";"Reichweite";"Zählerstand Beginn";'
        '"Zählerstand Ende";"Energie seit Anstecken"')

# Vier echte Zeilen aus dem Protokoll des Nutzers.
Z1 = ('"18.02.2025, 09:45:11";"18.02.2025, 15:03:34";1739868311;1739887414;'
      '"5:18";0,14;2,20;0,00;0,03;97,77;"Standard-Fahrzeug";0;"Sofort";"Nein";'
      ';;;;;"Interne openWB";4;"21938535";0,49;3;176,34;176,83;0,49')
Z2 = ('"20.02.2025, 17:52:21";"21.02.2025, 08:05:05";1740070341;1740121505;'
      '"14:12";2,30;99,68;0,00;0,01;0,31;"Standard-Fahrzeug";0;"Sofort";"Nein";'
      ';;;;;"Interne openWB";4;"21938535";34,12;201;176,83;210,95;34,12')
Z3 = ('"25.02.2025, 18:16:31";"27.02.2025, 06:54:25";1740503791;1740635665;'
      '"36:37";9,72;88,63;0,00;5,75;5,62;"Standard-Fahrzeug";0;"Sofort";"Nein";'
      ';;;;;"Interne openWB";4;"21938535";31,24;184;210,95;242,19;31,24')
Z4 = ('"03.09.2025, 18:14:02";"04.09.2025, 07:02:34";1756916042;1756962154;'
      '"12:48";4,21;53,70;0,00;40,65;5,65;"Standard-Fahrzeug";0;"Sofort";"Ja";'
      ';;;;;"Interne openWB";4;"21938535";13,83;81;1305,66;1319,48;13,83')

PROTOKOLL = "\n".join([KOPF, Z1, Z2, Z3, Z4]) + "\n"


def _zeile(beginn: str, kosten: str, netz: str, ladepunkte: str,
           speicher: str, pv: str, energie: str) -> str:
    """Eine Protokollzeile im openWB-Format — für die Sonderfälle."""
    return (f'"{beginn}";"{beginn}";1739868311;1739887414;"1:00";{kosten};'
            f'{netz};{ladepunkte};{speicher};{pv};"Standard-Fahrzeug";0;'
            f'"Sofort";"Nein";;;;;;"Interne openWB";4;"21938535";{energie};'
            f'3;176,34;176,83;{energie}')


def _datei(*zeilen: str, kopf: str = KOPF) -> str:
    return "\n".join([kopf, *zeilen]) + "\n"


# --------------------------------------------------------------------------
# Deutsches Zahlenformat
# --------------------------------------------------------------------------

def test_dezimalkomma():
    """Die Werte kommen mit Komma — „4,21" sind 4,21 und nicht 421."""
    assert openwb.zahl("4,21") == 4.21
    assert openwb.zahl("0,00") == 0.0
    assert openwb.zahl("53,70") == 53.70
    # Mit Tausenderpunkt, falls die Box einmal vierstellig wird.
    assert openwb.zahl("1.024,82") == 1024.82
    assert openwb.zahl("81") == 81.0


def test_kaputte_zahl_wird_nicht_zu_null():
    """Unlesbares ergibt ``None`` — eine 0 sähe aus wie eine Messung."""
    assert openwb.zahl("") is None
    assert openwb.zahl("   ") is None
    assert openwb.zahl("abc") is None
    assert openwb.zahl("-") is None


def test_zeitpunkt_aus_klartext_und_notfalls_aus_dem_stempel():
    assert openwb.zeitpunkt("03.09.2025, 18:14:02") == datetime(2025, 9, 3, 18, 14, 2)
    # Klartext unbrauchbar → der Unix-Zeitstempel trägt die Auswertung weiter.
    aus_stempel = openwb.zeitpunkt("kaputt", "1756916042")
    assert aus_stempel is not None and aus_stempel.year == 2025
    assert openwb.zeitpunkt("", "") is None


# --------------------------------------------------------------------------
# Die Summen — die Rechnung, auf die es ankommt
# --------------------------------------------------------------------------

def test_summen_ueber_den_ausschnitt():
    """Energie × Anteil, aufgeteilt in zugekauft und eigen.

    extern = „Energieanteil Netz", eigen = Speicher + PV."""
    p = openwb.lies(PROTOKOLL)
    assert len(p.ladungen) == 4
    assert p.warnungen == []

    s = openwb.summiere(p.ladungen, date(2025, 1, 1), date(2025, 12, 31))
    assert s.anzahl == 4
    assert s.kwh == 79.68                      # 0,49 + 34,12 + 31,24 + 13,83
    assert s.kosten == 16.37                   # 0,14 + 2,30 + 9,72 + 4,21
    assert s.extern_kwh == 69.14
    assert s.speicher_kwh == 7.42
    assert s.pv_kwh == 3.12
    assert s.eigen_kwh == 10.54                # Speicher + PV
    assert s.ladepunkte_kwh == 0.0
    # Die vier Töpfe ergeben zusammen wieder die Gesamtmenge.
    assert s.nicht_zugeordnet_kwh == 0.0
    assert round(s.extern_kwh + s.eigen_kwh, 2) == s.kwh


def test_anteile_in_prozent():
    p = openwb.lies(PROTOKOLL)
    d = openwb.summiere(p.ladungen, date(2025, 1, 1), date(2025, 12, 31)).als_dict()
    assert d["extern_prozent"] == 86.8
    assert d["eigen_prozent"] == 13.2
    assert round(d["extern_prozent"] + d["eigen_prozent"], 1) == 100.0


def test_eine_einzelne_ladung_wird_richtig_aufgeteilt():
    """Die Beispielzeile: 13,83 kWh, 53,70 % Netz, 40,65 % Speicher, 5,65 % PV."""
    ladung = openwb.lies(_datei(Z4)).ladungen[0]
    assert ladung.beginn == datetime(2025, 9, 3, 18, 14, 2)
    assert ladung.ende == datetime(2025, 9, 4, 7, 2, 34)
    assert ladung.tag == date(2025, 9, 3)
    assert ladung.kwh == 13.83
    assert ladung.kosten == 4.21
    assert round(ladung.extern_kwh, 2) == 7.43       # 13,83 × 53,70 %
    assert round(ladung.speicher_kwh, 2) == 5.62     # 13,83 × 40,65 %
    assert round(ladung.pv_kwh, 2) == 0.78           # 13,83 × 5,65 %
    assert round(ladung.eigen_kwh, 2) == 6.40        # Speicher + PV
    assert ladung.ladepunkte_kwh == 0.0


# --------------------------------------------------------------------------
# Zuschnitt nach Abrechnungszeitraum, über die Jahresgrenze hinweg
# --------------------------------------------------------------------------

JAHRESWECHSEL = _datei(
    _zeile("15.12.2024, 10:00:00", "3,00", "100,00", "0,00", "0,00", "0,00", "10,00"),
    _zeile("05.01.2025, 10:00:00", "0,00", "0,00", "0,00", "50,00", "50,00", "20,00"),
    _zeile("20.10.2025, 10:00:00", "1,50", "100,00", "0,00", "0,00", "0,00", "5,00"),
)


def test_zeitraum_geht_ueber_die_jahresgrenze():
    """01.10.2024–30.09.2025: die Dezember- und die Januar-Ladung zählen,
    die vom 20.10.2025 nicht — gefiltert wird nach Datum, nicht nach Jahr."""
    p = openwb.lies(JAHRESWECHSEL)
    s = openwb.summiere(p.ladungen, date(2024, 10, 1), date(2025, 9, 30))
    assert s.anzahl == 2
    assert s.kwh == 30.0
    assert s.extern_kwh == 10.0                 # nur die Dezember-Ladung
    assert s.eigen_kwh == 20.0                  # 50 % Speicher + 50 % PV
    assert s.kosten == 3.0


def test_kalenderjahr_liefert_andere_ladungen_als_die_periode():
    p = openwb.lies(JAHRESWECHSEL)
    kalender = openwb.summiere(p.ladungen, date(2025, 1, 1), date(2025, 12, 31))
    assert kalender.anzahl == 2                 # Januar + Oktober
    assert kalender.kwh == 25.0


def test_raender_zaehlen_mit():
    p = openwb.lies(JAHRESWECHSEL)
    s = openwb.summiere(p.ladungen, date(2024, 12, 15), date(2025, 1, 5))
    assert s.anzahl == 2


def test_welche_jahresdateien_gebraucht_werden():
    assert openwb.jahre(date(2024, 10, 1), date(2025, 9, 30)) == [2024, 2025]
    assert openwb.jahre(date(2025, 1, 1), date(2025, 12, 31)) == [2025]
    with pytest.raises(openwb.OpenwbFehler):
        openwb.jahre(date(2025, 9, 30), date(2024, 10, 1))


def test_doppelte_ladung_aus_zwei_jahresdateien_zaehlt_einmal():
    """Holt man zwei Jahre, darf eine Ladung, die in beiden Dateien steht,
    nicht doppelt in die Summe gehen."""
    eins = openwb.lies(PROTOKOLL).ladungen
    zwei = openwb.lies(PROTOKOLL).ladungen
    zusammen = openwb.zusammenfuehren(eins, zwei)
    assert len(zusammen) == 4
    assert zusammen == sorted(zusammen, key=lambda l: l.beginn)


# --------------------------------------------------------------------------
# „Energieanteil Ladepunkte" — getrennt geführt, nie stillschweigend verteilt
# --------------------------------------------------------------------------

def test_ladepunkte_anteil_wird_getrennt_gefuehrt_und_gemeldet():
    """War bisher immer 0. Ist er es einmal nicht, wird gewarnt statt geraten."""
    datei = _datei(_zeile("10.05.2025, 10:00:00", "5,00",
                          "60,00", "10,00", "20,00", "10,00", "100,00"))
    s = openwb.summiere(openwb.lies(datei).ladungen,
                        date(2025, 1, 1), date(2025, 12, 31))
    assert s.extern_kwh == 60.0
    assert s.eigen_kwh == 30.0                  # 20 Speicher + 10 PV
    assert s.ladepunkte_kwh == 10.0             # in keinem der beiden Töpfe
    assert any("Ladepunkte" in w for w in s.warnungen)


def test_ohne_ladepunkte_keine_warnung():
    s = openwb.summiere(openwb.lies(PROTOKOLL).ladungen,
                        date(2025, 1, 1), date(2025, 12, 31))
    assert s.ladepunkte_kwh == 0.0
    assert s.warnungen == []


def test_nicht_zugeordnete_energie_zaehlt_zum_pv_block():
    """Im echten Protokoll steht eine Ladung mit 23,31 kWh und vier Anteilen
    von 0 % (26.09.2025).

    Seit N143 zählt diese Energie zum PV-Block — eine Entscheidung des
    Nutzers. Nachvollziehbar bleibt sie über `rest_kwh`; ein eigener Topf
    „nicht zugeordnet" entsteht nicht mehr, und es wird auch nicht gewarnt:
    die Menge ist zugeordnet, nur eben per Regel."""
    datei = _datei(_zeile("26.09.2025, 15:57:31", "0,00",
                          "0,00", "0,00", "0,00", "0,00", "23,31"))
    p = openwb.lies(datei)
    ladung = p.ladungen[0]
    assert ladung.pv_kwh == 23.31
    assert ladung.rest_kwh == 23.31
    assert ladung.speicher_kwh == 0.0 and ladung.extern_kwh == 0.0

    s = openwb.summiere(p.ladungen, date(2025, 1, 1), date(2025, 12, 31),
                        p.warnungen)
    assert s.kwh == 23.31
    assert s.pv_kwh == 23.31 and s.rest_kwh == 23.31
    assert s.extern_kwh == 0.0 and s.speicher_kwh == 0.0
    assert s.eigen_kwh == 23.31
    # Die drei Blöcke ergeben wieder die volle Menge.
    assert round(s.extern_kwh + s.pv_kwh + s.speicher_kwh, 2) == s.kwh
    assert s.nicht_zugeordnet_kwh == 0.0
    assert s.warnungen == []


def test_die_drei_bloecke_ergeben_die_volle_energiemenge():
    """Netz · PV · Akku sind drei eigene Töpfe (N143) und lassen nichts übrig.

    Gemischt: eine saubere Ladung, eine mit 0 % in allen Anteilen und eine, in
    der nur ein Teil zugeordnet ist."""
    datei = _datei(
        _zeile("02.03.2025, 08:00:00", "1,00", "50,00", "0,00", "30,00",
               "20,00", "40,00"),
        _zeile("03.03.2025, 08:00:00", "0,00", "0,00", "0,00", "0,00",
               "0,00", "10,00"),
        _zeile("04.03.2025, 08:00:00", "1,00", "40,00", "0,00", "10,00",
               "0,00", "50,00"),
    )
    s = openwb.summiere(openwb.lies(datei).ladungen,
                        date(2025, 1, 1), date(2025, 12, 31))
    assert s.kwh == 100.0
    assert s.extern_kwh == 40.0                 # 20 + 0 + 20
    assert s.speicher_kwh == 17.0               # 12 + 0 + 5
    # PV: 8 direkt + 10 Rest + 25 Rest = 43
    assert s.pv_kwh == 43.0
    assert s.rest_kwh == 35.0
    assert s.eigen_kwh == 60.0                  # PV + Speicher
    assert round(s.extern_kwh + s.pv_kwh + s.speicher_kwh, 2) == s.kwh
    assert s.nicht_zugeordnet_kwh == 0.0
    d = s.als_dict()
    assert d["pv_prozent"] == 43.0 and d["speicher_prozent"] == 17.0
    assert d["rest_prozent"] == 35.0


def test_negativer_pv_anteil_der_box_bleibt_stehen():
    """Am 11.04.2025 schrieb die Box 164 % Speicher gegen −115,81 % PV.

    In der Summe ergibt das genau 100 %. Den negativen PV-Wert auf 0 zu heben
    würde `Netz + PV + Speicher` über die geladene Menge treiben — die
    Aufteilung der Box bleibt deshalb stehen."""
    datei = _datei(_zeile("11.04.2025, 14:46:32", "1,94", "51,81", "0,00",
                          "164,00", "-115,81", "6,68"))
    s = openwb.summiere(openwb.lies(datei).ladungen,
                        date(2025, 1, 1), date(2025, 12, 31))
    assert s.kwh == 6.68
    assert s.pv_kwh < 0                          # so steht es im Protokoll
    assert s.rest_kwh == 0.0                     # es fehlt nichts
    assert round(s.extern_kwh + s.pv_kwh + s.speicher_kwh, 2) == s.kwh
    assert s.warnungen == []


def test_ladung_ohne_energie_zaehlt_nicht_als_ladung():
    """Angesteckt, nichts geflossen — das ist keine Ladung, wird aber auch
    nicht verschwiegen."""
    datei = _datei(Z4, _zeile("23.07.2025, 19:21:32", "0,00",
                              "0,00", "0,00", "0,00", "0,00", "0,00"))
    s = openwb.summiere(openwb.lies(datei).ladungen,
                        date(2025, 1, 1), date(2025, 12, 31))
    assert s.anzahl == 1
    assert s.ohne_energie == 1


# --------------------------------------------------------------------------
# Robustheit — jeder Ausfall wird eine verständliche Meldung
# --------------------------------------------------------------------------

def test_leere_antwort():
    for leer in ("", "   ", "\n\n"):
        with pytest.raises(openwb.OpenwbFehler) as fehler:
            openwb.lies(leer)
        assert "leer" in str(fehler.value).lower()


def test_html_statt_csv():
    """Falsche Adresse oder Anmeldeseite — kein Absturz, sondern eine Ansage."""
    seite = ("<!DOCTYPE html>\n<html><head><title>openWB</title></head>"
             "<body>Login</body></html>")
    with pytest.raises(openwb.OpenwbFehler) as fehler:
        openwb.lies(seite)
    assert "HTML" in str(fehler.value)


def test_fehlende_spalte_wird_benannt():
    """Benennt openWB eine Spalte um, muss man das aus der Meldung erkennen."""
    ohne_pv = KOPF.replace(';"Energieanteil PV"', ';"Energieanteil Sonne"')
    with pytest.raises(openwb.OpenwbFehler) as fehler:
        openwb.lies(_datei(Z4, kopf=ohne_pv))
    text = str(fehler.value)
    assert "Energieanteil PV" in text          # welche fehlt
    assert "Energieanteil Sonne" in text       # und was stattdessen dastand


def test_kaputte_zahl_uebergeht_die_zeile_und_meldet_sie():
    """Eine unlesbare Zahl darf weder werfen noch als 0 durchgehen — die
    Zeile fällt heraus und wird benannt."""
    datei = _datei(Z4, _zeile("11.11.2025, 08:00:00", "1,00",
                              "100,00", "0,00", "0,00", "0,00", "keine Zahl"))
    p = openwb.lies(datei)
    assert len(p.ladungen) == 1                # nur die gute Zeile
    assert p.ladungen[0].kwh == 13.83
    assert any("Energie" in w and "11.11.2025" in w for w in p.warnungen)


def test_unlesbarer_beginn_uebergeht_die_zeile():
    kaputt = ('"";"";0;0;"1:00";1,00;100,00;0,00;0,00;0,00;"X";0;"Sofort";'
              '"Nein";;;;;;"Interne openWB";4;"21938535";5,00;3;1,00;6,00;5,00')
    p = openwb.lies(_datei(Z4, kaputt))
    assert len(p.ladungen) == 1
    assert any("Beginn" in w for w in p.warnungen)


def test_nur_der_kopf_ohne_zeilen():
    """Ein Jahr ohne Ladungen ist kein Fehler — nur eine leere Auswertung."""
    p = openwb.lies(KOPF + "\n")
    assert p.ladungen == []
    s = openwb.summiere(p.ladungen, date(2025, 1, 1), date(2025, 12, 31))
    assert s.anzahl == 0 and s.kwh == 0.0 and s.kosten == 0.0


def test_zeitraum_rueckwaerts():
    with pytest.raises(openwb.OpenwbFehler):
        openwb.summiere([], date(2025, 9, 30), date(2025, 1, 1))


# --------------------------------------------------------------------------
# Adresse der Box
# --------------------------------------------------------------------------

def test_adresse_normalisieren():
    assert openwb.normalisiere_basis("192.168.178.61") == "http://192.168.178.61"
    assert openwb.normalisiere_basis("192.168.178.61:80") == "http://192.168.178.61:80"
    assert openwb.normalisiere_basis("  http://192.168.178.61/  ") == "http://192.168.178.61"
    # Aus dem Browser kopiert — der Pfad der Oberfläche fällt weg.
    assert openwb.normalisiere_basis(
        "http://192.168.178.61/openWB/web/settings/") == "http://192.168.178.61"
    assert openwb.normalisiere_basis("wallbox.fritz.box") == "http://wallbox.fritz.box"


def test_unbrauchbare_adresse_ergibt_leer():
    """Was keine Adresse sein kann, darf gar nicht erst zur HTTP-Bibliothek."""
    for unsinn in ("", "   ", "!!!", "http://", "ftp://192.168.178.61",
                   "192.168.178.61 mit leerzeichen", "http://:8080"):
        assert openwb.normalisiere_basis(unsinn) == ""
    # Ein angehängter Pfad ist dagegen kein Fehler — er wird abgeschnitten.
    assert openwb.normalisiere_basis(
        "192.168.178.61/openWB/web/") == "http://192.168.178.61"


def test_protokoll_url():
    basis = "192.168.178.61"
    assert openwb.protokoll_url(basis, 2025) == (
        "http://192.168.178.61/openWB/web/settings/downloadChargeLog.php?year=2025")
    assert openwb.protokoll_url(basis, 2025, 9).endswith("?year=2025&month=09")
    with pytest.raises(openwb.OpenwbFehler):
        openwb.protokoll_url("", 2025)


# --------------------------------------------------------------------------
# Die Endpunkte — ohne Netz: es ist keine Adresse hinterlegt
# --------------------------------------------------------------------------

def test_status_ohne_adresse():
    with TestClient(app) as c:
        d = c.get("/api/openwb/status").json()
        assert d["eingerichtet"] is False
        assert d["erreichbar"] is False
        assert "Adresse" in d["hinweis"]


def test_ladungen_ohne_adresse_liefert_keine_nullen():
    """Ohne Box gibt es keine Zahlen — aber auch keinen Fehler und vor allem
    keine 0, die wie eine Messung aussähe."""
    with TestClient(app) as c:
        antwort = c.get("/api/openwb/ladungen",
                        params={"von": "2024-10-01", "bis": "2025-09-30"})
        assert antwort.status_code == 200
        d = antwort.json()
        assert d["ok"] is False
        assert d["kwh"] is None and d["extern_kwh"] is None
        assert d["eigen_kwh"] is None and d["anzahl"] is None
        assert "Hand" in d["hinweis"]


def test_zeitraum_rueckwaerts_ist_eine_fehleingabe():
    with TestClient(app) as c:
        antwort = c.get("/api/openwb/ladungen",
                        params={"von": "2025-09-30", "bis": "2024-10-01"})
        assert antwort.status_code == 400


def test_unbrauchbare_adresse_wird_abgelehnt():
    with TestClient(app) as c:
        assert c.post("/api/openwb/adresse", json={"url": "!!!"}).status_code == 400


def test_adresse_speichern_und_wieder_leeren():
    """Gespeichert wird auch, wenn die Box nicht antwortet — sie ist im
    Heimnetz nicht immer an. 127.0.0.1:9 lehnt sofort ab, kein Netzzugriff."""
    with TestClient(app) as c:
        d = c.post("/api/openwb/adresse", json={"url": "127.0.0.1:9"}).json()
        assert d["eingerichtet"] is True
        assert d["url"] == "http://127.0.0.1:9"
        assert d["erreichbar"] is False          # niemand da — trotzdem 200
        assert "Hand" in d["hinweis"]

        # Die Auswertung meldet denselben Grund, statt Nullen zu liefern.
        werte = c.get("/api/openwb/ladungen",
                      params={"von": "2025-01-01", "bis": "2025-12-31"}).json()
        assert werte["ok"] is False and werte["kwh"] is None

        leer = c.post("/api/openwb/adresse", json={"url": ""}).json()
        assert leer["eingerichtet"] is False and leer["url"] == ""
