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


# N445 — Kostenarten, die erst nachträglich in den Katalog gekommen sind
# (N439, aus einer echten WEG-Abrechnung). Neue Immobilien bekommen sie über
# `defaultKosten()` im Onboarding; BESTEHENDE hatten sie nicht, und es gab
# keinen Weg, sie nachzuholen ausser sie von Hand anzulegen.
# Gebäudehaftpflicht steht bewusst NICHT hier: sie ist längst eine
# Pflicht-Kostenart (`PFLICHT_KOSTENARTEN`) und in jeder Immobilie sichtbar
# vorhanden — der eigene Test hat das aufgedeckt.
NACHZUEGLER_KOSTENARTEN: tuple[str, ...] = (
    "Zählermiete", "Abrechnungskosten", "Wartung Enthärtungsanlage",
    "Mattenservice",
)


def nachzuegler_kostenarten_sichern(engine: Engine) -> list[str]:
    """Die nachgereichten Kostenarten in JEDER bestehenden Immobilie anbieten
    — bewusst **verborgen** (`aktiv=False`).

    Nutzer: „biete die neuen Kostenarten in allen vorhandenen Immobilien an.
    Wenn ich auf Kostenarten konfigurieren gehe, müssen die als ausgeblendet
    drinstehen. Ich kann die dann als Pflicht oder als optional einblenden."

    Verborgen ist hier die richtige Vorgabe: sichtbar wären sie sofort offene
    Checklistenpunkte in laufenden Abrechnungen, obwohl niemand sie bestellt
    hat. So stehen sie bereit, ohne etwas zu behaupten.

    Idempotent und rein additiv wie `pflicht_kostenarten_sichern`: eine
    Kostenart, die es unter diesem Namen schon gibt, wird NIE angefasst —
    auch dann nicht, wenn sie dort sichtbar ist."""
    from .models import Kostenart, Objekt

    gesetzt: list[str] = []
    with Session(engine) as session:
        for o in session.exec(select(Objekt)).all():
            vorhanden = session.exec(
                select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
            bekannt = {_fold(k.name) for k in vorhanden}
            for name in NACHZUEGLER_KOSTENARTEN:
                if _fold(name) in bekannt:
                    continue
                session.add(Kostenart(objekt_id=o.id, name=name,
                                      umlagefaehig=True, aktiv=False))
                bekannt.add(_fold(name))
                gesetzt.append(f"{o.slug}:{name}")
        session.commit()
    if gesetzt:
        log.info("Nachgereichte Kostenarten ergänzt (verborgen): %s",
                 ", ".join(gesetzt))
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
    # N366 — Datum und Zeitstempel fehlten hier. Eine nachträglich ergänzte
    # Pflicht-Datumsspalte bekäme sonst NULL, und der Lesecode rechnet mit
    # einem `date` (`z.start:%d.%m.%Y`, `v.bis_datum + timedelta(...)`) — das
    # bricht mit 500 auf einer bestehenden Datenbank. Der Wert ist bewusst
    # erkennbar alt, damit eine ungepflegte Zeile auffällt statt „heute" zu
    # behaupten.
    if "DATETIME" in typ or "TIMESTAMP" in typ:
        return "'1970-01-01 00:00:00'"
    if "DATE" in typ:
        return "'1970-01-01'"
    if "BOOL" in typ:
        return "0"
    return None


# N314(i) — vorher standen hier zwei von Hand gepflegte Listen mit
# zusammen zwei Einträgen. Das Datenmodell verlangt an 45 Spalten
# `index=True`/`unique=True` — `create_all` legt die nur an einer NEUEN
# Tabelle an; eine per ALTER ergänzte Spalte (`Dokument.sha1`, `nc_fileid`, …)
# bekam ihren Index sonst nie. Jetzt aus dem Datenmodell selbst abgeleitet,
# wie schon bei `dokumentlinks.register()`/`einheitname.register()` — eine
# von Hand gepflegte Liste hängt sonst zuverlässig hinterher.
def _register() -> list[tuple[str, str, str, bool]]:
    """Tabelle, Spalte, Indexname, eindeutig — für jede Spalte mit
    `index=True` oder `unique=True`. Der Name folgt SQLAlchemys eigener
    Konvention (`ix_<tabelle>_<spalte>`), damit `CREATE ... IF NOT EXISTS`
    auf einer frisch angelegten Tabelle exakt den schon vorhandenen Index
    trifft, statt einen zweiten, gleichbedeutenden danebenzusetzen."""
    eintraege: list[tuple[str, str, str, bool]] = []
    for tabelle in SQLModel.metadata.tables.values():
        for spalte in tabelle.columns:
            if spalte.primary_key or not (spalte.index or spalte.unique):
                continue
            eintraege.append((tabelle.name, spalte.name,
                             f"ix_{tabelle.name}_{spalte.name}",
                             bool(spalte.unique)))
    return eintraege


def _vorhandene_indizes(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'index'")).all()}


def indizes_sichern(conn, tabellen: set[str] | None = None) -> list[str]:
    """Legt alle nicht-eindeutigen Suchindizes des Datenmodells an, die noch
    fehlen. `eindeutigkeit_sichern` regelt die `unique=True`-Spalten
    gesondert, weil dort vorher auf Dopplungen geprüft werden muss.

    Ohne `tabellen` wird selbst nachgesehen, was es überhaupt gibt — ein
    Aufrufer, der nur EINE Tabelle im Blick hat (`_eindeutigkeit_sichern` in
    `routers/dokumente.py` kennt nur „dokument"), soll nicht an einer der
    anderen 40+ registrierten Tabellen scheitern, die bei ihm noch fehlt."""
    if tabellen is None:
        tabellen = set(inspect(conn).get_table_names())
    vorhanden = _vorhandene_indizes(conn)
    gesetzt: list[str] = []
    for tabelle, spalte, name, eindeutig in _register():
        if eindeutig or name in vorhanden:
            continue
        if tabelle not in tabellen:
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
    """Legt die Unique-Indizes des Datenmodells (`unique=True`) an, die noch
    fehlen. Gibt die gesetzten zurück.

    Findet sich ein Wert doppelt, scheitert das Anlegen — dann wird der
    Doppel-Wert protokolliert, statt still nichts zu tun. Entfernt wird
    nichts: welcher der beiden Einträge weg soll, entscheidet der Nutzer.

    Ohne `tabellen` wird selbst nachgesehen, was es gibt (siehe `indizes_sichern`).
    """
    if tabellen is None:
        tabellen = set(inspect(conn).get_table_names())
    vorhanden = _vorhandene_indizes(conn)
    gesetzt: list[str] = []
    for tabelle, spalte, name, eindeutig in _register():
        if not eindeutig or name in vorhanden:
            continue
        if tabelle not in tabellen:
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


def miete_vorgaenger_backfuellen(engine: Engine) -> int:
    """N235 — Vorgänger-Verknüpfung für vor N228 angelegte Mieterhöhungen.

    `Miete.vorgaenger_id` wird seit N228 beim Anlegen einer Mieterhöhung
    gesetzt (`erhoehungFormular()`/`handlers.js`) — Alt-Fälle, die VOR diesem
    Fix als zwei getrennte Mietstände angelegt wurden, blieben unverknüpft
    und zeigten deshalb die Dokumente des Vorgängers nicht (die Checkliste
    hängt an derselben Kette wie `belege_zum_eintrag`).

    Additiv, idempotent: nur Zeilen mit `vorgaenger_id IS NULL` werden
    angefasst, und nur wenn GENAU EIN eindeutiger Kandidat gefunden wird
    (gleiches Objekt, gleiche Einheit, gleiche nicht-leere Partei, Beginn
    == Vorgänger-Ende + 1 Tag) — mehrdeutige Fälle bleiben lieber
    unverknüpft als falsch verknüpft."""
    from datetime import timedelta

    from .models import Miete

    aktualisiert = 0
    try:
        with Session(engine) as session:
            alle = session.exec(select(Miete)).all()
            for m in alle:
                if m.vorgaenger_id or not m.partei or not m.ab_datum:
                    continue
                kandidaten = [
                    v for v in alle
                    if v.id != m.id and v.objekt_id == m.objekt_id
                    and (v.einheit or "") == (m.einheit or "")
                    and (v.partei or "").strip() == m.partei.strip()
                    and v.bis_datum and v.bis_datum + timedelta(days=1) == m.ab_datum
                ]
                if len(kandidaten) == 1:
                    m.vorgaenger_id = kandidaten[0].id
                    session.add(m)
                    aktualisiert += 1
            if aktualisiert:
                session.commit()
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Vorgänger-Verknüpfung nicht ergänzt: %s", fehler)
        return 0
    return aktualisiert


def miete_kaution_vorgaenger_uebernehmen(engine: Engine) -> int:
    """N239 — Kaution-Objektkonto/-Eingang gilt für die ganze Mietbeziehung.

    Die Kaution wird nicht bei jeder Mieterhöhung neu eingezahlt — ein
    Vermerk „Kaution auf Objektkonto" bzw. das Eingangsdatum am alten
    Mietstand muss deshalb auch am NEUEN (per Mieterhöhung angelegten)
    Mietstand gelten, genau wie die Dokumente (N235). Additiv, idempotent:
    läuft die `vorgaenger_id`-Kette rückwärts ab (mit Ringschutz, mehrstufige
    Mieterhöhungen eingeschlossen) und übernimmt einen fehlenden Wert vom
    nächsten Vorfahren, der ihn trägt. Ein Mietstand mit einem EIGENEN Wert
    (kaution_objektkonto=True bzw. gesetztes kaution_eingang) wird nie
    überschrieben — nur der leere/Default-Fall wird aufgefüllt."""
    from .models import Miete

    aktualisiert = 0
    try:
        with Session(engine) as session:
            alle = {m.id: m for m in session.exec(select(Miete)).all()}
            for m in alle.values():
                if m.kaution_objektkonto and m.kaution_eingang:
                    continue
                gesehen = {m.id}
                aktuell = m.vorgaenger_id
                gefunden_konto = False
                gefunden_eingang = None
                while aktuell and aktuell not in gesehen:
                    v = alle.get(aktuell)
                    if not v:
                        break
                    gesehen.add(aktuell)
                    gefunden_konto = gefunden_konto or v.kaution_objektkonto
                    if gefunden_eingang is None and v.kaution_eingang:
                        gefunden_eingang = v.kaution_eingang
                    if gefunden_konto and gefunden_eingang:
                        break
                    aktuell = v.vorgaenger_id
                geaendert_zeile = False
                if gefunden_konto and not m.kaution_objektkonto:
                    m.kaution_objektkonto = True
                    geaendert_zeile = True
                if gefunden_eingang and not m.kaution_eingang:
                    m.kaution_eingang = gefunden_eingang
                    geaendert_zeile = True
                if geaendert_zeile:
                    session.add(m)
                    aktualisiert += 1
            if aktualisiert:
                session.commit()
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Kaution-Vorgänger-Übernahme nicht ergänzt: %s", fehler)
        return 0
    return aktualisiert


# N436 — die Bestandsfamilie. Die Migration darf kein Passwort erfinden
# (`passwort_hash` bleibt None); die Familie wird erst über den
# "Passwort festlegen"-Erstanmeldungs-Flow nutzbar (routers/auth.py).
BESTANDSFAMILIE_NAME: str = "Heidenreich"

# Tabellen, die vor N436 keine familie_id kannten und aus dem Bestand heraus
# auf die Bestandsfamilie zurückgesetzt werden. Objekt zuerst: die anderen
# vier haben keinen Objekt-Pfad und brauchen ihre eigene Spalte, aber alle
# fünf folgen demselben Backfill-Muster (nur wo NULL, nie überschreiben).
_FAMILIE_BACKFILL_TABELLEN: tuple[str, ...] = (
    "objekt", "eigentuemer", "kontakt", "erkennungsregel", "dokumentvorlage")

# Diese Spalten trugen vor N436 einen globalen `unique=True`-Index; jetzt gilt
# Eindeutigkeit nur noch je Familie (Anwendungslogik bei der Slug-/Schlüssel-
# Vergabe), der alte, weiterhin als UNIQUE angelegte Index muss deshalb explizit
# weg — `eindeutigkeit_sichern` legt nur an, was fehlt, und löscht nie etwas,
# das schon unter demselben Namen existiert (auch wenn es strenger ist, als
# das Modell heute verlangt).
_ALTE_GLOBALE_UNIQUE_INDIZES: tuple[tuple[str, str, str], ...] = (
    ("objekt", "slug", "ix_objekt_slug"),
    ("kontakt", "schluessel", "ix_kontakt_schluessel"),
)


def familie_migration(engine: Engine) -> list[str]:
    """N436 — Mandantentrennung nachziehen: Bestandsfamilie anlegen, jede
    Zeile ohne `familie_id` ihr zuordnen, alte globale Unique-Indizes durch
    (weiterhin vorhandene, aber nicht mehr eindeutige) Suchindizes ersetzen.

    Läuft NACH der generellen Spalten-Ergänzung (die `familie_id`-Spalten
    selbst legt `migriere()`s Diff-Schleife bereits an) und ist idempotent:
    eine Zeile mit gesetzter `familie_id` wird nie angefasst, ein bereits
    ersetzter Index wird nicht zweimal ersetzt."""
    from .models import Familie

    geaendert: list[str] = []
    inspector = inspect(engine)
    vorhandene_tabellen = set(inspector.get_table_names())

    with Session(engine) as session:
        familie = session.exec(
            select(Familie).where(Familie.name == BESTANDSFAMILIE_NAME)).first()
        neu_angelegt = familie is None
        if neu_angelegt:
            familie = Familie(name=BESTANDSFAMILIE_NAME)
            session.add(familie)
            session.commit()
            session.refresh(familie)
            geaendert.append(f"familie[neu]={BESTANDSFAMILIE_NAME}")

        with engine.begin() as conn:
            for tabelle in _FAMILIE_BACKFILL_TABELLEN:
                if tabelle not in vorhandene_tabellen:
                    continue
                spalten = {s["name"] for s in inspector.get_columns(tabelle)}
                if "familie_id" not in spalten:
                    continue  # Spalte kommt erst mit dem naechsten Start
                ergebnis = conn.execute(text(
                    f'UPDATE "{tabelle}" SET familie_id = :fid '
                    f'WHERE familie_id IS NULL'), {"fid": familie.id})
                if ergebnis.rowcount:
                    geaendert.append(f"{tabelle}.familie_id[{ergebnis.rowcount} gesetzt]")

            vorhanden_indizes = _vorhandene_indizes(conn)
            for tabelle, spalte, name in _ALTE_GLOBALE_UNIQUE_INDIZES:
                if tabelle not in vorhandene_tabellen or name not in vorhanden_indizes:
                    continue
                # Nur den ALTEN UNIQUE-Index ersetzen — ein bereits nicht-eindeutiger
                # Index unter demselben Namen (frisches Schema) bleibt unangetastet.
                info = conn.execute(text(f'PRAGMA index_info("{name}")')).all()
                unique_info = conn.execute(text(
                    f'PRAGMA index_list("{tabelle}")')).all()
                ist_unique = any(r[1] == name and r[2] for r in unique_info)
                if not ist_unique or not info:
                    continue
                conn.execute(text(f'DROP INDEX "{name}"'))
                conn.execute(text(
                    f'CREATE INDEX "{name}" ON "{tabelle}" ("{spalte}")'))
                geaendert.append(f"{tabelle}.{spalte}[Unique-Index -> Suchindex]")

    return geaendert


# N436 — eigener Marker statt ein Muster im Schlüssel selbst zu erraten: ein
# bereits zusammengesetzter Marker wie "pv_versendet:slug:2026:Name" ließe
# sich sonst kaum sicher von einem schon umbenannten "3:pv_versendet:…"
# unterscheiden.
EINSTELLUNG_NAMENSRAUM_MARKE = "einstellung_namensraum_migriert"


def einstellung_namensraum_migration(engine: Engine) -> int:
    """N436 — Nextcloud-/Mail-/KI-/Wallbox-Zugang und alle objektbezogenen
    Versand-Marker (PV, E-Tankstelle) lagen bisher als BLANKE Schlüssel in
    `Einstellung` — instanzweit, nicht je Familie. Benennt jede bestehende
    Zeile (außer dem Seed-Marker) einmalig auf
    "<bestandsfamilie_id>:<alter_schlüssel>" um; ab dann greifen
    `familienraum.schluessel()` und alle darauf aufbauenden Lese-/
    Schreibfunktionen (`cloudkern._lies`, `routers.cloud._schreib`, …)
    automatisch auf den richtigen Namensraum zu — hier ändert sich nichts an
    einer einzigen anderen Code-Stelle.

    Läuft bewusst NACH `tankstelle_zukunftsmarker_bereinigen`: die bereinigt
    noch die alten, blanken Marker-Schlüssel; würde diese Umbenennung davor
    laufen, liefe die Bereinigung ins Leere."""
    from .models import Einstellung, Familie
    from .seed import MARKE as SEED_MARKE            # spät, wegen Zirkelbezug

    with Session(engine) as session:
        if session.get(Einstellung, EINSTELLUNG_NAMENSRAUM_MARKE):
            return 0
        familie = session.exec(select(Familie).where(
            Familie.name == BESTANDSFAMILIE_NAME)).first()
        if not familie:
            return 0          # familie_migration lief vor diesem Schritt
        umbenannt = 0
        for zeile in session.exec(select(Einstellung)).all():
            if zeile.schluessel in (SEED_MARKE, EINSTELLUNG_NAMENSRAUM_MARKE):
                continue
            zeile.schluessel = f"{familie.id}:{zeile.schluessel}"
            session.add(zeile)
            umbenannt += 1
        session.add(Einstellung(schluessel=EINSTELLUNG_NAMENSRAUM_MARKE, wert="1"))
        session.commit()
        return umbenannt


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

    # N436 — Mandantentrennung: Bestandsfamilie anlegen, familie_id auf jeder
    # noch nicht zugeordneten Zeile nachziehen, alte globale Unique-Indizes
    # ersetzen. Muss vor `pflicht_kostenarten_sichern` laufen? Nein — beide
    # sind unabhängig; hier zuerst, weil andere Backfills künftig auf eine
    # gesetzte familie_id angewiesen sein könnten.
    try:
        geaendert += familie_migration(engine)
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Familien-Zuordnung nicht ergänzt: %s", fehler)

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

    # N436 — Nextcloud/Mail/KI/Wallbox-Zugang und alle Versand-Marker in den
    # Namensraum der Bestandsfamilie umbenennen (siehe familienraum.py).
    # Bewusst NACH der Zukunfts-Marker-Bereinigung oben (siehe dort).
    try:
        n = einstellung_namensraum_migration(engine)
        if n:
            geaendert.append(f"einstellung.schluessel[{n} umbenannt]")
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Einstellung-Namensraum nicht migriert: %s", fehler)

    # N235 — Vorgänger-Verknüpfung für Alt-Mieterhöhungen (vor N228) ergänzen.
    try:
        n = miete_vorgaenger_backfuellen(engine)
        if n:
            geaendert.append(f"miete.vorgaenger_id[{n} verknüpft]")
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Vorgänger-Verknüpfung nicht ergänzt: %s", fehler)

    # N239 — Kaution-Objektkonto/-Eingang über die Vorgänger-Kette nachziehen.
    # Nach der Verknüpfung oben, damit frisch verkettete Alt-Mietstände direkt
    # mit erfasst werden.
    try:
        n = miete_kaution_vorgaenger_uebernehmen(engine)
        if n:
            geaendert.append(f"miete.kaution_objektkonto/-eingang[{n} übernommen]")
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Kaution-Vorgänger-Übernahme nicht ergänzt: %s", fehler)

    if geaendert:
        log.info("Schema ergänzt: %s", ", ".join(geaendert))
    return geaendert
