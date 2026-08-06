# `api/app/objekt/` — Themen des Objekt-Routers

N216: Der frühere Monolith `routers/objekte.py` (~1980 Zeilen) ist hier nach
Themen zerlegt. Jedes Modul trägt einen eigenen `APIRouter` (ohne Präfix);
der Dach-Router in `routers/objekte.py` sammelt sie unter `/api` und legt die
Include-Reihenfolge fest.

## Wer wohnt wo?

| Modul               | Endpunkte / Symbole                                              |
|---------------------|------------------------------------------------------------------|
| `stammdaten.py`     | `GET/POST /objekte`, `GET/PATCH /objekte/{slug}`, `GET /objekte/{slug}/export`, `POST /objekte/import`; Helfer `_slugify`, `_freier_slug`, `_laeuft`, `_zuordnung`, `_miete_je_einheit`, `_miete_felder`, `_je_objekt`; `EinheitIn`, `ObjektIn`; `_ORDNER_FELDER` |
| `loeschen.py`       | `DELETE /objekte/{slug}` mit Cloud-Sicherung; `SICHERUNGSORDNER`, `_sicherung_in_die_cloud` |
| `einheiten.py`      | `GET/POST /objekte/{slug}/einheiten`, `PATCH/DELETE /einheiten/{eid}`; `EinheitNeu`; `_einheit_zeile`, `_lageplaene_je_einheit`, `_gemeinflaechen_liste`, `_gemein_bereinigt`, `_nutzflaechen_liste`, `_nutz_bereinigt`, `_bezeichnung_frei` |
| `kostenarten.py`    | `GET /objekte/{slug}/kostenarten`, `PATCH /kostenarten/{kid}` (Namenswechsel zieht Positionen + Belege nach) |
| `zeitraeume.py`     | `GET /objekte/{slug}/zeitraum-fuer`, `POST /objekte/{slug}/zeitraeume`, `POST /zeitraeume/aufraeumen`, `PATCH /zeitraeume/{zid}`, `POST /zeitraeume/{zid}/teilen`, `POST /objekte/{slug}/zeitraeume/belege-abgleichen`, `GET /zeitraeume/{zid}/positionen`; `ZeitraumIn`, `ZeitraumPatch`, `TeilenIn`; `zeitraum_label_jahr`, `_zeitraum_grenzen`, `_zeitraum_jahr`, `_zeitraum_leer_entfernen`, `_verknuepfungen`, `_zeitraum`, `_z_label` |
| `checkliste.py`     | `GET /zeitraeume/{zid}` — Checkliste, Fluss/Sankey auf Einheiten (CCCLVII) |
| `positionen.py`     | `GET /zeitraeume/{zid}/schluessel`, `POST /zeitraeume/{zid}/positionen`, `PATCH/DELETE /positionen/{pid}`; `PositionNeu`, `PositionIn`; `_gewichte` |
| `abrechnung.py`     | `GET /zeitraeume/{zid}/abrechnung` — Engine + Vorab-Split (CCCLIX); `_engine_positionen` |
| `entwuerfe.py`      | `POST /entwuerfe/{typ}/{eintrag_id}/bestaetigen|verwerfen`; Registry `_ENTWURF_MODELLE`, `_entwurf` |
| `erinnerungen.py`   | `GET /erinnerungen` — offene Fristen + erwartete Belege |

## Wer importiert wen?

- `einheiten` → `stammdaten` (`_laeuft`, `_zuordnung`)
- `checkliste` → `zeitraeume` (`zeitraum_label_jahr`)
- `positionen` → `zeitraeume` (`_zeitraum`, `_zeitraum_leer_entfernen`)
- `abrechnung` → `zeitraeume` (`_zeitraum`)
- `stammdaten` → `zeitraeume` (`zeitraum_label_jahr`, Laufzeit-Import in `objekt`)

Kein Modul importiert aus `..routers.objekte` — der Dach-Router zieht ledig-
lich Symbole zu Re-Exports.

## Re-Exports am Router-Kopf

Andere Router (`cloud`, `dokumente`, `strom`, `stromkette`) und ein Test
(`test_zeitraum_label.py`) beziehen Symbole weiter über `.objekte` bzw.
`app.routers.objekte`. Ihre Namen bleiben stabil dank Re-Exports in
`routers/objekte.py`:

- `SICHERUNGSORDNER` ← `objekt.loeschen`
- `zeitraum_label_jahr`, `_zeitraum_grenzen`, `_zeitraum_jahr`,
  `_zeitraum_leer_entfernen` ← `objekt.zeitraeume`
- `_ENTWURF_MODELLE` ← `objekt.entwuerfe`

## Lageplan-Router

`routers/dokumente.py` liefert einen kleinen `lageplan_router` unter
`/einheiten` mit. Der Dach-Router in `routers/objekte.py` schließt ihn zum
Schluss ein, damit `/api/einheiten/{id}/lageplan(e)` unter dem Objekt-Router
erreichbar bleibt (CCCXXVI) — ohne die Ablagelogik zu doppeln und ohne
`main.py` anzufassen.
