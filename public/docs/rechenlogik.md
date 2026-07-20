# Fachkonzept: Rechenlogik & Verteilerschlüssel

Grundlage: die zwei realen Objekte *Musterstraße 5* (komplex, eigene Zähler) und
*Beispielweg 6a* (einfach, externe Abrechnung).

---

## Teil A — Rechenlogik einer Abrechnung

Jede Abrechnung läuft in vier Schritten. Der einzige Unterschied zwischen einem
einfachen und einem komplexen Objekt liegt in **Schritt 2**.

### Schritt 1 — Zeitraum festlegen
Start- und Enddatum frei wählen. Regulär, Rumpf- oder Zwischenabrechnung. Das
Enddatum ist der **Soll-Stichtag**, auf den alle Zähler bezogen werden.

### Schritt 2 — Betrag je Position bestimmen (nach Wertquelle)

**a) Wertquelle „Scan" / „extern" (Normalfall Objekt 2):**
Der Betrag steht auf der Rechnung bzw. der externen Abrechnung (z. B. delta-t).
Er wird übernommen, geprüft, fertig. Keine Berechnung nötig.
Beispiel Objekt 2, 2024: Heizkosten 925,13 € (aus delta-t), Müll 152,14 €,
Versicherung 406,93 € usw. → alle Positionen einfach aufsummiert.

**b) Wertquelle „Zähler" (Objekt 1):**
Hier steckt die eigentliche Arbeit. Zweistufig:

*b1) Interpolation der Ablesung auf den Soll-Stichtag.*
Die Ablesung passiert selten exakt am Stichtag. Beispiel Gesamtwasser 2024:

- abgelesen am 11.10.2024, Stand 781
- Vorjahresstand (30.09.2023): 634,1256
- Ist-Differenz = 146,874 über **376 Tage**
- gebraucht wird die Differenz über **365 Tage** (bis 30.09.2024)

```
interpolierter Verbrauch = Ist-Differenz × (Soll-Tage / Ist-Tage)
                         = 146,874 × 365 / 376
                         = 142,577
```

*b2) Berechnete (virtuelle) Zähler.*
Nicht alles ist gemessen. Die WG hat keinen eigenen Wasserzähler, ihr Verbrauch
ist der **Rest**:

```
WG-Verbrauch = Gesamtverbrauch − Summe aller gemessenen Unterzähler
             = 142,577 − (4,14 + 29,83 + 8,79 + 5,68 + 15,00)
             = 79,14
```

**c) Wertquelle „manuell":**
Freie Position, z. B. Gutschrift „Support Heizungsdefekt" (Objekt 2, 2021).

### Schritt 3 — Position auf die Parteien verteilen
Jede Position trägt einen Verteilerschlüssel (siehe Teil B). Beispiel: die
Wasserkosten 847,52 € werden über den Verbrauch verteilt.

Rate = Gesamtkosten / Gesamtverbrauch = 847,52 / 142,577 = **5,944 €/Einheit**

| Partei                 | Verbrauch | Anteil (€) |
|------------------------|-----------|-----------:|
| Büro                   | 4,14      | 24,61      |
| Partei OG (Bad)   | 29,83     | 177,33     |
| Partei OG (WM)    | 8,79      | 52,22      |
| Partei OG (WW)    | 5,68      | 33,79      |
| Garten (P1, fix)    | 15,00     | 89,16      |
| WG (berechnet, Rest)   | 79,14     | 470,41     |
| **Summe**              | **142,58**| **847,52** |

### Schritt 4 — Ergebnis je Partei
Alle Anteile einer Partei aus allen Positionen aufsummieren, Vorauszahlungen
gegenrechnen:

```
Saldo = umgelegte Kosten − Vorauszahlungen
```

Beispiel Objekt 2, 2024:
Kosten 3.121,33 € − Vorauszahlungen (12 × 220 =) 2.640 € = **−481,33 €**
→ Nachzahlung 481,33 €. Zusätzlich wird die **§35a-Summe** (haushaltsnahe
Dienstleistungen) separat ausgewiesen.

---

## Teil B — Verteilerschlüssel im Detail

Für jede Position wird genau ein Schlüssel gewählt. Die Formeln:

**1. Nach Wohnfläche**
`Anteil = Kosten × (Fläche der Einheit / Gesamtfläche)`

**2. Nach Personen**
`Anteil = Kosten × (Personen der Partei / Gesamtpersonen)`

**3. Nach Bewohnermonaten** *(deckt Ein-/Auszug und Rumpfzeiträume ab)*
`Bewohnermonate = Personen × anwesende Monate im Zeitraum`
`Anteil = Kosten × (Bewohnermonate der Partei / Summe aller Bewohnermonate)`
Beispiel Objekt 1: WG = 12 von 36 Bewohnermonaten → 1/3 der Umlagekosten.

**4. Nach Einheiten**
`Anteil = Kosten / Anzahl Einheiten`

**5. Nach Verbrauch** *(mit Interpolation + berechneten Zählern, siehe Teil A)*
`Rate = Kosten / Gesamtverbrauch`
`Anteil = Partei-Verbrauch × Rate`

**6. Fester Prozent-Split**
`Anteil = Kosten × Prozentsatz` (z. B. 2. OG 50 %, Büroanteil anteilig)

**7. Individuell / Direktzuordnung**
Ganze Position genau einer Partei zugeordnet (z. B. Gartenwasser).

**8. Heizkosten (Heizkostenverordnung)**
Aufteilung in Grund- und Verbrauchsanteil (typ. 30/70 oder 50/50):
Grundanteil nach Fläche, Verbrauchsanteil nach Wärmezählern.
Bei Objekt 2 kommt dieser Split fertig von delta-t — dann nur Betrag übernehmen.

### Zeitanteiligkeit (querliegend über alle Schlüssel)
Deckt die Nutzungszeit einer Partei nicht den ganzen Zeitraum ab, wird ihr
Anteil taggenau gekürzt:
`Faktor = Nutzungstage der Partei / Tage im Abrechnungszeitraum`

---

## Was die Datenstruktur dafür können muss (Zusammenfassung)
- Position kennt ihre **Wertquelle** (Scan / Zähler / extern / manuell)
- Zähler kennt Typ **gemessen vs. berechnet**
- Ablesung speichert **Ist-Datum, Soll-Stichtag, Ist-Stand, interpolierten Stand**
- Verteilerschlüssel als eigenes Objekt mit **Typ + Parameter**
- Partei kennt **Nutzungszeitraum** für Zeitanteiligkeit und Bewohnermonate
- Position trägt Flags **umlagefähig, §35a, Status (final/vorläufig)**
