/* Beleg abfotografieren — die Choreografie, genau einmal (CCCLXVII).
 *
 * Aufnehmen, zuschneiden, als PDF ablegen, durchsuchbar machen: das sind vier
 * Schritte, die auf jeder Seite gleich ablaufen müssen. Stünden sie zweimal
 * im Code, liefen sie mit der Zeit auseinander — die eine Seite schickt den
 * Zeitraum mit, die andere vergisst ihn; die eine wartet auf die
 * Texterkennung, die andere nicht. Deshalb wohnt der Ablauf hier, und die
 * Seiten sagen nur noch, wohin der Beleg gehört.
 *
 * Der Zuschnitt kommt aus `kamerascan.js` (Kanten erkennen, entzerren, PDF
 * bauen), die Ablage aus `POST /api/dokumente/scannen`. Die Textschicht wird
 * danach nebenher angestossen: sie dauert Sekunden, und der Beleg ist auch
 * ohne sie schon sicher abgelegt.
 */
import { kamerascanStarten, istBildDatei } from './kamerascan.js';

// Ein mehrseitiger Scan wandert als PDF über die Leitung; auf dem Telefon ist
// das gerne mal eine schmale Mobilfunkverbindung. Lieber grosszügig warten
// als einen fertigen Beleg wegen einer Sekunde verwerfen.
const ZEITLIMIT_MS = 120000;

/** Bilder gehen durch den Zuschnitt, ein fertiges PDF geht direkt durch. */
function aufteilen(dateien) {
  const liste = Array.from(dateien || []);
  // iOS liefert für Kamerafotos manchmal einen leeren `type` — `istBildDatei`
  // fängt das ab (alles außer PDF gilt als Bild), damit kein Foto still
  // verschwindet und das Zuschnitt-Overlay ausbleibt.
  return {
    bilder: liste.filter(istBildDatei),
    fertig: liste.filter(d => (d.type || '') === 'application/pdf'
                           || /\.pdf$/i.test(d.name || '')),
  };
}

/** Was am Ende hochgeladen wird: `{ datei, name, seiten }` — oder `null`,
    wenn der Nutzer den Zuschnitt abgebrochen hat. */
async function aufnahmeVorbereiten(dateien, titel) {
  const { bilder, fertig } = aufteilen(dateien);
  if (bilder.length) {
    const ergebnis = await kamerascanStarten(bilder, titel ? { titel } : {});
    if (!ergebnis) return null;                    // abgebrochen
    return { datei: ergebnis.pdf, name: 'scan.pdf', seiten: ergebnis.seiten };
  }
  // Ein schon fertiges PDF (aus der Dateiauswahl statt aus der Kamera) läuft
  // denselben Weg — nur ohne Zuschnitt, denn da gibt es nichts zu entzerren.
  if (fertig.length) return { datei: fertig[0], name: fertig[0].name, seiten: 0 };
  return null;
}

/** Das Jahr aus dem Datei-Datum (`File.lastModified`) — nur ein Rückfall für
    den Server, falls Name und erkanntes Datum kein plausibles Jahr hergeben
    (CCCLXXXIV). Genommen wird das früheste der übergebenen Fotos: bei einem
    mehrseitigen Scan ist das die erste Aufnahme, näher am Belegdatum als eine
    zuletzt nachgeschossene Seite. `null`, wenn kein Zeitstempel vorliegt —
    dann bleibt alles wie bisher. */
function dateiJahr(dateien) {
  const zeiten = Array.from(dateien || [])
    .map(d => d && d.lastModified)
    .filter(t => Number.isFinite(t) && t > 0);
  if (!zeiten.length) return null;
  return new Date(Math.min(...zeiten)).getFullYear();
}

/** Die KI-Auslese (N42): der zentrale „Schritt 2" nach dem Zuschnitt. Liest aus
    der Aufnahme Betrag/Datum/Art — der Server benennt und sortiert danach. Läuft
    über `/api/dokumente/erkennen` (speichert nichts). Schlägt sie fehl (kein
    Schlüssel, kein Guthaben, offline), gibt sie `null` und der Scan läuft ganz
    normal mit dem Kontext weiter — die KI darf nie einen Beleg aufhalten. */
async function kiErkennen(datei) {
  if (!datei) return null;
  try {
    const paket = new FormData();
    paket.append('datei', datei, datei.name || 'seite.jpg');
    const antwort = await fetch('/api/dokumente/erkennen',
                                { method: 'POST', body: paket });
    return antwort.ok ? await antwort.json() : null;
  } catch {
    return null;
  }
}

/** KI-Auslese und Kontext zusammenführen — **Kontext hat Vorrang** (bin ich in
    Nebenkosten/dieser Kostenart/an diesem Mietverhältnis, bleibt das so). Die KI
    füllt nur Lücken: Betrag und Datum (die gibt beim Scannen niemand von Hand
    ein) sowie Kategorie/Kostenart/Bezeichnung dort, wo der Kontext nichts sagt.
    Nichts vom Nutzer Gewähltes wird überschrieben. */
function mitKi(ziel, ki) {
  if (!ki) return ziel;
  const z = { ...ziel };
  if (ki.kategorie && (!z.kategorie || z.kategorie === 'Sonstiges')) z.kategorie = ki.kategorie;
  if (ki.kostenart && !z.kostenart) z.kostenart = ki.kostenart;
  if (!z.kostenart && !z.beschreibung && ki.sache) z.beschreibung = ki.sache;
  if (typeof ki.betrag === 'number' && ki.betrag > 0) z.betrag = ki.betrag;
  if (ki.datum) z.datum = ki.datum;
  if (!z.jahr && Number.isInteger(ki.jahr)) z.jahr = ki.jahr;
  return z;
}

/** Nur belegte Felder wandern mit: ein leeres `jahr` würde sonst als „0"
    ankommen und den Beleg in einen Ordner ohne Jahr sortieren. */
function paketBauen(datei, name, ziel, jahrHinweis) {
  const paket = new FormData();
  paket.append('objekt', ziel.objekt || '');
  paket.append('kategorie', ziel.kategorie || 'Sonstiges');
  if (ziel.kostenart) paket.append('kostenart', ziel.kostenart);
  if (ziel.jahr) paket.append('jahr', String(ziel.jahr));
  if (ziel.beschreibung) paket.append('beschreibung', ziel.beschreibung);
  // N42 — Betrag/Datum aus der KI: der Server setzt sie in Namen (Betrag hinten,
  // Datum vorn) und ans Dokument (Kostenposition, Zeitraum-Zuordnung).
  if (ziel.betrag) paket.append('betrag', String(ziel.betrag));
  if (ziel.datum) paket.append('datum', ziel.datum);
  if (ziel.zeitraumId) paket.append('zeitraum_id', String(ziel.zeitraumId));
  // Immer als Rückfall mitschicken; der Server nimmt es nur, wenn sonst kein
  // plausibles Jahr zustande kommt — ein gewähltes `jahr` behält den Vorrang.
  if (jahrHinweis) paket.append('datei_jahr', String(jahrHinweis));
  if (ziel.anTyp && ziel.anId) {
    paket.append('an_typ', ziel.anTyp);
    paket.append('an_id', String(ziel.anId));
  }
  paket.append('datei', datei, name);
  return paket;
}

/** Der Fehlertext, den der Nutzer lesen soll — der vom Server, wenn es einen
    gibt, sonst wenigstens der Status. Ein nacktes „TypeError" hilft niemandem. */
async function fehlertext(antwort) {
  const grund = await antwort.json().then(k => k.detail).catch(() => null);
  return grund || `Der Beleg konnte nicht abgelegt werden (${antwort.status}).`;
}

/**
 * Nimmt Kamerafotos (oder ein fertiges PDF) entgegen und legt sie als einen
 * Beleg ab.
 *
 * `ziel`: `{ objekt, kategorie, kostenart, jahr, beschreibung, zeitraumId,
 * anTyp, anId, titel }` — nur `objekt` und `kategorie` sind wirklich nötig.
 * `anTyp`/`anId` hängen den Beleg gleich an einen bestehenden Eintrag.
 *
 * Gibt `null` zurück, wenn der Nutzer abgebrochen hat (kein Fehler), sonst
 * `{ id, dateiname, seiten, groesse }`. Geht die Ablage schief, fliegt ein
 * `Error` mit einem Satz, den man anzeigen kann.
 */
export async function belegScannen(dateien, ziel = {}) {
  // Aus den Originaldateien lesen, nicht aus dem gebauten Scan-PDF: dessen
  // Zeitstempel wäre „jetzt". Das Foto bzw. die gewählte Datei trägt dagegen
  // ein Datum nahe am Beleg.
  const jahrHinweis = dateiJahr(dateien);
  // N42 — Schritt 2 (KI-Auslese) läuft PARALLEL zum Zuschnitt-Overlay auf der
  // Originalaufnahme: kostet kaum Tokens, kostet keine Wartezeit (der Nutzer
  // schneidet gerade zu) und liefert Betrag/Datum/Art für Benennung + Ablage.
  const liste = Array.from(dateien || []);
  const erstes = liste.find(istBildDatei) || liste[0];
  const kiVersprechen = kiErkennen(erstes);

  const aufnahme = await aufnahmeVorbereiten(dateien, ziel.titel);
  if (!aufnahme) return null;                       // Zuschnitt abgebrochen
  // Kontext hat Vorrang, KI füllt nur Lücken — nie etwas überschreiben.
  ziel = mitKi(ziel, await kiVersprechen);

  const abbruch = new AbortController();
  const uhr = setTimeout(() => abbruch.abort(), ZEITLIMIT_MS);
  let antwort;
  try {
    antwort = await fetch('/api/dokumente/scannen', {
      method: 'POST',
      body: paketBauen(aufnahme.datei, aufnahme.name, ziel, jahrHinweis),
      signal: abbruch.signal,
    });
  } catch (fehler) {
    throw new Error(fehler?.name === 'AbortError'
      ? 'Die Ablage hat zu lange gedauert — der Beleg wurde nicht gespeichert.'
      : 'Keine Verbindung zum Server — der Beleg wurde nicht gespeichert.');
  } finally {
    clearTimeout(uhr);
  }
  if (!antwort.ok) throw new Error(await fehlertext(antwort));
  const ergebnis = await antwort.json();

  // Die Textschicht ist Beiwerk: sie darf dauern und sie darf ausfallen. Der
  // Beleg liegt schon richtig — deshalb nebenher, ohne Warten, ohne Meldung.
  fetch(`/api/dokumente/${ergebnis.id}/durchsuchbar`, { method: 'POST' })
    .catch(() => {});

  return { id: ergebnis.id, dateiname: ergebnis.dateiname,
           seiten: aufnahme.seiten, groesse: aufnahme.datei.size };
}
