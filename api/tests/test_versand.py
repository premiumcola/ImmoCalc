"""Versand: keine Mail zweimal an denselben Mieter.

Der Versand geht an echte Menschen. Ein Fehler mitten drin darf beim zweiten
Anlauf nicht dazu führen, dass die ersten Parteien ihre Abrechnung noch einmal
bekommen — und ein abgeschlossener Zeitraum darf sich nicht beiläufig erneut
verschicken lassen.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_versand.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlmodel import Session  # noqa: E402

from app import mailversand  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.mailversand import MailFehler, Zugang  # noqa: E402
from app.models import (Bewohner, Kostenposition, Miete,  # noqa: E402
                        Vorauszahlung)
from app.routers import versand as versand_router  # noqa: E402


class Postfach:
    """Notiert statt zu senden. `stolpert_bei` bricht bei dieser Partei ab."""

    def __init__(self, stolpert_bei: str | None = None):
        self.gesendet: list[str] = []
        self.stolpert_bei = stolpert_bei
        self.absender_name = "Prüfstand"

    def sende(self, an, betreff, text, anhang=None):
        if self.stolpert_bei and self.stolpert_bei in an:
            raise MailFehler("Prüfstand: Verbindung abgebrochen")
        self.gesendet.append(an)


@pytest.fixture
def postfach(monkeypatch):
    """Setzt ein Postfach ein, ohne dass eine Mail den Rechner verlässt."""
    kasten = Postfach()
    # versand.py bindet `zugang` beim Import — dort ersetzen, nicht in mail.py
    monkeypatch.setattr(versand_router, "zugang", lambda session: kasten)
    return kasten


def _zeitraum_mit_zwei_mietern(c) -> int:
    """Objekt, zwei Mieter mit Mailadresse, eine verteilte Kostenposition.

    Die Position wird direkt in die Datenbank geschrieben: es gibt (noch)
    keinen Endpunkt, der `anteile` setzt — ohne Anteile hat die Abrechnung
    aber keine Parteien, und dann gibt es auch nichts zu versenden."""
    slug = c.post("/api/objekte", json={
        "name": "Versandweg 1", "ort": "Prüfstadt",
        "kostenarten": ["Wasser"]}).json()["slug"]
    for partei, adresse in [("Alpha", "alpha@example.org"),
                            ("Beta", "beta@example.org")]:
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": partei, "kaltmiete": 500.0, "email": adresse,
            "ab_datum": "2024-01-01"})
    zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]

    with Session(db_engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=600.0,
                             schluessel="flaeche", status="erledigt",
                             anteile={"Alpha": 1, "Beta": 1}))
        s.add(Vorauszahlung(zeitraum_id=zid, partei="Alpha", betrag=400.0))
        s.add(Vorauszahlung(zeitraum_id=zid, partei="Beta", betrag=400.0))
        s.commit()
    return zid


def test_abgeschlossener_zeitraum_wird_nicht_beilaeufig_erneut_versendet(postfach):
    """Zwei offene Tabs genügten früher für einen zweiten Versand."""
    with TestClient(app) as c:
        zid = _zeitraum_mit_zwei_mietern(c)
        erst = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                      json={"versenden": True, "offene_uebergehen": True})
        assert erst.status_code == 200
        assert sorted(erst.json()["versendet"]) == ["Alpha", "Beta"]
        assert len(postfach.gesendet) == 2

        zweit = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                       json={"versenden": True, "offene_uebergehen": True})
        assert zweit.status_code == 409
        assert len(postfach.gesendet) == 2, "zweiter Versand ist durchgerutscht"


def test_erneuter_versand_ueberspringt_bereits_belieferte(monkeypatch):
    """Bricht der Versand bei Partei zwei ab, bekommt Partei eins beim
    zweiten Anlauf nicht noch eine Mail."""
    kasten = Postfach(stolpert_bei="beta@")
    # versand.py bindet `zugang` beim Import — dort ersetzen, nicht in mail.py
    monkeypatch.setattr(versand_router, "zugang", lambda session: kasten)

    with TestClient(app) as c:
        zid = _zeitraum_mit_zwei_mietern(c)
        erst = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                      json={"versenden": True, "offene_uebergehen": True})
        assert erst.status_code == 400
        assert kasten.gesendet == ["alpha@example.org"]

        kasten.stolpert_bei = None            # das Postfach ist wieder da
        zweit = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                       json={"versenden": True, "offene_uebergehen": True})
        assert zweit.status_code == 200
        assert zweit.json()["schon_versendet"] == ["Alpha"]
        assert kasten.gesendet == ["alpha@example.org", "beta@example.org"], \
            "Alpha hat die Abrechnung zweimal bekommen"


def test_abschliessen_ohne_versand_braucht_kein_postfach():
    """Wer per Post abrechnet, muss den Zeitraum trotzdem schliessen können."""
    with TestClient(app) as c:
        zid = _zeitraum_mit_zwei_mietern(c)
        antwort = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                         json={"versenden": False, "offene_uebergehen": True})
        assert antwort.status_code == 200
        assert antwort.json()["status"] == "abgeschlossen"
        assert antwort.json()["versendet"] == []


def test_mailtext_enthaelt_die_vorauszahlungen(postfach, monkeypatch):
    """Der Text las den falschen Schlüssel und liess jeden Versand mit 500
    scheitern, bevor die erste Mail gebaut war."""
    texte = []
    postfach.sende = lambda an, betreff, text, anhang=None: texte.append(text)

    with TestClient(app) as c:
        zid = _zeitraum_mit_zwei_mietern(c)
        antwort = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                         json={"versenden": True, "offene_uebergehen": True})
        assert antwort.status_code == 200, antwort.text
        assert texte, "keine Mail gebaut"
        assert "Geleistete Vorauszahlungen:" in texte[0]
        assert "None" not in texte[0]


def test_echter_zugang_bleibt_unberuehrt():
    """Sicherheitsnetz: der Prüfstand darf den echten Versandweg nicht ersetzen."""
    assert mailversand.Zugang is Zugang


def test_ausgezogener_mieter_bekommt_seine_abrechnung(postfach):
    """CCX: ein mitten im Jahr ausgezogener Mieter steht mit seinem Anteil in
    der Abrechnung — und muss sie auch bekommen.

    `_empfaenger` zählte früher nur laufende Verhältnisse (bis_datum is None),
    die Verteilung aber alle, die den Zeitraum berühren. Der ausgezogene Mieter
    landete so unter „ohne Mailadresse", obwohl seine Adresse gespeichert war."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Wechselweg 2", "ort": "Prüfstadt",
            "kostenarten": ["Wasser"]}).json()["slug"]
        # Der Abrechnungszeitraum des neuen Objekts; Mieterwechsel in seiner Mitte
        z = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]
        zid = z["id"]
        jahr = z["label"][6:10]           # „01.01.JJJJ – …"
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Vormieter", "kaltmiete": 500.0, "einheit": "EG",
            "email": "vor@example.org", "ab_datum": f"{jahr}-01-01",
            "bis_datum": f"{jahr}-06-30"})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Nachmieter", "kaltmiete": 500.0, "einheit": "EG",
            "email": "nach@example.org", "ab_datum": f"{jahr}-07-01"})

        with Session(db_engine) as s:
            s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=600.0,
                                 schluessel="flaeche", status="erledigt",
                                 anteile={"Vormieter": 1, "Nachmieter": 1}))
            s.add(Vorauszahlung(zeitraum_id=zid, partei="Vormieter", betrag=0.0))
            s.add(Vorauszahlung(zeitraum_id=zid, partei="Nachmieter", betrag=0.0))
            s.commit()

        # In der Übersicht darf der Vormieter nicht als „ohne Mailadresse" gelten
        ueb = c.get(f"/api/zeitraeume/{zid}/versand").json()
        assert "Vormieter" not in ueb["ohne_mail"], ueb["ohne_mail"]

        erg = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                     json={"versenden": True, "offene_uebergehen": True}).json()
        assert "Vormieter" in erg["versendet"], erg
        assert "vor@example.org" in postfach.gesendet


def test_teilversand_liefert_die_zweite_adresse_nach(monkeypatch):
    """CCXI: schlägt beim Ehepaar die zweite Mail fehl, muss der zweite Anlauf
    genau diese eine Adresse nachliefern — nicht die Partei überspringen."""
    kasten = Postfach(stolpert_bei="jan@example.org")
    monkeypatch.setattr(versand_router, "zugang", lambda session: kasten)
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Paarweg 3", "ort": "Prüfstadt",
            "kostenarten": ["Wasser"]}).json()["slug"]
        mid = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Lorenz", "kaltmiete": 500.0, "einheit": "EG",
            "email": "lea@example.org", "ab_datum": "2024-01-01"}).json()["id"]
        zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
        with Session(db_engine) as s:
            s.add(Bewohner(miete_id=mid, name="Jan", email="jan@example.org",
                           abrechnung=True))
            s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=600.0,
                                 schluessel="flaeche", status="erledigt",
                                 anteile={"Lorenz": 1}))
            s.add(Vorauszahlung(zeitraum_id=zid, partei="Lorenz", betrag=0.0))
            s.commit()

        # Erster Anlauf: Lea bekommt ihre Mail, Jan stolpert -> 400
        erst = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                      json={"versenden": True, "offene_uebergehen": True})
        assert erst.status_code == 400
        assert kasten.gesendet == ["lea@example.org"]

        # Zweiter Anlauf (kein `erneut` — der Zeitraum ist wegen des Fehlers
        # noch „in Arbeit"): nur Jan wird nachgeliefert, Lea NICHT erneut.
        kasten.stolpert_bei = None
        zweit = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                       json={"versenden": True, "offene_uebergehen": True})
        assert zweit.status_code == 200
        assert kasten.gesendet == ["lea@example.org", "jan@example.org"], \
            "Lea darf nicht doppelt, Jan muss nachgeliefert werden"


def test_erneut_stellt_korrigierte_abrechnung_neu_zu(postfach):
    """CCXII: nach einer Korrektur muss `erneut=True` die Abrechnung wieder an
    alle zustellen — das alte Versandprotokoll darf nicht blockieren."""
    with TestClient(app) as c:
        zid = _zeitraum_mit_zwei_mietern(c)
        c.post(f"/api/zeitraeume/{zid}/abschliessen",
               json={"versenden": True, "offene_uebergehen": True})
        assert len(postfach.gesendet) == 2

        # Zeitraum wieder öffnen, korrigieren (hier: einfach erneut senden)
        c.post(f"/api/zeitraeume/{zid}/oeffnen")
        erneut = c.post(f"/api/zeitraeume/{zid}/abschliessen",
                        json={"versenden": True, "offene_uebergehen": True,
                              "erneut": True})
        assert erneut.status_code == 200
        assert sorted(erneut.json()["versendet"]) == ["Alpha", "Beta"]
        assert len(postfach.gesendet) == 4, "beide müssen die Korrektur bekommen"
