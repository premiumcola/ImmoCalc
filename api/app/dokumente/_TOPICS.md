# `app.dokumente/` — Themen im Überblick

Der Router `app/routers/dokumente.py` bündelt die Endpunkte der
Dokumentenablage; die eigentlichen Bausteine wohnen hier daneben, damit jede
Frage an einer Stelle beantwortet wird.

## Text und Darstellung (N216)

| Modul              | Wofür                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------|
| `namen.py`         | Dateinamen und Pfad-Bausteine: kanonisch benennen (`dateiname`), Sidecars erkennen, Ordner titeln, Adress-/Namensvergleich, HTTP-Kopfzeilen für Downloads. Dazu die Dokumentarten (`DOKUMENTARTEN`, `LAGEPLAN`). |
| `ki_werte.py`      | Rohwerte aus dem KI-Raster in Python-Typen wandeln: `_ki_zahl`, `_ki_datum`, `_ki_text`.       |
| `datum.py`         | Datumsbausteine für Belege: Jahr/Monat aus ISO-Datum ziehen, Tagesdatum sicher parsen, Belegjahr mit Rückfall auf Name und Datei-Datum. |
| `strom_hilfen.py`  | Formatierungshelfer für den KI-Stromzweig: Kontexthinweis, lesbarer Zeitraum, Übernahme in die Antwortfelder. |
| `darstellung.py`   | Kleine Anzeige-Bausteine: kurze Belegkarten, Anhänger-Chips, Feldwerte als Klartext, Kostenfrei-Erkennung, Anbieter-Auslese aus dem Raster, die Ablage-Vermutung (`_vorschlag`) und die volle Listenzeile (`_zeige`), samt Status `VERMISST`. |
| `filter.py`        | `_dokument_passt` — das eine Filter-Prädikat für Liste, Kostenart-Facette und die Sammelaktion „zurück ins Warten". |
| `eintraege.py`     | Modellübergreifende Eintrags-Bausteine: Umklassifizieren (`_UMKLASS_ZIEL`, `_eintrag_kern`, `_bewahrt`, CCCXXIV) und die knappe Anzeigebenennung eines Eintrags (`_eintrag_wo`). |
| `dedup.py`         | Reine Rang- und Merge-Regeln für byte-gleiche Duplikate: Keeper-Wahl beim Scan-Dedup (`_dedup_rang`) und beim Bündeln (`_duplikat_rang`/`_duplikat_ziel`), additives Lücken-Erben (`_keeper_erbt_luecken`). |

## Ablage, Abgleich und Fachlogik (N288)

| Modul              | Wofür                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------|
| `ablage.py`        | Wohin ein Beleg gehört und wie er dorthin kommt: Sach- und Ablageordner (`_zielordner`, `_ablageordner`, `_projektordner`), Ordner anlegen, kollisionsfreier Name (`_freier_name`), Umziehen samt Sidecar (`_beleg_umziehen`, `_sidecar_mitnehmen`), Einsperren auf den Objektordner (`_ziel_im_objekt`). |
| `grabstein.py`     | Einträge, deren Datei ausserhalb der App verschwunden ist (N242/N248): Pfad als Grabstein beiseitelegen statt löschen, Grabsteine aus Listen halten, einen verwaisten Namen freigeben. |
| `abgleich.py`      | Bausteine des Cloud-Abgleichs: Ordner rein lesend auslesen (`_baum`, mit „welche Ordner wurden WIRKLICH gelesen"), umgezogene Dateien wiedererkennen (`_wiedergefunden`, N290), die Bremsen gegen voreiliges Aufräumen (`_mehrdeutig`, `_nachweislich_geloescht`, N248) und der Durchlauf je Immobilie (`_abgleiche_objekt`). |
| `pfade.py`         | CCCVII — einen verlorenen Dateipfad wiederfinden, ohne etwas zu bewegen: Dateien im Objektordner auflisten, Pfad heilen, selbstheilend an die Bytes kommen (`_datei_holen`). |
| `duplikate.py`     | Byte-gleiche Zweitkopien: Gleichheit über SHA1 beweisen (`_byte_gleiche_geschwister`, `_duplikat_gruppen`), erst umhängen und dann weichen lassen (`_duplikat_weg`, N300), Dedup direkt nach dem Scan (`_dedup_nach_scan`, CD) und die Klartext-Ansicht der Verweise (`_VERWEIS_TITEL`, `_verknuepfungen`, `_kopie_zeigen`). |
| `entwuerfe.py`     | CCLXXVIII — aus dem KI-Raster wird ein vorläufiger (oranger) Datensatz: je Kategorie ein Bauplan (`_ENTWURF_BAUER`), dieselben über die Rubrik adressiert (`_ZIEL_BAUER`, CCCIX), Zeitraum zum Beleg finden, kein zweiter Entwurf zum selben Beleg. |
| `zuordnung.py`     | Welche Einträge an einem Beleg hängen können (`_ZUORDNUNG_MODELLE`) und an welchen bestehenden er sich hängen lässt (`_AN_TYP_MODELLE`, `_INFO_RUBRIK`, `_eintrag_holen`) — samt Riegel gegen fremde Immobilien. |
| `ki_beleg.py`      | Was die KI-Auslese am Beleg hinterlässt: Ergebnis festhalten (`_ki_am_beleg_festhalten`) und wieder hervorholen statt neu zu fragen (`_ki_aus_db`, N98), Prüfsumme nebenbei nachtragen (N296), Rechnungssumme bei aufgeteilten Belegen (N103). |
| `warten.py`        | CCLXXXI/CCLXXXII — einen Beleg zurück ins Warten nehmen: vorläufige Entwürfe löschen, NK-Bindung lösen, leer gewordene Zeiträume räumen. Die Cloud bleibt unberührt. |

`app/routers/dokumente.py` importiert die Bausteine gezielt und stellt sie am
eigenen Namensraum bereit — Aufrufer aus anderen Routern und Tests, die
`app.routers.dokumente.<name>` lesen, sehen unverändert dieselben Symbole. Ein
Name, der dort im Re-Export-Block steht, aber im Router selbst nicht mehr
vorkommt, ist deshalb kein toter Import, sondern genau dieser Zweck.

## Was bewusst im Router bleibt

* **Die Endpunkte selbst.** Die Reihenfolge der `@router`-Dekorationen
  entscheidet, welcher Pfad zuerst greift (`tests/test_routen_reihenfolge.py`
  wacht darüber). Sie über mehrere Module zu verteilen hiesse, diese
  Reihenfolge einem zweiten Mechanismus anzuvertrauen.
* **Alles, was sich den Nextcloud-Client selbst holt** (`verbindung`):
  `_einsortieren`, `_scanne`, `_abgleiche`, `_im_ordner_umbenennen`,
  `nachtraeglich_ocren`, `pruefsummen_nachtragen`,
  `verwaiste_immocalc_aufraeumen`, `_hole_beleg_bytes`. Die Tests reichen den
  Client über `monkeypatch.setattr(dok, "verbindung", …)` am Router-Modul
  durch — eine Funktion in einem Nebenmodul schlüge diesen Namen dort nicht
  mehr nach und bekäme die echte Cloud statt der Attrappe.
* **Alles, was gezielt gepatcht wird**: `_ki_key`/`_ki_modell` (Schlüssel aus
  den Einstellungen), `OCR_STAPEL` und der OCR-Nachlauf.

Die hiesigen Bausteine bekommen den Client von aussen gereicht und kennen den
Router nicht — die Abhängigkeit läuft nur in eine Richtung.
