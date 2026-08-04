"""N200 — die E-Tankstelle zahlt live auf die PV-Amortisation ein.

Bis N200 kam der E-Tanken-Ertrag aus `Tankladung.kwh × Tankladung.preis`. Der
Handpreis ist aber seit N148 stillgelegt; die echten Ladungen liegen in der
Wallbox. Der Verlauf zeigte für 2025/2026 deshalb 0, obwohl längst geladen wird.

Geprüft wird:
  * die reine Beitragsformel (eigene Lademenge × abgeleiteter Eigen-Satz),
  * die Kategorien-Aufteilung der Amortisation (€-Anteil und kWh je Kategorie),
  * und die Ehrlichkeit: geladen, aber kein ableitbarer Satz → 0 €, die kWh
    stehen trotzdem da (nie eine erfundene Zahl).
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_pv_tanken.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import strom as rs  # noqa: E402
from app.routers import tankstelle as tk  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# 1) Die reine Beitragsformel
# --------------------------------------------------------------------------

def test_beitrag_ist_menge_mal_satz():
    assert rs.tanken_beitrag_eur(1500, 0.30) == 450.0
    assert rs.tanken_beitrag_eur(966.83, 0.3109) == round(966.83 * 0.3109, 2)


def test_beitrag_ohne_menge_oder_satz_ist_null_nicht_erfunden():
    # Fehlt die Aufteilung (Menge) oder die Stromkosten (Satz), gibt es keinen
    # Beitrag — nie eine 0,00 € als Behauptung, sondern eine echte 0.
    assert rs.tanken_beitrag_eur(None, 0.30) == 0.0
    assert rs.tanken_beitrag_eur(1500, None) == 0.0
    assert rs.tanken_beitrag_eur(0, 0.30) == 0.0
    assert rs.tanken_beitrag_eur(None, None) == 0.0


# --------------------------------------------------------------------------
# 2) Die Kategorien-Aufteilung der Amortisation
# --------------------------------------------------------------------------

def _jahre_realnah():
    """Die Form, die der Verlauf baut — der Vorlauf 2024 aufgeschlüsselt, die
    E-Tanken-Beiträge 2025/2026 aus den live abgeleiteten Werten."""
    return [
        {"jahr": 2024, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0,
         "vorlauf": 2355.36,
         "vorlauf_teile": {"pv_strom": 1798.5, "einspeisung": 556.86,
                           "tanken": 0.0}},
        {"jahr": 2025, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 300.58,
         "vorlauf": 0.0, "vorlauf_teile": None},
        {"jahr": 2026, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 142.15,
         "vorlauf": 0.0, "vorlauf_teile": None},
    ]


def test_kat_eur_zaehlt_den_vorlauf_nach_derselben_regel_wie_die_tabelle():
    jahre = _jahre_realnah()
    assert rs._kat_eur(jahre, "pv_strom", 2024) == 1798.5
    assert rs._kat_eur(jahre, "einspeisung", 2024) == 556.86
    assert rs._kat_eur(jahre, "tanken", 2024) == round(300.58 + 142.15, 2)


def test_kat_eur_unaufgeschluesselter_vorlauf_faellt_der_pv_strom_spalte_zu():
    jahre = [{"jahr": 2023, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0,
              "vorlauf": 1000.0, "vorlauf_teile": None}]
    assert rs._kat_eur(jahre, "pv_strom", 2023) == 1000.0
    assert rs._kat_eur(jahre, "einspeisung", 2023) == 0.0
    assert rs._kat_eur(jahre, "tanken", 2023) == 0.0


def test_kategorien_summieren_sich_und_zeigen_den_kwh_kontrast():
    jahre = _jahre_realnah()
    kwh = {"pv_strom": 13857.0, "einspeisung": 8029.0, "tanken": 1390.4}
    kat = rs._kategorien(jahre, 2024, kwh)
    posten = {p["feld"]: p for p in kat["posten"]}

    # Die Summe der drei Kategorien ist exakt der kumulierte Ertrag.
    assert kat["gesamt_eur"] == round(1798.5 + 556.86 + 442.73, 2)
    assert round(sum(p["eur"] for p in kat["posten"]), 2) == kat["gesamt_eur"]
    # Die Prozente sind der €-Anteil an der Amortisation und ergeben ~100 %.
    assert round(sum(p["prozent"] for p in kat["posten"]), 1) == 100.0

    # Der Kern, den der Nutzer sehen will: die Einspeisung bringt VIELE kWh zu
    # WENIG € je kWh, E-Tanken WENIGE kWh zu einem Vielfachen je kWh.
    assert posten["einspeisung"]["kwh"] > posten["tanken"]["kwh"]
    assert posten["einspeisung"]["eur_pro_kwh"] < posten["tanken"]["eur_pro_kwh"]
    assert posten["einspeisung"]["eur_pro_kwh"] < 0.10   # ~7 ct EEG
    assert posten["tanken"]["eur_pro_kwh"] > 0.25        # Eigen-Satz


def test_kategorie_kwh_verwaessert_nicht_mit_unabgerechneten_jahren(client):
    """N204 — die kWh-Basis folgt der €-Basis: eine spätere Eigenverbrauchsmenge
    ohne abgerechnete Kosten darf den €/kWh-Wert NICHT verwässern.

    Szenario wie beim Nutzer (Eschenau): der einzige abgerechnete PV-Strom-/
    Einspeisungs-€ ist der Vorlauf 2024; die Jahre 2025/2026 haben zwar echten
    Eigenverbrauch (solar/akku) und Einspeisung, sind aber (noch) nicht über die
    Nebenkostenabrechnung verrechnet — ihre kWh gehören also NICHT in die Basis.
    Vorher teilte der Verlauf 1.798,50 € eines Jahres durch 13.857 kWh dreier
    Jahre und zeigte 0,13 €/kWh; richtig ist hier: keine sauber zuordenbare Menge
    → None statt einer erfundenen Zahl."""
    from sqlmodel import Session, select
    from app import db
    from app.models import Objekt

    slug = _pv_objekt(client, "KWH-Basis-unabgerechnet")
    client.put(f"/api/objekte/{slug}/strom/2025",
               json={"solar_kwh": 5400, "akku_kwh": 2808, "einspeisung_kwh": 4125})
    client.put(f"/api/objekte/{slug}/strom/2026",
               json={"solar_kwh": 3595, "akku_kwh": 2054, "einspeisung_kwh": 3904})

    jahre = [
        {"jahr": 2024, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0,
         "vorlauf": 2355.36,
         "vorlauf_teile": {"pv_strom": 1798.5, "einspeisung": 556.86,
                           "tanken": 0.0}},
        {"jahr": 2025, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 300.6,
         "vorlauf": 0.0, "vorlauf_teile": None},
        {"jahr": 2026, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 142.18,
         "vorlauf": 0.0, "vorlauf_teile": None},
    ]
    with Session(db.engine) as s:
        oid = s.exec(select(Objekt).where(Objekt.slug == slug)).first().id
        kwh = rs._kategorie_kwh(s, oid, jahre, 2024, {})

    # Der einzige abgerechnete €-Jahr ist der Vorlauf 2024 — dort ist keine kWh
    # erfasst; 2025/2026 sind (noch) nicht verrechnet und dürfen nicht einfließen.
    assert kwh["pv_strom"] is None
    assert kwh["einspeisung"] is None


def test_kategorie_kwh_nimmt_abgerechnetes_jahr_aber_nicht_das_spaetere(client):
    """N204 — das positive Gegenstück: ein abgerechnetes Jahr X (PV-Strom-€ und
    kWh) zählt seine kWh, ein späteres Jahr Y mit Eigenverbrauch, aber ohne
    abgerechnete Kosten, bleibt außen vor. €/kWh spiegelt so nur Jahr X."""
    from sqlmodel import Session, select
    from app import db
    from app.models import Objekt

    slug = _pv_objekt(client, "KWH-Basis-abgerechnet")
    client.put(f"/api/objekte/{slug}/strom/2025",
               json={"solar_kwh": 5400, "akku_kwh": 2808, "einspeisung_kwh": 4125})
    client.put(f"/api/objekte/{slug}/strom/2026",
               json={"solar_kwh": 3595, "akku_kwh": 2054, "einspeisung_kwh": 3904})

    # 2025 IST abgerechnet (PV-Strom 900 €, Einspeisung 300 €), 2026 nicht.
    jahre = [
        {"jahr": 2025, "pv_strom": 900.0, "einspeisung": 300.0, "tanken": 0.0,
         "vorlauf": 0.0, "vorlauf_teile": None},
        {"jahr": 2026, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0,
         "vorlauf": 0.0, "vorlauf_teile": None},
    ]
    with Session(db.engine) as s:
        oid = s.exec(select(Objekt).where(Objekt.slug == slug)).first().id
        kwh = rs._kategorie_kwh(s, oid, jahre, None, {})

    # Nur 2025 fließt ein: 5400 + 2808 = 8208 kWh PV-Strom, 4125 kWh Einspeisung.
    assert kwh["pv_strom"] == 8208.0
    assert kwh["einspeisung"] == 4125.0


def test_kategorien_ohne_ertrag_erfinden_keine_prozente():
    jahre = [{"jahr": 2024, "pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0,
              "vorlauf": 0.0, "vorlauf_teile": None}]
    kat = rs._kategorien(jahre, 2024, {"pv_strom": None, "einspeisung": None,
                                       "tanken": None})
    assert kat["gesamt_eur"] == 0.0
    assert kat["gesamt_kwh"] is None
    assert all(p["prozent"] is None for p in kat["posten"])
    assert all(p["eur_pro_kwh"] is None for p in kat["posten"])


# --------------------------------------------------------------------------
# 3) Ende zu Ende: geladen, aber kein ableitbarer Satz → 0 €, kWh bleibt sichtbar
# --------------------------------------------------------------------------

def _pv_objekt(c, name: str) -> str:
    slug = c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Müller"}],
    }).json()["slug"]
    c.put(f"/api/objekte/{slug}/strom/2025", json={"anschaffung_eur": 20000})
    return slug


def test_geladen_ohne_ableitbaren_satz_bleibt_null_die_kwh_stehen_da(
        client, monkeypatch):
    slug = _pv_objekt(client, "PV-Tanken-ohne-Satz")

    # 100 kWh geladen, davon 60 kWh eigen — aber kein ableitbarer Satz.
    posten = [tk.Posten(tag=date(2025, 3, 10), kwh=100.0,
                        extern_kwh=40.0, eigen_kwh=60.0)]
    monkeypatch.setattr(tk, "_posten_holen",
                        lambda *a, **k: (posten, "wallbox", ""))
    monkeypatch.setattr(tk, "satz_ableiten",
                        lambda *a, **k: tk.Satz(grund="keine Stromkosten erfasst"))

    v = client.get(f"/api/objekte/{slug}/pv/verlauf").json()
    jahr = next(z for z in v["jahre"] if z["jahr"] == 2025)
    # Ohne Satz kein Beitrag — aber keine erfundene Zahl.
    assert jahr["tanken"] == 0.0

    tanken = next(p for p in v["kategorien"]["posten"] if p["feld"] == "tanken")
    assert tanken["eur"] == 0.0
    assert tanken["kwh"] == 60.0            # die eigene Lademenge steht trotzdem
    assert tanken["eur_pro_kwh"] == 0.0     # 0 € auf echte kWh — nichts erfunden


def test_geladen_mit_satz_zahlt_den_eigenanteil_auf_die_amortisation(
        client, monkeypatch):
    slug = _pv_objekt(client, "PV-Tanken-mit-Satz")

    posten = [tk.Posten(tag=date(2025, 4, 5), kwh=200.0,
                        extern_kwh=50.0, eigen_kwh=150.0)]
    monkeypatch.setattr(tk, "_posten_holen",
                        lambda *a, **k: (posten, "wallbox", ""))
    monkeypatch.setattr(tk, "satz_ableiten",
                        lambda *a, **k: tk.Satz(netz=0.34, eigen=0.31, misch=0.31))

    v = client.get(f"/api/objekte/{slug}/pv/verlauf").json()
    jahr = next(z for z in v["jahre"] if z["jahr"] == 2025)
    assert jahr["tanken"] == round(150.0 * 0.31, 2)   # 46,50 €

    tanken = next(p for p in v["kategorien"]["posten"] if p["feld"] == "tanken")
    assert tanken["kwh"] == 150.0
    assert tanken["eur"] == 46.5
    assert tanken["eur_pro_kwh"] == 0.31
