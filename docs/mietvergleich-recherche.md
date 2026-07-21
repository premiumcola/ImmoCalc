# Mietvergleich — Entscheidungsgrundlage

Warum der Orientierungswert so gerechnet wird, wie er gerechnet wird, was die
Datenlage hergibt und was nicht, und wie das Ergebnis in der Oberfläche
beschriftet werden muss.

Geschrieben für den, der später die Oberfläche baut. Alle Quellen sind mit URL
belegt; abgerufen am 21.07.2026. Was nicht belegt werden konnte, ist als
unsicher gekennzeichnet.

Code: `api/app/mietvergleich.py` · Tests: `api/tests/test_mietvergleich.py` ·
Daten: `api/app/daten/zensus2022_nettokaltmiete_1km.csv.gz`

---

## 1. Die wichtigste Festlegung: „Orientierungswert"

**Der Wert heißt in der Oberfläche „Orientierungswert". Niemals „ortsübliche
Vergleichsmiete".**

Die ortsübliche Vergleichsmiete ist ein Rechtsbegriff. § 558 Abs. 2 BGB
definiert sie als die üblichen Entgelte, die in der Gemeinde „für Wohnraum
vergleichbarer Art, Größe, Ausstattung, Beschaffenheit und Lage einschließlich
der energetischen Ausstattung und Beschaffenheit in den letzten sechs Jahren
vereinbart oder […] geändert worden sind".
<https://www.gesetze-im-internet.de/bgb/__558.html>

Wer eine Mieterhöhung darauf stützt, muss sie nach § 558a Abs. 2 BGB mit einem
von **vier abschließend aufgezählten Begründungsmitteln** belegen:

1. einem Mietspiegel,
2. einer Auskunft aus einer Mietdatenbank,
3. einem begründeten Gutachten eines öffentlich bestellten und vereidigten
   Sachverständigen,
4. entsprechenden Entgelten für einzelne vergleichbare Wohnungen — drei
   Wohnungen genügen.

<https://www.gesetze-im-internet.de/bgb/__558a.html>

Ein Mittelwert aus dem Zensus ist **keines dieser vier Mittel**. Er kann eine
Mieterhöhung nicht begründen und würde vor Gericht nicht tragen. Er taugt zur
Einordnung — „liege ich ungefähr richtig?" —, nicht als Rechtsgrundlage.

Daraus folgt für die Oberfläche: das Ergebnis wird als Orientierung
präsentiert, nicht als Anspruch. Ein Test wacht darüber, dass die Begriffe
„Vergleichsmiete" und „ortsüblich" in keiner Ausgabe des Moduls auftauchen
(`test_der_begriff_vergleichsmiete_taucht_nirgends_auf`).

### Was der Nutzer trotzdem wissen sollte

Zwei Grenzen bestimmen, wie viel Luft nach oben überhaupt besteht. Beide setzen
die *ortsübliche* Vergleichsmiete voraus, nicht unseren Orientierungswert —
darum können sie nur erklärt, nicht gerechnet werden:

- **Kappungsgrenze, § 558 Abs. 3 BGB.** Bei einer Erhöhung auf die ortsübliche
  Vergleichsmiete darf die Miete innerhalb von drei Jahren um nicht mehr als
  20 % steigen. In Gemeinden, in denen die Versorgung mit Mietwohnungen
  „besonders gefährdet" ist, senkt eine Landesverordnung diesen Satz auf 15 %.
  <https://www.gesetze-im-internet.de/bgb/__558.html>
- **Mietpreisbremse, § 556d BGB.** In per Landesverordnung ausgewiesenen
  Gebieten mit angespanntem Wohnungsmarkt darf die Miete zu Beginn eines
  Mietverhältnisses die ortsübliche Vergleichsmiete um höchstens 10 %
  übersteigen. Eine solche Verordnung muss nach § 556d Abs. 2 BGB in der
  geltenden Fassung „spätestens mit Ablauf des 31. Dezember 2029 außer Kraft
  treten" — die Regelung wurde also über das ursprüngliche Ende hinaus
  verlängert. <https://www.gesetze-im-internet.de/bgb/__556d.html>

---

## 2. Quellenlage

### Was es nicht gibt

Es gibt **keine bundesweite, kostenlose, maschinenlesbare Quelle für
Vergleichsmieten mit echter Spanne.** Mietspiegel sind kommunal, uneinheitlich,
meist nur als PDF veröffentlicht und häufig urheberrechtlich geschützt.

### Die gewählte Quelle: Zensus 2022, Gitterzellen

Bundesweit flächendeckend und frei nutzbar ist allein der Zensus 2022.
Verwendet wird die Tabelle **„Durchschnittliche Nettokaltmiete und Anzahl der
Wohnungen in Gitterzellen"**:

<https://www.destatis.de/static/DE/zensus/gitterdaten/Durchschnittliche_Nettokaltmiete_und_Anzahl_der_Wohnungen.zip>

Übersicht aller Gitterdatensätze:
<https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Bevoelkerung/Zensus2022/_publikationen.html>

| Eigenschaft | Wert |
|---|---|
| Merkmal | durchschnittliche Nettokaltmiete/m² der **vermieteten** Wohnungen in Wohngebäuden (ohne Wohnheime), ohne mietfrei überlassene Wohnungen |
| Zusatzmerkmal | Anzahl dieser Wohnungen je Zelle |
| Auflösung | 100 m, **1 km** (verwendet), 10 km |
| Zellen im 1-km-Gitter | 136.024 belegte Zellen, zusammen 21.247.058 vermietete Wohnungen |
| Koordinatensystem | ETRS89-LAEA Europe, EPSG:3035, INSPIRE-konform |
| Stichtag | **15.05.2022** |
| Version | 2, erschienen 08.07.2025 |
| Lizenz | Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0), <http://www.govdata.de/dl-de/by-2-0> — auch kommerziell nutzbar, Quellenvermerk erforderlich |

Wichtige Eigenheiten, alle aus der mitgelieferten Datensatzbeschreibung:

- **Zellen ohne Wohnungen fehlen** in der Datei. Ein fehlender Eintrag heißt
  also nicht „Miete unbekannt", sondern „dort wohnt niemand zur Miete".
- **Geheimhaltung nach § 16 BStatG** über eine stochastische Überlagerung
  (Cell-Key-Methode). Die Werte sind also bewusst leicht verrauscht. Bei Zellen
  mit wenigen Wohnungen fällt das stark ins Gewicht — der Grund für die
  Gewichtung weiter unten.
- **Werterläuterndes Zeichen `KLAMMERN`**: „Aussagewert eingeschränkt, da der
  Zahlenwert statistisch relativ unsicher ist." 6.689 der 136.024 Zellen (4,9 %)
  tragen es. Sie werden nicht verworfen — das würde verzerren —, sondern
  mitgezählt und in der Herkunft ausgewiesen.
- Die Angabe ist ein **Mittelwert je Zelle**, keine Verteilung. Die Spanne, die
  dieses Modul bildet, ist deshalb eine Spanne *zwischen Nachbarschaften*, nicht
  zwischen einzelnen Wohnungen. Das ist die zentrale Einschränkung — siehe
  Abschnitt 5.

### Geprüft und verworfen: „Nettokaltmiete nach Gebäudealter und Wohnungsgröße"

Es gibt einen zweiten Zensus-Datensatz, der die Miete nach Gebäudealter und
Wohnungsgröße aufschlüsselt — das wäre für eine differenzierte Spanne
interessant. Er wird **nicht** verwendet:

- Er liegt **nur im 100-m-Gitter** vor. Bei dieser Auflösung ist eine einzelne
  Zelle fast immer zu dünn besetzt, um nach Baujahr *und* Größe aufgeteilt noch
  eine Aussage zu tragen; das Geheimhaltungsverfahren schlägt entsprechend
  stärker durch.
- Er ist mit rund 15,9 MB gepackt deutlich größer, bei geringerem Nutzen.
- Der auf der Publikationsseite verlinkte Download war am 21.07.2026 defekt
  (HTTP 404 bei allen geprüften Schreibweisen des „ß" im Dateinamen). *Dieser
  Punkt ist ein Momentbefund und kann sich geändert haben.*

Falls der Datensatz später doch gebraucht wird: er ließe sich als
**Zuschlagsfaktor** auf den 1-km-Wert legen (Baujahresklasse, Größenklasse),
statt ihn als eigene Basis zu verwenden. Das wäre der saubere Weg.

### Kommunale Mietspiegel als Open Data

Einzelne Städte veröffentlichen Mietspiegeldaten maschinenlesbar — Hamburg mit
Unter-, Mittel- und Oberwert je Rasterfeld, Dortmund mit rund 35
Ausstattungsmerkmalen. Für die Lagen des Nutzers in Mittelfranken gibt es
nichts Vergleichbares (Details in Abschnitt 3).

Sollte die App später eine Stadt mit offenem Mietspiegel abdecken, ist die
Architektur darauf vorbereitet: `spanne()` liefert die Herkunft mit, und eine
zweite Quelle würde denselben Rückgabeaufbau bedienen und in der Herkunft
lediglich anders benannt.

### Was ausdrücklich nicht getan wird

- **Keine Immobilienportale scrapen.** Das verstößt gegen deren
  Nutzungsbedingungen und berührt das Datenbankherstellerrecht nach § 87b UrhG.
- **Keine fremden Mietspiegel abtippen.** Ein Mietspiegel ist nicht
  gemeinfrei: Das OLG Stuttgart hat mit Urteil vom 14.07.2010 (Az. 4 U 24/10)
  entschieden, dass auch ein kommunaler qualifizierter Mietspiegel
  urheberrechtlich geschützt ist und **kein amtliches Werk nach § 5 UrhG**
  darstellt.
  <https://www.strunz-alter.de/aktuelle-informationen/auch-ein-kommunaler-qualifizierter-mietspiegel-ist-urheberrechtlich-geschuetzt/>

### Angebotsmieten liegen systematisch über Bestandsmieten

Was in Inseraten steht, ist nicht, was gezahlt wird. Angebotsmieten beziehen
sich auf **neu vermietete** Wohnungen; Bestandsmieten umfassen auch alle
laufenden Verträge, die seit Jahren unverändert sind und die Kappungsgrenze des
§ 558 Abs. 3 BGB im Rücken haben. Der Zensuswert ist eine **Bestandsmiete** —
er umfasst alle vermieteten Wohnungen, nicht nur die gerade angebotenen.

Praktische Folge für die Oberfläche: Wenn der Nutzer den Orientierungswert mit
Zahlen von Immobilienportalen vergleicht, wird ihm unsere Spanne zu niedrig
vorkommen. Das ist kein Fehler, sondern ein Unterschied in der Grundgesamtheit,
und die Oberfläche sollte ihn benennen.

*Eine konkrete, belegte Größenordnung für den Abstand ist in dieser Recherche
nicht gesichert worden — die Aussage „Angebot über Bestand" ist der Sache nach
unstrittig, eine Prozentzahl sollte die Oberfläche aber nur nennen, wenn sie
zuvor belegt wird.*

---

## 3. Die Lagen des Nutzers: Mittelfranken

Die Objekte liegen in Eckental (Eschenau, Eckenhaid), Unterschöllenbach
(Landkreis Erlangen-Höchstadt) und Nürnberg.

Für diese Lagen gibt es **keine offene, maschinenlesbare Mietspiegelquelle**.
Der Zensus ist hier ohne Alternative.

<!-- ERGÄNZEN: Ergebnis der laufenden Detailrecherche zu Mietspiegel Nürnberg /
Erlangen / Landkreis ERH sowie zur bayerischen Mieterschutzverordnung
(Mietpreisbremse, Kappungsgrenze) — welche Gemeinden erfasst sind und bis wann
die Verordnung gilt. -->

Für den Nutzer wichtiger als der Mietspiegel ist ohnehin die Frage, ob seine
Gemeinden unter die bayerische Verordnung zu angespannten Wohnungsmärkten
fallen: davon hängen Kappungsgrenze (15 % statt 20 %) und Mietpreisbremse ab.
Nürnberg als Großstadt und die Umlandgemeinden im Erlanger Speckgürtel sind
dafür Kandidaten — **das ist zu prüfen, bevor die Oberfläche eine Aussage dazu
trifft.**

---

## 4. Der Rechenweg

### 4.1 Koordinate → Gitterzelle

Der Zensus liegt in **EPSG:3035** (ETRS89-LAEA Europe, Lambert azimutal
flächentreu, GRS80). Die Umrechnung von WGS84 ist im Modul von Hand
implementiert — das Projekt hat bewusst keine externen Bibliotheken, und
`pyproj` wäre für zwei Formeln unverhältnismäßig.

Formeln nach Snyder, *Map Projections — A Working Manual* (USGS Professional
Paper 1395), Kapitel 24, in der Fassung der EPSG-Methode 9820.

**Geprüft gegen das amtliche Rechenbeispiel** der IOGP Geomatics Guidance Note
7-2: 50° N / 5° O ergibt E 3.962.799,45 m / N 2.999.718,85 m. Die
Implementierung trifft das auf **unter einen Millimeter**.
<https://www.iogp.org/wp-content/uploads/2019/09/373-07-02.pdf> ·
<https://epsg.io/9820-method>

Die Zellkennung entspricht der INSPIRE-Systematik des Zensus: sie benennt die
**linke untere Ecke**, z. B. `CRS3035RES1000mN2943000E4409000` für Eschenau.

Die **Geokodierung (Adresse → Koordinate) gehört nicht in dieses Modul.** Sie
braucht einen Netzdienst, und zur Laufzeit soll nichts nachgeladen werden. Wer
die Oberfläche baut, liefert Breite und Länge.

### 4.2 Nachbarschaft, und wann eine Aussage trägt

Eine einzelne Zelle reicht nicht. Beispiel Unterschöllenbach: die Zelle des
Objekts weist **2,75 €/m² aus sechs Wohnungen** aus. Bei so wenigen Wohnungen
schlägt sowohl ein einzelnes günstiges Haus als auch das Rauschen des
Geheimhaltungsverfahrens voll durch.

Deshalb wird die Umgebung ausgeweitet, bis sie trägt:

- Mindestens **500 vermietete Wohnungen** und mindestens **5 belegte Zellen**.
- Der Radius wächst von 1 km an, bis das erreicht ist, höchstens auf **10 km**.
- Wird die Schwelle auch dann nicht erreicht, wird **nichts gerechnet**:
  `tragfaehig: False` mit Begründung. Lieber „weiß ich nicht" als eine Zahl,
  auf die sich niemand stützen kann.

In der Praxis genügt in Nürnberg ein Radius von 1 km (9 Zellen, 47.903
Wohnungen), in Eckental werden 1–2 km gebraucht.

### 4.3 Gewichtete Quartile

Median und Quartile werden **mit der Zahl der vermieteten Wohnungen
gewichtet**. Das ist der entscheidende Kunstgriff: ungewichtet wäre der Median
der Median der *Zellen* — und auf dem Land sind das lauter kaum besiedelte
Zellen mit verrauschten Extremwerten. Gewichtet ist es der Median der
*Wohnungen*, also das, was eine typische Mietwohnung dieser Gegend kostet.

Die Spanne ist das **untere bis obere Quartil (25 % bis 75 %)** — das mittlere
Feld. Die zurückgegebenen Werte sind echte beobachtete Zellmittelwerte, keine
interpolierten Kunstwerte.

### 4.4 Fortschreibung auf heute

Der Zensus bildet den 15.05.2022 ab. Ohne Fortschreibung wäre jeder
Orientierungswert im Jahr 2026 systematisch zu niedrig.

Fortgeschrieben wird mit dem Verbraucherpreisindex, Teilindex **„Tatsächliche
Nettokaltmiete"** (COICOP 04.1.1, Wägungsanteil 68,30 ‰, Basis 2020 = 100).

Die Wahl des Teilindex ist nicht beliebig. Destatis führt drei ähnlich
benannte Reihen:

| Reihe | Inhalt | passend? |
|---|---|---|
| **Tatsächliche Nettokaltmiete** (CC13-0411) | nur tatsächlich gezahlte Mieten | **ja** — genau das misst der Zensus |
| Tatsächliche Wohnungsmiete (CC13-041) | zusätzlich Garagen, Stellplätze, Zweitwohnungen | nein |
| Nettokaltmiete, Sondergliederung (CC13-73) | zusätzlich die *unterstellte* Miete von Selbstnutzern | nein |

Hinterlegte Jahresdurchschnitte (2020 = 100), GENESIS-Online Tabelle
61111-0003:

| Jahr | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| Index | 100,0 | 101,4 | 103,2 | 105,4 | 107,7 | 110,0 |

<https://genesis.destatis.de/datenbank/online/statistic/61111/table/61111-0003>

Gegengeprüft an den Pressemitteilungen des Statistischen Bundesamtes, die
Indexstand und Veränderungsrate nennen:

- Jahresdurchschnitt 2024 = 107,7 (+2,2 %) — PM Nr. 020 vom 16.01.2025
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/01/PD25_020_611.html>
- Jahresdurchschnitt 2025 = 110,0 (+2,1 %) — PM Nr. 019 vom 16.01.2026
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/01/PD26_019_611.html>
- Juni 2026 = 112,4 (+2,2 % zum Vorjahresmonat) — PM Nr. 243 vom Juli 2026
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/07/PD26_243_611.html>

**Rechenmodell.** Ein Jahresdurchschnitt gilt als Wert der Jahresmitte,
dazwischen wird linear interpoliert. Über das Ende der Reihe hinaus wird mit
der zuletzt beobachteten Jahresrate (derzeit +2,2 %) hochgerechnet und das
Ergebnis als **geschätzt** gekennzeichnet.

Zwei unabhängige Proben belegen, dass das Modell trägt — beide sind als Test
fixiert:

- Für **Mai 2022** liefert die Interpolation 103,0 — genau den veröffentlichten
  Monatswert (GENESIS 61111-0004).
- Für **Juni 2026** liefert die Hochrechnung 112,4 — genau den veröffentlichten
  Monatswert.

Der Faktor vom Stichtag auf den 21.07.2026 beträgt damit **1,0931**, also rund
+9,3 %.

**Pflege.** Neue Jahre werden einfach in `MIETINDEX` ergänzt und
`MIETINDEX_FORTSCHREIBUNG` auf die jüngste Jahresrate gesetzt. Die Rechnung
zieht sie von selbst heran; Tests wachen darüber, dass die Reihe lückenlos und
monoton bleibt.

### 4.5 Einordnung

- Miete unter dem unteren Quartil → **zu niedrig**
- Miete innerhalb der Spanne (Grenzen eingeschlossen) → **fair**
- Miete über dem oberen Quartil → **zu hoch**

Ein Test prüft über ein feines Raster, dass die Einordnung immer zur Spanne
passt (`test_einordnung_passt_immer_zur_spanne`).

### 4.6 Herkunft

Jede Rückgabe liefert die Herkunft mit: Quelle, Lizenz, Stichtag, Zellkennung,
Radius, Zahl der Zellen und Wohnungen, Zahl der unsicheren Zellen. Dazu eine
grobe **Güte** — `gut`, `mittel` oder `grob` —, die Radius, Datenmenge und
Anteil unsicherer Zellen zusammenfasst.

Ein Wert ohne Herkunft ist in dieser App wertlos.

---

## 5. Grenzen der Aussage

Ehrlich benannt, damit die Oberfläche sie nicht verschweigt:

1. **Es ist eine Spanne zwischen Nachbarschaften, nicht zwischen Wohnungen.**
   Der Zensus liefert je Zelle nur einen Mittelwert. Die tatsächliche Streuung
   zwischen einzelnen Wohnungen ist **größer** als die hier gezeigte Spanne.
   Eine Miete knapp außerhalb der Spanne ist deshalb noch kein Beleg für
   „falsch".
2. **Keine Ausstattung, kein Baujahr, keine Wohnungsgröße.** Ein sanierter
   Neubau und ein unrenovierter Altbau derselben Straße bekommen denselben
   Orientierungswert. Ein echter Mietspiegel unterscheidet hier; wir können es
   nicht.
3. **Der Stichtag liegt vier Jahre zurück.** Die Fortschreibung über den
   Preisindex ist ein bundesweiter Durchschnitt. Örtliche Sonderentwicklungen —
   ein neues Baugebiet, ein abgewanderter Arbeitgeber — bildet sie nicht ab.
4. **Bestandsmieten, nicht Angebotsmieten.** Siehe Abschnitt 2.
5. **Bewusstes Rauschen.** Die Zensuswerte sind zur Geheimhaltung stochastisch
   überlagert. Bei kleinen Zellen ist der Einzelwert entsprechend unscharf; die
   Gewichtung dämpft das, hebt es aber nicht auf.
6. **Kein Begründungsmittel nach § 558a Abs. 2 BGB.** Siehe Abschnitt 1.

---

## 6. Empfehlung für die Beschriftung in der Oberfläche

**Überschrift:** „Orientierungswert Kaltmiete"
**Unterzeile:** „Was in dieser Lage üblicherweise gezahlt wird"

**Darstellung:** Ein Band von `unten` bis `oben` mit einer Marke für `mitte`
und einer deutlich abgesetzten Marke für die tatsächliche Miete des Nutzers.
Die Einordnung als kurzes Wort daneben — „in der Spanne", „unter der Spanne",
„über der Spanne" —, nicht als Ampel. Eine rote Ampel bei einer Miete, die
lediglich 20 Cent über dem oberen Quartil liegt, wäre eine Behauptung, die die
Daten nicht hergeben.

**Immer sichtbar, nicht in einem Aufklapper versteckt:**

- Quellenvermerk (`mietvergleich.quellenvermerk()`) — die Datenlizenz verlangt
  ihn „sichtbar und in optischem Zusammenhang".
- Stichtag und Hinweis auf die Fortschreibung.
- Radius und Zahl der ausgewerteten Wohnungen — das macht die Güte greifbar.

**Wortwahl, die vermieden werden muss:**

| nicht | sondern |
|---|---|
| ortsübliche Vergleichsmiete | Orientierungswert |
| Mietspiegel | Zensus-Auswertung |
| „Sie dürfen erhöhen auf …" | „Zur Einordnung: in dieser Lage werden üblicherweise … gezahlt" |
| „zu teuer" / „zu billig" | „über der Spanne" / „unter der Spanne" |

**Bei `tragfaehig: False`** wird keine Zahl gezeigt, sondern der Grund. Eine
leere Fläche mit „—" wäre schlechter als ein Satz, der erklärt, warum es hier
keine Aussage gibt.

**Der Hinweis auf die Rechtslage gehört dazu**, kurz und einmal: dass dieser
Wert eine Orientierung ist und eine Mieterhöhung nach § 558a Abs. 2 BGB einen
Mietspiegel, ein Gutachten, eine Mietdatenbank oder drei Vergleichswohnungen
braucht.

---

## 7. Datengrundlage erneuern

Die Datei `api/app/daten/zensus2022_nettokaltmiete_1km.csv.gz` (452 KB) ist eine
verlustfreie Umpackung der 7,9-MB-CSV aus dem Zensus-ZIP. **Die Werte selbst
sind unverändert** — geändert wurde nur die Speicherform: die aus den
Koordinaten ableitbare Gitter-ID entfällt, Koordinaten stehen in Kilometern
statt Metern, die Miete in Cent statt Euro, und die Zellen einer Ost-West-Reihe
sind delta-kodiert. Der Aufbau ist im Kopf der Datei selbst beschrieben, samt
Quellenvermerk und dem von der Lizenz geforderten Veränderungshinweis.

Diese Wahl war bewusst: Eine Rundung der Mietwerte hätte weitere 90 KB
gespart, wäre aber eine inhaltliche Veränderung der amtlichen Daten gewesen.
452 KB im Repo sind das nicht wert.

Der Ablageort ist `api/app/daten/` und nicht `api/data/`: `data/` steht in der
`.gitignore` (Schutz der echten Nutzerdaten), und das Dockerfile kopiert nur
`api/app` in das Abbild. Unter `api/app/daten/` ist die Datei sowohl im Repo
als auch im Container.

Wenn ein neuer Zensus erscheint: ZIP herunterladen, die 1-km-CSV in dasselbe
Format bringen, `STICHTAG` im Modul setzen und die Zellzahlen in den Tests
nachziehen (`test_gitter_hat_die_erwartete_groesse`,
`test_summe_der_wohnungen_stimmt_mit_der_quelle`,
`test_unsichere_zellen_sind_erhalten`) — diese Tests sind Wächter gegen einen
stillen Datenverlust beim Umpacken.

---

## 8. Beispielrechnung

Eschenau (Eckental), 49,5983° N / 11,2225° O, Zelle
`CRS3035RES1000mN2943000E4409000`, Stichtag der Anfrage 21.07.2026:

| | unteres Quartil | Median | oberes Quartil |
|---|---|---|---|
| Zensus, 15.05.2022 | 6,26 €/m² | 7,25 €/m² | 7,53 €/m² |
| fortgeschrieben (× 1,0931) | **6,84 €/m²** | **7,92 €/m²** | **8,23 €/m²** |

Herkunft: Radius 1 km, 8 Zellen, 655 vermietete Wohnungen, 0 davon unsicher,
Güte `mittel`.

Eine 72-m²-Wohnung dort für 520 € kalt entspricht 7,22 €/m² — **in der Spanne**,
8,8 % unter der Mitte, mit rechnerisch 72,72 € Luft bis zum oberen Quartil.
Dieselbe Wohnung für 900 € kalt entspricht 12,50 €/m² und liegt **über der
Spanne** (+57,8 % zur Mitte).

Zum Vergleich Nürnberg Mitte: 9,53 / 9,78 / 10,19 €/m², Radius 1 km, 9 Zellen,
47.903 Wohnungen, Güte `gut`.

---

## 9. Quellen

**Datengrundlage**
- Zensus 2022, Gitterdaten (Übersicht):
  <https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Bevoelkerung/Zensus2022/_publikationen.html>
- Tabelle „Durchschnittliche Nettokaltmiete und Anzahl der Wohnungen":
  <https://www.destatis.de/static/DE/zensus/gitterdaten/Durchschnittliche_Nettokaltmiete_und_Anzahl_der_Wohnungen.zip>
- Datenlizenz Deutschland – Namensnennung – 2.0: <http://www.govdata.de/dl-de/by-2-0>

**Fortschreibung**
- GENESIS-Online 61111-0003 (Jahre, COICOP):
  <https://genesis.destatis.de/datenbank/online/statistic/61111/table/61111-0003>
- GENESIS-Online 61111-0004 (Monate, COICOP):
  <https://genesis.destatis.de/datenbank/online/statistic/61111/table/61111-0004>
- PM Nr. 020 vom 16.01.2025:
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/01/PD25_020_611.html>
- PM Nr. 019 vom 16.01.2026:
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/01/PD26_019_611.html>
- PM Nr. 243 vom Juli 2026:
  <https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/07/PD26_243_611.html>

**Projektion**
- IOGP Geomatics Guidance Note 7-2: <https://www.iogp.org/wp-content/uploads/2019/09/373-07-02.pdf>
- EPSG-Methode 9820: <https://epsg.io/9820-method>

**Recht**
- § 558 BGB: <https://www.gesetze-im-internet.de/bgb/__558.html>
- § 558a BGB: <https://www.gesetze-im-internet.de/bgb/__558a.html>
- § 556d BGB: <https://www.gesetze-im-internet.de/bgb/__556d.html>
- OLG Stuttgart, Urteil vom 14.07.2010, Az. 4 U 24/10:
  <https://www.strunz-alter.de/aktuelle-informationen/auch-ein-kommunaler-qualifizierter-mietspiegel-ist-urheberrechtlich-geschuetzt/>

---

## Nachtrag 21.07.2026: Was für die Objekte des Nutzers konkret gilt

Diese Punkte betreffen nicht nur den (zurückgestellten) Mietvergleich, sondern
jede geplante Mieterhöhung — sie gehören deshalb in die App, auch wenn das
Vergleichsmodul liegen bleibt.

### Eckental ist seit 01.01.2026 Gebiet mit angespanntem Wohnungsmarkt

Bayerische **Mieterschutzverordnung (MiSchuV) vom 16.12.2025**, GVBl. S. 718,
BayRS 400-6-J, gültig 01.01.2026 bis 31.12.2029. Die Anlage listet 285
Gemeinden, darunter **Nürnberg** (Nr. 5.1.3) und **Eckental** (Nr. 5.3.5).
Eckental ist neu dabei — in der Vorgängerverordnung von 2019 war im Landkreis
Erlangen-Höchstadt nur Uttenreuth gelistet.

Damit gilt für Eschenau, Eckenhaid und Unterschöllenbach als Ortsteile:

- **Kappungsgrenze 15 % statt 20 %** in drei Jahren (§ 558 Abs. 3 Satz 2 BGB)
- **Mietpreisbremse**: bei Neuvermietung höchstens 110 % der ortsüblichen
  Vergleichsmiete (§ 556d BGB)
- Kündigungssperrfrist zehn Jahre (§ 577a Abs. 2 BGB)

**Falle beim Abgleich:** In der rechtsverbindlichen Anlage steht die Gemeinde
als „Eckenthal" (mit „th"), in der Begründung korrekt „Eckental". Ein
Namensvergleich läuft ins Leere — sauber ist der **AGS 09572121**.

- <https://www.justiz.bayern.de/media/pdf/gesetze/mieterschutzverordnung_vom_16._dezember_2025.pdf>
- <https://www.gesetze-bayern.de/Content/Document/BayMiSchuV2025>
- <https://www.verkuendung-bayern.de/files/baymbl/2025/558/baymbl-2025-558.pdf> (Begründung, Indikatoren)

### Mietpreisbremse bundesweit bis 31.12.2029 verlängert

Gesetz vom 17.07.2025, **BGBl. 2025 I Nr. 163**, in Kraft seit 23.07.2025:
In § 556d Abs. 2 Satz 4 BGB wurde „2025" durch „2029" ersetzt, die Befristung
auf jeweils fünf Jahre gestrichen. Das BVerfG hat eine Verfassungsbeschwerde
dagegen am 08.01.2026 (1 BvR 183/25) nicht zur Entscheidung angenommen.

- <https://www.recht.bund.de/bgbl/1/2025/163/VO.html>

### Für Eckental gibt es keinen Mietspiegel — und für Nürnberg keinen offenen

- **Nürnberg**: qualifizierter Mietenspiegel 2024 nach § 558d BGB, aber nur als
  PDF und mit ausdrücklicher Sperrklausel („Nachdruck — auch auszugsweise — nur
  mit schriftlicher Erlaubnis … Nicht zur Weitergabe bestimmt!"). Die Tabellen
  dürfen also **nicht** ins Repo.
- **Erlangen**: qualifizierter Mietspiegel 2025–2027, ebenfalls nur PDF plus
  Formular-Rechner, trotz des Pfads „open-data".
- **Eckental**: kein amtlicher Mietspiegel — die Pflicht nach § 558c Abs. 4 BGB
  gilt erst ab 50 000 Einwohnern. Die Zahlen kommerzieller Portale sind kein
  Begründungsmittel nach § 558a Abs. 2 BGB.
- GovData-Abfrage: bundesweit 41 Mietspiegel-Datensätze, für Nürnberg und
  Erlangen **null**.

### Angebotsmieten liegen systematisch über Bestandsmieten

Sachverständigenrat, Jahresgutachten 2024/25, Kapitel 4 Ziffer 325, gegen die
Rohdaten nachgerechnet: Bestandsmieten seit 2010 +1,44 % im Jahr,
Angebotsmieten +3,99 % — der Indexabstand ist bis 2023 auf 37,9 % aufgelaufen.
Im Niveau (Mikrozensus 2018, Nettokaltmiete je m²): Kleinstadt/Landgemeinde
5,66 € Bestand gegen 6,43 € Neuvermietung (+13,5 %).

Vorbehalt: Angebotsmiete (Inserat) ist nicht gleich Neumiete (tatsächlich
vereinbart) — laut BBSR liegen GdW-Wiedervermietungsmieten rund 24 % unter
reinen Internet-Angebotsmieten. Ein Vergleich mit Inseraten überzeichnet also.

- <https://www.sachverstaendigenrat-wirtschaft.de/fileadmin/dateiablage/gutachten/jg202425/JG202425_Kapitel_4.pdf>
