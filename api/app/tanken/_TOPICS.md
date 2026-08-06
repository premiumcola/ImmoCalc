# app.tanken — Themenübersicht

Aufteilung des ehemaligen 2201-Zeilen-Routers `app.routers.tankstelle` in
zusammenhängende Bausteine (N215).  Der Router bleibt schmal, ruft von hier —
und hält für Alt-Aufrufer Re-Exports bereit.

| Modul               | Thema                                                                                 |
|---------------------|---------------------------------------------------------------------------------------|
| `typen.py`          | Datenklassen `Posten`, `Buchung`, `RohLadung` — leicht importierbar, ohne Wallbox-Deps |
| `perioden.py`       | Zeit: `quartal_zeitraum`, `monatsfolge`, `aktive_monate`, `abrechnungs_label`, `faelliges_quartal`, `suchfenster`, `belegte_spanne`, `jahre_mit_verbrauch`, Konstanten `MONATSKURZ`/`GRACE_TAGE`/`MAX_MONATE`/`RUECKBLICK_JAHRE` |
| `satz.py`           | Preis je kWh aus der Stromkette (N148): `Satz`, `satz_ableiten`, `eigen_satz`, `mischsatz`, `passender_zeitraum`, `deutsch`, Konstante `EIGEN_RABATT` |
| `posten.py`         | Datenquellen: Wallbox (`wallbox_posten`) und erfasste Ladungen (`erfasste_posten`), Bündelung (`_posten_holen`); Zuordnung: `buchungen`, `zuordnen`, `posten_als_buchungen`, `_stations_verbrauch` |
| `verlauf.py`        | Monatsverlauf: `verlauf`, `verlauf_summe`, `_monatszeile`, `_prozent`; €/km-Anreicherung `_verlauf_kosten_km` (N188) |
| `nutzer.py`         | Tabelle `Tanknutzer` (N164): `nutzer_lesen`, Migration aus JSON, `_pruefe_name`, `_pruefe_email`, `schluessel`, Konstante `S_NUTZER` |
| `einstellungen.py`  | Schlüssel/Wert-Ablage der E-Tankstelle: `_setze`, `autoversand_aktiv`, `zuordnung_lesen`, `S_AUTOVERSAND`/`S_ZUORDNUNG` |
| `marker.py`         | Versendet-/Abgerechnet-Marker (N182/N187): `ist_versendet`, `_versendet_merken`, `abgerechnet_marker`, `_expand_quartale`, `_monat_schluessel`, Konstante `S_VERSENDET` |
| `versand.py`        | Mail- und PDF-Zusammenbau: `abrechnungstext`, `_mailtext`, `_empfaenger`, `_quartal_verlauf`, `_pdf_und_name`, Benzin-Cache `_benzin_verbrauch` (N177), `S_BENZIN` |
| `abrechnung.py`     | Die eine Zusammenführung: `_abrechnung`, `_zeile_holen`, `abrechne` |

## Was ausdrücklich NICHT wandert

* **`_sende_abrechnung` bleibt in `app.routers.tankstelle`.** Tests
  monkeypatchen dort `zugang`; ein Umzug würde diesen Patch entwerten (die
  Funktion würde `versand.zugang` binden statt `tankstelle.zugang`).
* **Der Autoversand-Lauf** (`_autoversand_objekt`, `versand_faellig_pruefen`,
  `autoversand_lauf`) bleibt beim Router — er ruft `_sende_abrechnung` und ist
  die Grenze zum Wachdienst.

## Regeln für spätere Änderungen

* Alle Importe am Modulanfang. Ein Zyklus mit `routers/stromkette` löst
  `satz._stromkette_holen` lokal auf (dort dokumentiert).
* Signaturen der bewegten Funktionen bleiben identisch — der Router und die
  Tests dürfen sie ohne Anpassung benutzen.
* Konstanten wandern mit ihrer Primärlogik: `EIGEN_RABATT` bei `satz`,
  `MONATSKURZ` bei `perioden`, `S_VERSENDET` bei `marker`, `S_NUTZER` bei
  `nutzer`, `S_BENZIN` bei `versand`, `S_AUTOVERSAND`/`S_ZUORDNUNG` bei
  `einstellungen`, `S_OPENWB_URL`/`TIMEOUT` bei `posten`.
