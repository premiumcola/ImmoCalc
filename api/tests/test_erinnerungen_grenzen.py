"""Zwei Funde an der Erinnerungsliste — beide fallen erst im Bestand auf.

1. `beleg_monat` und `erinnerung_tage` gingen ungeprüft ins Datum ein:
   `date(jahr, 13, 1)` wirft ValueError, `timedelta(days=10**9)` einen
   OverflowError. Weil `/api/erinnerungen` ALLE Objekte in einer Schleife
   durchgeht, riss ein einziger krummer Altwert die komplette Liste mit HTTP 500
   herunter — auch für jede gesunde Kostenart.
2. Die Beleg-Erinnerung stand in der Zeitraum-Schleife, kennt aber gar keinen
   Zeitraum. Bei zwei offenen Zeiträumen (der Regelfall im Januar: Vorjahr noch
   offen, laufendes Jahr schon angelegt) erschien jeder Hinweis wortgleich
   doppelt.
"""
import os
import sys
import tempfile
from collections import Counter

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_erinnerungen_grenzen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.erinnerungen import termin_im_jahr  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Kostenart, Objekt  # noqa: E402


def _objekt_mit_zwei_zeitraeumen(c, name: str, arten: list[str]) -> str:
    """Ein Objekt, wie es im Januar dasteht: zwei Abrechnungen in Arbeit, jede
    mit mindestens einer Position (leere Zeiträume zählen nach N51 nicht)."""
    slug = c.post("/api/objekte", json={
        "name": name, "turnus": "kalender", "kostenarten": arten,
    }).json()["slug"]
    for jahr in (2022, 2023):
        neu = c.post(f"/api/objekte/{slug}/zeitraeume", json={"jahr": jahr})
        assert neu.status_code == 201, neu.text
        zid = neu.json()["id"]
        angelegt = c.post(f"/api/zeitraeume/{zid}/positionen",
                          json={"kostenart": arten[0], "betrag": 100.0})
        assert angelegt.status_code == 201, angelegt.text
    return slug


def _krumm_ablegen(slug: str, **werte) -> None:
    """Altdaten nachstellen: an der API vorbei in die Datenbank, denn genau so
    sind sie entstanden — die Grenzen am Modell gab es damals nicht."""
    from app import db

    with Session(db.engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        for k in s.exec(select(Kostenart).where(
                Kostenart.objekt_id == o.id)).all():
            for feld, wert in werte.items():
                setattr(k, feld, wert)
            s.add(k)
        s.commit()


def test_krummer_belegmonat_sprengt_die_liste_nicht():
    """Monat 13 aus dem Bestand: die Liste antwortet, statt 500 zu werfen."""
    with TestClient(app) as c:
        # „Wasser" bleibt ohne Position — nur eine Kostenart ohne Beleg kommt
        # überhaupt bis zur Terminrechnung.
        slug = _objekt_mit_zwei_zeitraeumen(c, "Grenzweg 13",
                                            ["Strom", "Wasser"])
        _krumm_ablegen(slug, beleg_monat=13)

        antwort = c.get("/api/erinnerungen")
        assert antwort.status_code == 200, antwort.text
        assert "erinnerungen" in antwort.json()


def test_unsinnige_karenz_sprengt_die_liste_nicht():
    """Eine Milliarde Tage Karenz: `timedelta` liefe über."""
    with TestClient(app) as c:
        slug = _objekt_mit_zwei_zeitraeumen(c, "Grenzweg 99",
                                            ["Wasser", "Müll"])
        _krumm_ablegen(slug, beleg_monat=3, erinnerung_tage=10 ** 9)

        antwort = c.get("/api/erinnerungen")
        assert antwort.status_code == 200, antwort.text


def test_termin_bleibt_im_kalender():
    """Der Riegel selbst — jeder Wert ergibt ein gültiges Datum."""
    assert termin_im_jahr(13, 7, 2026).month == 12
    assert termin_im_jahr(0, 7, 2026).month == 1
    assert termin_im_jahr(None, 7, 2026).month == 1
    assert termin_im_jahr(6, 10 ** 9, 2026).year == 2027     # gedeckelt
    assert termin_im_jahr(6, -5, 2026).day == 1              # keine Rückdatierung
    # Gültige Werte rechnen unverändert weiter.
    assert termin_im_jahr(6, 7, 2026).isoformat() == "2026-06-08"


def test_modell_laesst_krumme_werte_nicht_mehr_neu_entstehen():
    """Die Grenzen am Modell — damit der Bestand nicht weiter wächst."""
    with pytest.raises(ValidationError):
        Kostenart.model_validate({"objekt_id": 1, "name": "Strom",
                                  "beleg_monat": 13})
    with pytest.raises(ValidationError):
        Kostenart.model_validate({"objekt_id": 1, "name": "Strom",
                                  "erinnerung_tage": 10 ** 9})
    # Der gültige Rand bleibt erlaubt.
    assert Kostenart.model_validate({"objekt_id": 1, "name": "Strom",
                                     "beleg_monat": 12}).beleg_monat == 12


def test_patch_speichert_keinen_dreizehnten_monat():
    """Über die Oberfläche kommt kein krummer Wert mehr in die Datenbank."""
    with TestClient(app, raise_server_exceptions=False) as c:
        slug = c.post("/api/objekte", json={
            "name": "Grenzweg 7", "turnus": "kalender", "kostenarten": ["Strom"],
        }).json()["slug"]
        kid = c.get(f"/api/objekte/{slug}/kostenarten").json()[0]["id"]

        assert c.patch(f"/api/kostenarten/{kid}",
                       json={"beleg_monat": 13}).status_code != 200
        arten = c.get(f"/api/objekte/{slug}/kostenarten").json()
        assert arten[0]["beleg_monat"] is None

        # Ein gültiger Monat geht weiterhin durch.
        assert c.patch(f"/api/kostenarten/{kid}",
                       json={"beleg_monat": 6}).status_code == 200
        assert c.get(f"/api/objekte/{slug}/kostenarten"
                     ).json()[0]["beleg_monat"] == 6


def test_beleg_erinnerung_steht_nur_einmal_da():
    """Zwei offene Zeiträume, ein Hinweis je Kostenart — nicht zwei."""
    with TestClient(app) as c:
        slug = _objekt_mit_zwei_zeitraeumen(c, "Doppelweg 4",
                                            ["Strom", "Wasser", "Müll"])
        # Januar + 7 Tage ist zu jeder Jahreszeit verstrichen: die Erinnerung
        # ist damit sicher fällig und steht in der Liste.
        for k in c.get(f"/api/objekte/{slug}/kostenarten").json():
            c.patch(f"/api/kostenarten/{k['id']}",
                    json={"beleg_monat": 1, "erinnerung_tage": 7})

        eintraege = [e for e in c.get("/api/erinnerungen").json()["erinnerungen"]
                     if e["objekt"] == slug and e["art"] == "beleg"]
        gezaehlt = Counter(e["kostenart"] for e in eintraege)
        # „Strom" trägt in beiden Zeiträumen eine Position und kann deshalb als
        # erledigt gelten; die beiden anderen stehen sicher aus — und zwar
        # genau einmal, nicht je offenem Zeitraum einmal.
        assert gezaehlt["Wasser"] == 1
        assert gezaehlt["Müll"] == 1
        assert max(gezaehlt.values()) == 1
        # Und wirklich keine Doublette — auch nicht in der Formulierung.
        assert len({e["text"] for e in eintraege}) == len(eintraege)
