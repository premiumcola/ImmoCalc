"""N240/N247 — das Vorlagenarchiv (`Dokumentvorlage` + `/api/dokumentvorlagen`).

Die reinen DB-Endpunkte (Liste, Typen-Katalog, Löschen) plus die beiden
Riegel des Hochladens, die ohne Cloud prüfbar sind: die erlaubte Dateiart
(N247 — keine Fotos) und der Home-Ordner. Der eigentliche PUT braucht eine
echte Nextcloud-Verbindung und ist hier bewusst nicht Gegenstand, genau wie
bei den vergleichbaren Tests für `kidb`/`Belegdaten`.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_dokumentvorlagen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from sqlmodel import select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import BESTANDSFAMILIE_NAME  # noqa: E402
from app.models import Dokumentvorlage, Einstellung, Familie  # noqa: E402


def _familie_id(session: Session) -> int:
    """N436 — `liste()` filtert jetzt nach `familie_id`; Fixtures, die direkt
    in der DB anlegen (statt über die API), müssen sie selbst setzen —
    dasselbe Muster wie in test_kidb.py/test_kontakte.py."""
    return session.exec(select(Familie)
                        .where(Familie.name == BESTANDSFAMILIE_NAME)).first().id


def _vorlage(session: Session | None = None, **abweichung) -> Dokumentvorlage:
    daten = dict(name="Übergabeprotokoll", verwendungszweck="Vermietung",
                typ="Übergabeprotokoll Einzug",
                pfad="/[010]_Immobilien/00_Vorlagen/Vermietung/"
                     "Uebergabeprotokoll.pdf",
                dateiname="Uebergabeprotokoll.pdf",
                quelle_url="https://example.org/uebergabeprotokoll.pdf",
                erstellt_am=date.today())
    if session is not None:
        daten["familie_id"] = _familie_id(session)
    daten.update(abweichung)
    return Dokumentvorlage(**daten)


def test_liste_ist_leer_ohne_bestand():
    with TestClient(app) as c:
        antwort = c.get("/api/dokumentvorlagen")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["anzahl"] == 0
    assert daten["vorlagen"] == []


def test_liste_nennt_den_typen_katalog_auch_ohne_bestand():
    """N247 — die Oberfläche zeigt je Vorlagenart eine Zeile, auch die noch
    leeren. Der Katalog dafür kommt aus dem Backend, damit er nicht doppelt
    gepflegt wird."""
    from app.routers.dokumentvorlagen import TYPEN_KATALOG

    with TestClient(app) as c:
        daten = c.get("/api/dokumentvorlagen").json()
    assert [t["typ"] for t in daten["typen"]] == [t["typ"] for t in TYPEN_KATALOG]
    # Der Mietvertrag ist bewusst NICHT dabei — zu individuell für eine Vorlage.
    assert not any("Mietvertrag" == t["typ"] for t in daten["typen"])
    assert all(t["verwendungszweck"] == "Vermietung" for t in daten["typen"])


def test_liste_filtert_nach_verwendungszweck_und_typ():
    with TestClient(app) as c, Session(engine) as session:
        session.add(_vorlage(session))
        session.add(_vorlage(session, name="Selbstauskunft",
                             typ="Mieterselbstauskunft",
                             pfad="/Vorlagen/Vermietung/Selbstauskunft.pdf",
                             dateiname="Selbstauskunft.pdf"))
        session.commit()

        alle = c.get("/api/dokumentvorlagen").json()
        assert alle["anzahl"] == 2

        gefiltert = c.get("/api/dokumentvorlagen",
                          params={"typ": "Mieterselbstauskunft"}).json()
        assert gefiltert["anzahl"] == 1
        assert gefiltert["vorlagen"][0]["name"] == "Selbstauskunft"
        # Der Katalog folgt demselben Filter — sonst zeigte die Oberfläche
        # Zeilen für Arten, nach denen gar nicht gefragt wurde.
        assert [t["typ"] for t in gefiltert["typen"]] == ["Mieterselbstauskunft"]

        andernorts = c.get("/api/dokumentvorlagen",
                           params={"verwendungszweck": "Sonstiges"}).json()
        assert andernorts["anzahl"] == 0
        assert andernorts["typen"] == []


def test_loeschen_entfernt_nur_den_datenbankeintrag():
    with TestClient(app) as c, Session(engine) as session:
        v = _vorlage(session)
        session.add(v)
        session.commit()
        session.refresh(v)
        vid = v.id

    with TestClient(app) as c:
        antwort = c.delete(f"/api/dokumentvorlagen/{vid}")
        assert antwort.status_code == 200
        assert antwort.json() == {"ok": True}
        ids = [v["id"] for v in c.get("/api/dokumentvorlagen").json()["vorlagen"]]
        assert vid not in ids

        fehlt = c.delete(f"/api/dokumentvorlagen/{vid}")
        assert fehlt.status_code == 404


def test_es_gibt_keinen_startbestand_aus_dem_netz_mehr():
    """N247 — der Download fremder Muster ist ersatzlos entfallen: er lief in
    den Schreibriegel und war ohnehin nicht gewollt. Vorlagen kommen jetzt
    ausschliesslich vom Nutzer selbst."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen/startbestand")
    # 405 statt 404: der Pfad trifft nur noch `DELETE /{vorlage_id}` — ein POST
    # darauf gibt es nicht mehr.
    assert antwort.status_code == 405


def test_foto_wird_als_vorlage_abgelehnt():
    """N247 — ausdrücklicher Nutzerwunsch: hier gehören Roh-PDFs hin. Ein
    abfotografiertes Formular taugt nicht als Vordruck zum Ausdrucken.

    Der Riegel greift VOR jedem Cloud-Zugriff — die Absage kommt auch ohne
    eingerichtete Nextcloud, und zwar mit einer Begründung statt eines
    Verbindungsfehlers."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen",
                         params={"name": "Übergabeprotokoll",
                                 "typ": "Übergabeprotokoll Einzug"},
                         files={"datei": ("scan.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert antwort.status_code == 400
    assert "Vordruck" in antwort.json()["detail"]


def test_pdf_kommt_bis_zur_cloud_und_scheitert_erst_dort():
    """Die Gegenprobe: eine PDF passiert den Dateiart-Riegel und scheitert
    erst an der (hier nicht eingerichteten) Nextcloud — der Unterschied zur
    Absage oben zeigt, dass wirklich die Dateiart gefiltert wurde."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen",
                         params={"name": "Übergabeprotokoll",
                                 "typ": "Übergabeprotokoll Einzug"},
                         files={"datei": ("muster.pdf", b"%PDF-1.4",
                                          "application/pdf")})
    assert antwort.status_code == 400
    assert "eingerichtet" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# N264/N275 — Drucken
# --------------------------------------------------------------------------

def _druckerliste_leeren():
    """Die Drucker liegen als JSON in EINER Einstellungszeile — zwischen zwei
    Tests wird sie geleert, damit sich die Faelle nicht gegenseitig sehen.

    N436 — die Zeile liegt jetzt unter dem Namensraum der Familie
    (`familienraum.schluessel`); ohne das Präfix träfe dies die falsche
    (nie geschriebene) Zeile, und der reale Bestand einer Familie würde
    zwischen den Tests nie geleert."""
    from app.routers.dokumentvorlagen import S_DRUCKER
    with Session(engine) as session:
        voll = f"{_familie_id(session)}:{S_DRUCKER}"
        eintrag = session.get(Einstellung, voll)
        if eintrag:
            eintrag.wert = ""
            session.add(eintrag)
            session.commit()


def test_ohne_drucker_gibt_es_keine_drucker(monkeypatch):
    """Ist weder ein Drucker eingetragen noch ein CUPS-Dienst da, meldet die
    Liste ehrlich nichts — die Oberflaeche blendet die Knoepfe dann aus, statt
    welche anzubieten, die ins Leere laufen."""
    monkeypatch.delenv("DRUCKDIENST", raising=False)
    _druckerliste_leeren()
    with TestClient(app) as c:
        antwort = c.get("/api/drucker")
    assert antwort.status_code == 200
    assert antwort.json()["drucker"] == []


def test_drucken_ohne_drucker_sagt_es_deutlich(monkeypatch):
    """Ein Druckauftrag ohne eingerichteten Drucker darf nicht still
    verpuffen — 503 mit Klartext statt eines stummen Fehlschlags."""
    monkeypatch.delenv("DRUCKDIENST", raising=False)
    _druckerliste_leeren()
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen/1/drucken",
                         params={"drucker": "Egal"})
    assert antwort.status_code == 503
    assert "Drucker" in antwort.json()["detail"]


def test_cups_bleibt_der_rueckfall_ohne_eigene_drucker(monkeypatch):
    """N275 — solange der Nutzer keinen Drucker gepflegt hat, kommen die
    CUPS-Warteschlangen. Sie tragen keine IP: dort geht es ueber den Dienst.
    Der Ort wird zum `standort`, damit die Oberflaeche nur EINE Form kennt."""
    from app.routers import dokumentvorlagen as modul
    monkeypatch.setenv("DRUCKDIENST", "beispiel:631")
    monkeypatch.setattr(modul.druckdienst, "drucker_liste",
                        lambda dienst: [{"name": "HP_X", "ort": "2.OG"}])
    _druckerliste_leeren()
    with TestClient(app) as c:
        antwort = c.get("/api/drucker")
    assert antwort.json()["drucker"] == [
        {"name": "HP_X", "ip": "", "port": 0, "standort": "2.OG"}]


def test_eigene_drucker_verdraengen_den_cups_rueckfall(monkeypatch):
    """Sobald ein Drucker eingetragen ist, zaehlt nur noch der — CUPS ist ja
    genau der Weg, der bei diesem Nutzer nicht bis zum Geraet kommt."""
    from app.routers import dokumentvorlagen as modul
    monkeypatch.setenv("DRUCKDIENST", "beispiel:631")
    monkeypatch.setattr(modul.druckdienst, "drucker_liste",
                        lambda dienst: [{"name": "HP_X", "ort": "2.OG"}])
    with TestClient(app) as c:
        gespeichert = c.put("/api/drucker", json=[
            {"name": "Konica", "ip": "192.0.2.20", "port": 9100,
             "standort": "Buero EG"}])
        assert gespeichert.status_code == 200
        antwort = c.get("/api/drucker")
    assert antwort.json()["drucker"] == [
        {"name": "Konica", "ip": "192.0.2.20", "port": 9100,
         "standort": "Buero EG"}]
    _druckerliste_leeren()


def test_speichern_ersetzt_die_ganze_liste():
    """Anlegen, Aendern und Entfernen sind derselbe Vorgang: die Oberflaeche
    schickt den vollstaendigen Stand."""
    with TestClient(app) as c:
        c.put("/api/drucker", json=[
            {"name": "A", "ip": "192.0.2.1", "port": 9100, "standort": "OG"},
            {"name": "B", "ip": "192.0.2.2", "port": 9100, "standort": "EG"}])
        c.put("/api/drucker", json=[
            {"name": "B", "ip": "192.0.2.9", "port": 9101, "standort": "Keller"}])
        drucker = c.get("/api/drucker").json()["drucker"]
    assert drucker == [{"name": "B", "ip": "192.0.2.9", "port": 9101,
                        "standort": "Keller"}]
    _druckerliste_leeren()


def test_kaputte_druckerzeile_kippt_die_liste_nicht():
    """Unlesbar Gespeichertes wird uebergangen statt geworfen — eine kaputte
    Einstellung darf keine Seite mitreissen."""
    from app.routers.dokumentvorlagen import S_DRUCKER
    with Session(engine) as session:
        voll = f"{_familie_id(session)}:{S_DRUCKER}"
        session.merge(Einstellung(schluessel=voll, wert="{kein json"))
        session.commit()
    with TestClient(app) as c:
        antwort = c.get("/api/drucker")
    assert antwort.status_code == 200
    assert antwort.json()["drucker"] == []
    _druckerliste_leeren()


def test_pruefen_meldet_klartext_statt_500():
    """Der Erreichbar-Knopf gegen ein Ziel, das niemand bedient: `false`,
    kein Serverfehler. Getestet wird gegen 127.0.0.1 auf einem Port, auf dem
    nichts lauscht — nie gegen ein echtes Geraet."""
    with TestClient(app) as c:
        c.put("/api/drucker", json=[
            {"name": "Tot", "ip": "127.0.0.1", "port": 9, "standort": ""}])
        antwort = c.post("/api/drucker/Tot/pruefen")
    assert antwort.status_code == 200
    assert antwort.json() == {"erreichbar": False}
    _druckerliste_leeren()


def test_pruefen_kennt_nur_eingetragene_drucker():
    with TestClient(app) as c:
        c.put("/api/drucker", json=[
            {"name": "Konica", "ip": "192.0.2.20", "port": 9100}])
        antwort = c.post("/api/drucker/Fremd/pruefen")
    assert antwort.status_code == 404
    _druckerliste_leeren()


def test_drucken_geht_an_ip_und_port_des_eingetragenen_geraets(monkeypatch):
    """N275 — der Kern der Aenderung: der Auftrag nimmt nicht mehr den Umweg
    ueber CUPS, sondern die Adresse aus den Einstellungen. Die Cloud ist hier
    nicht im Spiel, deshalb wird nur die Datei-Beschaffung ersetzt."""
    from app.routers import dokumentvorlagen as modul
    gerufen: dict = {}

    monkeypatch.setenv("DRUCKDIENST", "beispiel:631")
    monkeypatch.setattr(modul, "_vorlage_bytes",
                        lambda s, vid, familie: (
                            _vorlage(), b"%PDF-1.4", "application/pdf"))
    monkeypatch.setattr(modul.druckdienst, "roh_drucken",
                        lambda ip, port, daten, titel="": (
                            gerufen.update(ip=ip, port=port, daten=daten),
                            (True, "An den Drucker geschickt"))[1])
    with TestClient(app) as c:
        c.put("/api/drucker", json=[
            {"name": "Konica", "ip": "192.0.2.20", "port": 9100,
             "standort": "Buero EG"}])
        antwort = c.post("/api/dokumentvorlagen/1/drucken",
                         params={"drucker": "Konica"})
    assert antwort.status_code == 200
    assert gerufen["ip"] == "192.0.2.20" and gerufen["port"] == 9100
    assert gerufen["daten"] == b"%PDF-1.4"
    # Ehrlich bleiben: „geschickt", nicht „gedruckt".
    assert "geschickt" in antwort.json()["meldung"]
    _druckerliste_leeren()


# --- Die IP wandert in eine TCP-Verbindung: streng pruefen ------------------

def test_unsinnige_adressen_und_ports_werden_abgewiesen():
    """N275 — was aus den Einstellungen kommt, oeffnet spaeter einen Socket.
    Ein Pfad, ein Semikolon oder ein Port ausserhalb 1..65535 darf gar nicht
    erst so weit kommen."""
    from app.drucker import pruefe_ziel
    assert pruefe_ziel("../../etc/passwd", 9100)
    assert pruefe_ziel("1.2.3.4;rm -rf", 9100)
    assert pruefe_ziel("192.168.178.14", 0)
    assert pruefe_ziel("192.168.178.14", 99999)
    assert pruefe_ziel("", 9100)
    # Die Gegenprobe: gueltig heisst leerer Grund.
    assert pruefe_ziel("192.168.178.14", 9100) == ""
    assert pruefe_ziel("drucker-og.fritz.box", 631) == ""


def test_speichern_weist_eine_unsinnige_adresse_ab():
    with TestClient(app) as c:
        antwort = c.put("/api/drucker", json=[
            {"name": "Boese", "ip": "1.2.3.4;rm -rf", "port": 9100}])
    assert antwort.status_code == 400
    assert "IP" in antwort.json()["detail"]
    _druckerliste_leeren()


def test_roh_drucken_weist_unsinn_ab_statt_zu_werfen():
    from app.drucker import roh_drucken
    for ip, port in (("../../etc/passwd", 9100), ("1.2.3.4;rm -rf", 9100),
                     ("192.168.178.14", 0), ("192.168.178.14", 99999)):
        geklappt, meldung = roh_drucken(ip, port, b"%PDF-1.4")
        assert geklappt is False
        assert meldung and "Traceback" not in meldung


def test_nicht_erreichbarer_drucker_ergibt_klartext():
    """Kein 500, keine Ausnahme — ein Satz, den der Nutzer lesen kann."""
    from app.drucker import erreichbar, roh_drucken
    geklappt, meldung = roh_drucken("127.0.0.1", 9, b"%PDF-1.4")
    assert geklappt is False
    assert "antwortet nicht" in meldung
    assert erreichbar("127.0.0.1", 9) is False


def test_die_bytes_kommen_unveraendert_am_ziel_an():
    """Der Sendeweg gegen einen lokalen Test-Socket — NIE gegen ein echtes
    Geraet des Nutzers. Ueber Port 9100 wird nichts umgewandelt: was
    reingeht, kommt raus."""
    import socket
    import threading

    from app.drucker import erreichbar, roh_drucken

    empfangen: list[bytes] = []
    lauscher = socket.socket()
    lauscher.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lauscher.bind(("127.0.0.1", 0))
    lauscher.listen(2)
    port = lauscher.getsockname()[1]

    def annehmen() -> None:
        for _ in range(2):
            verbindung, _ = lauscher.accept()
            with verbindung:
                puffer = b""
                while True:
                    stueck = verbindung.recv(4096)
                    if not stueck:
                        break
                    puffer += stueck
            empfangen.append(puffer)

    faden = threading.Thread(target=annehmen, daemon=True)
    faden.start()
    try:
        # Der Pruefknopf oeffnet nur die Verbindung und druckt nichts.
        assert erreichbar("127.0.0.1", port) is True
        geklappt, meldung = roh_drucken("127.0.0.1", port, b"%PDF-1.4 Muster")
        assert geklappt is True
        # Ehrlich: „geschickt", nicht „gedruckt" — Port 9100 meldet nichts
        # darueber zurueck, ob das Geraet die Bytes versteht.
        assert "geschickt" in meldung
        faden.join(timeout=5)
    finally:
        lauscher.close()
    assert empfangen[-1] == b"%PDF-1.4 Muster"
