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
  /* Heizkostenverteiler (Art „2SONT") und Wärmemengenzähler (Art „WMZ").

     `faktor` steht in den Ableseformularen von Delta-t (2018, 2020, 2022,
     2023) und ist dort in allen vier identisch — er gehört zum Gerät (Bauart
     und Grösse des Heizkörpers), nicht zum Jahr.

     `staende` ist der abgelesene Verbrauch der Abrechnungsperiode. Für 2019,
     2021, 2023 und 2024 aus den vollständigen Abrechnungen (jede enthält alle
     neun Nutzer). Für 2022 (Saison 2021/22) aus dem handgeschriebenen
     Ableseformular „2022.Ableseergebnisse" — sehr klar leserlich, ein
     einziger Wert je Zähler, keine zweite Quelle zum Gegenprüfen. Fehlt ein
     Jahr, gab es das Gerät damals nicht oder es war schon abgebaut.

     N340k — bewusst NICHT übernommen: das Formular „2023.09-Ableseergebnisse"
     (Saison 2022/23) zeigt bei 5057/5058/5059 exakt dieselben Werte wie das
     Vorjahresformular (432/295/971) — für jährlich neu gesetzte
     Verdunstungsröhrchen an drei verschiedenen Zählern praktisch
     ausgeschlossen, eher ein Durchdrücker von der Rückseite des Scans. Für
     2023 gilt weiter die Abrechnung, nicht dieses Formular. */
  { nr: '5057', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL',
    belegt: 'mehrfach', staende: {2019: 622, 2021: 407, 2022: 432, 2023: 715, 2024: 614} },
  { nr: '5058', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGL',
    belegt: 'mehrfach', staende: {2019: 4, 2021: 223, 2022: 295, 2023: 0, 2024: 125} },
  { nr: '5059', art: 'hkv', raum: 'Z', faktor: 1.938, war: 'EGL',
    belegt: 'mehrfach', staende: {2019: 603, 2021: 920, 2022: 971, 2023: 767, 2024: 879} },
  { nr: '5060', art: 'hkv', raum: '—', faktor: null, war: '—',
    belegt: '', staende: {2021: 0, 2022: 0} },
  { nr: '5061', art: 'hkv', raum: 'WK', faktor: 2.223, war: 'EG1G',
    belegt: 'mehrfach', staende: {2021: 161, 2022: 93, 2023: 0, 2024: 0} },
  { nr: '5062', art: 'hkv', raum: 'B', faktor: 0.928, war: 'EG1G',
    belegt: 'mehrfach', staende: {2021: 600, 2022: 5, 2023: 0, 2024: 0} },
  { nr: '5063', art: 'hkv', raum: 'Flur', faktor: 1.259, war: '—',
    belegt: 'mehrfach', staende: {2021: 0} },
  { nr: '5064', art: 'hkv', raum: 'K', faktor: 0.667, war: 'EG1G',
    belegt: 'mehrfach', staende: {2021: 1652, 2022: 1164, 2023: 837, 2024: 1168} },
  { nr: '5065', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR',
    belegt: 'mehrfach', staende: {2019: 764, 2021: 415, 2022: 551, 2023: 408, 2024: 564} },
  { nr: '5066', art: 'hkv', raum: 'Z', faktor: 1.108, war: 'EGR',
    belegt: 'mehrfach', staende: {2019: 964, 2021: 379, 2022: 558, 2023: 276, 2024: 224} },
  { nr: '5067', art: 'hkv', raum: 'K', faktor: 2.407, war: '1GL',
    belegt: 'mehrfach', staende: {2019: 143, 2021: 215, 2022: 174, 2023: 24, 2024: 16} },
  { nr: '5068', art: 'hkv', raum: 'W', faktor: 0.875, war: '1GL',
    belegt: 'mehrfach', staende: {2019: 376, 2021: 132, 2022: 82, 2023: 0, 2024: 1} },
  { nr: '5069', art: 'hkv', raum: '—', faktor: 0.875, war: '1GL',
    belegt: 'mehrfach', staende: {2019: 9, 2021: 273, 2022: 121, 2023: 190, 2024: 255} },
  { nr: '5070', art: 'hkv', raum: 'Z', faktor: 1.193, war: '1GR',
    belegt: 'mehrfach', staende: {2019: 2, 2021: 0, 2022: 0, 2023: 0, 2024: 0} },
  { nr: '5071', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR',
    belegt: 'mehrfach', staende: {2019: 463, 2021: 448, 2022: 312, 2023: 275, 2024: 131} },
  { nr: '5072', art: 'hkv', raum: 'Z', faktor: 0.875, war: '1GR',
    belegt: 'mehrfach', staende: {2019: 454, 2021: 504, 2022: 332, 2023: 286, 2024: 236} },
  { nr: '5073', art: 'hkv', raum: 'B/1G', faktor: 1.317, war: 'EG1G',
    belegt: 'mehrfach', staende: {2021: 1562, 2022: 816, 2023: 710, 2024: 613} },
  { nr: '5074', art: 'hkv', raum: 'Z', faktor: 2.47, war: 'DG',
    belegt: 'mehrfach', staende: {2021: 87, 2022: 183, 2023: 18, 2024: 31} },
  { nr: '5075', art: 'hkv', raum: 'S', faktor: 1.976, war: 'DG',
    belegt: 'mehrfach', staende: {2021: 97, 2022: 401, 2023: 449, 2024: 753} },
  /* N340k — der Zähler-Werdegang steht auf den Formularen schwarz auf weiss:
     beide Wärmemengenzähler wurden im Herbst 2021 bei 0 neu installiert
     (Stand ALT 0.000 auf dem Formular „2021/22"); am 30.09.2023 stand 3706
     auf 8210 kWh und 3705 auf 8996 kWh — exakt derselbe Wert steht auch als
     Stand ALT auf der Abrechnung 2023/24. `staende` sind deshalb
     Saison-Verbräuche (NEU−ALT): 2022 = 0→4581 / 0→5463,
     2023 = 4581→8210 / 5463→8996. Vorher stand hier fälschlich „8210" als
     Wert FÜR 2024 — das war der Stand am Saisonende 2023, nicht der Verbrauch
     von 2023/24. Für 2023/24 ist nur die addierte Menge beider Zähler bekannt
     (7.316 kWh laut Abrechnung, „Verbrauch H02"), keine Aufteilung je Gerät —
     deshalb bleibt 2024 hier offen statt geraten. */
  { nr: '3706', art: 'wmz', raum: 'HZ', faktor: null, war: 'Anbau',
    belegt: '', staende: { 2022: 4581, 2023: 3629 } },
  { nr: '3705', art: 'wmz', raum: 'T/DG', faktor: null, war: 'Anbau',
    belegt: '', staende: { 2022: 5463, 2023: 3533 } },
];

/* Die Lanes: die Einheiten der Immobilie plus ein allgemeiner Bereich für
   alles, was keiner Wohnung allein gehört (Flure, Küche/Bäder der WG). */
export const ALLGEMEIN = 'allgemein';

/* N340l — die Erstbelegung, vom Nutzer handschriftlich zugeordnet (Zettel
   „Zähler: Nick 2 Schlafzimmer / Vicky Wohnzimmer / …", zwei Fotos). Feste
   Einheit-Ids der Laufer Str. 5 (Wohnug 1.OG=7, Wohung EG=8, Studio 1.OG=9,
   Büro EG=10) statt Namensvergleich — der Bestand trägt Tippfehler
   („Wohnug", „Wohung"), auf die sich kein Textabgleich verlassen kann.

   EG (Erdgeschoss) → Wohung EG (8): Nick — 2 Schlafzimmer (5057-59),
   Vicky — Wohnzimmer (5065/66), Vicky/Nick (5064), Robert — Bad (5062).
   1.OG → Wohnug 1.OG (7): Küche/Wohnzimmer (5067-69),
   Schlafzimmer Anderle (5070-72), Bad 1.OG (5073).
   Waschküche (alle Mieter) → Allgemein (5061).

   NICHT auf dem Zettel und darum unzugeordnet gelassen: 5074/5075 (Raum
   „DG", der Zettel schreibt nur „DG (von 1.OG)" — ob das dieselbe Einheit
   Wohnug 1.OG meint oder das separate Studio 1.OG, war nicht eindeutig zu
   entscheiden, also lieber offen als geraten); 3706/3705 (Anbau, keine der
   vier Einheiten passt ohne Weiteres); Büro EG kommt auf dem Zettel gar
   nicht vor. Wer diese Erstbelegung schon verändert hat (eigener Stand im
   Browser), bekommt sie nicht überschrieben — sie greift nur beim allerersten
   Öffnen der Seite. */
const ERSTBELEGUNG_EINHEIT = {
  '5057': '8', '5058': '8', '5059': '8', '5065': '8', '5066': '8',
  '5064': '8', '5062': '8',
  '5067': '7', '5068': '7', '5069': '7', '5070': '7', '5071': '7',
  '5072': '7', '5073': '7',
  '5061': ALLGEMEIN,
};

const ERSTBELEGUNG_NAME = {
  '5057': 'Nick — Schlafzimmer', '5058': 'Nick — Schlafzimmer',
  '5059': 'Nick — Schlafzimmer',
  '5065': 'Vicky — Wohnzimmer', '5066': 'Vicky — Wohnzimmer',
  '5064': 'Vicky/Nick',
  '5062': 'Robert — Bad',
  '5067': 'Küche/Wohnzimmer', '5068': 'Küche/Wohnzimmer',
  '5069': 'Küche/Wohnzimmer',
  '5070': 'Schlafzimmer Anderle', '5071': 'Schlafzimmer Anderle',
  '5072': 'Schlafzimmer Anderle',
  '5073': 'Bad 1.OG',
  '5074': 'Dachgeschoss (DG, von 1.OG)', '5075': 'Dachgeschoss (DG, von 1.OG)',
  '5061': 'Waschküche (alle Mieter)',
};

export function leererStand(einheiten) {
  return {
    namen: { ...ERSTBELEGUNG_NAME },      // Zähler-Nr -> selbst vergebener Name
    faktoren: {},                         // Zähler-Nr -> abweichender Faktor
    zuordnung: { ...ERSTBELEGUNG_EINHEIT }, // Zähler-Nr -> Einheit-Id/ALLGEMEIN/''
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
