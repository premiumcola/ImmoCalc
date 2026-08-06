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
| `darstellung.py`   | Kleine Anzeige-Bausteine: kurze Belegkarten, Anhänger-Chips, Feldwerte als Klartext, Kostenfrei-Erkennung, Anbieter-Auslese aus dem Raster. |

`app/routers/dokumente.py` importiert die Bausteine gezielt und stellt sie am
eigenen Namensraum bereit — Aufrufer aus anderen Routern und Tests, die
`app.routers.dokumente.<name>` lesen, sehen unverändert dieselben Symbole.

Was noch **nicht** hier lebt (weil es in Tests intensiv monkey-gepatcht wird
oder eng an FastAPI-Kontext hängt), bleibt im Router: die Scan- und
Abgleichslogik, die Cloud-Orchestrierung um Duplikate/OCR, die Endpunkte
selbst. Sie greifen auf die hiesigen Bausteine zu — nicht umgekehrt.
