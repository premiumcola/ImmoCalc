/* N181 — Erklärtexte in Info-Popups. Die langen Fließtexte am Kartenanfang
   wandern hinter ein kleines i am jeweiligen Titel; ein Tap zeigt den Text als
   Popover.

   N288 — die Mechanik dahinter (Karte/Blatt, Escape, Klick daneben, und der
   Wirt: nächster offener <dialog> statt immer `document.body`) liegt jetzt
   einmal in `../infopopup.js`. Hier bleiben nur noch die Texte.

   Den Klick-Fänger bringt tankstelle.html selbst mit — deshalb wird hier
   bewusst keiner angehängt, sonst liefe jeder Klick doppelt. */
import { infoModul } from '../infopopup.js';

export const INFOS = {
  verlauf: { titel: 'Verlauf', text:
    'Wie viel je Monat geladen wurde — und woher der Strom kam: zugekaufter '
    + 'Netzstrom, eigener Strom direkt vom Dach und aus dem Akku. Über alle '
    + 'Monate hinweg, nicht nur über ein Jahr. Die Zahlen holt die Wallbox '
    + 'selbst; fehlt sie, treten die erfassten Ladungen an ihre Stelle.' },
  abrechnung: { titel: 'Abrechnung', text:
    'Was jeder Nutzer geladen hat, zu welchem Satz und was er zahlt. Der Satz '
    + 'wird nicht eingegeben, sondern aus den Stromkosten des Zeitraums '
    + 'gerechnet: Netzstrom zu seinem Durchschnittspreis — Rechnungsbetrag '
    + 'geteilt durch die bezogenen kWh, Grundgebühr inbegriffen — und eigener '
    + 'Strom aus PV und Akku etwas darunter. Vor dem Versand zeigt die Vorschau, '
    + 'was ankommt.' },
  zuordnen: { titel: 'Ladungen zuordnen', text:
    'Die Wallbox weiß, wie viel geladen wurde — aber nicht, von wem. Diese '
    + 'Zuordnung ist die Grundlage der Abrechnung. Bei mehreren Nutzern: leg je '
    + 'Person einen Zeitraum fest, statt jede Ladung einzeln zuzuordnen. Jede '
    + 'Ladung geht an den, in dessen Zeitraum ihr Datum fällt. Einzelne Ladungen '
    + 'schließt du unten aus.' },
  nutzer: { titel: 'Nutzer', text:
    'Wer an dieser Ladestation lädt. Beliebig viele, jederzeit ergänzbar — und '
    + 'nicht zwangsläufig Eigentümer der Immobilie. Die E-Mail-Adresse braucht '
    + 'es für die Quartalsabrechnung.' },
  autoversand: { titel: 'Automatisch verschicken', text:
    'Einen Tag nach Quartalsende geht die Abrechnung automatisch an jeden '
    + 'Nutzer mit Adresse, Ladung und Satz — als Mail mit PDF im Anhang.' },
};

const modul = infoModul(INFOS);

export const infoKnopf = modul.infoKnopf;
export const infoKnopfText = modul.infoKnopfText;
export const infoOeffnen = modul.infoOeffnen;
export const infoSchliessen = modul.infoSchliessen;
