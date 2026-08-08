"""N283 a + e — was `weg.stand()` zurückgeben muss.

Zwei Lücken, die derselbe Aufruf schließt:

**(a)** Der frühere Direkteintrag „Nebenkosten laut Hausverwaltung" (CCVIII)
schreibt je Mieter eine Kostenposition `Nebenkosten (WEG) · <Einheit>`. Sie ist
eine Handeingabe und wird von der Übernahme nie angefasst — der WEG-Stand hat
sie aber auch nie *gezeigt* und nie *mitgerechnet*. Im echten Bestand
(Zeitraum „Wohnung 1.OG", 235,00 € von Hand, 235,00 €/Monat Vorauszahlung)
stand deshalb ein Guthaben von 2.820,00 € — die volle Vorauszahlung, als gäbe
es keine Kosten dagegen. Die Abrechnung selbst rechnet die Position längst mit.

**(e)** `uebersprungen`/`entfernt` gab es nur in der Antwort auf `/uebernehmen`.
Nach einem Neuladen war der Hinweis weg und der Nutzer sah nicht mehr, dass
eine Position bewusst nicht übernommen wurde.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_weg_stand.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db, weg  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Einheit, Kostenposition, Miete, Objekt,  # noqa: E402
                        WegVorauszahlung, Zeitraum)

EINHEIT = "Wohnung 1.OG"
PARTEI = "Mieter 1.OG"

# Der echte Bestand aus der laufenden Instanz: 235,00 € von Hand eingetragen,
# 235,00 € Vorauszahlung im Monat über zwölf Monate.
DIREKT_BETRAG = 235.0
VZ_MONAT = 235.0
VZ_SUMME = 2820.0


def _beleg() -> dict:
    """Ein knapper, stimmiger Beleg — hier zählt der Stand, nicht die Auslese."""
    return {
        "firma": "Delta-t Messdienst Wenzel GmbH",
        "liegenschaft": "Hauptstr. 6a",
        "nutzer_nr": "0004-001",
        "von": "2025-01-01", "bis": "2025-12-31", "datum": "2026-03-16",
        "positionen": [
            {"bezeichnung": "Wasserkosten", "gesamtkosten": 788.80,
             "ihre_kosten": 103.24, "schluessel": "Wasser", "umlagefaehig": True},
            {"bezeichnung": "Verwalter", "gesamtkosten": 1028.16,
             "ihre_kosten": 205.63, "schluessel": "Anzahl WE",
             "umlagefaehig": True},
            {"bezeichnung": "Reparatur", "gesamtkosten": 135.66,
             "ihre_kosten": 27.13, "schluessel": "", "umlagefaehig": False},
        ],
        "heizkosten": 0.0, "warmwasserkosten": 0.0, "warnung": "",
    }


def _objekt_id() -> int:
    with Session(db.engine) as s:
        vorhanden = s.exec(select(Objekt).where(Objekt.slug == "weg-stand")).first()
        if vorhanden:
            return vorhanden.id
        o = Objekt(slug="weg-stand", name="Hauptstr. 6a", start_monat=1, weg=True)
        s.add(o)
        s.commit()
        s.refresh(o)
        s.add(Einheit(objekt_id=o.id, bezeichnung=EINHEIT, flaeche=107.3))
        s.add(Miete(objekt_id=o.id, einheit=EINHEIT, partei=PARTEI,
                    ab_datum=date(2020, 1, 1)))
        s.commit()
        return o.id


def _zeitraum(jahr: int) -> int:
    oid = _objekt_id()
    with Session(db.engine) as s:
        z = Zeitraum(objekt_id=oid, start=date(jahr, 1, 1), ende=date(jahr, 12, 31),
                     typ="regulär", status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        return z.id


def _direkteintrag(zid: int, betrag: float = DIREKT_BETRAG) -> int:
    """Genau das, was der CCVIII-Block anlegt: eine Handeingabe mit dem
    Kostenart-Namen aus `zeitraum/state.js` (`WEG_ART`)."""
    with Session(db.engine) as s:
        p = Kostenposition(zeitraum_id=zid, kostenart=weg.DIREKT_PRAEFIX + EINHEIT,
                           betrag=betrag, schluessel="flaeche",
                           wertquelle="manuell", status="erledigt",
                           nur_einheit=EINHEIT, anteile={PARTEI: 1.0})
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _vorauszahlung(zid: int) -> None:
    with Session(db.engine) as s:
        s.add(WegVorauszahlung(zeitraum_id=zid, einheit=EINHEIT,
                               betrag_monat=VZ_MONAT))
        s.commit()


def _uebernehmen(zid: int, beleg: dict | None = None) -> dict:
    with Session(db.engine) as s:
        return weg.uebernehmen(s, s.get(Zeitraum, zid), beleg or _beleg(),
                               einheit=EINHEIT)


def _stand(zid: int) -> dict:
    with Session(db.engine) as s:
        return weg.stand(s, s.get(Zeitraum, zid))


# --------------------------------------------------------------------------
# (a) Der Direkteintrag geht im WEG-Modus auf
# --------------------------------------------------------------------------
def test_direkteintrag_wird_gezeigt_und_gerechnet():
    """Der Fall aus dem echten Bestand: WEG-Modus an, keine übernommene Zeile,
    aber 235,00 € von Hand und 2.820,00 € vorausgezahlt."""
    zid = _zeitraum(2051)
    pid = _direkteintrag(zid)
    _vorauszahlung(zid)

    stand = _stand(zid)
    assert [d["id"] for d in stand["direkt"]] == [pid]
    assert stand["direkt"][0]["einheit"] == EINHEIT
    assert stand["direkt"][0]["betrag"] == DIREKT_BETRAG
    assert stand["direkt_summe"] == DIREKT_BETRAG
    # Und er zählt — vorher stand hier ein Guthaben über die volle Vorauszahlung.
    assert stand["uebernommen_summe"] == 0.0
    assert stand["umlagefaehig_summe"] == DIREKT_BETRAG
    assert stand["vorauszahlung_summe"] == VZ_SUMME
    assert stand["saldo"] == round(VZ_SUMME - DIREKT_BETRAG, 2)


def test_direkteintrag_ueberlebt_die_uebernahme_und_zaehlt_daneben():
    """Eine Übernahme fasst nur ihre eigenen Zeilen an. Der Direkteintrag bleibt
    stehen, bleibt eine Handeingabe — und steht in beiden Summen getrennt, damit
    die Oberfläche die Doppelung zeigen kann statt sie zu verstecken."""
    zid = _zeitraum(2052)
    pid = _direkteintrag(zid)
    stand = _uebernehmen(zid)

    assert [d["id"] for d in stand["direkt"]] == [pid]
    assert stand["direkt"][0]["wertquelle"] == "manuell"
    assert weg.DIREKT_PRAEFIX + EINHEIT not in {
        p["kostenart"] for p in stand["positionen"]}
    assert stand["uebernommen_summe"] == 308.87           # 103,24 + 205,63
    assert stand["umlagefaehig_summe"] == round(308.87 + DIREKT_BETRAG, 2)
    # Ein zweiter Lauf entfernt ihn nicht — er ist keine WEG-Zeile.
    assert [d["id"] for d in _uebernehmen(zid)["direkt"]] == [pid]


def test_ohne_direkteintrag_bleiben_die_summen_wie_bisher():
    """Additiv: wer keinen Direkteintrag hat, sieht dieselben Zahlen wie zuvor."""
    zid = _zeitraum(2053)
    stand = _uebernehmen(zid)
    assert stand["direkt"] == []
    assert stand["direkt_summe"] == 0.0
    assert stand["umlagefaehig_summe"] == stand["uebernommen_summe"] == 308.87
    assert stand["nicht_umlagefaehig_summe"] == 27.13


def test_fremde_handeingabe_bleibt_aussen_vor():
    """Nur der CCVIII-Name zählt als Direkteintrag — „Gartenpflege" ist eine
    ganz gewöhnliche Position und hat im WEG-Saldo nichts verloren."""
    zid = _zeitraum(2054)
    with Session(db.engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Gartenpflege",
                             betrag=180.0, schluessel="individuell",
                             wertquelle="manuell", status="erledigt",
                             anteile={PARTEI: 1.0}))
        s.commit()
    stand = _stand(zid)
    assert stand["direkt"] == []
    assert stand["umlagefaehig_summe"] == 0.0


# --------------------------------------------------------------------------
# (e) Übersprungen und entfernt überleben ein Neuladen
# --------------------------------------------------------------------------
def test_uebersprungene_position_steht_auch_im_frisch_geholten_stand():
    zid = _zeitraum(2055)
    with Session(db.engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Verwalter",
                             betrag=199.0, schluessel="individuell",
                             wertquelle="manuell", status="erledigt",
                             anteile={PARTEI: 1.0}))
        s.commit()
    assert _uebernehmen(zid)["uebersprungen"] == ["Verwalter"]
    # Und nach dem Neuladen — genau das fehlte bisher.
    assert _stand(zid)["uebersprungen"] == ["Verwalter"]
    assert _stand(zid)["entfernt"] == []


def test_entfallene_position_steht_auch_im_frisch_geholten_stand():
    zid = _zeitraum(2056)
    _uebernehmen(zid)
    schmaler = _beleg()
    schmaler["positionen"] = [p for p in schmaler["positionen"]
                              if p["bezeichnung"] != "Verwalter"]
    assert _uebernehmen(zid, schmaler)["entfernt"] == ["Verwalter"]
    assert _stand(zid)["entfernt"] == ["Verwalter"]
    # Die nächste, wieder vollständige Übernahme räumt den Hinweis ab.
    _uebernehmen(zid)
    assert _stand(zid)["entfernt"] == []


def test_hinweise_bleiben_leer_ohne_uebernahme():
    zid = _zeitraum(2057)
    stand = _stand(zid)
    assert stand["uebersprungen"] == [] and stand["entfernt"] == []


def test_hinweise_verunreinigen_den_beleg_nicht():
    """Die Merker stehen im freien JSON des Belegs — sie dürfen weder als
    Position noch im Belegkopf auftauchen."""
    zid = _zeitraum(2058)
    _uebernehmen(zid)
    with Session(db.engine) as s:
        beleg = s.get(Zeitraum, zid).weg_beleg
    assert "_uebersprungen" in beleg and "_entfernt" in beleg
    stand = _stand(zid)
    assert set(stand["beleg"]) == {"firma", "liegenschaft", "nutzer_nr",
                                   "von", "bis", "datum"}
    assert len(stand["nicht_umlagefaehig"]) == 1


# --------------------------------------------------------------------------
# Über den Endpunkt — so sieht es die Oberfläche
# --------------------------------------------------------------------------
def test_endpunkt_liefert_direkt_und_hinweise():
    zid = _zeitraum(2059)
    _direkteintrag(zid)
    _vorauszahlung(zid)
    with TestClient(app) as c:
        beleg = _beleg()
        beleg["einheit"] = EINHEIT
        stand = c.post(f"/api/zeitraeume/{zid}/weg/uebernehmen",
                       json=beleg).json()["stand"]
        assert stand["direkt_summe"] == DIREKT_BETRAG

        frisch = c.get(f"/api/zeitraeume/{zid}/weg").json()["stand"]
    assert frisch["direkt_summe"] == DIREKT_BETRAG
    assert frisch["uebernommen_summe"] == 308.87
    assert frisch["umlagefaehig_summe"] == round(308.87 + DIREKT_BETRAG, 2)
    assert frisch["saldo"] == round(VZ_SUMME - 308.87 - DIREKT_BETRAG, 2)
    assert frisch["uebersprungen"] == [] and frisch["entfernt"] == []
