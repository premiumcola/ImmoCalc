/* N340f — Konfig-Ebene der Heizungszähler.

   Der Messdienst wird abgelöst; seine Zuordnung „welcher Zähler gehört zu
   welchem Nutzer" verschwindet damit. Sie muss einmal hier stehen — mit
   sprechenden Namen statt blosser Nummern, denn „5059" sagt niemandem, dass
   der Heizkörper im Wohnzimmer gemeint ist.

   Bewusst ohne Datenbank: das Ganze liegt im Browser (localStorage) und ist
   damit genauso schnell wieder weg wie die Seite selbst. Steht der Rechenweg,
   wandert die Zuordnung in die richtigen Zähler-Tabellen. */

const SPEICHER = 'immocalc.waermesim.zaehler.v1';

/* Die Geräte, wie sie in den Delta-t-Abrechnungen stehen. Nummer, Art und —
   wo bekannt — der Bewertungsfaktor des Heizkörpers. Der Faktor hängt an der
   Bauart und Grösse des Heizkörpers, nicht am Raum: derselbe Zähler trägt ihn
   in allen vier geprüften Jahren unverändert (5057 stets 1,108, 5059 stets
   1,938). Wo die Abrechnung ihn nicht preisgibt, steht `null` — dann muss er
   von Hand nach. */
export const GERAETE = [
  /* Heizkostenverteiler (Delta-t-Art „2SONT") — messen Einheiten (VE).

     `faktor` ist aus den Abrechnungen gezogen, nicht geschätzt. `belegt` sagt,
     wie gut: „mehrfach" heisst, derselbe Wert steht in mindestens zwei
     Abrechnungsjahren (2018/19 gegen 2020/21, 2022/23, 2023/24 geprüft);
     „2019" heisst, nur die älteste Abrechnung führt ihn auf, weil die neueren
     nur die Seiten ihres jeweiligen Nutzers enthalten. */
  { nr: '5057', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL', belegt: 'mehrfach' },
  { nr: '5058', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL', belegt: 'mehrfach' },
  { nr: '5059', art: 'hkv', raum: 'Z', faktor: 1.938, war: 'EGL', belegt: 'mehrfach' },
  { nr: '5065', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR', belegt: 'mehrfach' },
  { nr: '5066', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR', belegt: 'mehrfach' },
  { nr: '5067', art: 'hkv', raum: 'K', faktor: 2.407, war: '1GL', belegt: 'mehrfach' },
  { nr: '5068', art: 'hkv', raum: 'W', faktor: 0.875, war: '1GL', belegt: 'mehrfach' },
  { nr: '5069', art: 'hkv', raum: '—', faktor: 0.875, war: '1GL', belegt: 'mehrfach' },
  { nr: '5070', art: 'hkv', raum: 'Z', faktor: 1.193, war: '1GR', belegt: '2019' },
  { nr: '5071', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR', belegt: '2019' },
  { nr: '5072', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR', belegt: '2019' },
  /* Diese sechs gab es 2018/19 noch nicht; in den neueren Abrechnungen liegen
     nur die Seiten des jeweiligen Empfängers bei, und dort tauchen sie nicht
     auf. Ihr Faktor steht auf der Ablesequittung bzw. der Einzelabrechnung
     der Nutzer 0005/0006/0007 hinter dem Ablesewert. */
  { nr: '5074', art: 'hkv', raum: 'Z', faktor: null, war: 'DG', belegt: '' },
  { nr: '5075', art: 'hkv', raum: 'S', faktor: null, war: 'DG', belegt: '' },
  { nr: '5061', art: 'hkv', raum: 'WK', faktor: null, war: 'EG1G', belegt: '' },
  { nr: '5062', art: 'hkv', raum: 'B', faktor: null, war: 'EG1G', belegt: '' },
  { nr: '5064', art: 'hkv', raum: 'K', faktor: null, war: 'EG1G', belegt: '' },
  { nr: '5073', art: 'hkv', raum: 'B/1G', faktor: null, war: 'EG1G', belegt: '' },
  /* Wärmemengenzähler (Art „WMZ") — messen kWh. Es gibt genau zwei, beide
     am Anbau; jede andere Einheit hat nur Heizkostenverteiler. Ein Faktor
     wäre hier sinnlos: der Zähler misst die Energie unmittelbar. */
  { nr: '3706', art: 'wmz', raum: 'HZ', faktor: null, war: 'Anbau', belegt: '' },
  { nr: '3705', art: 'wmz', raum: 'T/DG', faktor: null, war: 'Anbau', belegt: '' },
];

/* Die Lanes: die Einheiten der Immobilie plus ein allgemeiner Bereich für
   alles, was keiner Wohnung allein gehört (Flure, Küche/Bäder der WG). */
export const ALLGEMEIN = 'allgemein';

export function leererStand(einheiten) {
  return {
    namen: {},            // Zähler-Nr -> selbst vergebener Name
    faktoren: {},         // Zähler-Nr -> abweichender Faktor
    zuordnung: {},        // Zähler-Nr -> Einheit-Id oder ALLGEMEIN oder ''
    einheiten: einheiten.map(e => ({ id: String(e.id), name: e.bezeichnung || '',
                                     flaeche: e.flaeche || 0 })),
  };
}

export function lade(einheiten) {
  let stand;
  try {
    stand = JSON.parse(localStorage.getItem(SPEICHER) || 'null');
  } catch { stand = null; }
  const frisch = leererStand(einheiten);
  if (!stand) return frisch;
  // Die Einheiten kommen immer frisch aus der API — sie können sich ändern,
  // die Zuordnung darf deshalb nie eine veraltete Liste konservieren.
  return { ...frisch, ...stand, einheiten: frisch.einheiten };
}

export function sichere(stand) {
  try {
    localStorage.setItem(SPEICHER, JSON.stringify(stand));
    return true;
  } catch {
    return false;
  }
}

/** Der Faktor, mit dem ein Ablesewert in Einheiten umgerechnet wird. */
export function faktorVon(stand, geraet) {
  const eigen = stand.faktoren?.[geraet.nr];
  if (eigen !== undefined && eigen !== null && eigen !== '') return Number(eigen);
  return geraet.faktor;
}

/** Wie viele Geräte sind schon einer Einheit zugewiesen, wie viele nicht. */
export function fortschritt(stand) {
  const offen = GERAETE.filter(g => !stand.zuordnung?.[g.nr]);
  const ohneFaktor = GERAETE.filter(
    g => g.art === 'hkv' && !faktorVon(stand, g));
  const ohneName = GERAETE.filter(g => !(stand.namen?.[g.nr] || '').trim());
  return { gesamt: GERAETE.length, offen: offen.length,
           ohneFaktor: ohneFaktor.length, ohneName: ohneName.length };
}
