/* CCCXXXVII — geteilter Zustand der Objektseite. Andere Module lesen `objekt`,
   `slug` usw. als Live-Bindung; geschrieben wird nur hier über die Setter, die
   `laden()` aufruft. So bleibt eine einzige Quelle der Wahrheit über alle
   Module hinweg erhalten (ES-Modul-Live-Bindings). */
const anfrage = new URLSearchParams(location.search);
export const slug = anfrage.get('o');

/* Ein Grundstück ist ein eigener Fall, kein Haus mit weniger Feldern: keine
   Einheiten, keine Nebenkostenabrechnung, dafür Kataster und Grundsteuer.
   Erkannt wird es am Objekttyp. */
export const GRUNDSTUECK = 'lg-grundstueck';

export let objekt = null;
/* CCCI — die Eigentümer-Namen dieses Objekts, für die Nießbrauch-Auswahl. */
export let objektEigentuemer = [];
/* CCCXXXV — alle app-weit geführten Eigentümer (Personen). */
export let alleEigentuemer = [];

export function setObjekt(v) { objekt = v; }
export function setObjektEigentuemer(v) { objektEigentuemer = v; }
export function setAlleEigentuemer(v) { alleEigentuemer = v; }

export const istGrundstueck = () => Boolean(objekt) && objekt.typ === GRUNDSTUECK;
