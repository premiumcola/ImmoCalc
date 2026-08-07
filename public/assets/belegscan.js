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
import { kamerascanStarten, istBildDatei, fotoAlsJpeg } from './kamerascan.js';

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
    // `blaetter` (N250) sind die entzerrten Seiten als Bilder — die
    // Bestätigungsmaske zeigt damit, was gleich abgelegt wird. Für ein fertig
    // gewähltes PDF gibt es sie nicht; die Maske kommt dann ohne Vorschau aus.
    return { datei: ergebnis.pdf, name: 'scan.pdf', seiten: ergebnis.seiten,
             blaetter: ergebnis.bilder || [] };
  }
  // Ein schon fertiges PDF (aus der Dateiauswahl statt aus der Kamera) läuft
  // denselben Weg — nur ohne Zuschnitt, denn da gibt es nichts zu entzerren.
  if (fertig.length) {
    return { datei: fertig[0], name: fertig[0].name, seiten: 0, blaetter: [] };
  }
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
async function kiErkennen(datei, kostenart = '') {
  if (!datei) return null;
  try {
    // N207 — iOS-Kamerafotos (HEIC/leerer type) erst in ein vom Server lesbares
    // JPEG wandeln; sonst liest die OCR nichts und es käme kein Vorschlag.
    const lesbar = await fotoAlsJpeg(datei);
    const paket = new FormData();
    paket.append('datei', lesbar, lesbar.name || 'seite.jpg');
    // N78 — optionaler Kontext-Hinweis: bei einem Wasser-Beleg liest die KI
    // zusätzlich die drei Bereichsbeträge (Feld `wasser`). Additiv; ohne den
    // Hinweis bleibt der Aufruf wie zuvor.
    if (kostenart) paket.append('kostenart', kostenart);
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
  // N251 — die erkannte Sache IMMER übernehmen, wenn der Aufrufer keine eigene
  // Bezeichnung mitbringt. Früher stand hier zusätzlich `!z.kostenart`: wer aus
  // einer Kostenart-Karte heraus scannte (Grundsteuer, Wasser …), verlor damit
  // genau die Angabe, die den Beleg unterscheidbar macht — die KI erkannte
  // „Abbuchungsvorankündigung", der Name wurde trotzdem nur „NK-Grundsteuer".
  // `dateiname()` fügt Kostenart und Sache serverseitig zusammen und lässt den
  // Normalfall unberührt: ist die Sache die Kostenart selbst, bleibt es bei
  // „NK-Grundsteuer"; ist sie genauer, wird daraus
  // „NK-Grundsteuer-Abbuchungsvorankündigung".
  if (!z.beschreibung && ki.sache) z.beschreibung = ki.sache;
  if (typeof ki.betrag === 'number' && ki.betrag > 0) z.betrag = ki.betrag;
  if (ki.datum) z.datum = ki.datum;
  if (!z.jahr && Number.isInteger(ki.jahr)) z.jahr = ki.jahr;
  return z;
}

/** Nur belegte Felder wandern mit: ein leeres `jahr` würde sonst als „0"
    ankommen und den Beleg in einen Ordner ohne Jahr sortieren. */
function paketBauen(datei, name, ziel, jahrHinweis, ki = null) {
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
  // N255 — die schon geholte Auslese mitgeben, damit sie am frischen Beleg
  // festgehalten wird. `/erkennen` lief auf den nackten Bytes, da gab es den
  // Datensatz noch nicht; ohne diesen Weg bliebe die Dokumentenerkennung für
  // jeden gescannten Beleg dauerhaft leer und müsste — auf Kosten des Nutzers —
  // noch einmal gelesen werden.
  if (ki) {
    try { paket.append('ki_json', JSON.stringify(ki)); } catch { /* egal */ }
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
 * N250 — Schritt 1: Kamerafotos (oder ein fertiges PDF) aufnehmen, zuschneiden
 * und auslesen — aber NOCH NICHT ablegen.
 *
 * `ziel`: `{ objekt, kategorie, kostenart, jahr, beschreibung, zeitraumId,
 * anTyp, anId, titel }` — nur `objekt` und `kategorie` sind wirklich nötig.
 * `anTyp`/`anId` hängen den Beleg gleich an einen bestehenden Eintrag.
 *
 * Gibt `null` zurück, wenn der Nutzer den Zuschnitt abgebrochen hat, sonst
 * `{ aufnahme, ziel, jahrHinweis, ki }` — das Paket für `belegAblegen`. `ki`
 * ist die rohe Auslese (oder `null`), damit die Bestätigungsmaske zeigen kann,
 * was erkannt wurde, ohne ein zweites Mal zu fragen.
 */
export async function belegVorbereiten(dateien, ziel = {}, beimLesen = null) {
  // Aus den Originaldateien lesen, nicht aus dem gebauten Scan-PDF: dessen
  // Zeitstempel wäre „jetzt". Das Foto bzw. die gewählte Datei trägt dagegen
  // ein Datum nahe am Beleg.
  const jahrHinweis = dateiJahr(dateien);
  // N42 — Schritt 2 (KI-Auslese) läuft PARALLEL zum Zuschnitt-Overlay auf der
  // Originalaufnahme: kostet kaum Tokens, kostet keine Wartezeit (der Nutzer
  // schneidet gerade zu) und liefert Betrag/Datum/Art für Benennung + Ablage.
  const liste = Array.from(dateien || []);
  const erstes = liste.find(istBildDatei) || liste[0];
  // N78 — die Kostenart als Kontext mitgeben (Wasser-Beleg ⇒ drei Beträge).
  const kiVersprechen = kiErkennen(erstes, ziel.kostenart || '');

  const aufnahme = await aufnahmeVorbereiten(dateien, ziel.titel);
  if (!aufnahme) return null;                       // Zuschnitt abgebrochen
  // N254 — genau hier klafft die Lücke: der Zuschnitt ist zu, die Auslese
  // läuft noch. Der Aufrufer legt jetzt seine Decke über die Seite.
  if (beimLesen) { try { beimLesen(); } catch { /* darf nie stören */ } }
  const ki = await kiVersprechen;
  // Kontext hat Vorrang, KI füllt nur Lücken — nie etwas überschreiben.
  return { aufnahme, ziel: mitKi(ziel, ki), jahrHinweis, ki };
}

/**
 * N250 — Schritt 2: den vorbereiteten Beleg wirklich ablegen.
 *
 * Nimmt das Ergebnis von `belegVorbereiten` entgegen. Dazwischen darf der
 * Aufrufer den Nutzer fragen (Bestätigungsmaske mit Dateinamen) — deshalb
 * sind Vorbereiten und Ablegen überhaupt getrennt. `beschreibung` überschreibt
 * dabei die vorgeschlagene Bezeichnung; benannt wird weiterhin auf dem Server.
 */
export async function belegAblegen(vorbereitet, beschreibung = null) {
  const { aufnahme, jahrHinweis } = vorbereitet;
  const ziel = beschreibung === null || beschreibung === undefined
    ? vorbereitet.ziel : { ...vorbereitet.ziel, beschreibung };

  const abbruch = new AbortController();
  const uhr = setTimeout(() => abbruch.abort(), ZEITLIMIT_MS);
  let antwort;
  try {
    antwort = await fetch('/api/dokumente/scannen', {
      method: 'POST',
      body: paketBauen(aufnahme.datei, aufnahme.name, ziel, jahrHinweis,
                       vorbereitet.ki),
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

/**
 * Der bisherige Ein-Schritt-Weg: vorbereiten und sofort ablegen, ohne
 * Zwischenfrage. Bleibt für alle Aufrufer, die keine Bestätigungsmaske wollen —
 * ihr Verhalten ändert sich dadurch kein Stück.
 */
export async function belegScannen(dateien, ziel = {}) {
  const vorbereitet = await belegVorbereiten(dateien, ziel);
  if (!vorbereitet) return null;                    // Zuschnitt abgebrochen
  return belegAblegen(vorbereitet);
}
