"""N288-B — Wächter für die Routen-Reihenfolge in `app/main.py`.

`stammdaten.py` hält den Fänger `/api/objekte/{slug}/{bereich}`. Starlette
nimmt die **erste** passende Route; ein konkreterer Pfad wie
`/api/objekte/{slug}/anteile` muss deshalb VOR dem Fänger registriert sein,
sonst antwortet der Fänger mit „Unbekannter Bereich" und der Nutzer sieht eine
leere Seite. Bisher sicherte nur Kommentardisziplin in `main.py` diese
Reihenfolge — ein Umbau hätte sie lautlos brechen können.

Dieser Test prüft strukturell statt beispielhaft: er liest die gebaute App aus,
findet JEDE Route, die der Fänger verschlucken könnte, und meldet Pfad, Methode
und Router, falls eine davon zu spät registriert ist.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_routen_reihenfolge.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.main import app  # noqa: E402

FAENGER = "/api/objekte/{slug}/{bereich}"

# Untergrenze für den Selbstschutz: so viele Pfad/Methode-Paare unterliegen der
# Regel heute (18). Fällt die Zahl darunter, prüft der Wächter womöglich nichts
# mehr — etwa weil ein Umbau die Routen anders einhängt.
MINDESTENS_BETROFFEN = 8


def _routen() -> list[tuple[int, str, frozenset[str], str]]:
    """Alle registrierten Endpunkte in Match-Reihenfolge.

    Ab FastAPI 0.139 steht in `app.routes` je `include_router` ein Wrapper
    (`_IncludedRouter`) statt der flachen Routen; `effective_candidates()`
    liefert die enthaltenen Routen mit bereits angewandtem Prefix — in genau
    der Reihenfolge, in der Starlette sie durchprobiert. Ältere Versionen
    legen die Routen flach ab; beide Formen werden hier abgedeckt.
    """
    gefunden: list[tuple[int, str, frozenset[str], str]] = []

    def sammle(routen) -> None:
        for route in routen:
            if hasattr(route, "effective_candidates"):
                sammle(route.effective_candidates())
                continue
            pfad = getattr(route, "path", None)
            methoden = getattr(route, "methods", None)
            if not pfad or not methoden:
                continue        # Mounts, WebSockets, statische Verzeichnisse
            modul = getattr(getattr(route, "endpoint", None), "__module__", "?")
            gefunden.append((len(gefunden), pfad, frozenset(methoden), modul))

    sammle(app.routes)
    return gefunden


def _ist_platzhalter(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _verschluckt(faenger: str, pfad: str) -> bool:
    """Würde `faenger` jede Anfrage an `pfad` abfangen?

    Genau dann, wenn beide gleich viele Segmente haben, jedes Fängersegment das
    des Pfades abdeckt (Platzhalter deckt alles, Literal nur sich selbst) und
    der Pfad mindestens an einer Stelle konkreter ist. Nur dann kann der Fänger
    zuerst greifen, obwohl der konkretere Pfad gemeint war.
    """
    fs = faenger.strip("/").split("/")
    ps = pfad.strip("/").split("/")
    if len(fs) != len(ps) or faenger == pfad:
        return False
    if not all(_ist_platzhalter(f) or f == p for f, p in zip(fs, ps)):
        return False
    return any(_ist_platzhalter(f) and not _ist_platzhalter(p)
               for f, p in zip(fs, ps))


def _betroffene(faenger_pfad: str) -> list[tuple[bool, str, str, str, int, int]]:
    """(zu_spaet, methode, pfad, modul, position, faenger_position) je Treffer."""
    alle = _routen()
    treffer = []
    for f_pos, f_pfad, f_methoden, _f_modul in alle:
        if f_pfad != faenger_pfad:
            continue
        for pos, pfad, methoden, modul in alle:
            if not _verschluckt(f_pfad, pfad):
                continue
            for methode in sorted(f_methoden & methoden):
                treffer.append((pos > f_pos, methode, pfad, modul, pos, f_pos))
    return treffer


def test_der_stammdaten_faenger_existiert_ueberhaupt_noch():
    """Ohne Fänger prüften die anderen Tests hier stillschweigend nichts."""
    pfade = {pfad for _pos, pfad, _m, _mod in _routen()}
    assert FAENGER in pfade, (
        f"{FAENGER} ist nicht mehr registriert — dieser Wächter (und die "
        "Reihenfolge-Kommentare in api/app/main.py) sind dann gegenstandslos.")


def test_es_gibt_routen_die_der_reihenfolge_regel_unterliegen():
    treffer = _betroffene(FAENGER)
    assert len(treffer) >= MINDESTENS_BETROFFEN, (
        f"Nur {len(treffer)} Pfad/Methode-Paare unterliegen dem Fänger "
        f"{FAENGER} (erwartet mindestens {MINDESTENS_BETROFFEN}). Entweder "
        "wurden Routen entfernt oder die Auswertung von app.routes greift "
        "nicht mehr — dann prüft dieser Wächter nichts.")


def test_keine_route_wird_vom_stammdaten_faenger_verschluckt():
    treffer = _betroffene(FAENGER)
    zu_spaet = [t for t in treffer if t[0]]
    zeilen = [f"  {methode} {pfad}  (Router {modul}, Position {pos} — "
              f"Fänger steht auf {f_pos})"
              for _spaet, methode, pfad, modul, pos, f_pos in zu_spaet]
    assert not zu_spaet, (
        f"Routen-Reihenfolge kaputt: der Fänger {FAENGER} aus "
        "app/routers/stammdaten.py steht VOR diesen konkreteren Routen und "
        "beantwortet sie mit „Unbekannter Bereich“:\n" + "\n".join(zeilen) +
        "\n\nAbhilfe: in api/app/main.py die genannten include_router(...)-"
        "Aufrufe VOR app.include_router(stammdaten.router) ziehen.")


def test_kein_faenger_im_ganzen_api_verschluckt_eine_spaetere_route():
    """Dieselbe Regel für jede andere Route — der Fänger in stammdaten.py ist
    nur der bekannteste. Findet auch neue Fallen, die noch niemand kommentiert
    hat."""
    alle = _routen()
    fehler = []
    for f_pos, f_pfad, f_methoden, f_modul in alle:
        for pos, pfad, methoden, modul in alle:
            if pos <= f_pos or not _verschluckt(f_pfad, pfad):
                continue
            for methode in sorted(f_methoden & methoden):
                fehler.append(
                    f"  {methode} {pfad} ({modul}, Position {pos}) wird von "
                    f"{f_pfad} ({f_modul}, Position {f_pos}) abgefangen")
    assert not fehler, (
        "Ein allgemeinerer Pfad ist vor einem konkreteren registriert; die "
        "konkretere Route ist damit tot:\n" + "\n".join(fehler) +
        "\n\nAbhilfe: den konkreteren Router in api/app/main.py früher "
        "einhängen.")
