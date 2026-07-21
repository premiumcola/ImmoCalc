# ImmoCalc — Aufgabenliste

Alle Anforderungen aus den Gesprächen, fortlaufend nummeriert. Erledigtes mit
Commit, Offenes mit dem, was noch fehlt. Diese Liste wird bei jeder neuen
Anforderung fortgeschrieben — nichts muss doppelt gesagt werden.

Stand: 21.07.2026 · 166 pytest grün · Prüfung des Standes `0acdaa1` durch
fünf Agents, jeder Fund gegengeprüft

**Grundsatz aus dem Gespräch:** möglichst direkt bedienbar. Was man häufig
tut, gehört an die Oberfläche — nicht hinter einen zweiten Klick. Und nichts,
was der Browser zeichnet: keine `alert`, keine `confirm`, keine Systemlisten.

---

## Woran gerade gearbeitet wird

In einfachen Worten, damit man die eigenen Wünsche wiedererkennt.

| Nr. | In einfachen Worten | Stand |
|---|---|---|
| CXXII/CXXIII/CXXVII | Dateinamen ohne Doppelnennung, mit Sache und Betrag · Ordner vollständig neu einlesen | in Arbeit |
| CXXXVIII | Neuer Typ Grundstück: Nutzungsart, Grundstückswert, Pacht, Grundsteuerwert, eigenes Symbol | in Arbeit |
| CLV/CLVI | Steuernummer verrutscht beim Tippen · gefilterte Kennzahlen sehen aus wie echte | in Arbeit |

### Heute fertig geworden

| Nr. | In einfachen Worten | Commit |
|---|---|---|
| CX–CXIII | PDF-Ansicht schließbar · Scan ohne weiße Ränder · Ölrechnung erkannt · volle Euro | `7d72976` |
| CXXI | Steht eine Wohnung leer, zahlen das nicht mehr die anderen Mieter | `082f678` |
| CXIV | Kredite raus aus den Nebenkosten — Mietersache und Eigentümersache getrennt | `0a98941` |
| CXV–CXVII | Kreditstand zum 31.12. · geplante Mieterhöhungen · Kontakt je Bewohner | `a9c57f9` |
| CXVIII | Beträge, IBAN und Steuernummer beim Tippen gruppiert | `20b7a4e` |
| CXIX/CXX | Ordner entschachtelt, Umbenennung zieht die Belege mit | `957e644` |
| CXLIV/CXLVI | Bei offenem Dialog steht die Seite still · Fristen über ein Jahr ausgeblendet | `5703ef6` |
| CXLV | Einheiten als Bubbles auf der Startseite | `ba4e721` |
| CLIV/CLIX | Abrechnung erreicht alle Bewohner · Leerstand steht nicht mehr bei den Empfängern | `f377bf5` |
| CL–CLII | Umzug lässt keine Belege zurück · keine Waisen beim Löschen · eine Zahl für die Restschuld | `6a4cce1` |
| CLXIV | App-Symbol: hellerer Grund, Motiv mittig, Baum und Dach sichtbar | `870715e` |

## Sofort zu beheben — aus der Nachprüfung vom 21.07. (Nachmittag)

Die sieben Punkte CXIV–CXXI sind gebaut und committet (233 Tests grün), aber die
Gegenprüfung hat Fehler gefunden, die vor der nächsten echten Nutzung weg müssen.

| Nr. | Fund | Warum es zählt |
|---|---|---|
| CL | **Umzug lässt lose Dateien zurück** | `cloud.py:469`: beim Entschachteln wandert eine Datei, die direkt im Objektordner liegt, in der Cloud mit — ihr `Dokument.pfad` aber nicht. Der Eintrag zeigt danach ins Leere, und der Vorgang meldet trotzdem Erfolg. Genau das, was bei CXIX nicht passieren durfte |
| CLI | **Waisen nach dem Löschen einer Immobilie** | `export.py:110-139` räumt Kreditstände und Bewohner nicht mit ab. SQLite vergibt die id neu — der nächste Kredit erbt die fremden Jahresstände, der nächste Mieter fremde Bewohner. Nachgestellt und belegt |
| CLII | **Zwei verschiedene Restschulden** | Objektseite zeigt 209.731 €, die Vermögensübersicht 212.400 € für denselben Kredit: `besitz.py:211-223` reicht die Jahresstände nicht an die Berechnung weiter |
| CLIII | **Mieterhöhung mehrfach anlegbar** | „Planen" schließt die vorige geplante Scheibe nicht — im Test entstanden vier überlappende Stände derselben Partei ab demselben Datum, alle mit Chip „geplant" |
| CLIV | **Versand erreicht die neuen Bewohner nicht** | `versand.py:36-45` liest weiterhin nur `Miete.email`. Der Dialog verspricht, jede Person bekomme ihre Abrechnung — bis das nachgezogen ist, stimmt der Text nicht |
| CLV | **Steuernummer verrutscht beim Tippen** | `93815/08152` wird zu `938/15/08152`: der Vorgabe-Schrägstrich nach drei Ziffern kollidiert mit dem selbst getippten (`eingabe.js:276-282`) |
| CLVI | **Gefilterte Kennzahl sieht aus wie die echte** | Nebenkostenseite: mit Filter „Hausmeisterdienste" steht im Kopf „Guthaben 5.660 €", tatsächlich sind es 4.812 €. Auf einer Seite, deren Zahlen an Mieter gehen, ist das die falsche Unschärfe. Dazu: der Kostenart-Filter zeigt im leeren Jahr 17 Schalter und drückt auf dem iPhone die Diagramme aus dem Bild |
| CLVII | **Nachzahlung fehlt im Kostenfluss** | Sankey: Umlage 2.400 € gegen Vorauszahlungen 1.200 € — der Knoten gibt mehr ab, als er bekommt; die Nachzahlung taucht im Bild nicht auf |
| CLVIII | **Benennung nachziehen ohne Knopf** | Die Endpunkte für CXIX stehen, aber keine Oberfläche ruft sie auf. In den Einstellungen fehlt unter „Ordner-Benennung" der Knopf samt Trockenlauf-Liste (alt → neu) und Fehlerausgabe |
| CLIX | **Leerstand liest sich wie ein vergessener Mieter** | Im Abschluss-Dialog steht „Ohne Mailadresse und daher nicht versendbar: EG". Der Leerstand gehört von den Empfängern getrennt und als „bleibt beim Eigentümer" ausgewiesen. Ebenso: seine Personenzahl ist geraten (1), und alte, bereits abgeschlossene Abrechnungen behalten die frühere Verteilung |
| CLX | **Umlagefähig lässt sich nicht setzen** | `Kostenart.umlagefaehig` ist nirgends änderbar — damit gilt faktisch jede Kostenposition als umlagefähig, und die Trennung aus CXIV steht auf tönernen Füßen |

### Eigentum je Einheit — aus dem Gespräch vom 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CLXI | **Eigentümer je Einheit statt nur je Objekt** | `Anteil` hängt heute am Objekt (`objekt_id`, Promille). In einem Haus mit fünf Einheiten, von denen drei dem einen und eine einem Familienmitglied gehören, lässt sich das nicht ausdrücken. Gebraucht: je Einheit ein Eigentümer (bzw. Anteile daran). **Wichtig:** die Umlage auf die Mieter bleibt davon unberührt — sie verteilt nach Fläche/Personen, unabhängig vom Eigentum. Der Eigentümer entscheidet nur, wer die Abrechnung verschickt und wem Einnahmen und Vermögen zugerechnet werden |
| CLXII | **Auswertung je Eigentümer** | Cashflow, Vermögen und Mietverlauf zeigen heute das ganze Objekt. Gehört einem nur ein Teil, muss sich die Sicht auf die eigenen Einheiten einschränken lassen — sonst stehen fremde Einnahmen in der eigenen Übersicht |
| CLXIII | **Zwei Wege in die Kosten: roh oder schon verteilt** | Selbstverwaltetes Haus (Laufer Str. 5): Rechnungen kommen roh herein, die App verteilt. Eigentumswohnung in einer WEG (Unterschöllenbach, Klausner Winkel): die **Hausgeldabrechnung** der Verwaltung ist die Quelle, dort ist bereits verteilt. Beide Wege müssen erfassbar sein, ohne dass Beträge doppelt gezählt werden |

## Als Nächstes — in dieser Reihenfolge

| Nr. | In einfachen Worten |
|---|---|
| CXXII/CXXIII | Dateinamen: nichts doppelt nennen, dafür die Sache und den Betrag — `2026_Heizöl_1.284€.pdf` |
| CXXIV/CXXX | In der Dokumentenliste sehen, von wann der Beleg ist und über wie viel Euro |
| CXXV | Rechts sehen: das wurde erkannt → das wird eingetragen, und bestätigen. Kein Beleg ohne Position |
| CXXIX | Beleg anklicken → rechts die Vorschau, nochmal klicken → groß zum Prüfen |
| CXXVIII | Nicht nur „Nebenkosten" wählen, sondern welche — Heizkosten, Wasser, Müll |
| CXXVII | Ordner sofort neu einlesen, auch wenn selbst gelöscht oder umbenannt wurde |
| CXLI–CXLIII | Die vier Einheiten der Laufer Str. sehen, bearbeiten, Mieter per Klick zuordnen — keine Doppelbelegung |
| CXLV | Auf der Startseite die Einheiten als kleine Bubbles unter dem Haus |
| CXLVII | Das Euro- und Prozentzeichen ins Eingabefeld, rechts, grau |
| CXLVIII | Zinssatz oder Monatszins eingeben — die App rechnet das andere aus |
| CXLIX | Bausparer statt Kredit wählen können: angespart statt Restschuld, zählt als Guthaben |
| CXXVI | Der Bereich heißt „Dokumente & Ereignisse" |

## Erledigt

| Nr. | Aufgabe | Commit |
|---|---|---|
| I | Download statt Anzeige beheben (Content-Type, `no-store`) | `4b1106d` |
| II | DEV-Stack abschaffen, `public/` mounten, sofort wirksam | `4b1106d` |
| III | CLAUDE.md: Autonomie, Parallelität, Modularisierung, Design | `ababbe5` |
| IV | Visuelle Abnahme als Pflicht (Screenshots wirklich ansehen) | `a7d17c9` |
| V | Startseite = echte App, Objekt-Kacheln aus der API | `632bce7` |
| VI | Entwicklungswerkzeuge in die Einstellungen verschoben | `632bce7` |
| VII | Objektseite mit Mieten, Versicherungen, Krediten, Zahlungen | `632bce7` |
| VIII | Auswertung mit Kennzahlen, Kostenblöcken, Mietverlauf | `632bce7` |
| IX | Onboarding legt wirklich an (`POST /api/objekte`) | `632bce7` |
| X | Schreib-API: Objekte, Stammdaten, Auswertung | `98d9d32` |
| XI | Migration: bestehende Daten überleben Schema-Erweiterungen | `c98cb1c`, `43e81a5` |
| XII | Nextcloud-Verbindung mit Ordner-Browser und Home-Ordner | `7c4bbd7` |
| XIII | X-Knopf im Wizard, Escape schließt | `7c4bbd7` |
| XIV | Layout für iPhone, iPad, Desktop + iOS-Icon, PWA-Manifest | `0dbb093` |
| XV | Geräte-Matrix: jede Seite in drei Größen geprüft | `a7d17c9` |
| XVI | Mockup-Bearbeitenmodus samt Fantasiedaten entfernt | `a7d17c9` |
| XVII | Sankey-Kostenfluss, Cashflow je Einheit, €/m² | `2110249` |
| XVIII | Eigener Turnus je Kostenart + Belegmonat + Erinnerungen | `2110249` |
| XIX | Kontodaten je Objekt (Bank, IBAN, Inhaber) — Modell | `2110249` |
| XX | Eingangsordner mit Zuordnung und automatischer Benennung | `fa935da` |
| XXI | Postfach verbinden (GMX u. a.) mit Testmail | `fa935da` |
| XXII | Nextcloud nachträglich verbinden, Struktur später anlegen | `43e81a5` |
| XXIII | Automatischer Ordner-Scan alle 15 Minuten | `43e81a5` |
| XXIV | Abrechnungs-Checkliste mit Ampel, Belegen, Nachbearbeiten | `693f24e` |
| XXV | Mehrere Zeiträume + Beispielbelege in den Demodaten | `693f24e` |
| XXVI | Einheitliche Kategorie-Icons (grau/grün) | `bc717f8` |
| XXVII | Sortierung nach Offene/Größe/Name, Zusatzinfos je Zeile | `bc717f8` |
| XXVIII | Abschluss-Knopf + Versand der Abrechnungen an die Mieter | `bc717f8` |
| XXIX | Kamera-Scan → PDF (klein, mehrseitig) → Nextcloud | `cdbcb06` |
| XXX | Nextcloud-URL mit `/login` abfangen (der 405-Fehler) | `d0905c7` |
| XXXI | Wizard-Bugs: klebender Turnus-Text, Kachelraster, Knopfhöhe | `d0905c7` |
| XXXII | Kategorien ergänzt: Bankspesen, Hauskonto, Internet u. a. | `d0905c7` |
| XXXIII | Ordner-Benennung von grob nach fein, mit Vorlage | `d0905c7` |
| XXXIV | Schreibschutz: nichts außerhalb des Home-Ordners | `d28d3b4` |
| XXXV | Zahlungsturnus (monatlich … jährlich) — Rechenlogik | `d28d3b4` |
| XXXVI | Fristen erst ab Ende des Zeitraums erinnern | `d28d3b4` |
| XXXVII | Sankey: Bandfarbe = Quellfarbe, nichts wird abgeschnitten | `d28d3b4` |
| XXXVIII | Ordnerliste im Dialog als Raster statt Fließtext | `d28d3b4` |
| XXXIX | Immobilie löschen — mit Nachfrage, Cloud-Dateien bleiben | `d5a5550`, `f068042` |
| XL | Export/Sicherung als JSON, wieder importierbar | `d5a5550` |
| XLI | Objekt-Stammdaten sichtbar und bearbeitbar | `f068042` |
| XLII | Mieter-Kontaktdaten in der Oberfläche | `f068042` |
| XLIII | Scan-Knopf an jeder offenen Position | `f068042` |
| XLIV | Texterkennung schlägt Betrag und Datum vor | `d5a5550`, `f068042` |
| XLV | Symbole für Mieten, Versicherungen, Kredite, Zahlungen | `f068042` |
| XLVI | Weitere Zeiträume anlegen, Vorauszahlungen übernehmen | `d5a5550` |
| XLVII | Nachpflege-Hinweise, wenn Angaben fehlen | `d5a5550`, `f068042` |
| XLVIII | Turnus-Auswahlfeld in allen Formularen | `f068042` |
| XLIX | Eigentümerliste und Tausendstel je Objekt | `d5a5550`, `f068042` |
| L | Vermögensübersicht: Wert, Restschuld, Eigenkapital | `d5a5550`, `f068042` |
| LI | Einheiten gleicher Adresse gruppiert | `f068042` |
| LII | Marke in der Navigation führt zur Startseite | `f068042` |
| LIII | Verbundene Dienste mit grünem Punkt | `f068042` |
| LIV | „Fehlende Unterordner“ tritt zurück, wenn angelegt | `f068042` |
| LV | Selbst angelegte Ordner werden angezeigt, nie verändert | `d5a5550`, `f068042` |
| LVI | PDF-Anhang beim Versand | `d5a5550` |
| LVII | Belege im Browser öffnen | `d5a5550`, `f068042` |
| LX | „Beleg erfassen“ direkt in der Zeile, ohne Aufklappen | `f496e6a` |
| LXI | App-Symbol in der Kopfzeile jeder Seite | `f496e6a` |
| LXII | Auswahlmenüs im eigenen Design statt Systemliste | `f496e6a` |
| LXIII | Name aus Straße, Ort und Einheit — Feld entfällt | `f496e6a` |
| LXIV | Löschen per Schiebe-Regler statt Browser-Kasten | `f496e6a` |
| LXVII | Doppelklick legt keine zwei Eigentümer mehr an | `19fdf4f` |
| LXXIII | Texterkennung: Betrag, Datum **und** Kategorieart aus dem Text | `19fdf4f` |
| LXXIV | Mehrseitig fotografieren → ein PDF (mit pypdf gegengeprüft) | `19fdf4f` |
| LXXVII | Benennung Ort → Straße → Einheit in den Kacheln | `19fdf4f` |
| LXXVIII | Hauslogos in den Kacheln größer | `19fdf4f` |
| LXXIX | Zusammengehörige Einheiten: Oberkachel mit angedockten Kacheln | `19fdf4f` |
| LXXX | Eigentümer als eigener Menüpunkt | `19fdf4f` |
| LXXXI | Rolle wird aus dem Anteil abgeleitet, je Objekt | `19fdf4f` |
| LXXXII | Tausendstel auf eine Nachkommastelle, Fehlendes wird angezeigt | `19fdf4f` |
| LXXXIII | Auswertung geteilt: Wertentwicklung und Nebenkostenabrechnung | `19fdf4f` |
| LXXXIV | Menüleiste mit sechs Einträgen | `19fdf4f` |
| LXXXV | „Eingang" heißt jetzt „Dokumente" | `19fdf4f` |
| LXXXVI | Menüleiste auf dem Handy: vier Wege plus „Mehr" | `821a925` |
| LXVI | Abschluss rückgängig: Zeitraum wieder öffnen | `a8952a8` |
| LXVIII | Wachdienst legt nichts doppelt an (Sperre, 409) | `b692b10` |
| LXIX | Zuordnen ohne Cloud-Ordner meldet jetzt 409 statt Erfolg | `b692b10` |
| LXXI | Fänger entschärft: `/api/stammdaten/{bereich}/{id}` | `822e928` |
| LXXII | Je Testmodul eine eigene Datenbank (`conftest.py`) | `822e928` |
| LXXXVII | Verteilungsschlüssel aus Stammdaten ableiten (API) | `a8952a8` |
| LXXXVIII | Dokumentenablage flach: Filter, Suche, Korrigieren, Neu-Scan | `b692b10` |
| LXXXIX | „Was ansteht" auf der Startseite, Sicherung einlesen | `0acdaa1` |
| XCI–XCVIII | Zeitanteilige Gewichte, sichere Automatik, Position anlegen | `9fa866c` |
| CX | PDF-Ansicht lässt sich wieder schließen (Kreuz, Escape, daneben tippen) | `7d72976` |
| CXI | Scan-PDF hat Seitenformat der Aufnahme — keine weißen Ränder mehr | `7d72976` |
| CXII | Ölrechnung wird erkannt (Heizöl, Brennstoff, Pellets, Flüssiggas) | `7d72976` |
| CXIII | Verkehrswert, Restschuld und Eigenkapital auf volle Euro | `7d72976` |

---

## Offen

### Blocker — aus der Prüfung vom 21.07.2026

| Nr. | Fund | Warum es zählt |
|---|---|---|
| LXV | **Kostenposition lässt sich in der Oberfläche nicht anlegen** | Das Backend leitet Gewichte jetzt ab (`a8952a8`), aber `POST /api/zeitraeume/{zid}/positionen` hat keinen Aufrufer. Für ein selbst angelegtes Objekt bleibt `position_id: null`, das Betragsfeld erscheint nie — die Abrechnung bleibt 0,00 € |
| XC | **Beleg landet nie am Zeitraum** | `Dokument.zeitraum_id` wird außer im Seed von keinem Weg gesetzt; der Reiter „Belege" ist für echte Daten dauerhaft leer |

### Rechenlogik — Geld wird falsch verteilt

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCI | Mieterwechsel zählt Fläche, Personen und Einheiten doppelt | `verteilung.py:157-168` verteilt ohne Zeitanteil. Bei einem Wechsel im Jahr trägt die andere Einheit 42,86 % statt 60 % — unabhängig davon, wann gewechselt wurde |
| XCII | Mietverhältnis ohne Einheit fällt stumm aus der Verteilung | `Miete.einheit` ist Freitext; passt der Name nicht, verschwindet die Partei aus den Gewichten, bekommt keine Kosten und ihre Vorauszahlung voll erstattet. Kein Wächter meldet das |

### Datenintegrität — Wachdienst und echte Dateien

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCIII | Kategorie-Erkennung per Teilstring legt automatisch falsch ab | `klein.count(wort)` ohne Wortgrenzen: „Kaufvertrag Berg**gas**se 5.pdf" gilt als Nebenkosten. Der Wachdienst verschiebt und benennt solche Dateien alle 15 Minuten ungefragt um |
| XCIV | Unique-Index auf `dokument.pfad` fehlt in `migrate.py` | Für die Bestands-DB wirkungslos; er entsteht nur beim ersten Scan, ein Fehlschlag wird bis zum Neustart nie wiederholt. LXVIII besteht live weiter |
| XCV | `IntegrityError` nur in `_aufnehmen` abgefangen | Wurde eine Datei in der Cloud gelöscht, scheitert der Scan mit HTTP 500 — die Datei liegt schon im Zielordner, der Eintrag zeigt noch auf den Eingang |
| XCVI | `verschieben:false` benennt nur in der Datenbank um | Umgeht die 409-Sperre: DB-Name und Cloud-Datei laufen auseinander, der Eintrag gilt als „zugeordnet". Derselbe Schaden wie LXIX, nur hinter einem Schalter |
| XCVII | Automatische Ablage wirft den Originalnamen weg | Aus „Grundsteuerbescheid 2024.pdf" wird „2024_Steuer.pdf" — unumkehrbar, ohne Nutzeraktion. Zwei Belege eines Jahres sind danach nur noch durch Öffnen unterscheidbar |

### Oberfläche und Prüfstand

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCVIII | `auswahl.js` entfernt seine `document`-Listener nie | Jedes Neuzeichnen hängt weitere an; bei zehn Dokumenten und getippter Suche sammeln sich hunderte, deren Closures abgelöste DOM-Bäume halten |
| XCIX | `scan-check.mjs` kann nicht mehr fehlschlagen | Das Muster trifft auch den Ruhetext des Knopfes — ein Scan, der gar nicht anläuft, gilt als Erfolg |
| C | Kanonischer Stammdatenpfad und Verteilungsfälle ungetestet | Getestet wird nur die Altroute; ein Fehler im neuen Pfad bliebe in `make test` unsichtbar, obwohl die Oberfläche dann nicht speichern kann |
| LXX | Fünf Endpunkte ohne Aufrufer | u. a. `POST`/`DELETE` auf Positionen, `GET /zeitraeume/{zid}/positionen` — zwei davon in `a8952a8` neu gebaut. Erinnerungen und Import sind mit `0acdaa1` angebunden |

### Reststand aus dem Gespräch vom 20.07.2026

| Nr. | Aufgabe | Was noch fehlt |
|---|---|---|
| LXXV | **Dokumentenablage ohne Verschachtelung** | Grundgerüst steht (`b692b10`). Offen: Originalname bleibt erhalten (XCVII), verwaiste Einträge aufräumbar |
| LXXVI | **Dynamisch, filterbar, smart** | Offen: Metazeile wiederholt Jahr und Art aus dem Dateinamen, Zustand „neu" dreifach signalisiert, Art-Filter bietet leere Werte an |

### Neu aus dem Gespräch vom 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CI | **Mietvergleich im Mietbereich** | Zur aktuellen Miete die ortsübliche Vergleichsmiete je m² ermitteln — vergleichbare Objekte in der Lage, gleicher Standard. Ergebnis als Spanne, dazu die Einordnung: fair, zu niedrig oder zu hoch. Datenquelle steckbar halten: automatisches Abgreifen von Portalen ist rechtlich (AGB, Datenbankrecht) und technisch (Bot-Schutz) fragwürdig — erst prüfen, was tragfähig ist |
| CII | **Hinweis bei deutlicher Abweichung** | Weicht die Miete spürbar von der Spanne ab, erscheint ein Hinweis dort, wo ohnehin Nachrichten und Dokumente auflaufen: „Was ansteht" auf der Startseite und im Dokumenteneingang |
| CIII | **Kategorien entlang des Lebenszyklus** · Priorität **mittel** | Kategorien und Stammdaten entlang des tatsächlichen Ablaufs erweitern: Bau → Kaufvorgang → Inbetriebnahme als Mietobjekt → Kredit → laufender Betrieb. **Gewichtung:** was bei der Vermietung wiederkehrt, wird fein abgebildet und automatisiert. Die einmaligen Themen am Anfang dürfen gröber bleiben.<br>**Umfang bewusst klein:** je Ordner nur **ein bis zwei** Dokumente ansehen, nicht alle 466 — die Vielfalt zählt, nicht die Masse. Sieben Nebenkostenjahrgänge desselben Objekts bringen keine siebte Erkenntnis |
| CIV | **Parameter aus den Dokumenten lesen** · Priorität **mittel** | Aus den Stichproben ableiten, welche Felder die Stammdaten brauchen — damit ein Dokument nicht nur abgelegt, sondern ausgewertet wird. Die zehn großen Lücken stehen schon fest (CXXXI–CXL); weitere Sichtung dient nur noch der Bestätigung |
| CV | **Kaufnebenkosten eintragbar** | Grunderwerbsteuer, Notar, Grundbuch, Makler — beim Kaufvorgang erfassbar, damit die Anschaffungskosten vollständig sind |
| CVI | **Erstaufnahme — der einmalige Initiallauf** | „Wo liegen deine Unterlagen?" → Ordner angeben → einmal komplett drüberfahren: alles sichten, einordnen, benennen, den Stand in der App anlegen. **Wird ausdrücklich vom Nutzer angestoßen**, läuft nie von selbst und nie im Wachdienst mit. Am Ende bestätigt der Nutzer („jetzt passt alles"), erst dann wird einmalig in den Arbeitspfad übernommen — der ist heute leer, deshalb geht es überhaupt nur so |
| CVII | **Live-Logik und Einmal-Skript strikt getrennt** | Die Benennungs- und Einordnungslogik gehört in den laufenden Code (`bezeichnung.py`, `ocr.py`, neues `erstaufnahme.py`), damit sie später identisch weiterarbeitet. Das Initialskript bleibt dünn und ruft sie nur auf — es darf keine zweite Wahrheit entstehen, und nichts davon darf in den 15-Minuten-Takt geraten |
| CVIII | **Rückfragen landen unter „Dokumente"** | Was die Erstaufnahme nicht sicher zuordnen kann, erscheint als offener Punkt in der App — der Nutzer arbeitet sie dort direkt ab, statt auf einen Bericht zu warten |
| CIX | **Verständnis-Bericht nach jeder Sichtung** | Übersicht, welche Dokumente *nicht* verstanden wurden, damit gezielt nachgeschärft werden kann. Erst wenn dieser Rest klein genug ist, wird übernommen |

### Neu aus dem Gespräch vom 21.07.2026 — zweiter Teil

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CXIV | **Kredit gehört nicht in die Nebenkosten** | Klare Trennung der beiden Sichten: **Nebenkosten = Mieterbereich** (was auf den Mieter umgelegt wird), **Wertentwicklung = Eigentümerbereich** — dorthin gehören die Kredite. Betrifft `auswertung.py:19` (`BLOCK_NAMEN` mischt heute Kredit unter die Kostenblöcke) und die Seitenaufteilung |
| CXV | **Restschuld fortschreiben statt raten** | Eingetragen wird nur der Stand zum Jahresende — wie ein Zählerstand. Dazwischen rechnet die App aus Rate und Zinssatz monatlich fort; der nächste eingetragene Jahreswert korrigiert die Rechnung wieder |
| CXVI | **Geplante Mieterhöhungen** | Künftige Erhöhung mit Datum eintragbar, damit sie in Cashflow und Erinnerungen auftaucht, bevor sie wirksam wird |
| CXVII | **Kontakt je Bewohner** | Mail und Handy für **alle** Bewohner einer Einheit getrennt erfassbar, nicht nur ein Kontakt je Mietverhältnis |
| CXVIII | **Eingabemasken formatieren** | €-Beträge beim Eintippen in T€ lesbar gruppieren, IBAN in Vierergruppen, Steuernummer im üblichen Schnitt — jeweils beim Eingeben, nicht erst danach |
| CXIX | **Umbenennung zieht überall nach** | Ändert sich das Benennungsschema, wird es für **alle** Immobilien korrigiert — und die Belege bleiben dabei korrekt verknüpft (`Dokument.pfad` und die Cloud-Ordner müssen mitwandern, sonst zeigen Scans ins Leere) |
| CXX | **Alte Benennung wurde nicht umgezogen** | Im Cloud-Ordner steht die alte Struktur neben der neuen, und die neue ist doppelt geschachtelt: `(Eschenau) Laufer Str. 5/(Eschenau) Laufer Str. 5/`. Dazu die verwaiste `Wohnung 1.OG` von der alten Benennung. Aufräumen und den Umzug nachholen |
| CXXI | **Leerstand verschiebt Kosten auf die Mieter** | Nebenwirkung aus `9fa866c`: endet ein Mietverhältnis mitten im Jahr ohne Nachmieter, trägt der verbleibende Mieter 75 % statt 60 %. Der Leerstand braucht einen eigenen Bezug, damit er beim Eigentümer hängen bleibt |
| CXXII | **Keine Doppelnennung im Dateinamen** | `2026_Nebenkosten_Heizkosten.pdf` im Ordner `60_Nebenkosten` sagt „Nebenkosten" zweimal. Der Ordner ist Kontext — der Dateiname nennt nur, was er hinzufügt |
| CXXIII | **Spezifisch benennen, Betrag anhängen** | Nicht „Heizkosten", sondern die Sache selbst: `2026_Heizöl_1.284€.pdf`. Den Betrag hinten anhängen, so wie der Nutzer es auf seinen Zetteln notiert — dann steht die wichtigste Zahl schon im Ordner |
| CXXIV | **Datum und Betrag in der Dokumentenliste** | Fehlt heute komplett: von wann ist der Beleg, welcher Betrag wurde erkannt? Beides gehört in die Karte, nicht nur in den Dateinamen |
| CXXV | **Rechte Spalte: erkannt → wird eingetragen** | Je Beleg sichtbar machen, was erkannt wurde und was daraus in der App entsteht — mit Bestätigung. Über den Abrechnungszeitraum ist meist klar, wohin er gehört: also vorschlagen, auswählbar lassen, bestätigen. **Kein Beleg ohne Position** in der jeweiligen Immobilie |
| CXXVI | **Bereich heißt „Dokumente & Ereignisse"** | Es laufen dort nicht nur Dateien auf, sondern auch das, was daraus wird — Navigation und Seitenkopf entsprechend benennen |
| CXXVII | **Ordner sofort neu einlesen** | Zusätzlich zum 15-Minuten-Takt ein Knopf, der jetzt prüft — und zwar vollständig abgleicht: auch wenn der Nutzer in der Cloud selbst umbenannt oder gelöscht hat, muss die Liste danach stimmen |
| CXXVIII | **Kostenart statt nur Dokumentart wählen** | „Nebenkosten" allein ist nicht auswertbar. Zweite Ebene: welche Nebenkosten — Heizkosten, Wasser, Müll … Die Auswahl kommt aus den Kostenarten des jeweiligen Objekts, damit der Beleg direkt auf eine Position zeigt |
| CXXIX | **Vorschau rechts, zum Vergrößern** | Beleg anklicken → rechts erscheint das zugeschnittene PDF mit dem, was die Texterkennung gefunden hat. Nochmal klicken → groß, sodass sich die erfassten Werte links gegen das Blatt prüfen lassen |
| CXXX | **Belegdatum genau erkennen** | Nicht nur das Jahr: das tatsächliche Belegdatum aus dem Dokument lesen und anzeigen — es entscheidet, in welchen Abrechnungszeitraum der Beleg gehört |

### Neu aus dem Gespräch vom 21.07.2026 — dritter Teil

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CXLI | **Einheiten sichtbar und bearbeitbar** | Laufer Str. 5 hat vier Einheiten — sie sind nirgends zu sehen. Einheiten müssen auf der Objektseite stehen, anlegbar und änderbar sein |
| CXLII | **Mietverhältnis der Einheit zuordnen — per Auswahl** | Die Einheit wird **angeklickt, nicht eingetippt**. Heute ist `Miete.einheit` Freitext; ein Tippfehler lässt die Partei stumm aus der Verteilung fallen (XCII). Die Auswahl kommt aus den Einheiten des Objekts |
| CXLIII | **Keine Doppelbelegung** | Eine Einheit darf nicht zweimal gleichzeitig vermietet sein — beim Anlegen prüfen und den Überschneidungszeitraum nennen |
| CXLIV | **Dialog: Hintergrund festhalten** | Bei offenem Dialog scrollt heute die Seite darunter; im Dialog selbst nur, wenn der Zeiger genau darüber steht. Der Hintergrund wird festgestellt und zurückgenommen (abgedunkelt/entsättigt), damit der Fokus sichtbar oben liegt |
| CXLV | **Einheiten auf der Übersichtsseite** | Unter der Objektkachel die Einheiten als kleine Bubbles zeigen; das Symbol darf dafür etwas größer werden. Auf einen Blick: was gehört zu diesem Haus |
| CXLVI | **Fristen über ein Jahr ausblenden** | „Was ansteht" zeigt Abrechnungszeiträume, die noch weit weg sind. Was mehr als ein Jahr in der Zukunft liegt, ist heute nicht relevant |
| CXLVII | **Einheit ins Eingabefeld, nicht darunter** | Korrektur zu CXVIII: die Zeile `140 T€` unter dem Feld ist zusammenhanglos. Die Einheit steht **rechts im Feld selbst**, leicht gegraut — `€` bei Ursprungsbetrag, Restschuld und Rate, `%` beim Zinssatz. Gilt für jede Eingabezelle |
| CXLVIII | **Zinssatz aus dem Monatszins ableiten** | Wer den Zinssatz nicht zur Hand hat, gibt den Zinsanteil je Monat ein — die App rechnet den Satz daraus aus (und umgekehrt). Beides sind Wege zum selben Wert, keiner ist Pflicht |
| CXLIX | **Bausparvertrag ist kein Darlehen** | Beim Anlegen wählbar: **Darlehen** oder **Bausparvertrag**; die Eingabemaske richtet sich danach. Darlehen: Restschuld, die sinkt. Bausparer: Bausparsumme (z. B. 140.000 €) und **angesparter Betrag** (z. B. 45.000 €) — der Rest ergibt sich als Differenz. **Wichtig fürs Vermögen:** ein Bausparguthaben ist Guthaben, keine Schuld. Heute läuft „LBS Bausparer" als Kredit und drückt über `vermoegen.py` das Eigenkapital, obwohl es es erhöhen müsste |

### Aus der Sichtung des echten Bestands (Stand: 3 von 14 Bündeln, ~35 von 466 Dokumenten)

| Nr. | Fund | Was fehlt |
|---|---|---|
| CXXXI | **Erkannter Betrag wird weggeworfen** | Die Texterkennung liest den Betrag (z. B. Notarkosten 156,25 €) und `dokumente.py` speichert ihn nicht. `Dokument` braucht Betrag und Belegdatum als Felder — sonst ist jede Erkennung folgenlos |
| CXXXII | **Nur 8 Dokumentarten — der Lebenszyklus fehlt** | Es gibt kein Kauf, Notar, Grundbuch, Bau, Abnahme, Foto, Verbandspost. Die Eintragungsbekanntmachung — der Eigentumsnachweis — landet in `99_Sonstiges`. Die Ordner `50_Bauphase_Projekte` und `10_Fotos_Lage` werden angelegt, aber **keine Kategorie zeigt darauf**: sie bleiben für immer leer |
| CXXXIII | **Unterordner werden nie gescannt** | `dokumente.py:307-309` liest nur den Hauptordner eines Objekts. Der komplette Unterordner `Fotos/` mit 15 Baufortschrittsbildern ist für die App unsichtbar — und der Nutzer sortiert in Unterordnern |
| CXXXIV | **Kaufnebenkosten existieren nicht** | Grep über `api/app` und `public`: null Treffer für Notar, Grunderwerbsteuer, Grundbuch, Makler. Notarkosten lassen sich nur als Zahlung „Sonstiges" ablegen — ein Anschaffungsnebenkostenposten landet damit im falschen Topf (CV) |
| CXXXV | **Objekt-Stammdaten des Grundbuchs fehlen** | Kein Feld für Grundbuchamt, Blatt, Bezirk/Gemarkung, Flurstück, Wohnungsnummer, Notar-URNr, Auflassungs- und Eintragungsdatum. `Objekt.kaufdatum` ist ein einziges Feld — im Bestand liegen aber drei fachlich verschiedene Daten (Bauträgervertrag 2017, Auflassung 12.06.2019, Eintragung 27.06.2019), und von der richtigen hängt die Spekulationsfrist ab |
| CXXXVI | **Grundsteuer ist nicht nachvollziehbar** | Kein Feld für Einheitswert, Grundsteuerwert, Messbetrag, Steuermesszahl, Hebesatz. Die Kette Einheitswert → Messbetrag → Hebesatz → Grundsteuer ist nicht abbildbar, obwohl „Grundsteuer" überall als Kostenart aktiv ist. Beim Grundstück Eckenhaid springt der Messbetrag durch die Reform von 0,61 € auf 1,43 € — in der App wäre das eine zusammenhanglose zweite Zahl |
| CXXXVII | **Kein Baujahr, keine AfA-Grundlage** | `Objekt` (models.py:9-30) hat kein Baujahr. Der Einheitswertbescheid nennt die Aufteilung Gebäude 17.940 DM zu Boden 1.836 DM — genau die AfA-Bemessungsgrundlage. Abschreibung kommt im ganzen Repo nicht vor |
| CXXXVIII | **Objekttyp Grundstück** — vom Nutzer präzisiert | Eckenhaid (4.630 m² Wald- und Landwirtschaftsfläche) passt in kein Modell: `Objekt.flaeche` ist faktisch Wohnfläche und geht in den Verteilungsschlüssel — die Feldfläche dort einzutragen wäre fachlich falsch. Die Ordnervorlage `({ort}) {strasse} · {name}` läuft ohne Straße leer.<br>**Was ein Grundstück braucht:** deutlich weniger als ein Haus. Grundstückswert und Wert je m², **Nutzungsart** (Ackerland, Grünland, Wald, Bauerwartungsland …), **Pachterträge** statt Miete, **Grundsteuerwert** aus dem Finanzamtsbescheid (Messbetrag × Hebesatz). Keine Einheiten, keine Nebenkostenabrechnung, keine Mieter. Eigenes Symbol im bestehenden flachen Stil |
| CXXXIX | **Keine Fälligkeit, kein Zahlstatus** | Der Grundsteuerbescheid nennt „fällig 15.08." — der Turnus ist heute nur ein Hochrechnungsfaktor, es entsteht kein Zahlungsvorgang und keine Erinnerung. Offen/bezahlt, Mahnung, fortgeltender Bescheid: alles nicht vorhanden |
| CXL | **Verträge nur als Versicherung modelliert** | Verbandsbeitrag mit SEPA-Mandat (Gläubiger-ID, Mandatsreferenz), Kündigungsfrist, im Vertrag bereits festgeschriebene Beitragsstaffel (30 € → 36 €) — nichts davon hat ein Feld. Außerdem ist `Zahlung.objekt_id` Pflicht: eine Kostenzeile für **alle** Objekte ist nicht vorgesehen |

### Bewusst zurückgestellt

| Nr. | Aufgabe | Grund |
|---|---|---|
| LVIII | Push-Benachrichtigungen auf iOS | von dir zurückgestellt; braucht HTTPS über den Reverse Proxy |
| LIX | Umbenennung der App | „ImmoCalc“ bleibt vorerst; Vorschläge lagen vor (Hausflow, Immoflow) |

---

## Woran du dich erinnern solltest

- **Deploy nötig:** Die API läuft erst nach `./deploy.sh` mit dem neuen Stand.
  Diesmal besonders: das API-Image bekommt Tesseract, der Build dauert länger.
- **Texterkennung** schlägt nur vor. Ohne Tesseract läuft der Scan weiter,
  dann eben ohne Vorschlag für Betrag und Datum.
- **Sicherungen** landen in der Nextcloud unter `00_ImmoCalc_Sicherungen`
  im Home-Ordner — nicht beim Objekt, das beim Löschen ja gerade wegfällt.
- **Push scheitert:** In der Entwicklungsumgebung fehlen GitHub-Zugangsdaten —
  `git push origin main` musst du selbst ausführen.
- **Nextcloud und Postfach** brauchen deine Zugangsdaten in der Oberfläche.
