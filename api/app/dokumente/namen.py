"""Dateinamen, Pfade, Ordnertitel — die reine Textmechanik der Ablage.

Alle Helfer arbeiten ohne Datenbank und ohne Cloud: ein Name kommt herein, ein
Name kommt heraus. Das macht sie leicht prüfbar (`tests/test_dokumente.py`)
und wiederverwendbar aus mehreren Ecken des Routers, ohne dass sich Fachlogik
kopiert.

Zwei Zusicherungen sind wichtig:

* **Idempotenz.** Ein Name, der schon Standard aussieht, kommt unverändert
  wieder heraus (`dateiname`). Ohne das ginge bei jeder Korrektur des Jahres
  die Bezeichnung samt Betrag verloren.
* **Keine Löschung durch Zufall.** Ersetzt wird zum Bindestrich, nie einfach
  gestrichen — sonst klebte aus „231€+10€+180€" ein „23110180" zusammen.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

from ..bezeichnung import (betragsteil, datumsteil, ohne_betrag, ohne_datum,
                           ohne_ordnerwort, vergleichsname)
from ..cloudkern import ARTKUERZEL, ZIELORDNER


DOKUMENTARTEN = list(ZIELORDNER.keys())

# Die eine Dokumentart, die an mehreren Stellen ausdrücklich gemeint ist: der
# Lageplan hängt an einer Einheit (CCCXXVI), wird beim Geradedrehen ohne
# Seitenlage-Erkennung behandelt und ist vom Duplikat-Bündeln ausgenommen —
# mehrere Fotos desselben Plans sind dort gewollt. Als Konstante, damit sich
# der Vergleich nicht als loser Text durch den Code zieht.
LAGEPLAN = "Lageplan"


def _saubere_datei(text_: str) -> str:
    """Ein Stück Dateiname: keine Pfadtrenner, keine Trennzeichen am Rand.

    Unerlaubte Zeichen werden zum Bindestrich, nicht gelöscht — sonst klebte
    aus „231€+10€+180€" ein „23110180" zusammen und aus „Fitness&Büro" ein
    „FitnessBüro"."""
    text_ = re.sub(r"[^\wäöüÄÖÜß.\- ]+", "-", text_ or "").strip()
    text_ = re.sub(r"\s+", "-", text_)
    # Wo etwas herausgeschnitten wurde — Datum, Betrag, Ordnerwort —, blieben
    # sonst "--", "_-" oder ".-" stehen.
    return re.sub(r"[-_.]{2,}", "-", text_).strip("-_.")


# Wörter, die jeder Beleg trägt und die niemandem beim Wiederfinden helfen.
# Steht nur so etwas da, tritt die Kostenposition an ihre Stelle.
_NICHTSSAGEND = {"rechnung", "beleg", "scan", "dokument", "schreiben",
                 "abrechnung", "jahresabrechnung", "kopie", "pdf"}


def _kern(text: str) -> str:
    """Vergleichsform für Kürzel/Kostenart/Sache (CCXXII).

    Dasselbe wie `bezeichnung.vergleichsname` — dort für Ordnernamen gedacht,
    hier für die Bausteine des Dateinamens wiederverwendet, damit es nicht
    zweimal dieselbe Regel gibt. Ziffern bleiben absichtlich erhalten (wie
    dort): ein `§35a` in einer Kostenart soll nicht mit einem beliebigen
    zufällig anderen Textfetzen verwechselt werden, nur weil beide nach dem
    Entfernen der Ziffern gleich aussehen."""
    return vergleichsname(text)


def _sagt_nichts(text: str) -> bool:
    """Ist das nur ein Allerweltswort wie „Rechnung"?"""
    return _kern(text) in _NICHTSSAGEND


def _ohne_dopplung(sache: str) -> str:
    """Aufeinanderfolgende gleiche Bausteine zusammenfassen — das Idempotenz-
    Netz: „Hausmeister-Hausmeister-Polster" → „Hausmeister-Polster". Heilt
    auch Namen, die ein früherer, noch nicht idempotenter Lauf verdoppelt hat."""
    raus: list[str] = []
    for t in (t for t in sache.split("-") if t):
        if not raus or _kern(raus[-1]) != _kern(t):
            raus.append(t)
    return "-".join(raus)


def _endung(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


def dateiname(jahr: int | None, kategorie: str, beschreibung: str,
              endung: str, monat: int | None = None,
              betrag: float | None = None, kostenart: str = "") -> str:
    """JJJJ-MM_Sache_1234,56€.pdf — drei Stücke, jedes genau einmal.

    * **Datum vorn.** Nur so sortiert sich der Ordner von selbst; der Monat
      kommt mit, sobald er bekannt ist.
    * **Die Sache in der Mitte** — und nur, was der Ordner *nicht* schon sagt
      (CXXII): im Ordner 60_Nebenkosten heisst nichts „…_Nebenkosten_…".
      Was der Nutzer selbst benannt hat, bleibt dabei stehen (XCVII); erkannt
      wird nur, was sonst niemand beisteuert.
    * **Der Betrag hinten** (CXXIII), damit man ihn im Ordner sofort sieht.

    Die Funktion ist absichtlich idempotent: ein Name, der schon so aussieht,
    kommt unverändert wieder heraus. Beim Korrigieren wird der bestehende Name
    zerlegt und neu gesetzt — ohne das ginge bei jeder Änderung des Jahres die
    Bezeichnung samt Betrag verloren.
    """
    roh = ohne_datum(ohne_betrag(beschreibung or ""))
    sache = _saubere_datei(ohne_ordnerwort(roh, kategorie))
    # Der Name bleibt idempotent: steht das Kürzel schon vorn — weil dieser
    # Name schon einmal durch diese Funktion lief —, wird es nicht doppelt
    # gesetzt („NK-NK-Kaminkehrer").
    vorn = ARTKUERZEL.get(kategorie, "")
    if vorn and _kern(sache).startswith(_kern(vorn)):
        sache = sache[len(vorn):].lstrip("-_ ") or sache
    # Die Kostenposition sagt genauer, worum es geht, als eine Bezeichnung wie
    # „Rechnung": aus 2026-02_Rechnung wird 2026-02_NK-Schornsteinfeger.
    # Heisst die Position wie die Art („Nebenkosten" unter Nebenkosten), sagt
    # sie nichts Neues — das Kürzel steht ohnehin schon vorn.
    if kostenart and _kern(kostenart) != _kern(kategorie):
        genau = _saubere_datei(kostenart)
        if not sache or _sagt_nichts(sache):
            sache = genau
        # Steht die Kostenart schon vorn (weil dieser Name schon einmal durch
        # diese Funktion lief), NICHT doppeln — „Hausmeister-Polster" bleibt,
        # wird nicht zu „Hausmeister-Hausmeister-Polster" (Idempotenz).
        elif _kern(sache).startswith(_kern(genau)):
            pass
        # „Wasser" unter der Position „Wasser" braucht nicht zweimal dazustehen
        elif _kern(sache) in _kern(genau):
            sache = genau
        else:
            sache = f"{genau}-{sache}"
    sache = _ohne_dopplung(sache)
    kuerzel = ARTKUERZEL.get(kategorie, "")
    mitte = f"{kuerzel}-{sache}" if kuerzel and sache else (sache or kuerzel)
    # N24 — ein Lageplan trägt KEIN Belegjahr: „ohne-Jahr_" wäre nur Rauschen.
    # Der Name sagt selbst „Lageplan …" (wie der Upload-Weg, N9) — daher kein
    # Datumsteil und ein vorangestelltes „Lageplan", falls es noch fehlt.
    if kategorie == "Lageplan":
        if not _kern(mitte).startswith(_kern("Lageplan")):
            mitte = f"Lageplan-{mitte}" if mitte else "Lageplan"
        teile = [mitte, betragsteil(betrag)]
    else:
        # N44 — KEIN „ohne-Jahr"-Vorsatz mehr: fehlt das Jahr, entfällt der
        # Datumsteil ganz. Ein Beleg ohne Jahr sortiert nach seinem Namen, nicht
        # unter einem sinnlosen Präfix, das der Nutzer wieder wegräumen müsste.
        datum = datumsteil(jahr, monat) if jahr else ""
        teile = [datum, mitte or "Beleg", betragsteil(betrag)]
    return "_".join(t for t in teile if t) + endung


def _art_im_namen(lesbar: str) -> str:
    """Steht die Art wörtlich im Namen („2024_Steuer_…"), gilt sie.

    Ab Wortanfang gesucht — sonst macht „Steuerberater" jede Post zur
    Steuerakte und „Nebenkostenwiderspruch" bliebe zufällig richtig."""
    for art in DOKUMENTARTEN:
        if re.search(r"\b" + re.escape(art.lower()), lesbar):
            return art
    return ""


def _bezeichnung(name: str) -> str:
    """Der ursprüngliche Name als Bezeichnung — ohne Endung, Datum und Betrag.

    Ohne sie hießen alle Belege eines Jahres gleich: aus
    „Grundsteuerbescheid 2024.pdf" wurde „2024_Steuer.pdf" und aus dem
    zweiten Bescheid „2024_Steuer-2.pdf". Was der Nutzer selbst benannt hat,
    bleibt erhalten (XCVII).

    Datum und Betrag fallen hier heraus, weil `dateiname` sie an ihrem festen
    Platz neu setzt — vorn und hinten. Sonst stünden sie zweimal da."""
    stamm = name.rsplit(".", 1)[0] if "." in name else name
    return ohne_datum(ohne_betrag(stamm))


# CCLXXVIII: `.immocalc`-Steckbriefe (CCLXXIV) liegen als Sidecar neben dem
# Beleg. Sie sind keine eigenständigen Belege und dürfen nie als Dokument in den
# Eingang wandern — sonst stünde neben jedem PDF eine zweite, sinnlose Zeile.
def _ist_sidecar(name: str) -> bool:
    """Ist das ein `.immocalc`-Steckbrief statt eines echten Belegs?"""
    return (name or "").lower().endswith(".immocalc")


# --------------------------------------------------------------------------
# Pfad-Bausteine für den Abgleich
# --------------------------------------------------------------------------

def _norm(pfad: str) -> str:
    """Vergleichsform eines Cloud-Pfades: führender Trenner, keiner am Ende."""
    return "/" + "/".join(t for t in (pfad or "").split("/") if t)


def _elternteil(pfad: str) -> str:
    return _norm(pfad).rsplit("/", 1)[0] or "/"


def _einziger(kandidaten: list[str]) -> str:
    """Genau ein Treffer zählt. Bei mehreren wird nicht geraten — zwei gleich
    heissende Dateien lassen sich nicht auseinanderhalten, und ein falsch
    umgehängter Eintrag ist schlimmer als ein gemeldeter."""
    return kandidaten[0] if len(kandidaten) == 1 else ""


def _elternordner(pfad: str) -> str:
    """Der Elternordner eines Cloud-Pfades, ohne führenden Trenner —
    passend für `_freier_name`/`client.verschiebe`. Leer, wenn die Datei im
    Wurzelverzeichnis liegt."""
    return pfad.strip("/").rpartition("/")[0]


def _ordner_aus_pfad(pfad: str, wurzel: str) -> str:
    """Der echte Unterordner, in dem eine Datei liegt (CCCXVI).

    Aus `pfad` wird der Teil unter dem Objektordner genommen; der erste
    Abschnitt davon ist der Ordner. Liegt die Datei direkt im Hauptordner,
    ist das Ergebnis leer ("") — sie ist frisch hereingekommen."""
    p = (pfad or "").strip("/")
    w = (wurzel or "").strip("/")
    if w and p.startswith(w):
        p = p[len(w):].strip("/")
    teile = p.split("/")
    return teile[0] if len(teile) > 1 else ""


def _ordner_titel(ordner: str) -> str:
    """Der Ordnername lesbar: „40_Kauf_Eigentum_Finanzierung" → „Kauf Eigentum
    Finanzierung". Leer heißt Hauptordner (frisch hereingekommen)."""
    if not ordner:
        return "Neu / Hauptordner"
    ohne_nr = ordner.split("_", 1)[-1] if ordner[:2].isdigit() else ordner
    return ohne_nr.replace("_", " ").strip() or ordner


def _sidecar_pfad(pfad: str) -> str:
    """Der Pfad der `.immocalc`-Datei neben dem Beleg: die Endung wird ersetzt,
    ein Beleg ohne Endung bekommt sie angehängt."""
    stamm, punkt, endung = pfad.rpartition(".")
    if punkt and "/" not in endung:      # der Punkt gehört zur Dateiendung
        return f"{stamm}.immocalc"
    return f"{pfad}.immocalc"


def _dateistamm(name: str) -> str:
    """Der Name ohne Endung — „2025_NK-Müll.pdf" → „2025_NK-Müll". Die `.immocalc`
    -Sidecar teilt sich den Stamm mit ihrem Beleg."""
    stamm, punkt, endung = name.rpartition(".")
    return stamm if (punkt and "/" not in endung) else name


def _adr_norm(text: str) -> str:
    """Vergleichsform einer Adresse für den Objekt-Abgleich: klein, ohne
    Sonderzeichen, „Straße"/„Str."/„str" auf denselben Nenner gebracht."""
    t = (text or "").lower().replace("ß", "ss")
    t = t.replace("strasse", "str")
    t = re.sub(r"[^0-9a-zäöü]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _dateiname_kopfzeile(name: str) -> str:
    """Der Dateiname für `Content-Disposition` — auch mit € und Umlauten.

    Ein HTTP-Kopf trägt kein €. Seit der Betrag hinten im Namen steht
    (CXXIII), heisst fast jede Rechnung „…_1234,56€.pdf" — und jede Vorschau
    darauf antwortete mit einem 500er, weil sich der Kopf nicht kodieren
    liess. Also beides (RFC 6266): ein Name ohne Sonderzeichen als Rückfall
    und daneben der vollständige, prozentkodiert. Jeder heutige Browser nimmt
    den zweiten."""
    ohne_zoll = unicodedata.normalize("NFKD", name.replace('"', ""))
    schlicht = ohne_zoll.encode("ascii", "ignore").decode("ascii").strip()
    return (f'filename="{schlicht or "beleg"}"; '
            f"filename*=UTF-8''{quote(name)}")
