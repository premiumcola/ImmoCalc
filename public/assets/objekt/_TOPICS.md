# public/assets/objekt/ — Modul-Landkarte

`objekt.html` lädt seinen JS-Rumpf aus diesen Modulen (N216). Der Rahmen im
HTML (script type="module") bleibt schlank: er importiert `laden` und
`initHandlers`, ruft `installNav()`/`installLogos()` und startet `laden()`.

Grundprinzip: **State über `state.js` als lebende Bindungen.** Alle Module
lesen `state.daten`, `state.einheiten`, `state.bereicheDaten` etc. aus
`state.js`; Änderungen laufen über die dort exportierten Setter. Konstante
Katalogwerte (RUBRIKFARBE, ENTWURF_TYP, AN_TYP, SCAN_KATEGORIE,
UMKLASS_ZIELE, RUBRIK_WAHL, GRUNDSCHULDFELDER, ZEITRAUMFELDER,
MIET_PALETTE, MONATS_KURZ, ZINSTEXT, KAMERA_ICON, GAUGE_ICON) stehen
ebenfalls in `state.js`.

Wer welche Datei anfassen darf: jedes Modul gehört einer Aufgabe; wer eine
Kreuzänderung braucht, verändert `state.js` oder `helpers.js` (die
gemeinsame Basis). Nichts landet in zwei Modulen doppelt.

- `state.js` — mutable State + Setter + Katalogkonstanten.
- `helpers.js` — kleine Ableitungen: Datums-/Dauerformate (isoTag, dauerText,
  tagPlus; `heuteIso` kommt aus `immo.js` und wird hier nur weitergereicht),
  Flächenrechnung (effektiveFlaeche, qmMiete,
  hergeleiteteKaltmiete), laufendeMiete, mietzeitBeginn, flaechenSummen,
  wohnflaecheCells, flaecheWarnung, kennzahlenHtml, nachpflegeHtml,
  scanJahr, zuEinheit, mietFarbe.
- `turnus.js` — Cache für `/turnus/{bereich}` (Zahlungsturnus-Auswahl).
- `stammdaten.js` — Stammdaten-Kachel am Haus (`stammHtml`) und WEG-Block
  (`wegHtml`). N210a: Objektname UNTER dem Titel („secsub" in .setxt).
- `einheiten.js` — Einheiten-Liste am Haus (`einheitenHtml`), Stammdaten
  einer Einheit im Fokus (`einheitStammHtml`), Vermietet-Stempel, kompakte
  Mini-Timeline, Objekt-Summen (Monat/Jahr).
- `lageplan.js` — Lagepläne einer Einheit: Karten mit Vorschau, Umbenennen-
  und Titelabfrage-Dialog, Upload durch kamerascan (`lageplanHochladen`),
  Entfernen, Ansehen.
- `miete.js` — Timeline über Mietverhältnisse (mietModell, mietTimelineHtml),
  Miet-/Leerstand-Zeilen, generische Eintrag-/Entwurf-/Staffel-Zeilen und
  die `abschnitt()`-Fabrik (Rubrik-Kopf + Timeline + Liste).
- `diagramm.js` — Miet-/NK-Verlauf über den letzten 24 Monaten bzw. 12
  Quartalen (`mietVerlauf`, `mietDiagrammHtml`).
- `zeitraum-werkzeug.js` — Werkzeug „Zeiträume umstellen" (N35): Grenzen
  verschieben, teilen, neuen Zeitraum anlegen, Belege abgleichen.
- `anfangsstaende.js` — Rubrik-Einstiegskarte (`erststandHtml`) und
  Erfassungs-Dialog für Anfangszählerstände (N141).
- `eigentuemer.js` — Anteil-Liste mit Zurechnungs-Warnung, Anteil-Formular.
- `zuordnen.js` — Zuordnen-/Umhängen-Dialog (CCCIX/X/XI).
- `eintrag-detail.js` — Eintrags-Detailansicht (CCCXIII, Daten links / Beleg
  rechts, Miet-Checkliste), Bearbeiten-Formular öffnen.
- `formular.js` — Formular-Fabrik (`formular`, `feldHtml`, `feldLabel`,
  `feldEinheit`, `ausFormular`), Auswahlfelder verdrahten,
  Formatierungen (Eingabe: Tausenderpunkte/IBAN/Steuernummer), Zinskopplung.
- `bewohner.js` — Zusatzblöcke fürs Mietformular: Bewohner, Gemein- und
  Zusatz-Nutzflächen; Speichern der Bewohner.
- `miete-extras.js` — Miet-Vorschlagsblock (€/m² × Fläche), Erhöhung planen,
  Kappungsgrenzen-Wächter (§ 558 BGB).
- `kredit-extras.js` — Kredit-„Restschuld/Sparstand"-Block, Jahresstände-
  Formular mit Verlaufsblock (CCXXXI: Ist-Zinsen).
- `grundschulden.js` — Grundschulden-Liste + -Formular mit
  objektübergreifender Kreditauswahl.
- `cloud.js` — Nextcloud-Status/Ablage-Block, still fehlende Unterordner
  nachziehen.
- `laden.js` — `laden()`: Alles frisch aus der API holen, State setzen,
  Kopfzeile setzen, Haus- bzw. Fokus-/Grundstücks-Layout rendern, Cloud
  anzeigen, Lageplan-Vorschau nachladen.
- `handlers.js` — `initHandlers()`: zentrale Event-Delegation auf `#inhalt`
  (Klick + Change), `#dlgForm` (Klick + Submit), `#dlg` (Close) und `#back`.
  Nichts anderes darf Listener auf diese Wurzeln registrieren.
