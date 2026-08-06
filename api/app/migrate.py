"""Leichtgewichtige Schema-Angleichung für SQLite.

`SQLModel.metadata.create_all` legt ausschliesslich fehlende *Tabellen* an —
neue *Spalten* an bereits bestehenden Tabellen bleiben unberuecksichtigt. Eine
gewachsene Datenbank wuerde dadurch beim ersten Zugriff brechen. Hier werden
fehlende Spalten nachgezogen, damit bestehende Daten erhalten bleiben.
"""
import json
import logging

from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, SQLModel, select

log = logging.getLogger("immocalc")


# CCCLXII: Jede Immobilie braucht diese beiden umlagefähigen Kostenarten. Der
# Bestand hat oft nur „Gebäudeversicherung" (oder keine) — hier wird je Objekt
# nachgezogen, was fehlt. Rein additiv, idempotent, nichts wird angefasst.
PFLICHT_KOSTENARTEN: tuple[str, ...] = ("Gebäudeversicherung", "Gebäudehaftpflicht")


def _fold(text_: str | None) -> str:
    """Vergleichsschlüssel: klein, ohne Umlaute/ß, ohne Randweißraum.

    Umlaut-tolerant wie `kostenarten._fold`, damit „Gebaeudehaftpflicht" und
    „Gebäudehaftpflicht" als dieselbe Kostenart gelten und kein Duplikat
    entsteht. Dort geliehen, wenn vorhanden; sonst diese schlanke Kopie."""
    s = (text_ or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


try:                                                     # pragma: no cover
    from .kostenarten import _fold as _fold             # bevorzugt die zentrale
except Exception:                                        # noqa: BLE001
    pass                                                 # Fallback bleibt gültig


def pflicht_kostenarten_sichern(engine: Engine) -> list[str]:
    """Stellt je Objekt sicher, dass jede Pflicht-Kostenart existiert (CCCLXII).

    Für JEDES Objekt wird geprüft, ob eine aktive Kostenart mit dem passenden
    Namen (umlaut-/schreibweisentolerant) schon da ist. Fehlt sie, wird sie
    angelegt — sonst nichts. Es wird nie gelöscht, umbenannt oder deaktiviert;
    keine bestehende Kostenart wird angefasst. Idempotent: ein zweiter Lauf
    legt nichts Doppeltes an. Gibt die neu angelegten „objekt.name"-Paare
    zurück. Robust ohne Objekte (dann leere Liste, kein Commit-Effekt)."""
    from .models import Kostenart, Objekt

    gesetzt: list[str] = []
    with Session(engine) as session:
        objekte = session.exec(select(Objekt)).all()
        for o in objekte:
            vorhanden = session.exec(
                select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
            bekannt = {_fold(k.name) for k in vorhanden}
            for name in PFLICHT_KOSTENARTEN:
                if _fold(name) in bekannt:
                    continue
                session.add(Kostenart(objekt_id=o.id, name=name,
                                      umlagefaehig=True, aktiv=True))
                # gleich mitzählen: zwei Pflichtnamen desselben Objekts dürfen
                # sich im selben Lauf nicht gegenseitig als „fehlt" ausweisen.
                bekannt.add(_fold(name))
                gesetzt.append(f"{o.id}:{name}")
        session.commit()
    if gesetzt:
        log.info("Pflicht-Kostenarten ergänzt: %s", ", ".join(gesetzt))
    return gesetzt


def _literal(wert) -> str | None:
    if isinstance(wert, bool):
        return "1" if wert else "0"
    if isinstance(wert, (int, float)):
        return str(wert)
    if isinstance(wert, str):
        return "'" + wert.replace("'", "''") + "'"
    if isinstance(wert, (dict, list)):
        # JSON-Spalten (Kostenposition.anteile) liegen als Text in SQLite.
        return "'" + json.dumps(wert).replace("'", "''") + "'"
    return None


def _sql_vorgabe(spalte) -> str | None:
    """SQL-Literal für den Default einer Spalte.

    Auch für erzeugte Vorgaben (`default_factory`, in SQLAlchemy ein Callable):
    ohne sie bliebe `Kostenposition.anteile` in Bestandszeilen NULL, und die
    Abrechnung stolpert später über `None.values()` — die Zeitraumseite
    antwortet dann mit 500, obwohl die Daten unversehrt sind.
    """
    default = getattr(spalte, "default", None)
    if default is None:
        # Kein Default im Modell: den leeren Wert aus dem Spaltentyp ableiten,
        # damit eine gewachsene Datenbank nicht NULL enthält, wo eine frisch
        # angelegte NOT NULL hätte.
        return _neutral_fuer(spalte)
    if getattr(default, "is_callable", False):
        try:
            return _literal(default.arg(None))
        except Exception:       # noqa: BLE001 — eine Vorgabe ist kein Muss
            return None
    return _literal(getattr(default, "arg", None))


def _neutral_fuer(spalte) -> str | None:
    """„Nichts" in der Sprache des Spaltentyps."""
    typ = spalte.type.__class__.__name__.upper()
    # JSON auch dann, wenn die Spalte NULL erlaubt: der Lesecode erwartet ein
    # dict. Ein NULL dort legt die ganze Zeitraumseite lahm.
    if "JSON" in typ:
        return "'{}'"
    if spalte.nullable or spalte.primary_key:
        return None
    if any(t in typ for t in ("INT", "FLOAT", "NUMERIC", "DECIMAL")):
        return "0"
    if any(t in typ for t in ("VARCHAR", "TEXT", "STRING")):
        return "''"
    return None


# Eindeutigkeiten, die `create_all` nur an einer *neuen* Tabelle anlegt. An
# einer gewachsenen Datenbank fehlen sie sonst für immer — der Index kommt
# additiv hinzu, keine Spalte ändert sich, gelöscht wird nichts.
EINDEUTIG: list[tuple[str, str, str]] = [
    # Tabelle, Spalte, Indexname
    ("dokument", "pfad", "ux_dokument_pfad"),
]


# Suchindizes, die `create_all` ebenfalls nur an einer *neuen* Tabelle anlegt.
# Eine per ALTER ergänzte Spalte bekommt ihren Index sonst nie —
# `Dokument.position_id` wird an jeder Position der Zeitraumseite abgefragt
# (CLXXXIII). Rein additiv: angelegt wird nur, was fehlt, entfernt wird nichts.
INDEXE: list[tuple[str, str, str]] = [
    # Tabelle, Spalte, Indexname
    ("dokument", "position_id", "ix_dokument_position_id"),
]


def indizes_sichern(conn, tabellen: set[str] | None = None) -> list[str]:
    """Legt die Suchindizes aus `INDEXE` an. Gibt die gesetzten zurück."""
    gesetzt: list[str] = []
    for tabelle, spalte, name in INDEXE:
        if tabellen is not None and tabelle not in tabellen:
            continue
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" '
                          f'ON "{tabelle}" ("{spalte}")'))
        gesetzt.append(name)
    return gesetzt


def _doppel(conn, tabelle: str, spalte: str) -> list[tuple[str, int]]:
    """Werte, die mehrfach vorkommen — die einzige Hürde für den Index."""
    zeilen = conn.execute(text(
        f'SELECT "{spalte}", count(*) AS anzahl FROM "{tabelle}" '
        f'GROUP BY "{spalte}" HAVING count(*) > 1')).all()
    return [(str(z[0]), int(z[1])) for z in zeilen]


def eindeutigkeit_sichern(conn, tabellen: set[str] | None = None) -> list[str]:
    """Legt die Unique-Indizes aus `EINDEUTIG` an. Gibt die gesetzten zurück.

    Findet sich ein Wert doppelt, scheitert das Anlegen — dann wird der
    Doppel-Wert protokolliert, statt still nichts zu tun. Entfernt wird
    nichts: welcher der beiden Einträge weg soll, entscheidet der Nutzer.
    """
    gesetzt: list[str] = []
    for tabelle, spalte, name in EINDEUTIG:
        if tabellen is not None and tabelle not in tabellen:
            continue
        doppel = _doppel(conn, tabelle, spalte)
        if doppel:
            log.warning("%s.%s ist nicht eindeutig — kein Index. Mehrfach: %s",
                        tabelle, spalte,
                        ", ".join(f"{w} ({n}x)" for w, n in doppel[:10]))
            continue
        conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{name}" '
                          f'ON "{tabelle}" ("{spalte}")'))
        gesetzt.append(name)
    return gesetzt


# N213 — genau ein Objekt behält die vollständige, historisch gewachsene
# Laufer-Sicht (Stromkette, HKV, Wärmemengenverteilung, PV-/E-Tankstellen-
# Kette): die Laufer Str. 5 selbst. Alle anderen fallen auf `standard`. Der
# Setter läuft beim Start und ist idempotent — er stellt nur um, wenn das
# Feld noch auf dem Default `standard` steht. Ein Nutzer, der Laufer bewusst
# auf `standard` gesetzt hat, wird nicht überschrieben (er hat es einmal
# gewollt); ein anderes Objekt wird nie automatisch umgestellt.
LAUFER_SLUG: str = "eschenau-laufer-str-5"
LAUFER_MODELL: str = "laufer_spezial"


def laufer_modell_setzen(engine: Engine) -> bool:
    """Setzt Laufers Modell auf `laufer_spezial`, sofern noch Default.

    Nur der eine bekannte Slug wird angefasst, nur wenn `modell == 'standard'`
    (der Default). Rückgabe: True, wenn eine Änderung gemacht wurde. Robust
    gegen fehlende Spalte (frisches Schema ohne Migration) oder fehlendes
    Objekt (frische DB ohne Bestand). Additiv, idempotent.
    """
    from .models import Objekt

    try:
        with Session(engine) as session:
            objekt = session.exec(
                select(Objekt).where(Objekt.slug == LAUFER_SLUG)).first()
            if not objekt:
                return False
            if (objekt.modell or "").strip() != "standard":
                return False
            objekt.modell = LAUFER_MODELL
            session.add(objekt)
            session.commit()
            log.info("Objekt-Modell auf %s gesetzt: %s",
                     LAUFER_MODELL, LAUFER_SLUG)
            return True
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Laufer-Modell nicht gesetzt: %s", fehler)
        return False


def tankstelle_zukunftsmarker_bereinigen(engine: Engine) -> int:
    """N220 — Altlast vor dem Zukunfts-Guard räumen: Marker für Monate/Quartale,
    die bei diesem Start noch nicht abgeschlossen sind, werden geleert.

    `versenden` markierte vor dem Fix jeden Monat der gewählten Periode als
    abgerechnet — auch künftige, noch ungeladene (derselbe Guard fehlte dort,
    den `abgerechnet_setzen` schon hatte). Diese bereits geschriebenen Marker
    bleiben sonst für immer stehen. Kein Schema, keine Zeile wird gelöscht —
    nur der Wert geleert (derselbe Weg wie eine bewusste Entfernung über die
    Oberfläche, siehe `abgerechnet_setzen`); ein leerer Wert zählt in
    `abgerechnet_marker` ohnehin nicht mehr. Idempotent: läuft „heute" ein
    Zeitraum ab, wird er beim nächsten Start nicht mehr angefasst."""
    from datetime import date

    from .models import Einstellung
    from .tanken.marker import S_VERSENDET
    from .tanken.perioden import _monatsende, quartal_zeitraum

    heute = date.today()
    bereinigt = 0
    try:
        with Session(engine) as session:
            zeilen = session.exec(select(Einstellung).where(
                Einstellung.schluessel.like(f"{S_VERSENDET}:%"))).all()
            for e in zeilen:
                if not e.wert:
                    continue
                teile = e.schluessel.split(":")
                if len(teile) != 5:
                    continue
                _, _slug, jahr_roh, periode, _nid = teile
                try:
                    jahr = int(jahr_roh)
                    if periode.startswith("M"):
                        ende = _monatsende(jahr, int(periode[1:]))
                    elif periode.startswith("Q"):
                        ende = quartal_zeitraum(jahr, int(periode[1:]))[1]
                    else:
                        continue
                except ValueError:
                    continue
                if ende >= heute:
                    e.wert = ""
                    session.add(e)
                    bereinigt += 1
            if bereinigt:
                session.commit()
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Zukunfts-Marker nicht bereinigt: %s", fehler)
        return 0
    return bereinigt


def migriere(engine: Engine) -> list[str]:
    """Ergänzt fehlende Spalten. Gibt die durchgeführten Änderungen zurück."""
    inspector = inspect(engine)
    bestehende = set(inspector.get_table_names())
    geaendert: list[str] = []

    with engine.begin() as conn:
        for tabelle in SQLModel.metadata.sorted_tables:
            if tabelle.name not in bestehende:
                continue  # create_all hat sich darum gekümmert
            vorhanden = {s["name"] for s in inspector.get_columns(tabelle.name)}
            for spalte in tabelle.columns:
                if spalte.name in vorhanden:
                    continue
                typ = spalte.type.compile(engine.dialect)
                # Bewusst ohne NOT NULL: bestehende Zeilen haben keinen Wert.
                conn.execute(text(
                    f'ALTER TABLE "{tabelle.name}" ADD COLUMN "{spalte.name}" {typ}'))
                vorgabe = _sql_vorgabe(spalte)
                if vorgabe is not None:
                    conn.execute(text(
                        f'UPDATE "{tabelle.name}" SET "{spalte.name}" = {vorgabe} '
                        f'WHERE "{spalte.name}" IS NULL'))
                geaendert.append(f"{tabelle.name}.{spalte.name}")

        # Erst nach den Spalten: der Index braucht die Tabelle, wie sie
        # danach aussieht.
        try:
            geaendert += indizes_sichern(conn, bestehende)
            geaendert += eindeutigkeit_sichern(conn, bestehende)
        except Exception as fehler:                   # noqa: BLE001
            # Ein fehlender Index darf den Start nicht verhindern — die Sperre
            # im Code greift weiter, der Betrieb geht ohne ihn.
            log.warning("Eindeutigkeit nicht gesetzt: %s", fehler)

    # Nach den Spalten, in eigener Session: die Pflicht-Kostenarten je Objekt
    # nachziehen (CCCLXII). Betrifft Bestandsobjekte, die schon in der Datenbank
    # stehen; rein additiv, idempotent.
    try:
        geaendert += pflicht_kostenarten_sichern(engine)
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Pflicht-Kostenarten nicht gesetzt: %s", fehler)

    # N213 — Laufers Objekt-Modell auf `laufer_spezial` heben, falls noch Default.
    # Rein additiv, idempotent; keine anderen Slugs werden angefasst.
    try:
        if laufer_modell_setzen(engine):
            geaendert.append(f"objekt.modell[{LAUFER_SLUG}]={LAUFER_MODELL}")
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Laufer-Modell nicht gesetzt: %s", fehler)

    # N220 — Zukunfts-Marker der E-Tankstelle räumen (Altlast vor dem Guard).
    try:
        n = tankstelle_zukunftsmarker_bereinigen(engine)
        if n:
            geaendert.append(f"tankstelle_versendet[{n} geleert]")
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Zukunfts-Marker nicht bereinigt: %s", fehler)

    if geaendert:
        log.info("Schema ergänzt: %s", ", ".join(geaendert))
    return geaendert
