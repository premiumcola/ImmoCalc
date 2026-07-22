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
| CCXXVII | Neue Foto-/Scan-PDFs bekommen automatisch eine durchsuchbare Textschicht (OCR im Normalbetrieb) | offen — als Nächstes |
| CCXXVIII | Mehrseitige Dokumente einfach abfotografieren: Rand erkennen, entzerren, zu einem PDF, dann OCR | offen — als Nächstes |
| CCXXIX–CCXLVIII | 20 Modell-Lücken aus der OCR-Dokumentanalyse (Grundschuld, variabler Zins, Zinsen-Ist, Nießbrauch, Rücklagen-Historie, HKVO-Split, Kaution, Mängelliste …) | eingetragen, offen |

---

## Neu gewünscht — 22.07. nachmittags

| Nr. | Anforderung | Was zu tun ist |
|---|---|---|
| CCXXVII | **OCR-Textschicht auch im Normalbetrieb** | Der einmalige Master-Lauf (`tools/ocr_ersetzen.py`, rapidocr → durchsuchbares PDF) muss in die Standard-Dokumentaufnahme wandern: jedes neu aufgenommene PDF ohne Textschicht bekommt sie automatisch, bevor es abgelegt wird. Betrifft `dokumente.py`/`scan.js`/Cloud-Upload; der API-Container braucht die OCR-Abhängigkeiten (`rapidocr-onnxruntime`, `pymupdf`/`pypdfium2`) → Deploy nötig. OCR bleibt optional (fehlt die Lib, still weiter wie bisher). **Priorität hoch** |
| CCXXVIII | **Mehrseitiger Foto-Scan mit Zuschnitt & Entzerrung** | Dokumentseiten abfotografieren (mehrere nacheinander), den Rand des Dokuments erkennen und abschneiden, das Rest-Papier rechtwinklig skalieren (Perspektivkorrektur/Homographie), die Seiten zu **einem** PDF zusammenfügen, danach OCR (CCXXVII). **Guard:** abbrechen/warnen, wenn der Zuschnitt unrealistisch viel wegschneidet oder das erkannte Viereck sehr unparallel/ungleichseitig ist (schlechte Kantenerkennung → lieber manuell nachziehen). Vanilla, keine Libraries: Kamera über `<input capture>`, Ecken automatisch schätzen + manuell nachziehbar, Entzerrung auf Canvas per Zwei-Dreieck-Textur-Trick, PDF-Bau von Hand wie `abrechnung_pdf.py`. **Priorität hoch** |

### Am 21.07. abends fertig geworden

| Nr. | In einfachen Worten | Commit |
|---|---|---|
| CLXXX–CLXXXIV | Aus einem Beleg wird eine Kostenposition · mehrere Belege summieren sich · Rückweg zum Beleg | `1ed9801` |
| CXLVII/CXLVIII | € und % im Eingabefeld · Zinssatz oder Monatszins, beides geht | `64d8597` |
| CLXXXV | Ein abgelehntes Speichern behält die Eingaben | `1eca3c9` |
| CLXVI | Grundstück bekommt Gemarkung und Flurstück in den Ordnernamen | `5b703ec` |
| CLXXIII–CLXXV | Breitere Arbeitsfläche, Felder untereinander, Beleg ganz oben | `db0c01c` |
| CLXXXVIII | Keine Cloud ist eine Auskunft, kein Fehler | `56dcd45` |
| CLXXI | Dateiname nennt Art und Position: `2026-02_NK-Schornsteinfeger_104,15€.pdf` | `eb0f1bb` |
| CLVII/CLXVII | Der Kostenfluss geht auf (Nachzahlung sichtbar) · Pacht heißt Pacht | `294a0d2` |
| — | Ehrlicher Hinweis statt „fehlt der Betrag" · nach dem Einsortieren weiter zum nächsten | `3f6519e` |
| CXLIX/CLXXVI/CLXXXVII | Bausparer zählt als Guthaben · 15-%-Kappungsgrenze warnt · Touch-Targets 44 px | `797af8a` |
| — | Sparrate ist keine Ausgabe im Cashflow | `ec27f03` |

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
| CLV/CLVI | Steuernummer bleibt beim Tippen stehen · Kennzahlen zeigen das ganze Jahr | `a087374` |
| CXXII/CXXIII/CXXVII | Dateinamen mit Datum, Sache und Betrag · vollständiger Ordnerabgleich | `37a3d8d` |
| CLVIII/CLIX | „Benennung nachziehen" mit Trockenlauf · Leerstand bleibt beim Eigentümer | `f3619af` |
| CXXXVIII | Grundstück als eigener Objekttyp: Nutzungsart, Grundsteuerwert, Pacht, Symbol | `ac3ad95` |
| CXXIV/CXXV/CXXIX | Dokumentenseite zweispaltig: Datum, Betrag, Vorschau, „erkannt → wird eingetragen" | `cd4ea56` |
| CXXVI | Der Bereich heißt „Dokumente & Ereignisse" | `4cd2d05` |
| CLIII | Eine geplante Mieterhöhung entsteht nur einmal | `3b5e526` |
| CLXV | Grundstück bekommt keine Abrechnungsfrist mehr | `cd4ea56` |
| CLXXIII/CLXXIV | Breitere Arbeitsfläche, lesbare Auswahlfelder am großen Schirm | `c9a4841` |
| CLXX | Betrag wird aus Text-PDFs gelesen (dein Kaminkehrer: 104,15 €) | `dbdacbc` |
| CLXVII | Beim Grundstück heißt der Wert „Grundstückswert" | `cb759a1` |
| CLXXI/CLXXII/CLXXV/CLXXVII | Kostenart wählbar · Zeitraum aus dem genauen Belegdatum · erledigt wird grün · Erkennung auch für liegende Dateien | `61e2c5b` |
| CXLI/CXLII/CXLIII/CLXVIII/CLXIX | Haus- und Einheitenebene · Einheiten bearbeiten · Einheit per Bubble · keine Doppelbelegung | `051611a` |

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

### Reste aus dem Grundstückstyp (CXXXVIII)

| Nr. | Fund | Warum es zählt |
|---|---|---|
| CLXV | **Grundstück bekommt eine Abrechnungsfrist, die es nicht gibt** | `POST /api/objekte` legt für jedes Objekt einen Zeitraum an. Auf der Startseite steht dann „Frist in 528 T" und `/api/erinnerungen` mahnt eine § 556-Abrechnung an — für ein Feldgrundstück ohne Mieter sinnlos |
| CLXVI | Ordnervorlage läuft ohne Straße leer | Ein Grundstück hat oft keine Straße; die Vorlage `({ort}) {strasse} · {name}` sollte auf Gemarkung und Flurstück ausweichen |
| CLXVII | Pacht heißt in der Auswertung noch „Miete" | `auswertung.py`/`cashflow.py` führen ein Objekt ohne Einheiten als Pseudo-Einheit; Pachterträge laufen mit, sind aber nicht als Pacht benannt. Ebenso zeigt `wertentwicklung.html` „Verkehrswert" statt „Grundstückswert" |

### ~~Vom Beleg zur Kostenposition~~ — erledigt (`1ed9801`)

CLXXX–CLXXXIV sind gebaut: neues Modul `belegposten.py`, drei Endpunkte,
`Dokument.betrag`/`position_id`, `Kostenposition.beleg_summe`. Übernommen wird
als **eigener, sichtbarer Schritt** mit Vorschau („Bisher 1.284,50 € · Dieser
Beleg 982,30 € · Danach 2.266,80 €") — nicht automatisch, weil Einsortieren und
Abrechnen zwei Entscheidungen sind. Mehrere Abschlagsrechnungen laufen in
dieselbe Position; doppeltes Klicken zählt einmal, weil die Summe jedes Mal aus
allen verknüpften Belegen neu gebildet wird. Der Rückweg von der Abrechnung zum
Beleg steht.

| Nr. | Rest | Was fehlt |
|---|---|---|
| CXC | **Kostenart umbenennen zieht die Positionen nicht mit** | Kostenarten lassen sich über die API gar nicht umbenennen (kein PATCH, `stammdaten.ENTITAETEN` führt sie nicht). Sobald es diesen Weg gibt, muss er `Kostenposition.kostenart` mitziehen — so wie `einheit_aendern` es für `Miete.einheit` tut |

### Alte Sammlung: vom Beleg zur Kostenposition

Der Beleg trägt jetzt Kostenart, Belegdatum und Zeitraum (`61e2c5b`). Damit
daraus wirklich eine Position in der Abrechnung wird, fehlt noch:

| Nr. | Fund | Was fehlt |
|---|---|---|
| CLXXX | **Niemand legt die Position an** | `POST /api/zeitraeume/{zid}/positionen` wird vom Beleg aus nicht gerufen. Nötig: ein Schritt „als Position übernehmen" oder eine Automatik beim Einsortieren |
| CLXXXI | **Der Betrag steht nur im Dateinamen** | Bewusst so (CXXIII), aber für die Position unzuverlässig — eine eigene Spalte am Dokument wäre belastbarer |
| CLXXXII | **Eine Position je Kostenart und Zeitraum** | Der Endpunkt lehnt eine zweite mit 409 ab. Für vier Abschlagsrechnungen auf dieselbe Position braucht es eine Regel: summieren statt ablehnen |
| CLXXXIII | **Kein Rückweg von der Abrechnung zum Beleg** | `Kostenposition` kennt kein Dokument. Additiv ergänzbar (`dokument_id` oder Belegliste) |
| CLXXXIV | **Umbenannte Kostenart bricht die Verknüpfung** | Der Beleg zeigt auf einen Namen, den es nicht mehr gibt (`Kostenposition.kostenart` ist Freitext, kein Fremdschlüssel) |

### Reste aus der Einheiten-Ebene

| Nr. | Fund | Was fehlt |
|---|---|---|
| CLXXXV | **Dialog schließt beim abgewiesenen Speichern** | `<form method="dialog">` schließt, bevor der Handler antwortet — nach einem 409 sind alle Eingaben weg. Betrifft alle Formulare der Objektseite, fällt bei der Doppelbelegung am meisten auf |
| CLXXXVI | ~~**Verkehrswert je Einheit**~~ **erledigt** (Commit offen) | Feld `Einheit.verkehrswert` (schon im Modell) ist nun im Einheit-Formular pflegbar (`objekt.html`) und gewichtet die Wertzurechnung je Eigentümer (`vermoegen.eigentuemer_fraktion`): der teureren Wohnung fällt der grössere Anteil am Objektwert zu. Ohne eigenen Wert bleibt die Fläche (ersatzweise Gleichverteilung) massgeblich |
| CLXXXVII | **Löschknöpfe sind 36×36 px** | Gefordert sind 44×44 (Bestand in allen Listen von `objekt.html`) |
| CLXXXVIII | **`GET /api/nextcloud/umzug` antwortet mit 400** | Wirft auf `settings.html` einen JS-Fehler; liegt in `cloud.py` |
| CLXXXIX | **Umbenannte Einheit und alte Abrechnungen** | Mietverhältnisse ziehen mit, aber in bereits gespeicherten `Kostenposition.anteile` steht der alte Einheitsname als Partei — betrifft abgeschlossene Zeiträume mit Leerstand |

### Rechtliche Grenzen bei Mieterhöhungen — belegt am 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CLXXVI | **Kappungsgrenze 15 % statt 20 %** | Eckental ist seit 01.01.2026 Gebiet mit angespanntem Wohnungsmarkt (Bayerische Mieterschutzverordnung vom 16.12.2025, Anlage Nr. 5.3.5) — das betrifft Eschenau, Eckenhaid und Unterschöllenbach. Bei einer geplanten Mieterhöhung (CXVI) muss die App die **15-%-Grenze in drei Jahren** prüfen und warnen, nicht die allgemeinen 20 %. Ebenso gilt dort die Mietpreisbremse: bei Neuvermietung höchstens 110 % der ortsüblichen Vergleichsmiete. Beides läuft bis 31.12.2029.<br>**Falle:** die Verordnung schreibt „Eckenthal" mit „th" — ein Namensabgleich läuft ins Leere, sauber ist der AGS `09572121`. Belege in `docs/mietvergleich-recherche.md` |

### Aus der Erprobung der neuen Dokumentenseite (21.07.2026)

| Nr. | Fund | Was gemeint ist |
|---|---|---|
| CLXX | ~~Betrag aus Text-PDFs lesen~~ — **behoben** (`dbdacbc`) | Zwei Ursachen: die App las nur Bilder über Tesseract (das hier fehlt), und die Rechnung schreibt „104.15" mit Punkt statt Komma. Beides gelöst; am ganzen Bestand gemessen (405 PDFs: 162 mit Textschicht, 142 Betragsvorschläge). **Braucht `./deploy.sh`** — `pypdf` ist neu in den Abhängigkeiten |
| CLXXVII | **Erkennung für Dateien, die schon liegen** | `GET /api/dokumente/{id}/erkennen` ist gebaut, wird aber von niemandem gerufen: die Oberfläche erkennt nur beim Abfotografieren. Deshalb steht im Eingang weiter „nicht erkannt" |
| CLXXVIII | **Betragsauswahl bei mehreren Kandidaten** | `max` über alle Schlüsselwortzeilen greift daneben, wo mehrere Summen stehen: „enth. CO2-Abgabe 429,95 €, Brutto" gewinnt gegen den Rechnungsbetrag 2.895,27 €.<br>**Zwei Versuche sind gescheitert und wurden zurückgenommen** (21.07., gemessen an den 19 Belegen, die ihren Betrag im Dateinamen tragen): eine Rangfolge der Schlüsselwörter (`rechnungsbetrag` vor `summe`/`brutto`) verschlechterte auf 6 von 19 Treffern, „letzte Schlüsselwortzeile statt größter Betrag" auf 5 — Ausgangsstand ist 7. Die Fälle sind zu verschieden: Bündel mehrerer Belege, PV-Abrechnungen mit mehreren Summen, Formulare, deren Werte als Bild eingetragen sind. Nächster Ansatz müsste die **Lage auf dem Blatt** einbeziehen (Endbetrag steht rechts unten, oft nach einer Linie) statt nur das Wort — und braucht eine belastbarere Referenz als die Dateinamen, die selbst teils falsch sind (WWK: Name sagt 1196,09, auf dem Blatt stehen 1225,68) |
| CLXXIX | **Eingescannte PDFs bleiben stumm** | 243 der 405 Belege sind reine Scans ohne Textschicht. Auch mit Tesseract käme nichts heraus, weil es keine PDFs liest — es bräuchte einen Rasterschritt PDF→Bild und damit eine weitere Abhängigkeit |
| CLXXI | **Kostenart wählen, nicht nur die Art** | Wie CXXVIII: „Nebenkosten" allein reicht nicht, es muss „Kaminkehrer" wählbar sein — aus den Kostenarten des jeweiligen Objekts |
| CLXXII | **Rechnungsdatum muss in den Zeitraum passen** | Abrechnungszeiträume liegen nicht immer im Kalenderjahr (z. B. 01.10.–30.09.). Der Beleg gehört in den Zeitraum, in den sein **genaues Datum** fällt — das muss sichtbar geprüft und angezeigt werden |
| CLXXIII | **Aufteilung am großen Schirm** | Links steht viel Leerfläche, rechts wird es eng. Links gehört mehr untereinander, rechts mehr Platz für den Beleg |
| CLXXIV | **Auswahlfelder schneiden den Text ab** | „(Eschenau…", „Nebenkost…" — die Felder sind zu schmal, um lesbar zu sein |
| CLXXV | **Erledigtes wird grün** | Was gewählt und vollständig ist, färbt sich grün; ist alles grün, kann zugeordnet werden |

### Unterordner nach Vorlage — aus dem Gespräch vom 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CXCI | ~~**In den Nebenkosten liegt nicht alles flach**~~ — **gebaut** (`440012f`), offen bleibt nur der Umzug des Altbestands | Woertlich: „Die Unterordner in Nebenkosten und auch in anderen Ordnern sollen nach Vorlage dynamisch erzeugt werden. In NK kann nicht einfach alles flach drin liegen." Der Nutzer sortiert längst so: `60_Nebenkosten/2022 … 2026`, dazu Sammelordner wie `Ablesungsergebnisse` und `NK___PV-Anlage`; in Unterschöllenbach `NK-2018-1OG … NK-2024-1OG`; unter Steuer `2014_Renovierung`, `2020_Renovierung Haupthaus Flure`. Die App legt heute nur die elf Hauptordner an und wirft alles flach hinein. Gebraucht: eine Vorlage je Kategorie (Jahr, ggf. Einheit), aus der der Unterordner beim Einsortieren entsteht — und die vorhandenen Ordner werden dabei genutzt, nicht danebengestellt |

| CXCII | ~~Altbestand in die Unterordner umziehen~~ **erledigt** `8afe220` | Neue Belege wandern seit `440012f` in `60_Nebenkosten/2025`. Die schon abgelegten liegen weiter flach. Ein Umzug bräuchte: Trockenlauf alt → neu je Datei, verschoben wird nur, was flach im Sachordner liegt **und** einen `Dokument`-Eintrag hat (selbst angelegte Ordner wie `Ablesungsergebnisse` bleiben unangetastet), Belege ohne erkennbares Jahr bleiben liegen, `Dokument.pfad` erst nach geglücktem MOVE nachziehen. Vorbild ist `POST /api/nextcloud/umzug` |

### Zwei Ebenen: Haus und Einheit — aus dem Gespräch vom 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CLXVIII | **Das Haus zeigt alles, die Einheit nur ihres** | Zwei Ebenen mit klarer Aufteilung. **Am Haus** (übergeordnet, alles zusammengefasst): Stammdaten, Eigentümer, Kredite, Versicherungen, Steuer, Zahlungen, Dokumentenablage — alles, was nicht auf eine einzelne Wohnung läuft. Von dort springt man auf die Einheiten hinunter. **An der Einheit** (im Fokus): Mieter und Mietverhältnis, Kontakt, Nebenkosten und Abrechnungszeitraum. Die Stammdaten des Hauses werden dort **nicht wiederholt**. Verkehrswert nur, wenn er für diese Einheit gepflegt ist. Von der Einheit führt ein Weg zurück zum Haus |
| CLXIX | **Einheit per Bubble wählen** | Beim Anlegen eines Mietverhältnisses die Einheit als Bubbles anbieten — vier Blasen, eine antippen. Kein Freitext (siehe XCII: ein Tippfehler lässt die Partei stumm aus der Verteilung fallen), keine Liste zum Aufklappen |

### Aus der Bestandssichtung — 22.07.2026 (Details lokal in analyse/sichtung/)

Sichtung der Text-PDFs des echten Bestands, 6 Agents parallel. Ergebnis: die
meisten wichtigen Belege (Kauf-, Miet-, Darlehensverträge, Handwerker, ältere
Bescheide) sind Scans ohne Text -> brauchen CLXXIX (OCR). Die lesbaren Text-PDFs
(Versorger, delta-t, Bescheide, PV) bestätigen CXXXI–CXL und fördern neue Lücken
zutage. Nach Priorität (was jährlich wiederkehrt zuerst):

| Nr. | Aufgabe | Priorität |
|---|---|---|
| CXCVI | **Beleg-Metadaten vervollständigen** — Belegdatum, Abrechnungszeitraum (von–bis, jahresübergreifend erlaubt, Semester-Stichtag 30.09.), Zahldatum getrennt vom Belegdatum, Fälligkeit | hoch |
| CXCVII | ~~Zahlplan je Beleg~~ **verworfen** — der Nutzer: nur der finale echte Rechnungsbetrag zählt, die Zahltermine sind egal. Der Betrag am Beleg (CXXXI) deckt das ab | — |
| CXCVIII | **Zähler-Stammdaten + Ableseereignisse** — Zählernummer, Typ, Stand alt/neu, Ablesedatum, Zählerwechsel, Zählermiete als Position, Verbrauch als Umlagebasis | hoch |
| CXCIX | **Kombi-/Sammelbeleg aufteilbar** — ein Bescheid mischt mehrere Kostenarten (Grundsteuer + Wasser) oder zwei Perioden; muss auf mehrere Positionen/Zeiträume verteilbar sein | hoch |
| CC | **Darlehen mit Konditionen, mehrere je Objekt** — Sollzins, Effektivzins, Zinsbindungsende, Tilgung, Disagio, Rate (Zins/Tilgung getrennt), Auszahlung, Laufzeit, Belastungs-IBAN, Restschuld-Verlauf; Vertragsarten Annuität/Ratenkredit/Bausparer/Zwischenfinanzierung. `vermoegen.py` auf mehrere Tranchen erweitern | mittel |
| CCI | **Grundsteuer-Herleitung über zwei Bescheide** — Grundsteuerwert → Messzahl → Messbetrag → Hebesatz → Jahresbetrag (Finanzamt + Gemeinde), mit Aktenzeichen; Weg Bescheid → NK-Umlage. Erweitert CXXXVI/CXXXVII | mittel |
| CCII | **Vertrags-Stammdaten** — Mietvertrag (Grundmiete, NK-Split Wärme/WW vs. übrige, Kaution, Staffel, Umlagemaßstab je Kostenart, Laufzeit) und Versicherungspolice als eigene Objekte, nicht nur Belege. AcroForm-Formulare brauchen Feldauslesen, nicht nur OCR | mittel |
| CCIII | **WEG-Ebene** — Wirtschaftsplan + Hausgeld je Einheit (getrennt von der Mieter-NK), Rücklagen-/Girokonto mit Stichtagsständen, Dokumenttyp Protokoll/Beschluss, getrennte offizielle vs. interne Verteilerschlüssel | mittel |
| CCIV | **Anschaffungskosten/AfA** — Grund/Gebäude-Aufteilung, AfA-Basis, Kaufnebenkosten getrennt, anschaffungsnahe Herstellungskosten aggregieren (15-%-Grenze, 3-Jahres-Frist) | mittel |
| CCV | **CO2-Kostenaufteilung** je Brennstoffbeleg (kWh, CO2-kg, CO2-Abgabe, Vermieteranteil ab 2023 nach CO2KostAufG) | niedrig |
| CCVI | **PV-Einspeisung als Einnahmequelle** im Cashflow (kWp, Inbetriebnahme, kWh, gestaffelter Tarif, Abschlagsplan) | niedrig |
| CCVII | **Weitere Stammdaten** — Objekt-Hauskonto (IBAN) + SEPA-Mandat, Vergleichsmiete/Mietspiegel je Objekt, Eigentümer als Gemeinschaft/GbR, Objekttyp unbebautes Grundstück (Grundsteuer A), Pflichttermine ohne Zahlung (Feuerstättenschau), Inventarliste je Einheit, §-35a-Flag je Position mit Belegzuordnung, unterjähriger Versorger-/Mieterwechsel | niedrig |

### WEG-Ebene und Rücklagenkonto — 22.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CCVIII | **WEG-Ebene je Objekt an-/abschaltbar** | Beim Objekt wählbar, ob es eine Eigentümergemeinschaft (WEG) ist. **Ist sie an:** die Mieter-Nebenkosten werden als fertige Endwerte vom Zettel der Abrechnungsfirma direkt eingetragen (kein Verteilungsrechnen der App), und es gibt eine WEG-Ebene für die Werte, die nur aus Vermietersicht zählen — Hausgeld, Wirtschaftsplan, Rücklagenzuführung. Ersetzt CLXIII/CCIII |
| CCIX | **Rücklagenkonto je Objekt** | Ein Saldo (Stand des Rücklagenkontos) plus optional eine monatliche Rücklage/Sparrate. In der Eigentümersicht (Wertentwicklung) sichtbar; der Saldo ist zurückgelegtes Eigentümergeld |

### Aus der Code-Prüfung — 22.07.2026 (4 Finder parallel, jeder Fund gegengeprüft)

Vollständiger Bericht lokal in analyse/review/ bzw. scratch/review/GESAMT.md.
Reihenfolge: erst echte Bugs, dann Modularisierung/Regelverstöße, dann Kosmetik.

**Bugs — Geld/Zustellung:**

| Nr. | Fund | Datei |
|---|---|---|
| CCX | ~~**Ausgezogene Mieter bekommen ihre Abrechnung nie**~~ **erledigt** `e14a366` | `versand.py:45` — `_empfaenger` zählt nur Mieter mit `bis_datum is None`, die Verteilung aber alle, die den Zeitraum schneiden. Ein 2024 ausgezogener Mieter mit Nachzahlung und hinterlegter Mail wird als „ohne Mailadresse" übersprungen. Fix: dasselbe Prädikat wie `verteilung._laufend`, Zeitraum durchreichen |
| CCXI | ~~**Teilversand gilt beim Retry als vollständig**~~ **erledigt** `e14a366` | `versand.py:185` — Dedup auf Partei-Ebene, Versand aber je Adresse. Ehepaar mit zwei Mails, SMTP-Fehler bei Adresse 2 → nach dem Retry gilt die Partei als versorgt, die zweite Person bekommt nie etwas. Fix: Dedup auf `(Partei, Empfänger)` |
| CCXII | ~~**Korrigierte Abrechnung nicht erneut zustellbar**~~ **erledigt** `e14a366` | `versand.py:189` — `erneut=True` umgeht den 409, aber der Loop überspringt alle schon belieferten Parteien. Nach einer Korrektur bekommt niemand die neue Abrechnung. Fix: Versandprotokoll beim erneuten Abschluss zurücksetzen |

**Wichtig — Modularisierung, Regelverstöße:**

| Nr. | Fund | Datei |
|---|---|---|
| CCXIII | ~~**Natives `<select>` im Mailversand**~~ **erledigt** `0a15f38` | `settings.html:386` — Anbieter-Wähler ist ein natives select (Regelverstoß, System-Auswahlrad auf iOS). Auf `auswahlfeld` aus auswahl.js umstellen |
| CCXIV | ~~**Import-Zirkel cloud ↔ dokumente**~~ **erledigt** `2d0badf` | `cloud.py:76` — geteilte Infrastruktur (`_lies`/`_schreib`/`verbindung`/`STRUKTUR`) liegt im cloud-Router, dokumente importiert daraus, cloud fünfmal lazy zurück. In neutrale Module herauslösen |
| CCXV | ~~**`_objekt(session, slug)` 3× identisch, 17× inline**~~ **erledigt** `fb44d33` | `stammdaten.py:38` (+ besitz.py, objekte.py) — als gemeinsame FastAPI-Dependency `objekt_holen` herauslösen |
| CCXVI | ~~**Navigationsleiste in 8 Seiten kopiert**~~ **erledigt** `fc21f44` | `index.html:167` — den `<nav>`-Block zentral aus immo.js injizieren (wie `installLogos()`) statt 8× pflegen |
| CCXVII | ~~**`.applogo`/Kachel-CSS in 4 Seiten dupliziert**~~ **erledigt** `fc21f44` | `index.html:22` — die Regeln einmal nach immo.css, die inline-Kopien entfernen |

**Kosmetik — Aufräumen:**

| Nr. | Fund | Datei |
|---|---|---|
| CCXVIII | ~~Leerzustand-Hinweis des Ordner-Browsers greift nur an der Wurzel (Operator-Präzedenz)~~ **erledigt** `0a15f38` | `settings.html:575` |
| CCXIX | ~~Home/End scrollt die Markierung nicht ins Sichtfeld (A11y)~~ **erledigt** `ecd955f` | `auswahl.js:147` |
| CCXX | ~~Euro-/Promille-Formatierer je Seite neu statt aus immo.js (`eur`/`eurKurz`/`eurVoll` + ein neues `promille`)~~ **erledigt** `fc21f44` | eingang/status/app/onboarding/eigentuemer/objekt |
| CCXXI | ~~`Session` doppelt importiert (auch als `DBSession`)~~ **erledigt** `7251ec2` | `auswertung.py:17` |
| CCXXII | ~~`_kern` dupliziert `bezeichnung.vergleichsname` (abweichend bei Ziffern)~~ **erledigt** `ecd955f` | `dokumente.py:141` |
| CCXXIII | ~~Ungenutzter Import `field`~~ **erledigt** `7251ec2` | `engine.py:9` |
| CCXXIV | Fehlende Type-Hints auf Signaturen (breit: kappungsgrenze, nachpflege, export, seed, dokumente, cloud) | mehrere |
| CCXXV | `mietvergleich.py` in keinen Router verdrahtet (bewusst geparkt, CI/CII) | `mietvergleich.py` |
| CCXXVI | `alert()` + hartcodierte Mockup-Daten in Dev-Seiten aus public/ erreichbar | `app.html:357`, `logos.html:151` |

### Aus der Dokument-Lücken-Analyse — 22.07.2026 (3 Fach-Agents, 82 echte OCR-Dokumente)

Vollständiger Bericht lokal in `analyse/gap-analyse-22-07.md`. Nur NEUE Lücken
sind hier nummeriert; viele Dokumente bestätigen nur bestehende Punkte
(CXCVI–CCXII) — die Bestätigungen/Verfeinerungen stehen im Bericht. Alle
Vorschläge additiv (neue Optional-Felder/Tabellen, kein Bruch am Bestand).

**Finanzierung / Kredit / Steuer:**

| Nr. | Lücke | Was zu tun ist |
|---|---|---|
| CCXXIX | **Grundschuld als dingliche Sicherheit** — hoch | Zweckerklärungen: Betrag, Rang, Grundbuchblatt, mit/ohne Brief; im Bestand sichert eine Grundschuld auf Objekt A einen Kredit für Objekt B (Cross-Collateral). `Kredit` ist 1:1 zu `objekt_id`. → neue Tabelle `Grundschuld` + m:n-Zuordnung zu `Kredit` |
| CCXXX | **Variabler Anschlusszins nach Zinsbindung** — hoch | Verträge legen nach `zinsbindung_bis` einen variablen Satz (Referenzzins + Aufschlag) fest; `vermoegen.stand_fortschreiben` rechnet über das Bindungsende hinaus mit dem alten Satz weiter → für Bestandsverträge falsch. → `zinssatz_variabel`/`referenzzins` an `Kredit`, greift ab Bindungsende |
| CCXXXI | **Zinsen-Ist aus Kontoauszug** — hoch | Jahreskontoauszug weist den echten Sollzins-Jahresbetrag aus (→ Anlage V). App hat nur die Kalkulation. → Feld `zinsen_ist` je Jahr an `Kreditstand`, Auswertung zeigt beide Werte nebeneinander |
| CCXXXII | **Bereitstellungszinsen** — mittel | Eigener Satz p.a. auf nicht abgerufenen Betrag ab Datum. → `bereitstellungszins_satz`/`_ab` an `Kredit`, getrennter Ausweis |
| CCXXXIII | **Sondertilgungsrecht** — mittel | „bis X €/Kalenderjahr". → `sondertilgung_jahr_max` an `Kredit` (später ggf. Erinnerung „dieses Jahr noch nicht genutzt") |
| CCXXXIV | **Auszahlungskurs/Disagio** — niedrig | Nennbetrag ≠ Nettodarlehen über Auszahlkurs %. → `auszahlungskurs_pct` (Default 100) an `Kredit` |

**Erwerb / Eigentum / Grundstück:**

| Nr. | Lücke | Was zu tun ist |
|---|---|---|
| CCXXXV | **Unentgeltlicher Erwerb + Nießbrauch** — hoch | Überlassung/Vermächtnis mit vorbehaltenem Nießbrauch; App unterstellt Kauf. Betrifft AfA-Fortführung (Fußstapfenprinzip) und Einkünftezurechnung (Nießbraucher ≠ Eigentümer). → `Objekt.erwerbsart` (Kauf/Schenkung/Erbschaft/Überlassung), AfA-Basis vom Vorbesitzer, Nießbrauch-Felder |
| CCXXXVI | **Bauträger-Kaufpreisraten (MaBV)** — mittel | Gestaffelt nach Baufortschritt, Bezug auf Notar/UR-Nr., getrenntes Sammelkonto, Sonderausstattung. `Objekt` hat nur `kaufpreis`/`kaufdatum`. → Tabelle `Kaufpreisrate` + `notar`/`urkunden_nr` |
| CCXXXVII | **Grundbuch-Belastungen** — niedrig | Dienstbarkeiten (Leitungs-/Wegerecht), Veräußerungsverbote, Verfügungsbeschränkungen aus Abt. II; heute nur `flurstueck`/`gemarkung` als Freitext. → Feld `dingliche_lasten` (Freitext) am Objekt |
| CCXXXVIII | **Grundstückskauf: schwebende Genehmigungen** — niedrig | Fälligkeit hing an Behördengenehmigungen (GrdstVG-Zeugnis, Vorkaufsrechtsverzicht) mit Fristenlauf. → Status-/Freitextfelder am Grundstücks-Objekt |

**WEG / Nebenkosten / Zähler:**

| Nr. | Lücke | Was zu tun ist |
|---|---|---|
| CCXXXIX | **Rücklagenkonto-Historie** — mittel | Jahresblatt mit Anfangs-/Endsaldo, Einzahlung, Bankspesen. `Objekt.ruecklage_saldo` (CCIX) ist nur ein aktueller Wert. → Tabelle analog `Kreditstand` (objekt_id, jahr, saldo, notiz) |
| CCXL | **HKVO Grund-/Verbrauchssplit** — mittel | Heizkosten zwingend in Grund (Fläche) und Verbrauch (Zähler) geteilt, meist 30/70 (§7 HeizkostenV). Kostenart kennt keinen Split-Faktor. → Feld `grundkosten_anteil` an `Kostenart`, Engine teilt automatisch in zwei Positionen |
| CCXLI | **Flächenvariante je Zweck** — niedrig | Heiz-/Warmwasserfläche ≠ Wohnfläche (ista-Nutzerlisten). `Einheit.flaeche` ist ein einziger Wert. → optionale Zusatzflächen je Einheit, nur wirksam wenn gepflegt |

**Mietverhältnis / Bau / Gewährleistung:**

| Nr. | Lücke | Was zu tun ist |
|---|---|---|
| CCXLII | **Übergabe-/Abnahmeprotokoll je Mietverhältnis** — mittel | Zustand je Raum + Zählerstände (Gas/Wasser/Strom/Heizung/WW/Öl) zum Ein-/Auszug, Mängel. `Miete` hat nur ab/bis. → Tabelle `Übergabeprotokoll` (miete_id, Zeitpunkt, Zählerstände, Mängel) |
| CCXLIII | **Kaution: Anlageart/Rückgabe/Einbehalt** — mittel | `Miete.kaution` ist nur ein Betrag. → `kaution_anlageart`, `kaution_rueckgabe_datum`, `kaution_einbehalt` |
| CCXLIV | **Schönheitsreparaturen-/Kleinreparaturklausel** — mittel | Grenze je Fall/Jahr; wirkt auf §35a-/Instandhaltungszuordnung (wer zahlt die kleine Reparatur). → `kleinreparatur_grenze_position`/`_jahr`, `schoenheitsreparaturen` am Mietverhältnis |
| CCXLV | **Abnahme-Mängelliste** — mittel | Je Gewerk/Raum, Frist, Minderungsbetrag; auch Schornsteinfeger-Mängelbescheid mit Frist. → Tabelle `Mangel` (objekt_id, gewerk, beschreibung, frist, minderung_betrag, status) |
| CCXLVI | **Kündigungsfrist-Staffelung + Befristung** — niedrig | Verlängerung nach 5/8 Jahren, Befristungsgrund §575, Kündigungsverzicht. → `mietvertrag_typ`, `befristungsgrund`, `kuendigungsverzicht_bis` |
| CCXLVII | **Modernisierungsumlage §559** — niedrig | Maßnahme → Kaltmieten-Erhöhung, heute kein Bezug. → Datensatz „Mieterhöhung" mit Grund (Modernisierung/Index/Staffel/Vergleich) und Verweis auf die Maßnahme |
| CCXLVIII | **Gewährleistungsfrist ab Abnahme** — niedrig | Abnahmedatum = Fristbeginn (Bau i.d.R. 5 J.); `erinnerungen.py` kennt nur wiederkehrende Termine. → `gewaehrleistung_bis` am Abnahme-/Mangel-Datensatz, von `erinnerungen.py` erfasst |

> Präzisierung zu **CCVII** (kein eigener Punkt): Der „Pflichttermine ohne
> Zahlung"-Anlass sollte ein freier Text statt fester Enum sein, damit auch
> Nachbarschafts-/Rechtsfristen mit Eskalationsstufe hineinpassen.

### OCR für Scan-PDFs — 22.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CLXXIX | **Scan-PDFs per lokalem OCR lesbar machen** | 243 der 405 Belege haben keine Textschicht. Rastern (pypdfium2) -> tesseract -> Betrag/Datum wie bei Text-PDFs. Laeuft lokal im Container (dort ist tesseract), Agents bauen und testen nur. **Originale werden nur gelesen** — immo_DATA ist der neue Master |
| CXCV | **Scan-PDF durch durchsuchbare OCR-Variante ersetzen** | Vom Nutzer erlaubt: „wenn es funktioniert, darfst du die PDF gerne mit neuer besserer OCR-Variante ersetzen." **Erst nachdem CLXXIX steht und die Qualitaet geprueft ist.** Sicher: neue durchsuchbare Datei erzeugen, pruefen (gleiche Seitenzahl, enthaelt den Text, nicht kaputt), Original als Backup sichern, dann atomar ersetzen. Ausdruecklich angestossen, nie automatisch |

### Nebenkosten: global verteilen, Sonderfälle je Einheit — 22.07.2026

Grundlage steht schon: `Kostenart` hängt an der Immobilie, eine Kostenposition
wird per Schlüssel (Fläche, Personen, Zähler …) über alle Einheiten verteilt.
Grundsteuer & Co. werden also **einmal global** angelegt, nicht je Einheit. Was
fehlt, sind die zwei Sonderwege:

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CXCIII | ~~Einheit von der NK-Abrechnung ausschließen~~ **erledigt** `78d649a` | Eine Einheit soll ganz aus der Verteilung fallen können — selbstgenutzt, separat abgerechnet oder gewerblich mit eigenem Zähler. Neues Feld an `Einheit` (z. B. `nk_abrechnung: bool = True`); `verteilung.bezuege` lässt sie dann in keinem Schlüssel mitzählen. **Wichtig:** die Summe muss trotzdem exakt aufgehen — die ausgeschlossene Fläche darf die Anteile der übrigen nicht verzerren |
| CXCIV | ~~Position zu 100 % auf eine Einheit~~ **erledigt** `78d649a` | Der Sonderfall: eine Position gehört ganz einer Einheit (Reparatur nur in Wohnung 2, eigener Warmwasserboiler). Statt global anlegen und Gewichte von Hand setzen — direkt an der Einheit anlegen, dann trägt sie den Betrag allein. Neues Feld an `Kostenposition` (z. B. `nur_einheit: str = ""`); ist es gesetzt, geht der Schlüssel leer aus und die eine Einheit bekommt 100 %. In der Oberfläche: NK global am Haus **oder** als Sonderposten in der Einheit anlegbar |

### Eigentum je Einheit — aus dem Gespräch vom 21.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| CLXI | ~~**Eigentümer je Einheit statt nur je Objekt**~~ **erledigt** (Commit offen) | `Anteil.einheit` (leer = ganzes Haus) trägt jetzt optional eine Einheit. Anteile-Endpunkte (`besitz.py`) nehmen `einheit` entgegen, Eindeutigkeit je (Eigentümer, Einheit) — dieselbe Person kann Haus **und** Einheit halten. In `objekt.html` wird die Einheit beim Zuordnen als Blase gewählt („Ganzes Haus" + je Einheit). **Zusammenspiel:** Einheit-Anteile haben Vorrang für ihre Einheit, der Objekt-Anteil deckt den Rest. Konsistenz je Haus **und** je Einheit auf 1000 ‰ geprüft, Warnung analog `parteien_ohne_einheit`. Umlage auf die Mieter unberührt (`verteilung.py` nicht angefasst) |
| CLXII | ~~**Auswertung je Eigentümer**~~ **erledigt** (Commit offen) | Neuer Endpunkt `GET /api/eigentuemer/uebersicht` (`besitz.py`): Wert, Restschuld, Eigenkapital und Miete je Eigentümer — auf seine Einheiten eingeschränkt. Wert/Restschuld nach wertgewichtetem Anteil, die Miete konkret aus den eigenen Einheiten. Gezeigt je Person auf `eigentuemer.html` (Kennzahlen „Mein Wert / Mein Eigenkapital / Miete pro Jahr" + Einheiten je Objekt). Gesamtsicht `/vermoegen` bleibt unberührt |
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
| CI/CII | **Mietvergleich** | Von dir zurückgestellt (21.07.): „ich weiß nicht, ob das so wichtig ist". Das Rechenmodul samt Zensus-Daten und 56 Tests liegt fertig in `api/app/mietvergleich.py` (`ad50722`), ist aber **nirgends angebunden** — kein Endpunkt, keine Oberfläche. Anknüpfen kostet später wenig |
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
