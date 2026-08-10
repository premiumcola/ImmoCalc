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
  /* Heizkostenverteiler (Art „2SONT") — messen Einheiten (VE), und
     Wärmemengenzähler (Art „WMZ") — messen kWh.

     `faktor` steht in den Ableseformularen von Delta-t (2018, 2020, 2022,
     2023) und ist dort **in allen vier identisch** — er gehört zum Gerät
     (Bauart und Grösse des Heizkörpers), nicht zum Jahr.

     `staende` ist der abgelesene Verbrauch der jeweiligen Abrechnungsperiode,
     soweit die Abrechnungen ihn preisgeben. Lücken sind echt und bleiben
     Lücken: die neueren PDFs enthalten nur die Seiten ihres Empfängers. Der
     Verlauf steht am Kärtchen, damit ein fehlender Wert einzuschätzen ist —
     wer 2019 bis 2023 zwischen 400 und 900 lag, hatte 2024 kaum 20. */
  { nr: '5057', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL', belegt: 'mehrfach',
    staende: {2019: 622, 2021: 407, 2023: 715, 2024: 614} },
  { nr: '5058', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL', belegt: 'mehrfach',
    staende: {2019: 4, 2021: 223, 2023: 0, 2024: 125} },
  { nr: '5059', art: 'hkv', raum: 'Z', faktor: 1.938, war: 'EGL', belegt: 'mehrfach',
    staende: {2019: 603, 2021: 920, 2023: 767, 2024: 879} },
  { nr: '5061', art: 'hkv', raum: 'WK', faktor: 2.223, war: 'EG1G', belegt: 'mehrfach',
    staende: {} },
  { nr: '5062', art: 'hkv', raum: 'B', faktor: 0.928, war: 'EG1G', belegt: 'mehrfach',
    staende: {} },
  { nr: '5063', art: 'hkv', raum: 'Flur', faktor: 1.259, war: '—', belegt: 'mehrfach',
    staende: {} },
  { nr: '5064', art: 'hkv', raum: 'K', faktor: 0.667, war: 'EG1G', belegt: 'mehrfach',
    staende: {} },
  { nr: '5065', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR', belegt: 'mehrfach',
    staende: {2019: 764, 2021: 415, 2023: 408, 2024: 564} },
  { nr: '5066', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR', belegt: 'mehrfach',
    staende: {2019: 964, 2021: 379, 2023: 276, 2024: 224} },
  { nr: '5067', art: 'hkv', raum: 'K', faktor: 2.407, war: '1GL', belegt: 'mehrfach',
    staende: {2019: 143, 2021: 215, 2024: 16} },
  { nr: '5068', art: 'hkv', raum: 'W', faktor: 0.875, war: '1GL', belegt: 'mehrfach',
    staende: {2019: 376, 2021: 132, 2024: 1} },
  { nr: '5069', art: 'hkv', raum: '—', faktor: 0.875, war: '1GL', belegt: 'mehrfach',
    staende: {2019: 9, 2021: 273, 2024: 255} },
  { nr: '5070', art: 'hkv', raum: 'Z', faktor: 1.193, war: '1GR', belegt: 'mehrfach',
    staende: {2019: 2} },
  { nr: '5071', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR', belegt: 'mehrfach',
    staende: {2019: 463} },
  { nr: '5072', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR', belegt: 'mehrfach',
    staende: {2019: 454} },
  { nr: '5073', art: 'hkv', raum: 'B/1G', faktor: 1.317, war: 'EG1G', belegt: 'mehrfach',
    staende: {} },
  { nr: '5074', art: 'hkv', raum: 'Z', faktor: 2.47, war: 'DG', belegt: 'mehrfach',
    staende: {} },
  { nr: '5075', art: 'hkv', raum: 'S', faktor: 1.976, war: 'DG', belegt: 'mehrfach',
    staende: {} },
  { nr: '3706', art: 'wmz', raum: 'HZ', faktor: null, war: 'Anbau',
    belegt: '', staende: { 2024: 8210 } },
  { nr: '3705', art: 'wmz', raum: 'T/DG', faktor: null, war: 'Anbau',
    belegt: '', staende: { 2024: 8996 } },
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
