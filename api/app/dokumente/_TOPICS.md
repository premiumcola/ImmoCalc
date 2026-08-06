# `app.dokumente/` — Themen im Überblick

Der Router `app/routers/dokumente.py` bündelt die Endpunkte der
Dokumentenablage; die eigentlichen Bausteine wohnen hier daneben, damit jede
Frage an einer Stelle beantwortet wird.

| Modul              | Wofür                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------|
| `namen.py`         | Dateinamen und Pfad-Bausteine: kanonisch benennen (`dateiname`), Sidecars erkennen, Ordner titeln, Adress-/Namensvergleich, HTTP-Kopfzeilen für Downloads. |
| `ki_werte.py`      | Rohwerte aus dem KI-Raster in Python-Typen wandeln: `_ki_zahl`, `_ki_datum`, `_ki_text`.       |
| `datum.py`         | Datumsbausteine für Belege: Jahr/Monat aus ISO-Datum ziehen, Tagesdatum sicher parsen, Belegjahr mit Rückfall auf Name und Datei-Datum. |
| `strom_hilfen.py`  | Formatierungshelfer für den KI-Stromzweig: Kontexthinweis, lesbarer Zeitraum, Übernahme in die Antwortfelder. |
| `darstellung.py`   | Kleine Anzeige-Bausteine: kurze Belegkarten, Anhänger-Chips, Feldwerte als Klartext, Kostenfrei-Erkennung, Anbieter-Auslese aus dem Raster, die Ablage-Vermutung (`_vorschlag`) und die volle Listenzeile (`_zeige`), samt Status `VERMISST`. |
| `filter.py`        | `_dokument_passt` — das eine Filter-Prädikat für Liste, Kostenart-Facette und die Sammelaktion „zurück ins Warten". |
| `eintraege.py`     | Modellübergreifende Eintrags-Bausteine: Umklassifizieren (`_UMKLASS_ZIEL`, `_eintrag_kern`, `_bewahrt`, CCCXXIV) und die knappe Anzeigebenennung eines Eintrags (`_eintrag_wo`). |
| `dedup.py`         | Reine Rang- und Merge-Regeln für byte-gleiche Duplikate: Keeper-Wahl beim Scan-Dedup (`_dedup_rang`) und beim Bündeln (`_duplikat_rang`/`_duplikat_ziel`), additives Lücken-Erben (`_keeper_erbt_luecken`). |
| `immocalc_steckbrief.py` | Der `.immocalc`-Steckbrief als reiner Text: Feldtitel-Übersetzung (`_FELD_TITEL`) und der Textaufbau (`_immocalc_text`, CCLXXIV). |

`app/routers/dokumente.py` importiert die Bausteine gezielt und stellt sie am
eigenen Namensraum bereit — Aufrufer aus anderen Routern und Tests, die
`app.routers.dokumente.<name>` lesen, sehen unverändert dieselben Symbole.

Was noch **nicht** hier lebt (weil es in Tests intensiv monkey-gepatcht wird
oder eng an FastAPI-Kontext hängt), bleibt im Router: die Scan- und
Abgleichslogik, die Cloud-Orchestrierung um Duplikate/OCR, die Endpunkte
selbst. Sie greifen auf die hiesigen Bausteine zu — nicht umgekehrt.
