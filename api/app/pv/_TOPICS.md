# app.pv — Themenübersicht

Aufteilung des ehemaligen ~1030-Zeilen-Routers `app.routers.strom` in
zusammenhängende Bausteine (N216). Der Router bleibt schmal (Routen, Pydantic,
dünne Orchestrierung), ruft von hier — und hält für Alt-Aufrufer Re-Exports
bereit.

| Modul               | Thema                                                                                                 |
|---------------------|-------------------------------------------------------------------------------------------------------|
| `stammdaten.py`     | PVAnlage (Anschaffung, Vorlauf mit Aufschlüsselung N153, kWp, Anteile): `_stammdaten`, `_vorlauf`, `_anteile_dict`/`_anteile_tupel`, `_anteile_hinweise`, `_zeige_stammdaten`, `_uebernahme_aus_jahren`, `_erster_abrechnungsstart`, `_promille_text`, `StammdatenIn`, Konstanten `_STAMM_AUS_JAHR`, `_VORLAUF_QUELLEN`, `_VOLLE_PROMILLE`, `_PROMILLE_TOLERANZ` |
| `jahre.py`          | Ein `Stromjahr` lesen/speichern und die Engine-Eingaben zusammenstellen (inkl. Gruppen-Zuordnung N89): `_hole_oder_neu`, `_gespeicherte_zuordnung`, `_merke_zuordnung`, `_eingaben`, `_zeige`, `StromIn`, Konstanten `_FELDER`, `_ZUORDNUNG_SPALTE`, `_HAT_SPALTE` |
| `ertrag.py`         | Die Rechenlogik der Amortisation je Jahr und Kategorie (N127/N200/N204): `_ertraege_je_jahr`, `_kat_beitrag`, `_kat_eur`, `_kategorien`, `_kategorie_kwh`, `_nicht_umlagefaehig`, `_vorlauf_jahr`, `_abrechnungsjahre`, Konstanten `_HERKUNFT_EIGEN`, `_QUELLEN_LEER`, `_KAT_LABEL` |
| `tanken_bridge.py`  | Live-Beitrag der E-Tankstelle zur PV-Amortisation aus derselben Quelle wie ihre Abrechnung (N200): `tanken_beitrag_eur`, `_tanken_je_jahr` |
| `amortisation.py`   | Verlauf über alle Jahre inkl. Prognose (N127) — die Zusammenführung von Stammdaten, Erträgen, E-Tanken und der Amortisationskurve: `verlauf_daten`, `_anlage`, `_prognose`, Konstante `_PROGNOSE_MAX_JAHRE` |
| `eigentuemer.py`    | Personenliste + gesetzte PV-Anteile für die Auswahl (N112/N139): `eigentuemer_daten` |

## Namenskonflikt bewusst beachtet

* `app.strom`         — Engine-Modul (Stromkette, Rechenkern) — READ ONLY
* `app.routers.strom` — Router (Endpunkte, Pydantic, Orchestrierung)
* `app.pv`            — PV-Fachlogik (dieses Paket)

Die drei bleiben strikt getrennt.

## Regeln für spätere Änderungen

* Signaturen der bewegten Funktionen bleiben identisch — der Router und die
  Tests dürfen sie ohne Anpassung benutzen.
* Konstanten wandern mit ihrer Primärlogik.
* Die Test-Monkeypatches `rs.tanken_beitrag_eur`, `rs._kat_eur`,
  `rs._kategorien`, `rs._kategorie_kwh`, `strom_router._HAT_SPALTE` bleiben
  durch Re-Exports am Router-Kopf lauffähig.
* `_tanken_je_jahr` importiert `routers.tankstelle` **lazy**, damit die dortigen
  Monkeypatches (`tk._posten_holen`, `tk.satz_ableiten`) weiterhin greifen und
  kein Zirkelbezug entsteht.
