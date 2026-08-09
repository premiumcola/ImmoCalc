/* N183 — Erklaertexte in Info-Popups.

   Statt einer Textwand am Kartenanfang sitzt ein kleines i im Titel; ein Tap
   zeigt den Text als Popover.

   N288 — die Mechanik dahinter (Karte/Blatt, Escape, Klick daneben, und der
   Wirt: naechster offener <dialog> statt immer `document.body`) liegt jetzt
   einmal in `../infopopup.js`. Hier bleiben nur noch die Texte. */
import { infoModul } from '../infopopup.js';

const INFOS = {
  verlauf: { titel: 'Verlauf', text:
    'Die Anschaffung steht als negativer Betrag da und wird Jahr für Jahr '
    + 'aufgefressen: von der Direktnutzung (PV-Strom, den die Mieter bezahlt '
    + 'haben), der Einspeisevergütung und dem E-Tanken. Diese Werte kommen live '
    + 'aus den Nebenkostenjahren; der Balken davor ist der Vorlauf aus den '
    + 'Stammdaten — die Zeit vor der ersten Abrechnung. Durchstößt der Balken '
    + 'die Nulllinie, ist die Anlage amortisiert.' },
  verbrauchsseite: { titel: 'Verbrauchsseite', text:
    'Woher der im Haus verbrauchte Strom kam. Aus diesen drei Mengen zieht die '
    + 'Stromkette im Nebenkostenzeitraum ihre Anteile, und aus ihnen kommt die '
    + 'Autarkiequote.' },
  erzeugerseite: { titel: 'Erzeugerseite', text:
    'Was die Anlage produziert hat und wie viel davon wirklich ins Netz ging — '
    + 'dafür zahlt der Netzbetreiber. In Verbrauch und Autarkie geht diese Seite '
    + 'nicht ein. Ohne eigenen Betrag folgt die Vergütung den EEG-Stufen '
    + '(0–10 kWp 8,2 ct, 10–40 kWp 7,1 ct) auf Basis der Anlagenleistung aus '
    + 'den Stammdaten.' },
  tankstelle: { titel: 'E-Tankstelle', text:
    'Der E-Auto-Strom gehört der PV-Anlage: er wird der ladenden Person '
    + 'berechnet und zahlt auf die Amortisation ein. Der Satz je kWh wird aus '
    + 'den Stromkosten des Abrechnungszeitraums abgeleitet — Netzstrom zum '
    + 'Durchschnittspreis des Netzbezugs, eigener Strom 10 % darunter. Er steht '
    + 'bei der E-Tankstelle.' },
  eigentuemer: { titel: 'PV-Eigentümer', text:
    'Die PV-Anlage ist ein eigenes Investment: sie kann anderen gehören als das '
    + 'Haus. Zugeordnet wird aus den vorhandenen Eigentümern, die Anteile werden '
    + 'in Tausendsteln (‰) vergeben. Ohne Zuordnung gilt die Vorgabe 5/6 + 1/6.\n\n'
    + 'Darunter die Jahresabrechnung: was die Anlage GENAU in diesem Jahr zur '
    + 'Amortisation beigetragen hat, nach denselben ‰ verteilt — nicht der '
    + 'kumulierte Stand von oben in der Kurve. Ein Klick verschickt sie als '
    + 'Mail; ein bereits verschicktes Jahr lässt sich nicht doppelt senden.' },
};

const modul = infoModul(INFOS);

export const infoKnopf = modul.infoKnopf;
export const infoOeffnen = modul.infoOeffnen;
export const infoSchliessen = modul.infoSchliessen;

/* strom.html bringt keinen eigenen Klick-Faenger mit — der kommt von hier. */
modul.faengerAnhaengen();
