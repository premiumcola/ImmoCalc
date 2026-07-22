/* Immobilien-Lexikon — Wissensbasis aus Eigentümersicht.
 *
 * Reine Daten, kein Verhalten. Zwei Exporte:
 *
 *   BEGRIFFE  — die Lexikon-Einträge. Jeder erklärt einen Fachbegriff einfach,
 *               aber fachlich korrekt, aus der Sicht des Eigentümers.
 *   ABLAUF    — die Schritte eines Immobilienerwerbs mit Bauphase, für den
 *               anklickbaren Ablaufplan. Jeder Schritt verweist über `begriffe`
 *               auf die Lexikon-Einträge, die dort wichtig werden.
 *
 * Eintrags-Schema (BEGRIFFE):
 *   id        kebab-case, stabil — das Fragment für Deeplinks (lexikon.html#id)
 *             und der Anker der ?-Hilfe-Icons an den Eingabemasken.
 *   begriff   die Überschrift, ausgeschrieben.
 *   kategorie Schlüssel aus KATEGORIEN.
 *   synonyme  weitere Schreibweisen/Wörter, über die die Suche den Eintrag
 *             ebenfalls findet (Array, darf leer sein).
 *   kurz      ein bis zwei Sätze. Das ist der Text im ?-Icon-Popover an der
 *             Eingabemaske — muss für sich allein verständlich sein.
 *   lang      der volle Artikel. Absätze mit Leerzeile getrennt (\n\n). Immer
 *             in dieser Reihenfolge: WAS es ist · WARUM es das gibt · WAS der
 *             Eigentümer wissen sollte. Verwandte Begriffe im Text in eckigen
 *             Klammern als [[id]] markieren — die Seite macht daraus einen Link.
 *   verwandt  Ids verwandter Begriffe (Array) — die „siehe auch"-Verweise.
 *
 * Schritt-Schema (ABLAUF):
 *   id, phase (fortlaufende Nummer), titel, kurz (was in diesem Schritt
 *   passiert und was der Eigentümer tut), dauer (grobe Zeitangabe),
 *   begriffe (Ids der hier relevanten Lexikon-Einträge).
 */

export const KATEGORIEN = [
  { id: 'finanzierung', name: 'Finanzierung & Kredit' },
  { id: 'grundbuch', name: 'Kauf, Grundbuch & Bau' },
  { id: 'steuer', name: 'Steuer' },
  { id: 'nebenkosten', name: 'Nebenkosten & WEG' },
  { id: 'miete', name: 'Vermietung' },
  { id: 'wert', name: 'Wert & Rendite' },
];

export const BEGRIFFE = [
  // ---------------------------------------------------------------- Finanzierung
  {
    id: 'grundschuld',
    begriff: 'Grundschuld',
    kategorie: 'finanzierung',
    synonyme: ['Grundpfandrecht', 'Grundschulden'],
    kurz: 'Das Pfandrecht, mit dem die Bank deinen Kredit im Grundbuch absichert. Zahlst du nicht, darf sie die Immobilie verwerten.',
    lang:
      'Eine Grundschuld ist ein Pfandrecht an deiner Immobilie, eingetragen in Abteilung III des [[grundbuch]]s. Sie sichert der Bank einen bestimmten Geldbetrag zu: Kommst du mit dem Kredit dauerhaft in Verzug, darf sie aus der Grundschuld die Zwangsversteigerung betreiben und sich aus dem Erlös bedienen.\n\n' +
      'Es gibt sie, weil eine Bank einen sechsstelligen Kredit nicht allein auf dein Versprechen hin vergibt — sie braucht eine dingliche Sicherheit, die am Objekt klebt und auch einen Eigentümerwechsel überdauert. Anders als die frühere [[hypothek]] ist die Grundschuld nicht an eine bestimmte Forderung gebunden: Ist der Kredit getilgt, bleibt sie bestehen und kann für ein neues Darlehen wiederverwendet werden.\n\n' +
      'Wichtig für dich als Eigentümer: Der [[rang]] entscheidet, wer bei einer Verwertung zuerst bedient wird — die erstrangige Grundschuld ist am meisten wert. Eine Grundschuld kann mehrere Kredite sichern und sogar ein Kredit für ein *anderes* Objekt (Cross-Collateral). Ist der Kredit abbezahlt, gibt die Bank eine Löschungsbewilligung — löschen lassen kostet Notar- und Grundbuchgebühren; viele lassen sie stattdessen für spätere Finanzierungen stehen.',
    verwandt: ['rang', 'brief-buchgrundschuld', 'hypothek', 'grundbuch', 'restschuld'],
  },
  {
    id: 'rang',
    begriff: 'Rang im Grundbuch',
    kategorie: 'finanzierung',
    synonyme: ['Rangfolge', 'erstrangig', 'nachrangig'],
    kurz: 'Die Reihenfolge, in der eingetragene Rechte bei einer Verwertung bedient werden. Rang I zuerst, dann Rang II usw.',
    lang:
      'Der Rang legt fest, in welcher Reihenfolge die in Abteilung III eingetragenen Grundpfandrechte aus dem Versteigerungserlös bedient werden. Die erstrangige [[grundschuld]] wird voll bedient, bevor die zweitrangige überhaupt etwas bekommt.\n\n' +
      'Das gibt es, damit mehrere Gläubiger dasselbe Objekt besichern können, ohne sich zu blockieren — jeder weiß, wo er steht. Reicht der Erlös nicht für alle, fällt der Nachrang teilweise oder ganz aus.\n\n' +
      'Für dich heißt das: Ein erstrangiges Darlehen bekommst du günstiger, weil die Bank das kleinste Ausfallrisiko trägt. Ein nachrangiges (z. B. ein zweiter Kredit für eine Renovierung) ist teurer. Beim Umschulden achtet die neue Bank darauf, in den ersten Rang zu kommen.',
    verwandt: ['grundschuld', 'beleihung'],
  },
  {
    id: 'brief-buchgrundschuld',
    begriff: 'Brief- und Buchgrundschuld',
    kategorie: 'finanzierung',
    synonyme: ['Briefgrundschuld', 'Buchgrundschuld', 'Grundschuldbrief'],
    kurz: 'Zwei Formen der Grundschuld: Bei der Buchgrundschuld steht alles im Grundbuch, bei der Briefgrundschuld gibt es zusätzlich ein übertragbares Papier (den Brief).',
    lang:
      'Eine [[grundschuld]] kann als Buch- oder als Briefgrundschuld bestellt werden. Bei der Buchgrundschuld ist allein die Eintragung im Grundbuch maßgeblich. Bei der Briefgrundschuld wird zusätzlich ein Grundschuldbrief ausgestellt — ein Wertpapier, mit dem sich die Grundschuld formlos, ohne erneuten Grundbucheintrag, an eine andere Bank übertragen lässt.\n\n' +
      'Der Brief existiert, weil er den Gläubigerwechsel vereinfacht — praktisch, wenn ein Kredit weiterverkauft wird. Dafür muss der Brief sicher verwahrt werden; geht er verloren, ist ein aufwendiges Aufgebotsverfahren nötig.\n\n' +
      'Für dich als Eigentümer ist die Buchgrundschuld heute der Normalfall: übersichtlich, kein Papier, das abhandenkommen kann. Die Briefform verursacht zusätzliche Kosten und wird meist nur auf Wunsch der Bank gewählt.',
    verwandt: ['grundschuld', 'rang'],
  },
  {
    id: 'hypothek',
    begriff: 'Hypothek',
    kategorie: 'finanzierung',
    synonyme: ['Hypotheken'],
    kurz: 'Ein älteres Grundpfandrecht, das fest an eine bestimmte Kreditforderung gekoppelt ist. Heute meist durch die flexiblere Grundschuld ersetzt.',
    lang:
      'Die Hypothek ist wie die [[grundschuld]] ein Pfandrecht am Grundstück, aber streng akzessorisch: Sie besteht nur, solange die besicherte Forderung besteht, und sinkt mit der [[restschuld]] automatisch.\n\n' +
      'Genau diese feste Kopplung war ihr Nachteil — jede Umschuldung oder Wiederverwendung erforderte Anpassungen im Grundbuch. Deshalb hat sich in der Praxis die frei verwendbare Grundschuld durchgesetzt.\n\n' +
      'Für dich vor allem historisch relevant: In Altverträgen oder umgangssprachlich („die Hypothek aufs Haus") taucht der Begriff noch auf, gemeint ist heute fast immer eine Grundschuld.',
    verwandt: ['grundschuld', 'restschuld'],
  },
  {
    id: 'zinsbindung',
    begriff: 'Zinsbindung (Sollzinsbindung)',
    kategorie: 'finanzierung',
    synonyme: ['Sollzinsbindung', 'Zinsfestschreibung', 'Zinsbindungsfrist'],
    kurz: 'Der Zeitraum, für den dein Sollzins fest vereinbart ist. Danach wird neu verhandelt (Anschlussfinanzierung).',
    lang:
      'Die Zinsbindung ist die Dauer, für die der Sollzins deines Darlehens unveränderlich festgeschrieben ist — üblich sind 5, 10, 15 oder 20 Jahre. Innerhalb dieser Frist bleibt deine [[annuitaet]] gleich, egal wie sich der Markt bewegt.\n\n' +
      'Sie gibt es, weil sie Planungssicherheit schafft: Beide Seiten wissen, womit sie rechnen. Je länger die Bindung, desto höher meist der Zins — du bezahlst die Sicherheit mit einem Aufschlag.\n\n' +
      'Wichtig: Nach Ablauf der Zinsbindung ist der Kredit selten getilgt. Für die verbleibende [[restschuld]] brauchst du eine [[anschlusszins|Anschlussfinanzierung]] zu dann gültigen Konditionen — das ist das zentrale Zinsrisiko. Nach 10 Jahren hast du übrigens ein gesetzliches Sonderkündigungsrecht (§ 489 BGB), auch bei längerer Bindung.',
    verwandt: ['anschlusszins', 'sollzins', 'annuitaet', 'restschuld'],
  },
  {
    id: 'anschlusszins',
    begriff: 'Anschlussfinanzierung & variabler Zins',
    kategorie: 'finanzierung',
    synonyme: ['Anschlussfinanzierung', 'Anschlusszins', 'Prolongation', 'Forward-Darlehen'],
    kurz: 'Die Finanzierung der Restschuld nach Ablauf der Zinsbindung — zu dann gültigen Zinsen. Läuft der Kredit variabel weiter, ändert sich der Zins laufend.',
    lang:
      'Wenn die [[zinsbindung]] endet, ist die [[restschuld]] fast nie null. Die Anschlussfinanzierung regelt, wie es weitergeht: Verlängerung bei derselben Bank (Prolongation), Wechsel zu einer anderen (Umschuldung) oder — falls nichts vereinbart wird — ein variabler Zins, der sich an einen Referenzzinssatz (z. B. Euribor) koppelt und sich laufend ändert.\n\n' +
      'Das gibt es, weil kein Zins auf Jahrzehnte im Voraus festgeschrieben werden kann. Der Anschluss ist der Moment, in dem sich das Marktzinsniveau auf deine Rate auswirkt — nach oben wie nach unten.\n\n' +
      'Für dich als Eigentümer: Der Anschluss ist der wichtigste Termin nach dem Kauf. Steigt das Zinsniveau, kann die Rate spürbar höher werden. Ein Forward-Darlehen sichert dir schon Jahre vorher einen Zins (gegen Aufschlag). ImmoCalc rechnet, wenn du einen variablen Anschlusszins hinterlegst, die [[restschuld]] ab dem Bindungsende mit diesem Satz weiter — sonst würde sie fälschlich mit dem alten Zins fortgeschrieben.',
    verwandt: ['zinsbindung', 'restschuld', 'sollzins', 'annuitaet'],
  },
  {
    id: 'sollzins',
    begriff: 'Sollzins & Effektivzins',
    kategorie: 'finanzierung',
    synonyme: ['Sollzinssatz', 'Effektivzins', 'Nominalzins'],
    kurz: 'Der Sollzins ist der reine Zins aufs Darlehen. Der Effektivzins rechnet weitere Kosten mit ein und macht Angebote vergleichbar.',
    lang:
      'Der Sollzins ist der Prozentsatz, mit dem dein Darlehen nominal verzinst wird — aus ihm ergibt sich der Zinsanteil deiner [[annuitaet]]. Der Effektivzins (effektiver Jahreszins) rechnet zusätzlich preisbestimmende Kosten ein, etwa ein [[disagio]] oder den Auszahlungszeitpunkt.\n\n' +
      'Den Effektivzins gibt es, damit du Angebote mit unterschiedlichen Nebenbedingungen auf einer Zahl vergleichen kannst — er ist gesetzlich vorgeschrieben.\n\n' +
      'Für dich: Für die Rate zählt der Sollzins, für den Angebotsvergleich der Effektivzins. Steht im Vertrag ein variabler Satz für die Zeit nach der [[zinsbindung]], gilt dieser erst ab dem Anschluss.',
    verwandt: ['zinsbindung', 'annuitaet', 'disagio', 'anschlusszins'],
  },
  {
    id: 'annuitaet',
    begriff: 'Annuität (Rate)',
    kategorie: 'finanzierung',
    synonyme: ['Annuitätendarlehen', 'Rate', 'Monatsrate'],
    kurz: 'Die gleichbleibende Kreditrate aus Zins und Tilgung. Weil die Restschuld sinkt, wird der Zinsanteil kleiner und der Tilgungsanteil größer.',
    lang:
      'Die Annuität ist deine gleichbleibende Kreditrate. Sie besteht aus zwei Teilen: dem Zins auf die aktuelle [[restschuld]] und der [[tilgung]], die die Schuld verringert. Weil die Restschuld mit jeder Rate sinkt, sinkt auch der Zinsanteil — und da die Rate konstant bleibt, wächst im Gegenzug der Tilgungsanteil. Genau das ist der Annuitäteneffekt.\n\n' +
      'Dieses Modell gibt es, weil eine feste Rate planbar ist: Du zahlst über die gesamte [[zinsbindung]] jeden Monat denselben Betrag.\n\n' +
      'Für dich wichtig ist die anfängliche Tilgung (z. B. 2 %): Sie bestimmt, wie schnell du entschuldest. 1 % Tilgung bei niedrigem Zins bedeutet eine sehr lange Laufzeit; 2–3 % sind meist sinnvoller. Der [[kapitaldienst]] ist die Summe deiner Annuitäten im Jahr.',
    verwandt: ['tilgung', 'sollzins', 'restschuld', 'kapitaldienst', 'sondertilgung'],
  },
  {
    id: 'tilgung',
    begriff: 'Tilgung',
    kategorie: 'finanzierung',
    synonyme: ['Anfangstilgung', 'Tilgungssatz'],
    kurz: 'Der Teil der Rate, der die Schuld verringert (nicht der Zins). Höhere Tilgung = schneller schuldenfrei.',
    lang:
      'Die Tilgung ist der Anteil deiner [[annuitaet]], der tatsächlich die [[restschuld]] verringert — im Gegensatz zum Zins, der nur die Kosten des geliehenen Geldes deckt. Der anfängliche Tilgungssatz (z. B. 2 % p. a. der Darlehenssumme) legt fest, wie hoch dieser Anteil zu Beginn ist.\n\n' +
      'Sie ist der eigentliche Vermögensaufbau: Jeder getilgte Euro gehört dir, nicht mehr der Bank.\n\n' +
      'Für dich: Bei niedrigen Zinsen solltest du die Tilgung höher ansetzen, sonst tilgst du kaum. Faustregel — Zins + Tilgung sollten in Summe eine vernünftige Laufzeit ergeben. Zusätzliche außerplanmäßige Zahlungen sind über die [[sondertilgung]] möglich.',
    verwandt: ['annuitaet', 'restschuld', 'sondertilgung'],
  },
  {
    id: 'sondertilgung',
    begriff: 'Sondertilgung',
    kategorie: 'finanzierung',
    synonyme: ['Sondertilgungsrecht'],
    kurz: 'Eine zusätzliche, außerplanmäßige Rückzahlung neben der laufenden Rate — meist bis zu einem vereinbarten Betrag pro Jahr erlaubt.',
    lang:
      'Eine Sondertilgung ist eine freiwillige Zahlung zusätzlich zur normalen [[annuitaet]], die direkt die [[restschuld]] senkt. Im Kreditvertrag ist meist ein jährlicher Höchstbetrag vereinbart (z. B. bis 5 % der Darlehenssumme pro Kalenderjahr), oft nicht auf Folgejahre übertragbar.\n\n' +
      'Das Recht gibt es, weil ohne ausdrückliche Vereinbarung eine vorzeitige Rückzahlung während der [[zinsbindung]] gar nicht oder nur gegen Vorfälligkeitsentschädigung möglich wäre.\n\n' +
      'Für dich: Sondertilgungen sparen überproportional Zinsen, weil sie früh wirken. Ein vereinbartes Sondertilgungsrecht kostet manchmal einen kleinen Zinsaufschlag — es lohnt sich, wenn du absehbar Geld übrig hast (Bonus, Erbschaft). Nicht genutzte Rechte verfallen oft jahresweise.',
    verwandt: ['tilgung', 'annuitaet', 'restschuld'],
  },
  {
    id: 'restschuld',
    begriff: 'Restschuld',
    kategorie: 'finanzierung',
    synonyme: ['Restdarlehen', 'Restvaluta'],
    kurz: 'Der noch offene Kreditbetrag zu einem Stichtag. Die Bank weist ihn zum Jahresende aus.',
    lang:
      'Die Restschuld ist der Betrag, den du zu einem bestimmten Zeitpunkt noch schuldest. Sie sinkt mit jeder [[tilgung]] und jeder [[sondertilgung]]. Die Bank weist sie verlässlich zum 31.12. aus; zwischen zwei Ständen lässt sie sich aus Rate und Zins fortschreiben.\n\n' +
      'Sie ist die zentrale Kennzahl deiner Finanzierung: Objektwert minus Restschuld ergibt dein [[eigenkapital]] in der Immobilie.\n\n' +
      'Für dich besonders wichtig am Ende der [[zinsbindung]]: Die dann verbleibende Restschuld bestimmt, wie viel du über die [[anschlusszins|Anschlussfinanzierung]] neu finanzieren musst — und damit dein Zinsrisiko.',
    verwandt: ['tilgung', 'annuitaet', 'zinsbindung', 'eigenkapital', 'beleihung'],
  },
  {
    id: 'bereitstellungszins',
    begriff: 'Bereitstellungszinsen',
    kategorie: 'finanzierung',
    synonyme: ['Bereitstellungszins'],
    kurz: 'Zinsen auf den noch nicht abgerufenen Teil des Kredits — typisch in der Bauphase, wenn das Geld erst nach Baufortschritt fließt.',
    lang:
      'Bereitstellungszinsen zahlst du für den Teil des Darlehens, den die Bank für dich bereithält, den du aber noch nicht abgerufen hast. Sie fallen zusätzlich zum normalen Sollzins an, meist ab einigen Monaten nach Zusage.\n\n' +
      'Es gibt sie, weil die Bank das zugesagte Geld refinanzieren und vorhalten muss, auch wenn es noch auf deinem Konto fehlt — das kostet sie, unabhängig von deinem Abruf.\n\n' +
      'Für dich vor allem beim Neubau relevant: Der Kaufpreis fließt in Raten nach [[mabv|Baufortschritt]], das Darlehen wird also nach und nach abgerufen. Achte auf eine lange bereitstellungszinsfreie Zeit. Steuerlich sind sie als [[schuldzinsen|Werbungskosten]] absetzbar.',
    verwandt: ['mabv', 'schuldzinsen', 'sollzins'],
  },
  {
    id: 'disagio',
    begriff: 'Disagio (Auszahlungskurs)',
    kategorie: 'finanzierung',
    synonyme: ['Damnum', 'Auszahlungskurs', 'Abgeld'],
    kurz: 'Ein Abschlag bei der Auszahlung: Es wird weniger ausgezahlt, als du zurückzahlst. Im Gegenzug sinkt der laufende Sollzins.',
    lang:
      'Beim Disagio zahlt die Bank weniger aus, als im Vertrag als Darlehenssumme steht — bei 98 % Auszahlungskurs bekommst du von 100.000 € nur 98.000 €, schuldest aber 100.000 €. Der einbehaltene Teil ist vorweggenommener Zins.\n\n' +
      'Es gibt das Disagio, um den laufenden [[sollzins]] optisch zu senken und — früher vor allem — steuerliche Effekte zu nutzen: Das Disagio ist im Zahlungsjahr weitgehend als [[schuldzinsen|Werbungskosten]] absetzbar.\n\n' +
      'Für dich: Es ist keine Ersparnis, nur eine Umverteilung — vergleiche Angebote deshalb über den Effektiv-, nicht den Sollzins. In ImmoCalc bildest du es über den Auszahlungskurs ab, damit Darlehenssumme und tatsächlich geflossenes Geld auseinanderfallen dürfen.',
    verwandt: ['sollzins', 'schuldzinsen'],
  },
  {
    id: 'beleihung',
    begriff: 'Beleihung & Beleihungsauslauf',
    kategorie: 'finanzierung',
    synonyme: ['Beleihungsauslauf', 'Beleihungswert', 'Loan-to-Value', 'LTV'],
    kurz: 'Wie hoch die Immobilie im Verhältnis zu ihrem Wert belastet ist. Je niedriger, desto günstiger der Zins.',
    lang:
      'Der Beleihungsauslauf ist das Verhältnis aus Darlehen (bzw. [[restschuld]]) und dem Wert der Immobilie. 60 % Beleihung heißt: Die Schulden betragen 60 % des Werts, 40 % sind dein [[eigenkapital]] im Objekt.\n\n' +
      'Die Bank rechnet damit ihr Risiko: Je niedriger die Beleihung, desto sicherer ist ihr Geld im Fall einer Verwertung — und desto günstiger dein Zins. Oberhalb bestimmter Grenzen (oft 60 %, 80 %) steigen die Zinsen in Stufen.\n\n' +
      'Für dich: Mehr Eigenkapital senkt nicht nur die Summe, sondern über den Beleihungsauslauf auch den Zinssatz — ein doppelter Hebel. Der [[rang]] der [[grundschuld]] hängt eng damit zusammen.',
    verwandt: ['restschuld', 'eigenkapital', 'grundschuld', 'rang'],
  },
  {
    id: 'bausparvertrag',
    begriff: 'Bausparvertrag',
    kategorie: 'finanzierung',
    synonyme: ['Bausparen', 'Bausparer', 'Bausparsumme'],
    kurz: 'Erst sparst du an, dann hast du Anspruch auf ein zinsgesichertes Darlehen. Zwei Phasen in einem Vertrag.',
    lang:
      'Ein Bausparvertrag hat zwei Phasen. In der Ansparphase zahlst du Beiträge ein und bekommst einen (niedrigen) Guthabenzins, bis ein Teil der Bausparsumme angespart ist. Danach ist der Vertrag zuteilungsreif: Du kannst den Rest als Bauspardarlehen zu einem heute schon festgeschriebenen Zins abrufen.\n\n' +
      'Der Sinn liegt in der Zinssicherung: Du sicherst dir früh einen festen Darlehenszins für später — interessant, wenn du steigende Zinsen erwartest oder eine [[anschlusszins|Anschlussfinanzierung]] planbar machen willst.\n\n' +
      'Für dich beim Vermögen wichtig: In der Ansparphase ist die Rate keine Ausgabe, sondern Sparen — das Guthaben *erhöht* dein [[eigenkapital]]. ImmoCalc führt einen Bausparvertrag deshalb als Guthaben, nicht als Schuld.',
    verwandt: ['anschlusszins', 'eigenkapital', 'kapitaldienst'],
  },
  {
    id: 'kapitaldienst',
    begriff: 'Kapitaldienst',
    kategorie: 'finanzierung',
    synonyme: ['Kapitaldienstfähigkeit', 'Schuldendienst'],
    kurz: 'Die Summe aus Zins und Tilgung, die du im Jahr an die Bank zahlst.',
    lang:
      'Der Kapitaldienst ist alles, was im Jahr an die Bank geht: die Summe deiner [[annuitaet|Annuitäten]] aus Zins und [[tilgung]]. Bei mehreren Darlehen ist es die Summe über alle.\n\n' +
      'Die Kennzahl gibt es, weil die Bank vor der Zusage prüft, ob deine Einnahmen den Schuldendienst dauerhaft tragen (Kapitaldienstfähigkeit).\n\n' +
      'Für dich in der Auswertung: Beim Cashflow zählt der Kapitaldienst als Ausgabe — anders als die Sparrate eines [[bausparvertrag]]s, die Vermögensaufbau ist und den Cashflow nicht belasten sollte.',
    verwandt: ['annuitaet', 'tilgung', 'bausparvertrag', 'cashflow'],
  },
  // ----------------------------------------------------- Kauf, Grundbuch & Bau
  {
    id: 'grundbuch',
    begriff: 'Grundbuch',
    kategorie: 'grundbuch',
    synonyme: ['Grundbuchblatt', 'Grundbuchauszug', 'Abteilung I', 'Abteilung II', 'Abteilung III'],
    kurz: 'Das amtliche Register, das für jedes Grundstück festhält, wem es gehört und welche Rechte und Lasten darauf liegen. Erst die Eintragung macht dich zum Eigentümer.',
    lang:
      'Das Grundbuch ist ein öffentliches, vom Amtsgericht geführtes Register. Jedes Grundstück hat ein eigenes Blatt mit vier Teilen: das Bestandsverzeichnis (Lage, Flurstück, Gemarkung, Größe), Abteilung I (die Eigentümer), Abteilung II (Lasten und Beschränkungen — [[dienstbarkeit|Dienstbarkeiten]], [[niessbrauch]], [[auflassung|Vormerkungen]], Wohnrechte) und Abteilung III (die Grundpfandrechte, also [[grundschuld]] und [[hypothek]]).\n\n' +
      'Es gibt das Grundbuch, damit an Immobilien Rechtssicherheit herrscht: Wer eingetragen ist, gilt als Eigentümer, und ein gutgläubiger Käufer darf sich auf den Inhalt verlassen (öffentlicher Glaube). Ohne dieses Register wäre nie sicher, wem ein Grundstück wirklich gehört und welche Kredite darauf lasten.\n\n' +
      'Für dich als Eigentümer: Eigentum entsteht nicht mit dem Kaufvertrag, sondern erst mit der Umschreibung in Abteilung I — dazwischen schützt dich die [[auflassung|Auflassungsvormerkung]]. Die Reihenfolge der Einträge bestimmt den [[rang]]. Einsicht bekommt nur, wer ein berechtigtes Interesse nachweist. Prüfe vor dem Kauf immer einen aktuellen Auszug: Er verrät Altlasten wie eingetragene Wegerechte oder noch nicht gelöschte Grundschulden.',
    verwandt: ['auflassung', 'grundschuld', 'dienstbarkeit', 'niessbrauch', 'rang', 'teilungserklaerung'],
  },
  {
    id: 'notar',
    begriff: 'Notar & notarielle Beurkundung',
    kategorie: 'grundbuch',
    synonyme: ['Beurkundung', 'Notarvertrag', 'Urkundennummer', 'UR-Nr.', 'Notaranderkonto'],
    kurz: 'Ein Immobilienkauf ist nur wirksam, wenn ein Notar ihn beurkundet. Er ist neutrale Instanz und wickelt den Eigentumsübergang rechtssicher ab.',
    lang:
      'Der Notar beurkundet den Kaufvertrag — beim Neubau den [[bautraeger|Bauträgervertrag]]. Er liest den Vertrag vollständig vor, belehrt beide Seiten, veranlasst die [[auflassung|Auflassungsvormerkung]], die Löschung alter Lasten und schließlich die Eigentumsumschreibung im [[grundbuch]]. Jede Urkunde bekommt eine Urkundennummer (UR-Nr.), auf die sich Folgedokumente beziehen.\n\n' +
      'Die Beurkundungspflicht (§ 311b BGB) gibt es, weil ein Immobilienkauf weitreichend ist: Sie schützt vor Übereilung, sichert eine vollständige Belehrung und schafft eine fälschungssichere Urkunde. Der Notar ist dabei unparteiisch — er vertritt weder Käufer noch Verkäufer.\n\n' +
      'Für dich: Die Notarkosten sind gesetzlich geregelt (nach Kaufpreis gestaffelt) und Teil der [[kaufnebenkosten]]. Der Notar zahlt den Kaufpreis erst frei, wenn deine [[auflassung|Vormerkung]] steht und die Finanzierung gesichert ist — deshalb ist der Ablauf sicher, aber nicht schnell. Notarkosten zählen anteilig zu den [[anschaffungskosten]] und erhöhen damit deine [[afa]].',
    verwandt: ['bautraeger', 'auflassung', 'kaufnebenkosten', 'grundbuch', 'grunderwerbsteuer'],
  },
  {
    id: 'auflassung',
    begriff: 'Auflassung & Auflassungsvormerkung',
    kategorie: 'grundbuch',
    synonyme: ['Auflassungsvormerkung', 'Vormerkung', 'Eigentumsvormerkung'],
    kurz: 'Die Auflassung ist die Einigung über den Eigentumsübergang. Die Vormerkung sichert dir diesen Anspruch im Grundbuch, bis du wirklich als Eigentümer eingetragen bist.',
    lang:
      'Die Auflassung ist die notariell erklärte Einigung von Käufer und Verkäufer, dass das Eigentum übergehen soll. Weil zwischen Kaufvertrag und der endgültigen Umschreibung im [[grundbuch]] Wochen bis Monate vergehen, wird sofort eine Auflassungsvormerkung in Abteilung II eingetragen.\n\n' +
      'Die Vormerkung gibt es als Schutzschild in der Schwebezeit: Sie verhindert, dass der Verkäufer die Immobilie zwischenzeitlich ein zweites Mal verkauft, weiter belastet oder dass ein Gläubiger des Verkäufers noch zugreift. Dein Anspruch auf das Eigentum ist damit gesichert, obwohl du formal noch nicht Eigentümer bist.\n\n' +
      'Für dich: Erst wenn die Vormerkung steht, zahlst du üblicherweise den Kaufpreis — vorher gibt der [[notar]] das Geld nicht frei. Die eigentliche Eigentumsumschreibung folgt später, nach Zahlung und der steuerlichen [[unbedenklichkeitsbescheinigung|Unbedenklichkeitsbescheinigung]]. Ab dann bist du echter Eigentümer in Abteilung I.',
    verwandt: ['grundbuch', 'notar', 'unbedenklichkeitsbescheinigung', 'grunderwerbsteuer'],
  },
  {
    id: 'grunderwerbsteuer',
    begriff: 'Grunderwerbsteuer',
    kategorie: 'grundbuch',
    synonyme: ['GrESt', 'Grunderwerbssteuer'],
    kurz: 'Eine einmalige Steuer auf den Immobilienkauf, je nach Bundesland 3,5 bis 6,5 % des Kaufpreises. Sie gehört zu den Kaufnebenkosten.',
    lang:
      'Die Grunderwerbsteuer fällt einmalig beim Erwerb eines Grundstücks oder einer Immobilie an. Bemessungsgrundlage ist der Kaufpreis; der Satz liegt je nach Bundesland zwischen 3,5 % (Bayern, Sachsen) und 6,5 % (u. a. NRW, Brandenburg). Das Finanzamt setzt sie nach dem Kaufvertrag per Bescheid fest.\n\n' +
      'Es gibt sie, weil die Länder den Eigentumswechsel an Grundstücken besteuern — sie ist eine ihrer wichtigsten eigenen Einnahmen. Anders als die laufende [[grundsteuer]] wird sie nur ein einziges Mal, beim Erwerb, fällig.\n\n' +
      'Für dich: Erst nach Zahlung stellt das Finanzamt die [[unbedenklichkeitsbescheinigung|Unbedenklichkeitsbescheinigung]] aus, ohne die keine Eigentumsumschreibung erfolgt. Die Steuer ist Teil der [[kaufnebenkosten]] und zählt anteilig zu den [[anschaffungskosten]] — der auf das Gebäude entfallende Teil erhöht deine [[afa]]. Tipp: Mitgekaufte bewegliche Dinge (Einbauküche, Markise) getrennt ausweisen, sie unterliegen nicht der Grunderwerbsteuer.',
    verwandt: ['kaufnebenkosten', 'unbedenklichkeitsbescheinigung', 'anschaffungskosten', 'grundsteuer', 'notar'],
  },
  {
    id: 'kaufnebenkosten',
    begriff: 'Kaufnebenkosten (Erwerbsnebenkosten)',
    kategorie: 'grundbuch',
    synonyme: ['Erwerbsnebenkosten', 'Nebenkosten Kauf', 'Anschaffungsnebenkosten'],
    kurz: 'Die Kosten rund um den Kauf zusätzlich zum Kaufpreis: Grunderwerbsteuer, Notar, Grundbuch und ggf. Makler — grob 9 bis 12 % des Kaufpreises.',
    lang:
      'Kaufnebenkosten sind alle Ausgaben, die neben dem eigentlichen Kaufpreis anfallen: die [[grunderwerbsteuer]], die Kosten für [[notar]] und Grundbuchamt (zusammen rund 1,5–2 %) und, falls beauftragt, die Maklercourtage (regional bis 3,57 % für den Käufer). In Summe kommen je nach Bundesland etwa 9–12 % des Kaufpreises zusammen.\n\n' +
      'Sie existieren, weil ein rechtssicherer Eigentumsübergang Beurkundung, Register und Steuer erfordert — Aufwand, der bezahlt werden muss. Für die Finanzierung sind sie heikel, weil Banken sie selten mitfinanzieren: Sie müssen meist aus [[eigenkapital]] kommen.\n\n' +
      'Für dich doppelt wichtig: Erstens beim Budget — plane die Nebenkosten von Anfang an als Eigenkapitalbedarf ein. Zweitens steuerlich — der auf das Gebäude entfallende Anteil gehört zu den [[anschaffungskosten]] und wird über die [[afa]] abgeschrieben; reine Finanzierungsnebenkosten dagegen sind sofort als [[werbungskosten]] absetzbar.',
    verwandt: ['grunderwerbsteuer', 'notar', 'eigenkapital', 'anschaffungskosten', 'afa'],
  },
  {
    id: 'bautraeger',
    begriff: 'Bauträger & Bauträgervertrag',
    kategorie: 'grundbuch',
    synonyme: ['Bauträgervertrag', 'Neubau', 'schlüsselfertig'],
    kurz: 'Ein Bauträger verkauft dir Grundstück und noch zu errichtendes Gebäude in einem Vertrag. Bezahlt wird in Raten nach Baufortschritt.',
    lang:
      'Beim Bauträgerkauf erwirbst du von einem Unternehmen Grundstücksanteil und das darauf noch zu bauende (oder im Bau befindliche) Gebäude in einem einzigen notariellen Vertrag. Der Bauträger ist bis zur Fertigstellung Eigentümer und Bauherr; du zahlst den Kaufpreis nicht auf einmal, sondern in Raten nach [[mabv|Baufortschritt]].\n\n' +
      'Diese Konstruktion gibt es, damit du eine Neubauwohnung „schlüsselfertig" kaufen kannst, ohne selbst Bauherr zu sein. Weil du aber für ein noch nicht existierendes Werk vorauszahlst, schützt dich die Makler- und Bauträgerverordnung (MaBV) vor dem Insolvenzrisiko des Bauträgers.\n\n' +
      'Für dich: Der Vertrag verbindet Kauf- und Werkvertragsrecht — deshalb gibt es hier eine [[abnahme]] und eine [[gewaehrleistung|Gewährleistung]] wie beim Bau, nicht die kurze Sachmängelhaftung eines Gebrauchtkaufs. Achte auf die Baubeschreibung (was ist geschuldet?), Sonderwünsche, den Fertigstellungstermin und darauf, dass die Raten dem echten Baufortschritt entsprechen. In der Bauzeit fallen oft [[bereitstellungszins|Bereitstellungszinsen]] an.',
    verwandt: ['mabv', 'abnahme', 'gewaehrleistung', 'notar', 'bereitstellungszins'],
  },
  {
    id: 'mabv',
    begriff: 'MaBV — Ratenzahlung nach Baufortschritt',
    kategorie: 'grundbuch',
    synonyme: ['Makler- und Bauträgerverordnung', 'Kaufpreisraten', 'Ratenplan', 'Baufortschritt'],
    kurz: 'Die Verordnung, nach der du den Kaufpreis beim Neubau in Raten je erreichtem Bauabschnitt zahlst — als Schutz gegen die Insolvenz des Bauträgers.',
    lang:
      'Die Makler- und Bauträgerverordnung (MaBV) regelt, wie ein [[bautraeger]] den Kaufpreis abrufen darf: nicht im Voraus, sondern in bis zu sieben Raten (aufteilbar in maximal dreizehn Teilbeträge), jeweils erst nachdem ein bestimmter Bauabschnitt erreicht ist — Rohbau, Dach, Rohinstallation, Estrich, Fenster, Bezugsfertigkeit, vollständige Fertigstellung. Die erste Rate (Anteil für das Grundstück) darf erst fließen, wenn die [[auflassung|Vormerkung]] steht und die Baugenehmigung vorliegt.\n\n' +
      'Diesen Schutz gibt es, weil du für ein noch nicht fertiges Werk vorauszahlst: Würde der Bauträger insolvent, hättest du bezahlt, aber kein Haus. Die Kopplung an den echten Baufortschritt sorgt dafür, dass dein Geld immer nur einem entsprechenden Gegenwert folgt.\n\n' +
      'Für dich: Prüfe (oder lass prüfen), ob ein Bauabschnitt wirklich erreicht ist, bevor du eine Rate freigibst. Für die Finanzierung heißt der Ratenplan, dass das Darlehen nach und nach abgerufen wird — auf den noch nicht abgerufenen Teil fallen [[bereitstellungszins|Bereitstellungszinsen]] an. In ImmoCalc bildest du den Ratenplan als einzelne Zahlungen mit Datum ab, statt eines einzigen Kaufpreises.',
    verwandt: ['bautraeger', 'bereitstellungszins', 'auflassung', 'abnahme'],
  },
  {
    id: 'abnahme',
    begriff: 'Abnahme',
    kategorie: 'grundbuch',
    synonyme: ['Bauabnahme', 'Abnahmeprotokoll', 'förmliche Abnahme'],
    kurz: 'Die Erklärung, dass das Bauwerk im Wesentlichen vertragsgemäß erbracht ist. Sie ist ein rechtlicher Wendepunkt: Fristen und Haftung ändern sich.',
    lang:
      'Bei der Abnahme erklärst du als Käufer, dass das Werk des [[bautraeger|Bauträgers]] im Wesentlichen vertragsgemäß fertig ist. Festgestellte Mängel werden in einem Abnahmeprotokoll aufgeführt und mit Frist zur Beseitigung vorbehalten. Die förmliche Abnahme ist der zentrale Übergabemoment eines Neubaus.\n\n' +
      'Sie gibt es, weil an sie zahlreiche Rechtsfolgen geknüpft sind: Ab der Abnahme beginnt die [[gewaehrleistung|Gewährleistungsfrist]] zu laufen, die Beweislast für Mängel kehrt sich um (jetzt musst du sie nachweisen), die Vergütung wird fällig und die Gefahr geht auf dich über.\n\n' +
      'Für dich: Nimm nie unter Zeitdruck ab und protokolliere jeden noch so kleinen Mangel — was nicht drinsteht, gilt als in Ordnung. Ziehe für eine Neubauabnahme einen Sachverständigen hinzu. Das Abnahmedatum unbedingt festhalten: Es ist der Startpunkt aller [[gewaehrleistung|Gewährleistungsfristen]]. Nicht verwechseln mit der [[uebergabeprotokoll|Wohnungsübergabe]] an einen Mieter.',
    verwandt: ['gewaehrleistung', 'bautraeger', 'mabv', 'uebergabeprotokoll'],
  },
  {
    id: 'gewaehrleistung',
    begriff: 'Gewährleistung (Mängelhaftung)',
    kategorie: 'grundbuch',
    synonyme: ['Mängelhaftung', 'Gewährleistungsfrist', 'Sachmängelhaftung', 'Verjährung'],
    kurz: 'Die gesetzliche Haftung des Bauträgers für Mängel. Beim Neubau meist fünf Jahre ab Abnahme.',
    lang:
      'Die Gewährleistung verpflichtet den [[bautraeger]] oder Bauunternehmer, Mängel zu beseitigen, die bei der [[abnahme]] schon vorhanden waren, aber erst später auftreten. Für Bauwerke beträgt die Frist grundsätzlich fünf Jahre und beginnt mit der Abnahme.\n\n' +
      'Es gibt sie, weil Baumängel oft erst nach Monaten oder Jahren sichtbar werden — Feuchtigkeit, Risse, undichte Stellen. Ohne diese gesetzliche Frist trügest du das Risiko allein, obwohl der Fehler aus der Bauphase stammt.\n\n' +
      'Für dich: Halte das Abnahmedatum fest und behalte das Fristende im Blick — kurz davor lohnt eine gezielte Begehung, um verdeckte Mängel noch rechtzeitig zu rügen. Rüge Mängel immer schriftlich mit Fristsetzung. Auch der Schornsteinfeger- oder Feuerstätten-Mängelbescheid arbeitet mit solchen Fristen. Beseitigungskosten, die du trägst, können [[werbungskosten]] oder [[anschaffungskosten|nachträgliche Anschaffungskosten]] sein.',
    verwandt: ['abnahme', 'bautraeger', 'werbungskosten'],
  },
  {
    id: 'dienstbarkeit',
    begriff: 'Grunddienstbarkeit & beschränkte persönliche Dienstbarkeit',
    kategorie: 'grundbuch',
    synonyme: ['Grunddienstbarkeit', 'Wegerecht', 'Leitungsrecht', 'Geh- und Fahrtrecht'],
    kurz: 'Ein in Abteilung II eingetragenes Recht eines anderen, dein Grundstück in bestimmter Weise zu nutzen — etwa ein Wegerecht oder Leitungsrecht.',
    lang:
      'Eine Dienstbarkeit ist eine Last in Abteilung II des [[grundbuch]]s: Ein anderer darf dein Grundstück in einer festgelegten Weise nutzen oder du musst etwas dulden. Bei der Grunddienstbarkeit steht das Recht dem jeweiligen Eigentümer eines Nachbargrundstücks zu (typisch ein Geh- und Fahrtrecht über deine Zufahrt), bei der beschränkten persönlichen Dienstbarkeit einer bestimmten Person oder einem Unternehmen (typisch ein Leitungsrecht der Stadtwerke).\n\n' +
      'Solche Rechte gibt es, weil Grundstücke oft aufeinander angewiesen sind — der Hinterlieger braucht eine Zufahrt, Versorger brauchen Trassen für Kanal und Kabel. Die Eintragung sorgt dafür, dass das Recht auch einen Eigentümerwechsel überdauert.\n\n' +
      'Für dich: Prüfe den Grundbuchauszug vor dem Kauf auf solche Lasten — sie können die Nutzung und den [[verkehrswert]] mindern (fremdes Fahrtrecht mitten über den Hof) oder umgekehrt deinem Grundstück nützen. Nicht verwechseln mit dem [[niessbrauch]], der viel weiter reicht.',
    verwandt: ['grundbuch', 'niessbrauch', 'verkehrswert'],
  },
  {
    id: 'niessbrauch',
    begriff: 'Nießbrauch',
    kategorie: 'grundbuch',
    synonyme: ['Nießbrauchrecht', 'Vorbehaltsnießbrauch'],
    kurz: 'Das umfassende Recht, eine Immobilie zu nutzen und ihre Erträge (Mieten) zu ziehen, obwohl sie einem anderen gehört. Häufig bei Übertragung zu Lebzeiten.',
    lang:
      'Der Nießbrauch gibt einer Person das Recht, eine fremde Immobilie vollständig zu nutzen und alle Erträge — vor allem die Mieten — zu behalten, obwohl das Eigentum bei jemand anderem liegt. Er wird in Abteilung II des [[grundbuch]]s eingetragen. Sehr häufig ist der Vorbehaltsnießbrauch: Eltern übertragen die Immobilie zu Lebzeiten an die Kinder, behalten sich aber den Nießbrauch vor und beziehen weiter die Mieten.\n\n' +
      'Diese Gestaltung gibt es vor allem zur vorweggenommenen Erbfolge: Vermögen wird früh übertragen (das spart später Erbschaftsteuer, weil der Nießbrauch den Wert der Schenkung mindert), während die Altentleration abgesichert bleibt.\n\n' +
      'Für dich als Eigentümer entscheidend: Solange der Nießbrauch besteht, bezieht *nicht du*, sondern der Nießbraucher die Einkünfte — er versteuert sie und macht die [[afa]] geltend (sofern er die Anschaffung getragen hat). Erst mit Erlöschen des Nießbrauchs (meist Tod) fließen dir Mieten und steuerliche Rechte zu. Prüfe bei einer [[erwerbsart|unentgeltlichen Übertragung]] genau, wem die Einkünfte zuzurechnen sind.',
    verwandt: ['grundbuch', 'dienstbarkeit', 'erwerbsart', 'afa'],
  },
  {
    id: 'erwerbsart',
    begriff: 'Erwerbsart: Kauf, Erbschaft, Schenkung',
    kategorie: 'grundbuch',
    synonyme: ['unentgeltlicher Erwerb', 'Überlassung', 'Schenkung', 'Erbschaft', 'Fußstapfentheorie'],
    kurz: 'Wie du die Immobilie bekommen hast — gekauft, geerbt oder geschenkt — bestimmt Anschaffungskosten, AfA und Steuer.',
    lang:
      'Die Erwerbsart unterscheidet den entgeltlichen Kauf vom unentgeltlichen Erwerb durch Erbschaft, Schenkung oder Überlassung zu Lebzeiten. Beim Kauf hast du eigene [[anschaffungskosten]], von denen sich die [[afa]] ableitet. Beim unentgeltlichen Erwerb hast du nichts bezahlt — hier gilt die Fußstapfentheorie: Du führst die [[afa]] des Voreigentümers mit dessen ursprünglichen Anschaffungskosten und Restnutzungsdauer einfach fort.\n\n' +
      'Diese Unterscheidung gibt es, weil sich die Abschreibung an tatsächlichen Anschaffungskosten orientiert — die hat ein Erbe oder Beschenkter aber gar nicht. Statt die AfA zu verlieren, tritt er in die Position des Vorgängers ein.\n\n' +
      'Für dich wichtig: Bei einer Überlassung ist oft ein [[niessbrauch]] vorbehalten oder ein Veräußerungsverbot eingetragen — beides beeinflusst, wem die Mieten steuerlich zugerechnet werden. Du brauchst dann die alten Anschaffungs- und AfA-Daten des Übergebers, nicht einen fiktiven Kaufpreis. ImmoCalc unterstellt sonst einen Kauf; bei geerbten oder geschenkten Objekten musst du AfA-Bemessung und Zurechnung bewusst richtig setzen.',
    verwandt: ['anschaffungskosten', 'afa', 'niessbrauch', 'grunderwerbsteuer'],
  },
  {
    id: 'erbbaurecht',
    begriff: 'Erbbaurecht (Erbpacht)',
    kategorie: 'grundbuch',
    synonyme: ['Erbpacht', 'Erbbauzins', 'Erbbaurechtsvertrag'],
    kurz: 'Das Recht, auf fremdem Grund ein Gebäude zu haben. Dir gehört das Haus, nicht das Grundstück — dafür zahlst du laufend Erbbauzins.',
    lang:
      'Beim Erbbaurecht kaufst oder besitzt du das Gebäude, aber nicht den Grund darunter. Das Grundstück gehört weiter dem Erbbaurechtsgeber (oft Kommune, Kirche, Stiftung), der es dir für lange Zeit — typisch 75 bis 99 Jahre — überlässt. Dafür zahlst du einen jährlichen Erbbauzins. Das Erbbaurecht selbst wird wie ein Grundstück behandelt: eigenes Grundbuchblatt, verkäuflich und beleihbar.\n\n' +
      'Es gibt das Erbbaurecht, weil der Grundstückseigentümer sein Land nicht verkaufen, aber nutzbar machen will — und weil du so ohne den teuren Grundstückskauf bauen kannst. Der Einstieg ist günstiger, dafür läuft eine dauerhafte Zahlung.\n\n' +
      'Für dich als Kapitalanleger: Rechne den Erbbauzins als laufende Ausgabe in den [[cashflow]] ein (er ist als [[werbungskosten]] absetzbar). Beachte die Restlaufzeit — je kürzer, desto schwerer verkäuflich und finanzierbar, weil das Recht am Ende an den Grundstückseigentümer zurückfällt (meist gegen Entschädigung). Das drückt den [[verkehrswert]]. Erhöhungsklauseln für den Erbbauzins genau lesen.',
    verwandt: ['cashflow', 'werbungskosten', 'verkehrswert', 'grundbuch'],
  },
  {
    id: 'teilungserklaerung',
    begriff: 'Teilungserklärung',
    kategorie: 'grundbuch',
    synonyme: ['Aufteilungsplan', 'Sondereigentum', 'Gemeinschaftseigentum', 'Miteigentumsanteil'],
    kurz: 'Das Dokument, das ein Haus in einzelne Eigentumswohnungen aufteilt und festlegt, was Sondereigentum und was Gemeinschaftseigentum ist.',
    lang:
      'Die Teilungserklärung teilt ein Grundstück mit Gebäude rechtlich in Wohnungseigentum auf. Sie legt fest, welche Räume dir allein gehören (Sondereigentum: deine Wohnung), was allen zusammen gehört (Gemeinschaftseigentum: Dach, Fassade, Treppenhaus, Heizung) und welchen Miteigentumsanteil — meist in 1000stel — deine Einheit am Ganzen hat. Ein Aufteilungsplan zeigt das zeichnerisch.\n\n' +
      'Es gibt sie, weil man ein Gebäude physisch nicht in Scheiben schneiden kann: Erst die Teilungserklärung macht aus einem Haus mehrere handel- und finanzierbare Eigentumswohnungen und bildet die rechtliche Grundlage der [[weg|Eigentümergemeinschaft]].\n\n' +
      'Für dich: Der Miteigentumsanteil ist der wichtigste [[verteilerschluessel]] — nach ihm richten sich [[hausgeld]] und Stimmrecht. Prüfe die Teilungserklärung auf Sondernutzungsrechte (Garten, Stellplatz, Keller) und darauf, ob sie zur tatsächlichen Nutzung passt. Sie regelt oft auch Details wie die Kostenverteilung, die von der gesetzlichen Regel abweichen kann.',
    verwandt: ['weg', 'hausgeld', 'verteilerschluessel', 'grundbuch'],
  },
  {
    id: 'unbedenklichkeitsbescheinigung',
    begriff: 'Unbedenklichkeitsbescheinigung',
    kategorie: 'grundbuch',
    synonyme: ['UB', 'steuerliche Unbedenklichkeit'],
    kurz: 'Die Bestätigung des Finanzamts, dass die Grunderwerbsteuer bezahlt ist. Ohne sie trägt das Grundbuchamt dich nicht als Eigentümer ein.',
    lang:
      'Die Unbedenklichkeitsbescheinigung ist eine kurze Bestätigung des Finanzamts, dass der Eintragung des Käufers ins [[grundbuch]] steuerlich nichts entgegensteht — konkret: dass die [[grunderwerbsteuer]] gezahlt (oder sichergestellt) ist. Das Finanzamt schickt sie nach Zahlung direkt an den [[notar]].\n\n' +
      'Es gibt sie als Kontrollpunkt: Der Staat will sicherstellen, dass die Grunderwerbsteuer nicht ausfällt, bevor der Eigentumswechsel vollzogen ist. Sie ist damit die letzte Weiche vor der Eigentumsumschreibung.\n\n' +
      'Für dich bedeutet sie schlicht: Nach dem Kauf dauert es, bis du wirklich im Grundbuch stehst — erst Steuerbescheid, dann Zahlung, dann Bescheinigung, dann Umschreibung. In der Zwischenzeit schützt dich die [[auflassung|Auflassungsvormerkung]].',
    verwandt: ['grunderwerbsteuer', 'grundbuch', 'auflassung', 'notar'],
  },
  // -------------------------------------------------------------------- Steuer
  {
    id: 'afa',
    begriff: 'AfA (Gebäudeabschreibung)',
    kategorie: 'steuer',
    synonyme: ['Absetzung für Abnutzung', 'Abschreibung', 'Gebäude-AfA', 'lineare AfA'],
    kurz: 'Die jährliche Abschreibung des Gebäudewerts als Werbungskosten — meist 2 % (Altbau) oder 3 % (Neubau ab 2023) der Gebäude-Anschaffungskosten.',
    lang:
      'Die AfA (Absetzung für Abnutzung) verteilt die [[anschaffungskosten]] des Gebäudes über seine Nutzungsdauer und macht jedes Jahr einen Teil davon als [[werbungskosten]] steuerlich geltend. Der lineare Satz beträgt 2 % pro Jahr (Gebäude, Bauantrag vor 2023), 3 % für Neubauten ab 2023 und 2,5 % für Altbauten vor 1925. Wichtig: Nur das Gebäude wird abgeschrieben, nicht der Grund und Boden — der nutzt sich nicht ab.\n\n' +
      'Es gibt die AfA, weil ein Gebäude mit der Zeit an Wert verliert (Abnutzung). Der Steuergesetzgeber erlaubt, diesen Wertverzehr über Jahrzehnte anzusetzen — obwohl du nur einmal gekauft hast, mindert die AfA jedes Jahr deine Steuerlast.\n\n' +
      'Für dich der wichtigste Papierverlust: Die AfA senkt deine Steuer, ohne dass Geld abfließt — sie verbessert die Rendite spürbar. Entscheidend ist die richtige Kaufpreisaufteilung: Je höher der Gebäudeanteil (statt Boden), desto mehr AfA. Bei geerbten Objekten führst du die AfA des Voreigentümers fort (siehe [[erwerbsart]]). Die AfA trägst du in die [[anlage-v]] ein.',
    verwandt: ['anschaffungskosten', 'werbungskosten', 'anlage-v', 'erwerbsart', 'kaufnebenkosten'],
  },
  {
    id: 'anschaffungskosten',
    begriff: 'Anschaffungskosten & Kaufpreisaufteilung',
    kategorie: 'steuer',
    synonyme: ['Kaufpreisaufteilung', 'Gebäudeanteil', 'Bodenwertanteil', 'Herstellungskosten'],
    kurz: 'Der Kaufpreis plus anteilige Kaufnebenkosten, aufgeteilt in Gebäude und Grund. Nur der Gebäudeanteil ist über die AfA abschreibbar.',
    lang:
      'Zu den Anschaffungskosten zählen der Kaufpreis und die anteiligen [[kaufnebenkosten]] ([[grunderwerbsteuer]], Notar, Grundbuch, Makler). Für die [[afa]] müssen sie in zwei Teile zerlegt werden: den Gebäudeanteil (abschreibbar) und den Anteil für Grund und Boden (nicht abschreibbar, weil unvergänglich). Diese Kaufpreisaufteilung erfolgt meist nach dem Verhältnis der Verkehrswerte, oft mit dem amtlichen Bodenrichtwert.\n\n' +
      'Die Aufteilung gibt es, weil nur das Gebäude sich abnutzt. Ein möglichst hoher Gebäudeanteil erhöht deine jährliche Abschreibung — das Finanzamt schaut deshalb genau hin und stellt eine eigene Arbeitshilfe bereit.\n\n' +
      'Für dich der wichtigste Steuerhebel überhaupt: Eine gut begründete Aufteilung mit hohem Gebäudeanteil bringt über die gesamte Haltedauer viel AfA. Nachträgliche Modernisierungen können den anschaffungsnahen Aufwand betreffen (überschreiten sie in den ersten drei Jahren 15 % der Gebäude-Anschaffungskosten, gelten sie als Anschaffungskosten und sind nicht sofort abziehbar). Sonst sind Reparaturen [[werbungskosten]].',
    verwandt: ['afa', 'kaufnebenkosten', 'werbungskosten', 'grunderwerbsteuer', 'verkehrswert'],
  },
  {
    id: 'anlage-v',
    begriff: 'Anlage V',
    kategorie: 'steuer',
    synonyme: ['Anlage V', 'Einkünfte aus Vermietung und Verpachtung', 'V+V'],
    kurz: 'Die Steuerformular-Anlage, in der du Mieteinnahmen und Werbungskosten je Objekt angibst. Das Ergebnis fließt in deine Einkommensteuer.',
    lang:
      'Die Anlage V ist der Teil der Einkommensteuererklärung für Einkünfte aus Vermietung und Verpachtung. Pro Objekt trägst du auf der einen Seite die Einnahmen ein ([[kaltmiete]], umgelegte [[nebenkosten]], [[vorauszahlung|Vorauszahlungen]]) und auf der anderen die [[werbungskosten]] ([[afa]], [[schuldzinsen]], Erhaltungsaufwand, Verwaltung, nicht umlagefähige Kosten). Die Differenz ist dein steuerliches Ergebnis aus Vermietung.\n\n' +
      'Das Formular gibt es, weil Vermietung eine eigene Einkunftsart ist und getrennt ermittelt werden muss, bevor sie mit deinem übrigen Einkommen verrechnet wird. Ein Überschuss erhöht die Steuer, ein Verlust senkt sie.\n\n' +
      'Für dich: Gerade in den ersten Jahren führt hohe AfA plus Zinsen oft zu einem steuerlichen Verlust, obwohl der [[cashflow]] positiv ist — der Verlust senkt deine Steuer auf das übrige Einkommen. Führe alle Belege sauber je Objekt und Jahr; die Anlage V ist die Klammer, in der die Steuerbegriffe dieses Lexikons zusammenlaufen. Handwerkerkosten der Mieterseite können zusätzlich über [[paragraf-35a]] wirken.',
    verwandt: ['werbungskosten', 'afa', 'schuldzinsen', 'kaltmiete', 'cashflow'],
  },
  {
    id: 'werbungskosten',
    begriff: 'Werbungskosten',
    kategorie: 'steuer',
    synonyme: ['Erhaltungsaufwand', 'absetzbare Kosten', 'Erwerbsaufwendungen'],
    kurz: 'Alle Ausgaben rund um die Vermietung, die du steuerlich absetzen kannst — von der AfA über Zinsen bis zu Reparaturen und Verwaltung.',
    lang:
      'Werbungskosten sind alle Aufwendungen, die der Erzielung deiner Mieteinnahmen dienen. Dazu gehören die [[afa]], die [[schuldzinsen]], Erhaltungsaufwand (Reparaturen, Wartung), Hausverwaltung, nicht auf Mieter umlegbare [[nebenkosten]], Fahrtkosten, Kontoführung, Versicherungen und vieles mehr. Sie werden in der [[anlage-v]] von den Einnahmen abgezogen.\n\n' +
      'Den Abzug gibt es, weil nur der Überschuss — Einnahmen minus notwendiger Ausgaben — besteuert werden soll. Was du aufwenden musst, um Mieten zu erzielen, mindert folgerichtig die Steuerbemessung.\n\n' +
      'Für dich die wichtige Grenze: Erhaltungsaufwand (Reparatur, Instandsetzung) ist sofort in voller Höhe absetzbar; Herstellungs- oder anschaffungsnaher Aufwand dagegen nur über die [[afa]] (siehe [[anschaffungskosten]]). Reparaturen also möglichst nicht im ersten Jahr bündeln, sonst droht die 15-%-Falle. Umlagefähige Kosten, die du vom Mieter erstattet bekommst, sind sowohl Einnahme als auch Ausgabe — sie heben sich auf.',
    verwandt: ['afa', 'schuldzinsen', 'anlage-v', 'anschaffungskosten', 'nebenkosten'],
  },
  {
    id: 'schuldzinsen',
    begriff: 'Schuldzinsen (Finanzierungskosten)',
    kategorie: 'steuer',
    synonyme: ['Finanzierungskosten', 'Zinsaufwand', 'Kreditzinsen'],
    kurz: 'Die Zinsen für den Immobilienkredit — voll als Werbungskosten absetzbar. Die Tilgung dagegen nicht.',
    lang:
      'Schuldzinsen sind der Zinsanteil deiner Kreditrate — bei einem [[annuitaet|Annuitätendarlehen]] der Teil, der nicht [[tilgung]] ist. Bei einer vermieteten Immobilie sind sie in voller Höhe als [[werbungskosten]] absetzbar. Dazu zählen auch [[bereitstellungszins|Bereitstellungszinsen]], ein [[disagio]] und Finanzierungsnebenkosten.\n\n' +
      'Absetzbar sind sie, weil der Kredit unmittelbar der Finanzierung des vermieteten Objekts dient — die Zinsen sind damit Kosten der Einkünfteerzielung. Die Tilgung dagegen ist bloße Vermögensumschichtung (du wandelst Schuld in Eigentum) und deshalb nicht absetzbar.\n\n' +
      'Für dich zwei Dinge: Erstens den echten Zins-Jahresbetrag aus dem Bankbeleg (Jahreskontoauszug/Finanzierungskostennachweis) nehmen, nicht die überschlägige Rechnung — der Bank-Ist gehört in die [[anlage-v]]. Zweitens: Weil nur der Zins absetzbar ist, wird jede Rate mit sinkender [[restschuld]] steuerlich „schlechter" (weniger Zins, mehr Tilgung) — das ist normal und Ausdruck deines Vermögensaufbaus.',
    verwandt: ['werbungskosten', 'annuitaet', 'tilgung', 'anlage-v', 'bereitstellungszins'],
  },
  {
    id: 'paragraf-35a',
    begriff: '§ 35a EStG (haushaltsnahe Leistungen & Handwerker)',
    kategorie: 'steuer',
    synonyme: ['35a', 'Handwerkerleistung', 'haushaltsnahe Dienstleistung', 'Arbeitskosten'],
    kurz: 'Ein Steuerabzug für Arbeitskosten von Handwerkern und haushaltsnahen Diensten. Bei Vermietung nutzt ihn der Mieter — du weist die Arbeitskosten in der Abrechnung aus.',
    lang:
      '§ 35a EStG gewährt einen direkten Abzug von der Steuerschuld für den Arbeitslohn (nicht Material) von Handwerkerleistungen (20 %, max. 1.200 € im Jahr) und haushaltsnahen Dienstleistungen (20 %, max. 4.000 €) wie Hausmeister, Treppenhausreinigung, Gartenpflege, Wartung.\n\n' +
      'Diesen Bonus gibt es, um Schwarzarbeit einzudämmen und legale Beauftragung zu belohnen. Bei einer vermieteten Wohnung nutzt ihn nicht der Eigentümer (der setzt dieselben Kosten schon als [[werbungskosten]] ab), sondern der Mieter — für die über die [[nebenkosten]] auf ihn umgelegten Arbeitskosten.\n\n' +
      'Für dich als Vermieter eine Servicepflicht: Du musst in der Nebenkostenabrechnung die begünstigten Arbeitskosten getrennt vom Material ausweisen, damit der Mieter sie in seiner Steuererklärung geltend machen kann. Rechnungen der Dienstleister müssen diesen Split hergeben; bei unterjährigem Nutzerwechsel wird zeitanteilig zugeordnet. ImmoCalc trennt den Arbeitskostenanteil je Kostenart.',
    verwandt: ['werbungskosten', 'nebenkosten', 'verteilerschluessel', 'anlage-v'],
  },
  {
    id: 'grundsteuer',
    begriff: 'Grundsteuer',
    kategorie: 'steuer',
    synonyme: ['Grundsteuer B', 'Grundsteuermessbescheid', 'Grundsteuerwert', 'Hebesatz', 'Grundsteuerreform'],
    kurz: 'Eine laufende Steuer der Gemeinde auf Grundbesitz. Sie ist auf den Mieter umlagefähig und kommt jedes Jahr.',
    lang:
      'Die Grundsteuer erhebt die Gemeinde jährlich auf Grundbesitz. Sie entsteht in zwei Stufen: Das Finanzamt setzt per Messbescheid einen Grundsteuermessbetrag fest (aus dem Grundsteuerwert bzw. früher Einheitswert), die Gemeinde multipliziert ihn mit ihrem Hebesatz und schickt den eigentlichen Grundsteuerbescheid. Seit der Grundsteuerreform 2025 gelten neue, nach Bundesland unterschiedliche Bewertungsmodelle.\n\n' +
      'Es gibt sie, weil Kommunen eine verlässliche, an den Grundbesitz gebundene Einnahme brauchen — sie finanziert lokale Infrastruktur. Anders als die einmalige [[grunderwerbsteuer]] fällt sie jedes Jahr an, solange du Eigentümer bist.\n\n' +
      'Für dich: Die Grundsteuer ist eine umlagefähige Betriebskostenart (siehe [[umlagefaehigkeit]]) und wird über die [[nebenkosten]] auf den Mieter verteilt — bei mehreren Einheiten meist nach Fläche. Prüfe Messbescheid und Hebesatz nach der Reform, denn viele Werte haben sich verschoben. Änderungsbescheide mitten im Jahr müssen anteilig berücksichtigt werden.',
    verwandt: ['nebenkosten', 'umlagefaehigkeit', 'grunderwerbsteuer', 'verteilerschluessel'],
  },
  // ------------------------------------------------------------ Nebenkosten & WEG
  {
    id: 'nebenkosten',
    begriff: 'Nebenkosten (Betriebskosten)',
    kategorie: 'nebenkosten',
    synonyme: ['Betriebskosten', 'Nebenkostenabrechnung', 'kalte Betriebskosten', 'zweite Miete'],
    kurz: 'Die laufenden Kosten des Gebäudebetriebs, die du auf den Mieter umlegen darfst — von Grundsteuer über Wasser bis Hausmeister.',
    lang:
      'Betriebskosten sind die laufenden Kosten, die durch das Eigentum und den Betrieb der Immobilie regelmäßig entstehen: [[grundsteuer]], Wasser und Abwasser, Heizung und Warmwasser, Müll, Beleuchtung, Aufzug, Gartenpflege, Hausmeister, Gebäudeversicherung und weitere. Was davon der Mieter trägt, regelt die [[umlagefaehigkeit]] nach der Betriebskostenverordnung. Am Jahresende rechnest du sie in der Nebenkostenabrechnung gegen die [[vorauszahlung|Vorauszahlungen]] ab.\n\n' +
      'Es gibt die Umlage, weil diese Kosten durch das Wohnen des Mieters verursacht werden — nicht der Eigentümer soll das Wasser des Mieters bezahlen. Deshalb spricht man auch von der „zweiten Miete".\n\n' +
      'Für dich als Vermieter: Die Abrechnung muss binnen zwölf Monaten nach Ende des Abrechnungszeitraums beim Mieter sein, sonst kannst du Nachforderungen verlieren. Jede Kostenart braucht einen sachgerechten [[verteilerschluessel]], Heizkosten unterliegen der [[heizkostenverordnung]]. Nicht umlagefähige Anteile (z. B. Verwaltung, Instandhaltung) bleiben bei dir und sind deine [[werbungskosten]].',
    verwandt: ['umlagefaehigkeit', 'verteilerschluessel', 'vorauszahlung', 'heizkostenverordnung', 'grundsteuer', 'betriebskostenverordnung'],
  },
  {
    id: 'umlagefaehigkeit',
    begriff: 'Umlagefähigkeit',
    kategorie: 'nebenkosten',
    synonyme: ['umlagefähig', 'nicht umlagefähig', 'umlagefähige Kosten'],
    kurz: 'Ob eine Kostenart auf den Mieter abgewälzt werden darf oder beim Eigentümer bleibt. Nur die im Gesetz genannten Betriebskosten sind umlagefähig.',
    lang:
      'Umlagefähig heißt: Diese Kostenart darfst du über die [[nebenkosten|Nebenkostenabrechnung]] auf den Mieter verteilen. Maßgeblich ist der Katalog der [[betriebskostenverordnung]] — laufende Kosten wie [[grundsteuer]], Wasser, Heizung, Müll, Hausmeister, Versicherung. Nicht umlagefähig sind Verwaltungskosten, Instandhaltung und Reparaturen, Kontoführung des Eigentümers und die [[ruecklage|Instandhaltungsrücklage]].\n\n' +
      'Die Grenze gibt es, um den Mieter zu schützen: Er soll nur die verbrauchsnahen Betriebskosten tragen, nicht die Kosten, mit denen der Eigentümer sein Vermögen erhält oder verwaltet. Voraussetzung ist außerdem, dass die Umlage im Mietvertrag vereinbart ist.\n\n' +
      'Für dich zweischneidig: Umlagefähige Kosten bekommst du vom Mieter erstattet — sie sind für dich Einnahme und Ausgabe zugleich und heben sich im [[cashflow]] auf. Nicht umlagefähige Kosten trägst *du* wirtschaftlich, dafür sind sie deine [[werbungskosten]] und mindern die Steuer. Beim [[weg|Wohnungseigentum]] ist die Tücke: Ein Teil des [[hausgeld]]s (Verwaltung, Rücklage) ist nicht umlagefähig — du musst das Hausgeld zerlegen.',
    verwandt: ['nebenkosten', 'betriebskostenverordnung', 'ruecklage', 'werbungskosten', 'hausgeld'],
  },
  {
    id: 'verteilerschluessel',
    begriff: 'Verteilerschlüssel (Umlageschlüssel)',
    kategorie: 'nebenkosten',
    synonyme: ['Umlageschlüssel', 'Verteilungsschlüssel', 'Umlagemaßstab'],
    kurz: 'Die Regel, nach der eine Gesamtkostenart auf die einzelnen Einheiten verteilt wird — nach Fläche, Personen, Miteigentumsanteil oder Verbrauch.',
    lang:
      'Der Verteilerschlüssel legt fest, wie eine Gesamtsumme auf die Mietparteien oder Einheiten aufgeteilt wird. Übliche Maßstäbe sind Wohnfläche (m²), Personenzahl, Anzahl der Einheiten, der Miteigentumsanteil (bei [[weg|WEG]], siehe [[teilungserklaerung]]) oder der gemessene Verbrauch über [[zaehler]]. Jede Kostenart bekommt den zu ihr passenden Schlüssel: Grundsteuer nach Fläche, Wasser nach Verbrauch oder Personen, Aufzug ggf. nach Einheiten.\n\n' +
      'Es gibt verschiedene Schlüssel, weil sich Kosten unterschiedlich verursachen: Verbrauchsabhängiges soll verbrauchsgerecht verteilt werden, Flächenbezogenes nach Fläche. Ohne sachgerechten Schlüssel wäre die Abrechnung angreifbar.\n\n' +
      'Für dich: Ist im Mietvertrag nichts geregelt, gilt gesetzlich die Wohnfläche als Auffangschlüssel. [[heizkostenverordnung|Heizkosten]] müssen zwingend überwiegend nach Verbrauch verteilt werden. In der [[weg]] gibt es oft einen Doppelschlüssel (offizielle 1000stel vs. intern vereinbarte Verteilung). ImmoCalc rechnet die Verteilung exakt: Die Summe der Anteile ergibt immer die Gesamtkosten.',
    verwandt: ['nebenkosten', 'zaehler', 'heizkostenverordnung', 'weg', 'teilungserklaerung'],
  },
  {
    id: 'heizkostenverordnung',
    begriff: 'Heizkostenverordnung (HeizkostenV)',
    kategorie: 'nebenkosten',
    synonyme: ['HeizkostenV', 'HKVO', 'Grundkosten', 'Verbrauchskosten', '70/30-Regel'],
    kurz: 'Sie schreibt vor, dass Heiz- und Warmwasserkosten überwiegend nach Verbrauch abgerechnet werden — meist 70 % Verbrauch, 30 % Fläche.',
    lang:
      'Die Heizkostenverordnung verpflichtet dich, die Kosten für Heizung und Warmwasser nicht rein nach Fläche, sondern zu einem großen Teil nach dem gemessenen Verbrauch abzurechnen. Der Verbrauchsanteil muss zwischen 50 und 70 % liegen — üblich sind 70 % Verbrauch (nach [[zaehler]]) und 30 % Grundkosten (nach Fläche). Der Grundkostenanteil deckt Bereitschaft und Leitungsverluste.\n\n' +
      'Diese Aufteilung gibt es, um zum Energiesparen anzureizen: Wer wenig heizt, soll spürbar weniger zahlen. Ein reiner Flächenschlüssel würde den Sparsamen bestrafen und den Verschwender belohnen.\n\n' +
      'Für dich als Vermieter Pflicht, nicht Kür: Erfasst du nicht verbrauchsabhängig, darf der Mieter die Heizkosten um 15 % kürzen. Die Messung übernimmt meist ein Dienstleister (ista, Techem, Delta-T), der eine Heizkostenaufstellung liefert. Seit 2023 kommt die [[co2-kostenaufteilung]] hinzu. In ImmoCalc hinterlegst du den Grundkosten-/Verbrauchssplit je Heiz-Kostenart, die Engine teilt automatisch.',
    verwandt: ['zaehler', 'verteilerschluessel', 'nebenkosten', 'co2-kostenaufteilung'],
  },
  {
    id: 'vorauszahlung',
    begriff: 'Nebenkostenvorauszahlung',
    kategorie: 'nebenkosten',
    synonyme: ['Vorauszahlung', 'NK-Vorauszahlung', 'Abschlag', 'Betriebskostenvorauszahlung', 'Nachzahlung', 'Guthaben'],
    kurz: 'Der monatliche Abschlag, den der Mieter auf die Nebenkosten zahlt. Am Jahresende wird er gegen die tatsächlichen Kosten abgerechnet.',
    lang:
      'Die Vorauszahlung ist der monatlich mit der Miete gezahlte Abschlag auf die künftige [[nebenkosten|Nebenkostenabrechnung]]. Am Ende des Abrechnungsjahres stellst du die tatsächlichen umlagefähigen Kosten den geleisteten Vorauszahlungen gegenüber: War der Verbrauch höher, gibt es eine Nachzahlung; war er niedriger, ein Guthaben zurück.\n\n' +
      'Vorauszahlungen gibt es, weil die echten Kosten erst nach Jahresende feststehen, die Ausgaben aber laufend anfallen — der Abschlag verteilt die Last gleichmäßig übers Jahr und schützt dich vor einer großen offenen Forderung. Die Alternative wäre eine (seltene) Pauschale ohne Abrechnung.\n\n' +
      'Für dich: Setze die Vorauszahlung realistisch an — zu niedrig führt zu unangenehmen Nachforderungen, zu hoch bindet Geld des Mieters. Nach einer Abrechnung darfst du die Vorauszahlung anpassen. In der [[anlage-v]] sind sowohl Vorauszahlungen als auch das Abrechnungsergebnis Einnahmen. Beachte die Zwölf-Monats-Frist für die Abrechnung.',
    verwandt: ['nebenkosten', 'anlage-v', 'verteilerschluessel'],
  },
  {
    id: 'ruecklage',
    begriff: 'Instandhaltungsrücklage',
    kategorie: 'nebenkosten',
    synonyme: ['Instandhaltungsrücklage', 'Erhaltungsrücklage', 'Rücklage', 'Instandhaltungsrücklage WEG'],
    kurz: 'Das gemeinsame Sparbuch der Eigentümergemeinschaft für größere Reparaturen. Deine Einzahlung ist Teil des Hausgelds, aber nicht auf den Mieter umlegbar.',
    lang:
      'Die Instandhaltungsrücklage (heute: Erhaltungsrücklage) ist ein von der [[weg|Eigentümergemeinschaft]] angespartes Vermögen für größere Instandhaltungen am Gemeinschaftseigentum — Dach, Fassade, Heizung, Aufzug. Jeder Eigentümer zahlt über das [[hausgeld]] anteilig ein; der [[wirtschaftsplan]] und die Jahresabrechnung weisen Zuführung und Saldo aus.\n\n' +
      'Es gibt sie, damit teure Sanierungen nicht plötzlich als hohe Sonderumlage auf alle einprasseln, sondern über Jahre vorfinanziert sind. Sie ist die Vorsorge der Gemeinschaft gegen den Substanzverfall.\n\n' +
      'Für dich doppelt wichtig: Steuerlich ist deine Einzahlung noch keine [[werbungskosten|Werbungskosten]] — absetzbar wird sie erst, wenn die Rücklage tatsächlich für eine Reparatur verausgabt wird. Und sie ist *nicht* auf den Mieter [[umlagefaehigkeit|umlagefähig]]: Du musst das Hausgeld also in umlagefähige Betriebskosten und nicht umlagefähige Rücklage/Verwaltung zerlegen. Bei Kauf einer WEG-Wohnung: Der angesparte Rücklagenanteil steckt im Kaufpreis.',
    verwandt: ['weg', 'hausgeld', 'wirtschaftsplan', 'umlagefaehigkeit', 'werbungskosten'],
  },
  {
    id: 'weg',
    begriff: 'WEG (Wohnungseigentümergemeinschaft)',
    kategorie: 'nebenkosten',
    synonyme: ['Wohnungseigentümergemeinschaft', 'Eigentümergemeinschaft', 'Eigentümerversammlung', 'Verwalter', 'Beschluss'],
    kurz: 'Alle Eigentümer eines aufgeteilten Hauses zusammen. Sie verwalten das Gemeinschaftseigentum, tagen einmal im Jahr und beschließen mit Mehrheit.',
    lang:
      'Die WEG umfasst alle Eigentümer der Wohnungen eines Hauses, das per [[teilungserklaerung]] in Sonder- und Gemeinschaftseigentum aufgeteilt ist. Sie entscheidet gemeinsam über das Gemeinschaftseigentum — auf der jährlichen Eigentümerversammlung, per Mehrheitsbeschluss, meist umgesetzt durch einen bestellten Verwalter. Grundlage sind der [[wirtschaftsplan]], die Jahresabrechnung und das Wohnungseigentumsgesetz (WEG).\n\n' +
      'Diese Struktur gibt es, weil ein geteiltes Haus gemeinsame Teile hat, um die sich niemand allein kümmern kann: Dach, Fassade, Heizung, Treppenhaus. Ohne organisierte Gemeinschaft gäbe es für Reparaturen und Kosten keine verbindliche Willensbildung.\n\n' +
      'Für dich als Eigentümer einer Wohnung: Dein Stimmrecht und dein Kostenanteil richten sich nach dem Miteigentumsanteil. Du zahlst monatlich [[hausgeld]], das Betriebskosten *und* nicht umlagefähige Anteile ([[ruecklage]], Verwaltung) enthält — für die Mieterabrechnung musst du es zerlegen. Lies die Protokolle: Beschlüsse über Sonderumlagen oder Sanierungen treffen dich unmittelbar.',
    verwandt: ['hausgeld', 'wirtschaftsplan', 'ruecklage', 'teilungserklaerung', 'umlagefaehigkeit'],
  },
  {
    id: 'hausgeld',
    begriff: 'Hausgeld (Wohngeld)',
    kategorie: 'nebenkosten',
    synonyme: ['Wohngeld', 'Hausgeldvorauszahlung', 'WEG-Beitrag'],
    kurz: 'Der monatliche Beitrag, den du als Wohnungseigentümer an die WEG zahlst. Er deckt Betriebskosten, Verwaltung und Rücklagenzuführung.',
    lang:
      'Das Hausgeld ist die monatliche Vorauszahlung jedes Eigentümers an die [[weg]], festgelegt im [[wirtschaftsplan]]. Es enthält mehrere Bestandteile: die umlagefähigen Betriebskosten (Wasser, Heizung, Müll, Hausmeister, Versicherung), die nicht umlagefähigen Verwaltungskosten (Verwaltervergütung, Kontoführung) und die Zuführung zur [[ruecklage]].\n\n' +
      'Es gibt das Hausgeld, weil die laufenden Gemeinschaftskosten fortlaufend bezahlt werden müssen — die Gemeinschaft sammelt sie über die monatlichen Beiträge ein und rechnet am Jahresende über die Jahresabrechnung ab.\n\n' +
      'Für dich die zentrale Zerlegungsaufgabe: Nur der Betriebskostenanteil ist [[umlagefaehigkeit|umlagefähig]] und darf in die [[nebenkosten|Mieter-Nebenkostenabrechnung]] — Verwaltung und Rücklage bleiben bei dir (sind aber teils [[werbungskosten]]). Wer das Hausgeld ungeteilt auf den Mieter umlegt, rechnet falsch ab. Die WEG-Jahresabrechnung liefert dir die nötige Aufschlüsselung.',
    verwandt: ['weg', 'wirtschaftsplan', 'ruecklage', 'umlagefaehigkeit', 'nebenkosten'],
  },
  {
    id: 'wirtschaftsplan',
    begriff: 'Wirtschaftsplan',
    kategorie: 'nebenkosten',
    synonyme: ['WEG-Wirtschaftsplan', 'Jahresabrechnung', 'Hausgeldplan'],
    kurz: 'Der Haushaltsplan der Eigentümergemeinschaft fürs kommende Jahr. Aus ihm ergibt sich dein monatliches Hausgeld.',
    lang:
      'Der Wirtschaftsplan ist die von der [[weg]] beschlossene Vorschau auf die Einnahmen und Ausgaben des kommenden Wirtschaftsjahres. Er schätzt die Gesamtkosten (Betrieb, Verwaltung, Zuführung zur [[ruecklage]]) und verteilt sie über die Miteigentumsanteile auf die Eigentümer — daraus ergibt sich dein [[hausgeld]]. Am Jahresende folgt die Jahresabrechnung, die Plan und Ist gegenüberstellt.\n\n' +
      'Es gibt ihn, weil die Gemeinschaft ihre laufenden Kosten im Voraus finanzieren muss: Ohne geplante Beiträge wäre kein Geld für Heizung, Versicherung oder Hausmeister da. Er ist das Budget der WEG.\n\n' +
      'Für dich als Eigentümer: Der Wirtschaftsplan zeigt frühzeitig, was auf dich zukommt — vor allem geplante Instandhaltungen oder eine erhöhte Rücklagenzuführung. Er nennt oft granular je Kostenart die Verteilung, teils mit Doppelschlüssel (offizielle vs. interne 1000stel). Für deine Mieterabrechnung ist die *Jahresabrechnung* mit den Ist-Zahlen die Grundlage, nicht der Plan.',
    verwandt: ['weg', 'hausgeld', 'ruecklage', 'verteilerschluessel'],
  },
  {
    id: 'zaehler',
    begriff: 'Zähler (Verbrauchserfassung)',
    kategorie: 'nebenkosten',
    synonyme: ['Zählerstand', 'Wasserzähler', 'Stromzähler', 'Heizkostenverteiler', 'Eichfrist', 'Zählertausch'],
    kurz: 'Messgeräte für Wasser, Wärme, Strom oder Gas. Ihre Stände sind die Grundlage der verbrauchsabhängigen Abrechnung.',
    lang:
      'Zähler erfassen den tatsächlichen Verbrauch einer Einheit — Kaltwasser, Warmwasser, Wärme (Wärmemengenzähler oder Heizkostenverteiler), Strom, Gas. Aus der Differenz zweier Stände (Jahresanfang und -ende, oder bei Ein-/Auszug) ergibt sich der Verbrauch, der über den [[verteilerschluessel]] in die [[nebenkosten|Abrechnung]] einfließt.\n\n' +
      'Es gibt sie, weil verbrauchsabhängige Kosten nur mit Messung gerecht verteilt werden können — die [[heizkostenverordnung]] schreibt die Erfassung für Heizung und Warmwasser sogar zwingend vor. Ohne Zähler bliebe nur ein grober Flächenschlüssel.\n\n' +
      'Für dich: Führe die Zähler als Stammdaten mit Zählernummer und Eichfrist — Wasserzähler müssen regelmäßig geeicht oder getauscht werden, sonst sind ihre Werte anfechtbar. Beim Zählertausch mitten im Jahr addierst du die Verbräuche von altem und neuem Zähler. Die Stände zum Mieterwechsel gehören ins [[uebergabeprotokoll]]. ImmoCalc verwaltet Zähler je Einheit und rechnet die Differenzen aus.',
    verwandt: ['heizkostenverordnung', 'verteilerschluessel', 'nebenkosten', 'uebergabeprotokoll'],
  },
  {
    id: 'betriebskostenverordnung',
    begriff: 'Betriebskostenverordnung (BetrKV)',
    kategorie: 'nebenkosten',
    synonyme: ['BetrKV', 'Betriebskostenkatalog', '§ 2 BetrKV'],
    kurz: 'Die Verordnung, die abschließend auflistet, welche Kostenarten als umlagefähige Betriebskosten gelten.',
    lang:
      'Die Betriebskostenverordnung (BetrKV) definiert in ihrem § 2 einen Katalog von 17 Positionen, die als Betriebskosten gelten und damit grundsätzlich [[umlagefaehigkeit|umlagefähig]] sind: u. a. [[grundsteuer]], Wasserversorgung, Entwässerung, Heizung, Warmwasser, Aufzug, Straßenreinigung/Müll, Gebäudereinigung, Gartenpflege, Beleuchtung, Schornsteinreinigung, Versicherung, Hausmeister, Gemeinschaftsantenne und die „sonstigen Betriebskosten".\n\n' +
      'Diesen Katalog gibt es, um Klarheit zu schaffen: Was nicht in der Liste steht (Verwaltung, Instandhaltung, Reparaturen), ist keine Betriebskostenart und darf nicht auf den Mieter umgelegt werden.\n\n' +
      'Für dich als Vermieter der Prüfmaßstab jeder Position deiner [[nebenkosten|Abrechnung]]: Nur laufend anfallende Kosten aus dem Katalog gehören hinein. „Sonstige Betriebskosten" (Pos. 17, z. B. Wartung Rauchmelder) müssen im Mietvertrag ausdrücklich benannt sein. Einmalige Reparaturen bleiben immer bei dir und sind deine [[werbungskosten]].',
    verwandt: ['nebenkosten', 'umlagefaehigkeit', 'grundsteuer', 'werbungskosten'],
  },
  {
    id: 'co2-kostenaufteilung',
    begriff: 'CO₂-Kostenaufteilung',
    kategorie: 'nebenkosten',
    synonyme: ['CO2-Kosten', 'CO2KostAufG', 'CO₂-Preis', 'Stufenmodell'],
    kurz: 'Seit 2023 teilen sich Vermieter und Mieter den CO₂-Preis fürs Heizen — je schlechter das Gebäude gedämmt ist, desto mehr trägt der Vermieter.',
    lang:
      'Auf fossile Brennstoffe (Erdgas, Heizöl) wird ein CO₂-Preis erhoben, der im Brennstoffpreis steckt. Seit 2023 darf dieser Anteil nicht mehr allein auf den Mieter umgelegt werden: Ein Stufenmodell verteilt ihn zwischen Vermieter und Mieter nach dem CO₂-Ausstoß des Gebäudes pro Quadratmeter — je schlechter die energetische Qualität, desto höher der Vermieteranteil (bis 95 %), je besser, desto mehr trägt der Mieter (bis 100 %).\n\n' +
      'Diesen Split gibt es, um Anreize richtig zu setzen: Der Mieter kann durch sparsames Heizen etwas beeinflussen, die Dämmung des Gebäudes aber nur der Eigentümer — also soll auch er einen Teil des CO₂-Preises tragen und zum Sanieren bewegt werden.\n\n' +
      'Für dich als Vermieter eine neue Rechenpflicht in der [[heizkostenverordnung|Heizkostenabrechnung]]: Aus der Brennstoffrechnung den CO₂-Anteil herauslösen, die Kennzahl (kg CO₂/m²) bestimmen, die Stufe ablesen und den Vermieteranteil von den umlagefähigen [[nebenkosten]] abziehen. Der Dienstleister liefert die Werte oft mit.',
    verwandt: ['heizkostenverordnung', 'nebenkosten', 'verteilerschluessel'],
  },
  // ------------------------------------------------------------------- Vermietung
  {
    id: 'kaltmiete',
    begriff: 'Kaltmiete (Nettokaltmiete)',
    kategorie: 'miete',
    synonyme: ['Nettokaltmiete', 'Grundmiete', 'Nettomiete', 'Warmmiete', 'Bruttomiete'],
    kurz: 'Die reine Miete für die Wohnung ohne Nebenkosten. Sie ist die Basis für Mieterhöhungen und deine wichtigste Einnahme.',
    lang:
      'Die Kaltmiete (Nettokaltmiete) ist das Entgelt für die reine Überlassung der Wohnung — ohne Betriebs- und Heizkosten. Kommt die [[vorauszahlung|Nebenkostenvorauszahlung]] hinzu, ergibt sich die Warmmiete, die der Mieter monatlich überweist. Die Kaltmiete ist die Bezugsgröße für [[mietspiegel]], [[kappungsgrenze]], [[staffelmiete|Staffel-]] und [[indexmiete]].\n\n' +
      'Diese Trennung gibt es, weil nur die Kaltmiete dein echter Ertrag ist — die Nebenkosten sind durchlaufende Posten, die du an Versorger und Gemeinde weiterreichst. Mieterhöhungen und gesetzliche Grenzen knüpfen deshalb immer an der Kaltmiete an.\n\n' +
      'Für dich die wichtigste Einnahmezeile: In der [[anlage-v]] und im [[cashflow]] zählt die Kaltmiete als Ertrag, die umlagefähigen Nebenkosten heben sich als Einnahme und Ausgabe auf. Achte bei Neuvermietung auf die ortsübliche Vergleichsmiete (siehe [[mietspiegel]]) und regionale [[mietpreisbremse|Mietpreisbremse]].',
    verwandt: ['vorauszahlung', 'mietspiegel', 'staffelmiete', 'indexmiete', 'cashflow'],
  },
  {
    id: 'kaution',
    begriff: 'Mietkaution',
    kategorie: 'miete',
    synonyme: ['Mietsicherheit', 'Kaution', 'Barkaution', 'Kautionskonto'],
    kurz: 'Eine Sicherheit des Mieters für Schäden oder offene Forderungen — höchstens drei Nettokaltmieten, getrennt vom Vermietervermögen anzulegen.',
    lang:
      'Die Kaution ist eine Sicherheit, die der Mieter zu Beginn stellt, damit du am Ende offene Forderungen (Mietrückstände, Schäden über normale Abnutzung hinaus, Nebenkostennachzahlungen) daraus decken kannst. Sie beträgt höchstens drei [[kaltmiete|Nettokaltmieten]] und darf in drei Monatsraten gezahlt werden.\n\n' +
      'Es gibt sie, weil du sonst bei Auszug mit Schäden oder Schulden allein dastündest. Sie ist bewusst gedeckelt und geschützt, damit sie den Mieter nicht überfordert und im Streitfall verfügbar bleibt.\n\n' +
      'Für dich wichtige Pflichten: Die Barkaution musst du getrennt von deinem Vermögen und insolvenzfest anlegen (eigenes Kautionskonto), die Zinsen stehen dem Mieter zu. Statt bar ist auch eine Bürgschaft oder Verpfändung möglich. Nach Auszug hast du eine angemessene Frist (Rechtsprechung: bis zu sechs Monate) zur Abrechnung, für eine noch ausstehende [[nebenkosten|Nebenkostenabrechnung]] darfst du einen Teil einbehalten. Der Einbehalt und die Rückgabe gehören dokumentiert.',
    verwandt: ['kaltmiete', 'uebergabeprotokoll', 'nebenkosten'],
  },
  {
    id: 'staffelmiete',
    begriff: 'Staffelmiete',
    kategorie: 'miete',
    synonyme: ['Staffelmietvertrag', 'Mietstaffel'],
    kurz: 'Eine Miete, deren Erhöhungen von vornherein mit festen Beträgen und Terminen im Vertrag stehen. Planbar für beide Seiten.',
    lang:
      'Bei der Staffelmiete vereinbart ihr schon im Mietvertrag, wann und um welchen festen Betrag die [[kaltmiete]] steigt — etwa jährlich um einen bestimmten Euro-Betrag. Jede Stufe muss betragsmäßig oder als Endbetrag angegeben sein; zwischen zwei Staffeln muss mindestens ein Jahr liegen.\n\n' +
      'Diese Form gibt es, weil sie Planungssicherheit schafft: Beide wissen für Jahre im Voraus, was zu zahlen ist, ohne dass du jedes Mal eine Mieterhöhung begründen und den [[mietspiegel]] bemühen musst.\n\n' +
      'Für dich: Während der Staffel sind zusätzliche Erhöhungen (etwa bis zur ortsüblichen Vergleichsmiete) ausgeschlossen — die Staffel ist abschließend. In Gebieten mit [[mietpreisbremse|Mietpreisbremse]] muss auch jede Staffel die zulässige Grenze einhalten. Die Alternative mit Inflationsbindung ist die [[indexmiete]].',
    verwandt: ['kaltmiete', 'indexmiete', 'mietspiegel', 'mietpreisbremse'],
  },
  {
    id: 'indexmiete',
    begriff: 'Indexmiete',
    kategorie: 'miete',
    synonyme: ['Indexmietvertrag', 'indexierte Miete', 'Verbraucherpreisindex'],
    kurz: 'Eine Miete, die an den Verbraucherpreisindex gekoppelt ist: Steigt die Inflation, darf die Miete entsprechend angehoben werden.',
    lang:
      'Bei der Indexmiete wird die [[kaltmiete]] an den Verbraucherpreisindex des Statistischen Bundesamts gekoppelt. Steigt der Index, darfst du die Miete im gleichen Verhältnis erhöhen — frühestens ein Jahr nach der letzten Anpassung, per Erklärung in Textform mit Angabe der Indexwerte.\n\n' +
      'Diese Bindung gibt es, um die Miete real stabil zu halten: Sie gleicht die Geldentwertung aus, ohne dass du die ortsübliche Vergleichsmiete oder den [[mietspiegel]] heranziehen musst. In Zeiten hoher Inflation ist sie für Vermieter attraktiv.\n\n' +
      'Für dich: Während der Indexbindung sind Erhöhungen nach Vergleichsmiete oder wegen [[modernisierungsumlage|Modernisierung]] grundsätzlich ausgeschlossen (Ausnahme: gesetzlich veranlasste Maßnahmen). Die Erhöhung erfolgt nicht automatisch — du musst sie aktiv erklären. Die planbare Alternative ohne Inflationsrisiko ist die [[staffelmiete]].',
    verwandt: ['kaltmiete', 'staffelmiete', 'mietspiegel', 'modernisierungsumlage'],
  },
  {
    id: 'kappungsgrenze',
    begriff: 'Kappungsgrenze',
    kategorie: 'miete',
    synonyme: ['Kappungsgrenze 20', 'Kappungsgrenze 15', 'Mieterhöhungsgrenze'],
    kurz: 'Die Obergrenze, um die du eine laufende Miete innerhalb von drei Jahren anheben darfst — höchstens 20 %, in angespannten Lagen 15 %.',
    lang:
      'Die Kappungsgrenze begrenzt Mieterhöhungen im bestehenden Mietverhältnis: Bei Anhebung bis zur ortsüblichen Vergleichsmiete darf die [[kaltmiete]] innerhalb von drei Jahren um höchstens 20 % steigen — in Gebieten mit angespanntem Wohnungsmarkt, die die Länder festlegen, nur um 15 %.\n\n' +
      'Diese Grenze gibt es, um Mieter vor sprunghaften Erhöhungen zu schützen: Selbst wenn die Vergleichsmiete deutlich höher liegt, darf die Anpassung nur in gedeckelten Schritten erfolgen. Sie wirkt zusätzlich zur Bindung an den [[mietspiegel]].\n\n' +
      'Für dich als Vermieter: Die Kappungsgrenze betrifft nur laufende Verträge, nicht die Neuvermietung (dort greift die [[mietpreisbremse]]). Bei [[staffelmiete]] und [[indexmiete]] gilt sie nicht, ebenso wenig für [[modernisierungsumlage|Modernisierungserhöhungen]]. Prüfe vor jeder Erhöhung: erlaubt der Mietspiegel den Betrag *und* hält er die Kappungsgrenze ein?',
    verwandt: ['kaltmiete', 'mietspiegel', 'mietpreisbremse', 'staffelmiete'],
  },
  {
    id: 'mietspiegel',
    begriff: 'Mietspiegel & ortsübliche Vergleichsmiete',
    kategorie: 'miete',
    synonyme: ['ortsübliche Vergleichsmiete', 'qualifizierter Mietspiegel', 'einfacher Mietspiegel'],
    kurz: 'Eine Übersicht der ortsüblichen Mieten nach Lage, Größe, Baujahr und Ausstattung. Sie begründet Mieterhöhungen und begrenzt die Neuvermietungsmiete.',
    lang:
      'Der Mietspiegel bildet die ortsübliche Vergleichsmiete ab — die üblichen Entgelte für Wohnraum vergleichbarer Art, Größe, Ausstattung, Beschaffenheit und Lage in der Gemeinde. Er wird von Kommune und Interessenverbänden erstellt, als einfacher oder als qualifizierter (methodisch fundierter, alle zwei Jahre fortgeschriebener) Mietspiegel.\n\n' +
      'Es gibt ihn, um Mieterhöhungen und die zulässige Neuvermietungsmiete objektiv begründbar zu machen: Statt Willkür gibt es eine nachvollziehbare Referenz, auf die sich beide Seiten und die Gerichte stützen.\n\n' +
      'Für dich das zentrale Werkzeug: Eine Erhöhung bis zur ortsüblichen Vergleichsmiete begründest du mit dem Mietspiegel (dazu muss die [[kappungsgrenze]] eingehalten sein). Bei Neuvermietung in Gebieten mit [[mietpreisbremse]] darf die [[kaltmiete]] höchstens 10 % über der ortsüblichen Vergleichsmiete liegen. In Orten ohne Mietspiegel behilft man sich mit Vergleichswohnungen oder einem Gutachten.',
    verwandt: ['kaltmiete', 'kappungsgrenze', 'mietpreisbremse', 'staffelmiete'],
  },
  {
    id: 'modernisierungsumlage',
    begriff: 'Modernisierungsumlage (§ 559 BGB)',
    kategorie: 'miete',
    synonyme: ['Modernisierungsmieterhöhung', '§ 559 BGB', 'Modernisierung'],
    kurz: 'Nach einer wertsteigernden oder energiesparenden Modernisierung darfst du einen Teil der Kosten dauerhaft auf die Kaltmiete umlegen.',
    lang:
      'Nach einer echten Modernisierung — energetische Sanierung, Einbau neuer Ausstattung, nachhaltige Wohnwertverbesserung — darfst du jährlich 8 % der aufgewendeten Kosten dauerhaft auf die [[kaltmiete]] umlegen (§ 559 BGB). Reine Instandhaltung/Reparatur zählt nicht mit und muss herausgerechnet werden. Die Erhöhung ist zusätzlich betragsmäßig gekappt (einige Euro je m² über mehrere Jahre).\n\n' +
      'Diese Umlage gibt es, weil Modernisierungen dem Mieter zugutekommen (geringere Heizkosten, mehr Komfort) und du sonst keinen Anreiz hättest zu investieren. Sie beteiligt den Mieter an der Wertverbesserung.\n\n' +
      'Für dich: Die Maßnahme muss vorher angekündigt werden (Umfang, Kosten, künftige Miete), und die Kappungsgrenzen sind einzuhalten. Der modernisierungsbedingte Teil ist von der Instandhaltung abzugrenzen — nur der echte Modernisierungsanteil ist umlagefähig. Steuerlich sind die Kosten je nach Art [[werbungskosten]] oder erhöhen über [[anschaffungskosten]] die [[afa]]. Bei [[indexmiete]] ist die Umlage in der Regel ausgeschlossen.',
    verwandt: ['kaltmiete', 'kappungsgrenze', 'werbungskosten', 'indexmiete'],
  },
  {
    id: 'uebergabeprotokoll',
    begriff: 'Übergabeprotokoll',
    kategorie: 'miete',
    synonyme: ['Wohnungsübergabeprotokoll', 'Abnahmeprotokoll Mieter', 'Einzugsprotokoll', 'Auszugsprotokoll'],
    kurz: 'Das Protokoll bei Ein- und Auszug: Zustand der Räume und Zählerstände werden festgehalten — die Beweisgrundlage für Schäden und Abrechnung.',
    lang:
      'Das Übergabeprotokoll dokumentiert beim Ein- und Auszug den Zustand der Wohnung Raum für Raum (Mängel, Beschädigungen) und die [[zaehler|Zählerstände]] für Wasser, Wärme, Strom und Gas zum Stichtag. Beide Seiten unterschreiben. Es ist nicht mit der baurechtlichen [[abnahme]] eines Neubaus zu verwechseln.\n\n' +
      'Es gibt das Protokoll, weil bei Auszug sonst Streit droht: Ohne festgehaltenen Anfangszustand lässt sich kaum belegen, ob ein Schaden neu ist oder schon bestand. Die Zählerstände wiederum trennen sauber, welcher Mieter welchen Verbrauch trägt.\n\n' +
      'Für dich praktisch unverzichtbar: Es ist die Grundlage, um berechtigte Schäden von der [[kaution]] einzubehalten, und liefert die exakten Zählerstände für die verbrauchsgenaue [[nebenkosten|Nebenkostenabrechnung]] bei unterjährigem Mieterwechsel. Fotografiere den Zustand, notiere jeden Zähler mit Nummer und Stand. In ImmoCalc hinterlegst du die Übergabestände je Mietverhältnis.',
    verwandt: ['zaehler', 'kaution', 'nebenkosten', 'abnahme'],
  },
  {
    id: 'mietpreisbremse',
    begriff: 'Mietpreisbremse',
    kategorie: 'miete',
    synonyme: ['Mietpreisbegrenzung', '§ 556d BGB', 'angespannter Wohnungsmarkt'],
    kurz: 'In ausgewiesenen Gebieten darf die Miete bei Neuvermietung höchstens 10 % über der ortsüblichen Vergleichsmiete liegen.',
    lang:
      'Die Mietpreisbremse begrenzt die zulässige [[kaltmiete]] bei Neuvermietung: In Gebieten mit angespanntem Wohnungsmarkt, die die Länder per Verordnung ausweisen, darf die neue Miete höchstens 10 % über der ortsüblichen Vergleichsmiete (siehe [[mietspiegel]]) liegen. Ausnahmen gelten u. a. für Neubauten und umfassend modernisierte Wohnungen.\n\n' +
      'Diese Regel gibt es, weil bei Mieterwechsel die [[kappungsgrenze]] nicht greift und die Mieten in knappen Märkten sonst mit jedem Wechsel sprunghaft steigen würden. Sie soll bezahlbaren Wohnraum in Ballungsräumen erhalten.\n\n' +
      'Für dich als Vermieter: Prüfe vor der Neuvermietung, ob dein Objekt in einem ausgewiesenen Gebiet liegt, und begründe die Miete am Mietspiegel. Lag die Vormiete bereits höher, darfst du sie meist halten (Bestandsschutz). Bei einer [[staffelmiete]] muss jede Stufe die Grenze wahren. Verstöße kann der Mieter rügen und zu viel Gezahltes zurückfordern.',
    verwandt: ['kaltmiete', 'mietspiegel', 'kappungsgrenze', 'staffelmiete'],
  },
  // ---------------------------------------------------------------- Wert & Rendite
  {
    id: 'verkehrswert',
    begriff: 'Verkehrswert (Marktwert)',
    kategorie: 'wert',
    synonyme: ['Marktwert', 'Beleihungswert', 'Ertragswert', 'Sachwert', 'Wertermittlung'],
    kurz: 'Der Preis, der für die Immobilie am Markt realistisch zu erzielen wäre. Grundlage für Beleihung, Verkauf und Vermögensbilanz.',
    lang:
      'Der Verkehrswert (Marktwert) ist der Preis, der zu einem Stichtag im gewöhnlichen Geschäftsverkehr für die Immobilie erzielbar wäre — unabhängig von Zwang oder persönlichen Verhältnissen. Für vermietete Objekte ist meist das Ertragswertverfahren maßgeblich (Wert aus den nachhaltigen Mieterträgen), daneben gibt es Sachwert- und Vergleichswertverfahren. Die Bank rechnet zusätzlich mit einem vorsichtigeren Beleihungswert.\n\n' +
      'Den Verkehrswert braucht man, weil eine Immobilie keinen amtlichen Kurs hat — anders als eine Aktie muss ihr Wert jedes Mal geschätzt werden, für Kauf, Verkauf, Finanzierung, Erbschaft oder Bilanz.\n\n' +
      'Für dich mehrfach relevant: Er bestimmt zusammen mit der [[restschuld]] die [[beleihung]] und damit deinen Zins, er ist die Basis deiner Vermögensbilanz ([[eigenkapital]] = Wert minus Schulden) und der Maßstab beim Verkauf. Lasten wie eine [[dienstbarkeit]] oder ein knappes [[erbbaurecht]] mindern ihn. In ImmoCalc pflegst du den geschätzten Wert und siehst die Wertentwicklung über die Zeit.',
    verwandt: ['eigenkapital', 'beleihung', 'restschuld', 'rendite', 'anschaffungskosten'],
  },
  {
    id: 'eigenkapital',
    begriff: 'Eigenkapital',
    kategorie: 'wert',
    synonyme: ['Eigenmittel', 'Eigenkapitalquote', 'gebundenes Eigenkapital'],
    kurz: 'Dein eigenes Geld im Objekt — beim Kauf die Eigenmittel, laufend der Wert minus Restschuld.',
    lang:
      'Eigenkapital ist der Teil der Immobilie, der dir wirtschaftlich gehört und nicht der Bank. Beim Kauf sind es die eingebrachten Eigenmittel (für [[kaufnebenkosten]] und einen Teil des Kaufpreises). Laufend ergibt es sich als [[verkehrswert]] minus [[restschuld]]: Es wächst mit jeder [[tilgung]] und mit steigendem Objektwert. Ein angespartes [[bausparvertrag|Bausparguthaben]] zählt ebenfalls dazu.\n\n' +
      'Auf das Eigenkapital kommt es an, weil kaum jemand komplett fremdfinanziert kauft und weil die Bank eine Risikobeteiligung erwartet. Es ist Puffer und Hebel zugleich.\n\n' +
      'Für dich in zwei Richtungen: Mehr Eigenkapital senkt über die [[beleihung]] den Zinssatz und die Rate — ein doppelter Vorteil. Zu viel gebundenes Eigenkapital drückt aber die Eigenkapitalrendite (der Sinn des Kredithebels ist ja, mit wenig Eigenem viel zu bewegen). Die Kunst ist die Balance. In der Vermögensübersicht ist das Eigenkapital deine eigentliche Vermögensposition im Objekt.',
    verwandt: ['verkehrswert', 'restschuld', 'beleihung', 'kaufnebenkosten', 'rendite'],
  },
  {
    id: 'cashflow',
    begriff: 'Cashflow (Liquidität)',
    kategorie: 'wert',
    synonyme: ['Liquidität', 'Überschuss', 'monatlicher Überschuss', 'Cashflow nach Steuern'],
    kurz: 'Was am Monatsende real übrig bleibt: Mieteinnahmen minus Kapitaldienst und nicht umlegbare Kosten. Positiv heißt, die Immobilie trägt sich selbst.',
    lang:
      'Der Cashflow ist die tatsächliche Geldbewegung deiner Immobilie: die Einnahmen (vor allem [[kaltmiete]]) minus alle Auszahlungen — [[kapitaldienst]] (Zins und [[tilgung]]), nicht umlagefähige [[nebenkosten]], Verwaltung, Rücklagenbildung. Umlagefähige Nebenkosten sind neutral (Einnahme = Ausgabe). Rechnet man die Steuerwirkung ein, ergibt sich der Cashflow nach Steuern.\n\n' +
      'Auf den Cashflow kommt es an, weil er zeigt, ob dich die Immobilie monatlich Geld kostet oder einbringt — anders als das steuerliche Ergebnis der [[anlage-v]], das durch die [[afa]] oft negativ ist, obwohl real Geld übrig bleibt (die AfA ist ein Papieraufwand ohne Geldabfluss).\n\n' +
      'Für dich die Liquiditätswahrheit: Ein negativer Cashflow (Unterdeckung) muss aus anderem Einkommen zugeschossen werden — dauerhaft riskant. Achtung bei der Trennung: Die [[tilgung]] mindert den Cashflow, ist aber Vermögensaufbau; ein [[bausparvertrag|Bausparsparbeitrag]] dagegen sollte den Cashflow nicht als Kosten belasten. ImmoCalc stellt Cashflow und Vermögensaufbau getrennt dar.',
    verwandt: ['kaltmiete', 'kapitaldienst', 'tilgung', 'nebenkosten', 'anlage-v', 'rendite'],
  },
  {
    id: 'rendite',
    begriff: 'Rendite (Brutto, Netto, Eigenkapital)',
    kategorie: 'wert',
    synonyme: ['Bruttomietrendite', 'Nettomietrendite', 'Eigenkapitalrendite', 'Mietrendite', 'Kaufpreisfaktor'],
    kurz: 'Wie viel Ertrag die Immobilie im Verhältnis zum eingesetzten Geld bringt. Brutto grob, netto ehrlich, auf das Eigenkapital am aussagekräftigsten.',
    lang:
      'Die Rendite misst den Ertrag deiner Investition. Die Bruttomietrendite setzt die Jahres-[[kaltmiete]] ins Verhältnis zum Kaufpreis — eine schnelle, grobe Kennzahl (der Kehrwert ist der Kaufpreisfaktor, „das X-fache der Jahresmiete"). Die Nettomietrendite berücksichtigt zusätzlich [[kaufnebenkosten]] und nicht umlagefähige Kosten und ist realistischer. Die Eigenkapitalrendite schließlich bezieht den Überschuss auf dein tatsächlich eingesetztes [[eigenkapital]] und zeigt die Wirkung des Kredithebels.\n\n' +
      'Renditekennzahlen gibt es, um Objekte und Alternativen vergleichbar zu machen: Ohne sie sagt ein Kaufpreis nichts darüber, ob sich die Investition lohnt.\n\n' +
      'Für dich: Die Bruttorendite eignet sich nur zum groben Sortieren — entscheidend sind Netto- und Eigenkapitalrendite. Der Kredithebel kann die Eigenkapitalrendite deutlich über die Objektrendite heben, solange die Mietrendite über dem [[sollzins]] liegt (positiver Leverage); dreht sich das, wirkt der Hebel gegen dich. Betrachte Rendite immer zusammen mit [[cashflow]] und Wertentwicklung ([[verkehrswert]]).',
    verwandt: ['kaltmiete', 'eigenkapital', 'cashflow', 'verkehrswert', 'kaufnebenkosten'],
  },
];

export const ABLAUF = [
  {
    id: 'entscheidung',
    phase: 1,
    titel: 'Kaufentscheidung & Budget',
    kurz: 'Objekt und Lage prüfen, Budget aus Eigenkapital und tragbarer Rate ableiten, Kaufnebenkosten einplanen.',
    dauer: 'Wochen',
    begriffe: ['eigenkapital', 'kaufnebenkosten', 'beleihung', 'verkehrswert'],
  },
  {
    id: 'finanzierung',
    phase: 2,
    titel: 'Finanzierung klären',
    kurz: 'Darlehen vergleichen, Zinsbindung und Tilgung festlegen, Finanzierungszusage einholen.',
    dauer: 'Wochen',
    begriffe: ['zinsbindung', 'annuitaet', 'tilgung', 'sollzins', 'anschlusszins', 'bausparvertrag'],
  },
  {
    id: 'kaufvertrag',
    phase: 3,
    titel: 'Notartermin & Kaufvertrag',
    kurz: 'Der Kauf wird notariell beurkundet. Beim Neubau ist es ein Bauträgervertrag mit Ratenplan nach Baufortschritt.',
    dauer: '1 Termin',
    begriffe: ['notar', 'bautraeger', 'mabv', 'grundbuch'],
  },
  {
    id: 'vormerkung',
    phase: 4,
    titel: 'Auflassungsvormerkung',
    kurz: 'Eine Vormerkung im Grundbuch sichert deinen Anspruch auf das Eigentum, bis die Umschreibung erfolgt.',
    dauer: 'Tage',
    begriffe: ['auflassung', 'grundbuch'],
  },
  {
    id: 'grunderwerbsteuer',
    phase: 5,
    titel: 'Grunderwerbsteuer',
    kurz: 'Das Finanzamt setzt die Grunderwerbsteuer fest. Erst nach Zahlung kommt die Unbedenklichkeitsbescheinigung.',
    dauer: 'Wochen',
    begriffe: ['grunderwerbsteuer', 'kaufnebenkosten'],
  },
  {
    id: 'grundschuld-bestellen',
    phase: 6,
    titel: 'Grundschuld bestellen',
    kurz: 'Für die Bank wird die Grundschuld notariell bestellt und ins Grundbuch eingetragen — die Sicherheit für den Kredit.',
    dauer: 'Tage bis Wochen',
    begriffe: ['grundschuld', 'rang', 'brief-buchgrundschuld'],
  },
  {
    id: 'kaufpreisraten',
    phase: 7,
    titel: 'Kaufpreis (in Raten) zahlen',
    kurz: 'Beim Neubau fließt der Kaufpreis in Raten nach Baufortschritt (MaBV). Das Darlehen wird dafür nach und nach abgerufen.',
    dauer: 'über die Bauzeit',
    begriffe: ['mabv', 'bereitstellungszins'],
  },
  {
    id: 'bauphase',
    phase: 8,
    titel: 'Bauphase',
    kurz: 'Das Objekt entsteht. Baufortschritt dokumentieren, Bereitstellungszinsen im Blick behalten.',
    dauer: 'Monate',
    begriffe: ['bautraeger', 'bereitstellungszins'],
  },
  {
    id: 'abnahme',
    phase: 9,
    titel: 'Abnahme & Mängel',
    kurz: 'Bei der Abnahme prüfst du das Werk. Mängel werden protokolliert; das Abnahmedatum startet die Gewährleistungsfrist.',
    dauer: '1 Termin',
    begriffe: ['abnahme', 'gewaehrleistung'],
  },
  {
    id: 'eigentumsumschreibung',
    phase: 10,
    titel: 'Eigentumsumschreibung',
    kurz: 'Nach Zahlung und Unbedenklichkeitsbescheinigung wirst du als Eigentümer ins Grundbuch eingetragen.',
    dauer: 'Wochen',
    begriffe: ['auflassung', 'grundbuch'],
  },
  {
    id: 'uebergabe',
    phase: 11,
    titel: 'Übergabe & Vermietung',
    kurz: 'Übergabe mit Protokoll und Zählerständen, dann Vermietung: Mietvertrag, Kaution, laufende Miete.',
    dauer: 'Tage',
    begriffe: ['uebergabeprotokoll', 'kaltmiete', 'kaution'],
  },
  {
    id: 'laufend',
    phase: 12,
    titel: 'Laufender Betrieb',
    kurz: 'Ab jetzt: Nebenkosten abrechnen, Rücklage bilden, Steuer über die Anlage V (AfA, Schuldzinsen, Werbungskosten).',
    dauer: 'jährlich',
    begriffe: ['nebenkosten', 'ruecklage', 'afa', 'schuldzinsen', 'anlage-v'],
  },
];
