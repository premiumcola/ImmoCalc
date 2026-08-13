"""Der Sammelversand an echte Mieter — drei Fehler, die live Schaden anrichten.

1. Ein Zeitraum galt als „abgeschlossen", auch wenn keine einzige Abrechnung
   rausging: fehlte allen Parteien die Mailadresse, blieb `versendet` leer und
   der Status kippte trotzdem. Der Zeitraum verschwand damit aus Fristen und
   Erinnerungen, obwohl niemand seine Abrechnung hatte.
2. Eine kopierte Adresse mit Zeilenumbruch liess den Nachrichtenaufbau mit
   `ValueError` platzen — kein `MailFehler`, also HTTP 500 ohne die Liste
   „Bereits verschickt: …". Danach wusste der Nutzer nicht mehr, wer seine
   Mail schon hat.
3. Je Empfänger eine eigene SMTP-Verbindung samt Login. Ein Haus mit zwölf
   Einheiten ergibt zwanzig Anmeldungen in Folge — GMX und Web.de drosseln
   das, der Lauf kippt mitten drin.

Hier verlässt keine Mail den Rechner: die SMTP-Verbindung ist ein Prüfstand,
der nur mitschreibt.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_versand_robust.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine as db_engine  # noqa: E402
from app.mailversand import MailFehler, Zugang  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Kostenposition, Miete, Vorauszahlung  # noqa: E402
from app.routers import versand as versand_router  # noqa: E402


class Leitung:
    """Eine SMTP-Verbindung, die nichts verschickt, sondern mitschreibt."""

    def __init__(self, protokoll: dict):
        self.protokoll = protokoll
        protokoll["verbindungen"] += 1

    def login(self, benutzer: str, passwort: str) -> None:
        self.protokoll["logins"] += 1

    def send_message(self, nachricht) -> None:
        self.protokoll["mails"].append(str(nachricht["To"]))

    def quit(self) -> None:
        self.protokoll["quits"] += 1

    def close(self) -> None:
        pass


def _pruefstand(monkeypatch) -> tuple[dict, Zugang]:
    """Echter `Zugang` mit echter `sende`-Logik, aber ohne echten Mailserver.

    Bewusst nicht der ganze Zugang ersetzt: die drei Fehler stecken genau in
    `mailversand.sende`/`verbindung_offen` — ein Ersatz-Postfach würde sie
    überspringen."""
    protokoll = {"verbindungen": 0, "logins": 0, "quits": 0, "mails": []}
    z = Zugang(server="mail.example.org", port=587, benutzer="ich",
               passwort="geheim", absender="ich@example.org",
               absender_name="Prüfstand")
    monkeypatch.setattr(Zugang, "_verbindung",
                        lambda self, timeout=20.0: Leitung(protokoll))
    monkeypatch.setattr(versand_router, "zugang", lambda session: z)
    return protokoll, z


def _objekt(c, name: str, parteien: list[tuple[str, str]]) -> tuple[str, int]:
    """Objekt mit Parteien und einer verteilten Position.

    `parteien` ist [(Partei, Mailadresse)]; eine leere Adresse steht für ein
    Mietverhältnis, bei dem die Mail noch nicht gepflegt ist. Die Position wird
    direkt geschrieben, weil kein Endpunkt `anteile` setzt — ohne Anteile hat
    die Abrechnung keine Parteien und es gäbe nichts zu versenden."""
    slug = c.post("/api/objekte", json={
        "name": name, "ort": "Prüfstadt", "kostenarten": ["Wasser"]},
    ).json()["slug"]
    for partei, adresse in parteien:
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": partei, "kaltmiete": 500.0, "email": adresse,
            "ab_datum": "2024-01-01"})
    zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
    with Session(db_engine) as s:
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=600.0,
                             schluessel="flaeche", status="erledigt",
                             anteile={p: 1 for p, _ in parteien}))
        for partei, _ in parteien:
            s.add(Vorauszahlung(zeitraum_id=zid, partei=partei, betrag=100.0))
        s.commit()
    return slug, zid


def _adresse_setzen(c, slug: str, partei: str, adresse: str) -> None:
    """Die Mailadresse eines Mietverhältnisses ändern.

    Direkt in der Datenbank statt über `PATCH /api/stammdaten/mieten/…`: dieser
    Endpunkt leitet die Verteilung neu ab und verwirft dabei die von Hand
    gesetzten Anteile — die Abrechnung hätte danach keine Parteien mehr und der
    Versand nichts zu tun."""
    mid = next(m["id"] for m in c.get(f"/api/objekte/{slug}/mieten").json()
               if m["partei"] == partei)
    with Session(db_engine) as s:
        m = s.get(Miete, mid)
        m.email = adresse
        s.add(m)
        s.commit()


def _abschliessen(c, zid: int, **felder):
    return c.post(f"/api/zeitraeume/{zid}/abschliessen",
                  json={"versenden": True, "offene_uebergehen": True, **felder})


# ---------------------------------------------- 1) „Erledigt" nur wenn fertig

def test_partei_ohne_adresse_haelt_den_zeitraum_offen(monkeypatch):
    """Wer keine Abrechnung bekommen hat, darf nicht als erledigt gelten."""
    protokoll, _ = _pruefstand(monkeypatch)
    with TestClient(app) as c:
        _, zid = _objekt(c, "Adressweg 1",
                         [("Alpha", "alpha@example.org"), ("Beta", "")])
        antwort = _abschliessen(c, zid)
        assert antwort.status_code == 409, antwort.text
        grund = antwort.json()["detail"]
        assert "Beta" in grund, grund
        assert "Alpha" in grund, "wer schon versorgt ist, gehört in die Meldung"
        # Der Status bleibt offen — sonst fällt der Zeitraum aus den Fristen.
        assert c.get(f"/api/zeitraeume/{zid}").json()["status"] == "in Arbeit"
        assert protokoll["mails"] == ["alpha@example.org"]


def test_nachgetragene_adresse_schliesst_den_zeitraum_ab(monkeypatch):
    """Der 409 ist eine Aufforderung, keine Sackgasse: Adresse nachtragen,
    erneut abschliessen — und nur die fehlende Mail geht raus."""
    protokoll, _ = _pruefstand(monkeypatch)
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Adressweg 2",
                            [("Alpha", "alpha@example.org"), ("Beta", "")])
        assert _abschliessen(c, zid).status_code == 409

        _adresse_setzen(c, slug, "Beta", "beta@example.org")

        zweit = _abschliessen(c, zid)
        assert zweit.status_code == 200, zweit.text
        assert zweit.json()["status"] == "abgeschlossen"
        assert protokoll["mails"] == ["alpha@example.org", "beta@example.org"], \
            "Alpha darf die Abrechnung nicht zweimal bekommen"


def test_unerreichbare_partei_laesst_sich_ausdruecklich_uebergehen(monkeypatch):
    """Es gibt Adressen, die es nicht gibt — ein Mieter zieht ohne neue
    Anschrift aus. Der Riegel darf dann keine Sackgasse sein: mit einer
    ausdrücklichen Bestätigung geht der Abschluss durch."""
    protokoll, _ = _pruefstand(monkeypatch)
    with TestClient(app) as c:
        _, zid = _objekt(c, "Unbekanntweg 6",
                         [("Alpha", "alpha@example.org"), ("Beta", "")])
        antwort = _abschliessen(c, zid, ohne_adresse_abschliessen=True)
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["status"] == "abgeschlossen"
        assert antwort.json()["ohne_mail"] == ["Beta"]
        assert protokoll["mails"] == ["alpha@example.org"]


def test_abschluss_ohne_versand_bleibt_moeglich(monkeypatch):
    """Wer per Post abrechnet, schliesst ab, ohne dass eine Adresse gepflegt
    sein muss — der neue Riegel gilt nur für den Versandweg."""
    _pruefstand(monkeypatch)
    with TestClient(app) as c:
        _, zid = _objekt(c, "Postweg 3", [("Alpha", ""), ("Beta", "")])
        antwort = _abschliessen(c, zid, versenden=False)
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["status"] == "abgeschlossen"
        assert antwort.json()["versendet"] == []


# ------------------------------------------- 2) Kaputte Adresse als MailFehler

def test_adresse_mit_zeilenumbruch_ist_ein_mailfehler(monkeypatch):
    """`nachricht["To"] = an` warf einen nackten ValueError — der Aufrufer
    fängt nur `MailFehler` und lief deshalb in einen HTTP-500."""
    protokoll, z = _pruefstand(monkeypatch)
    with pytest.raises(MailFehler) as fehler:
        z.sende("beta@example.org\nBcc: fremd@example.org", "Betreff", "Text")
    assert "unbrauchbar" in str(fehler.value)
    assert protokoll["mails"] == [], "eine kaputte Adresse darf nichts senden"


def test_kaputte_adresse_beendet_den_lauf_bedienbar(monkeypatch):
    """Der Lauf endet mit einer Meldung, die sagt, wer seine Mail schon hat —
    statt mit einem Serverfehler, nach dem niemand mehr weiterweiss."""
    protokoll, _ = _pruefstand(monkeypatch)
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Umbruchweg 4",
                            [("Alpha", "alpha@example.org"),
                             ("Beta", "beta@example.org")])
        # So entsteht das live: die Adresse wird aus einer Mail kopiert und
        # bringt den Zeilenumbruch mit.
        _adresse_setzen(c, slug, "Beta",
                        "beta@example.org\nBcc: fremd@example.org")

        antwort = _abschliessen(c, zid)
        assert antwort.status_code == 400, antwort.text
        grund = antwort.json()["detail"]
        assert "Bereits verschickt: Alpha" in grund, grund
        assert protokoll["mails"] == ["alpha@example.org"]
        assert c.get(f"/api/zeitraeume/{zid}").json()["status"] == "in Arbeit"


def test_adresse_wird_beim_senden_getrimmt(monkeypatch):
    """Ein angehängtes Leerzeichen oder ein abschliessender Umbruch ist kein
    Grund, eine Abrechnung nicht zuzustellen."""
    protokoll, z = _pruefstand(monkeypatch)
    z.sende("  alpha@example.org \n", "Betreff", "Text")
    assert protokoll["mails"] == ["alpha@example.org"]


# --------------------------------------------- 3) Ein Login für den ganzen Lauf

def test_sammelversand_meldet_sich_nur_einmal_an(monkeypatch):
    """Fünf Parteien, eine Anmeldung. Je Empfänger ein Login liess GMX und
    Web.de drosseln, und der Versand kippte mitten im Haus."""
    protokoll, _ = _pruefstand(monkeypatch)
    with TestClient(app) as c:
        _, zid = _objekt(c, "Loginweg 5",
                         [(f"Partei {i}", f"p{i}@example.org")
                          for i in range(1, 6)])
        antwort = _abschliessen(c, zid)
        assert antwort.status_code == 200, antwort.text
        assert len(protokoll["mails"]) == 5, protokoll["mails"]
        assert protokoll["verbindungen"] == 1, \
            "je Empfänger eine eigene Verbindung — genau das drosselt GMX"
        assert protokoll["logins"] == 1
        assert protokoll["quits"] == 1, "die Verbindung wird auch geschlossen"


def test_einzelversand_oeffnet_weiterhin_selbst(monkeypatch):
    """Die bestehende Signatur bleibt: Testmail, Strom und Tankstelle rufen
    `sende` ohne offene Verbindung auf und dürfen davon nichts merken."""
    protokoll, z = _pruefstand(monkeypatch)
    z.sende("einzeln@example.org", "Betreff", "Text")
    assert protokoll["mails"] == ["einzeln@example.org"]
    assert protokoll["verbindungen"] == 1
    assert protokoll["logins"] == 1
    assert protokoll["quits"] == 1
