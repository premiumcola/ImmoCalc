/* Belege abfotografieren und als PDF zusammensetzen — ohne Bibliothek.
 *
 * Der Weg über <input capture> ist auf iOS der zuverlässigste: Safari öffnet
 * die Systemkamera, der Nutzer kann mehrere Aufnahmen wählen. Die Bilder
 * werden verkleinert, als JPEG neu kodiert und anschliessend 1:1 in ein PDF
 * eingebettet (DCTDecode) — dadurch bleibt die Datei klein, weil das JPEG
 * nicht ein zweites Mal komprimiert wird.
 */

const A4 = { breite: 595.28, hoehe: 841.89 };   // Punkte

/** Bild verkleinern und als JPEG kodieren. Liefert Bytes plus Masse. */
export async function aufbereiten(datei, { maxKante = 1700, guete = 0.72 } = {}) {
  const bitmap = await createImageBitmap(datei);
  const faktor = Math.min(1, maxKante / Math.max(bitmap.width, bitmap.height));
  const breite = Math.round(bitmap.width * faktor);
  const hoehe = Math.round(bitmap.height * faktor);

  const flaeche = document.createElement('canvas');
  flaeche.width = breite;
  flaeche.height = hoehe;
  const stift = flaeche.getContext('2d');
  stift.fillStyle = '#fff';
  stift.fillRect(0, 0, breite, hoehe);
  stift.drawImage(bitmap, 0, 0, breite, hoehe);
  bitmap.close?.();

  const klecks = await new Promise(fertig =>
    flaeche.toBlob(fertig, 'image/jpeg', guete));
  return { bytes: new Uint8Array(await klecks.arrayBuffer()), breite, hoehe };
}

const roh = text => new TextEncoder().encode(text);

/** Setzt die Seiten zu einem PDF zusammen. Eine Seite je Aufnahme. */
export function bauePdf(seiten, { titel = 'Beleg' } = {}) {
  const teile = [];
  let laenge = 0;
  const schreibe = daten => {
    const bytes = typeof daten === 'string' ? roh(daten) : daten;
    teile.push(bytes);
    laenge += bytes.length;
    return laenge;
  };

  // Objektnummern: 1 Katalog, 2 Seitenbaum, dann je Seite 3 Objekte
  const anzahl = seiten.length;
  const seitenIds = seiten.map((_, i) => 3 + i * 3);
  const gesamtObjekte = 2 + anzahl * 3;
  const versatz = new Array(gesamtObjekte + 1).fill(0);

  // Zweite Zeile: hohe Bytes als Hinweis "diese Datei ist binär". Bewusst
  // roh geschrieben — durch den TextEncoder würden daraus UTF-8-Folgen.
  schreibe('%PDF-1.4\n');
  schreibe(new Uint8Array([0x25, 0xE2, 0xE3, 0xCF, 0xD3, 0x0A]));

  const objekt = (nr, inhalt) => {
    versatz[nr] = laenge;
    schreibe(`${nr} 0 obj\n`);
    schreibe(inhalt);
    schreibe('\nendobj\n');
  };

  objekt(1, `<< /Type /Catalog /Pages 2 0 R >>`);
  objekt(2, `<< /Type /Pages /Count ${anzahl} /Kids [${
    seitenIds.map(id => `${id} 0 R`).join(' ')}] >>`);

  seiten.forEach((seite, i) => {
    const seitenId = seitenIds[i];
    const bildId = seitenId + 1;
    const inhaltId = seitenId + 2;

    // Die Seite bekommt das Format der Aufnahme, nicht umgekehrt: A4 dient nur
    // als Groessenmass, damit ein Ausdruck stimmt. Wuerde man das Bild in ein
    // festes A4 einpassen, blieben je nach Seitenverhaeltnis weisse Streifen
    // stehen — im Betrachter sieht man dann Papierkanten mitten im Beleg.
    const skala = Math.min(A4.breite / seite.breite, A4.hoehe / seite.hoehe);
    const b = seite.breite * skala;
    const h = seite.hoehe * skala;
    const strom = `q\n${b.toFixed(2)} 0 0 ${h.toFixed(2)} 0 0 cm\n/Bild Do\nQ\n`;

    objekt(seitenId,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${b.toFixed(2)} ${h.toFixed(2)}] ` +
      `/Resources << /XObject << /Bild ${bildId} 0 R >> >> /Contents ${inhaltId} 0 R >>`);

    // Bild als eigener Datenstrom — DCTDecode heisst: JPEG unverändert
    versatz[bildId] = laenge;
    schreibe(`${bildId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${seite.breite} ` +
      `/Height ${seite.hoehe} /ColorSpace /DeviceRGB /BitsPerComponent 8 ` +
      `/Filter /DCTDecode /Length ${seite.bytes.length} >>\nstream\n`);
    schreibe(seite.bytes);
    schreibe('\nendstream\nendobj\n');

    objekt(inhaltId, `<< /Length ${strom.length} >>\nstream\n${strom}endstream`);
  });

  const xrefStart = laenge;
  let xref = `xref\n0 ${gesamtObjekte + 1}\n0000000000 65535 f \n`;
  for (let nr = 1; nr <= gesamtObjekte; nr++) {
    xref += String(versatz[nr]).padStart(10, '0') + ' 00000 n \n';
  }
  schreibe(xref);
  schreibe(`trailer\n<< /Size ${gesamtObjekte + 1} /Root 1 0 R ` +
    `/Info << /Title (${titel.replace(/[()\\]/g, '')}) >> >>\n` +
    `startxref\n${xrefStart}\n%%EOF\n`);

  return new Blob(teile, { type: 'application/pdf' });
}

/** Vollständiger Weg: Dateien aus der Kamera -> fertiges PDF. */
export async function scanZuPdf(dateien, optionen = {}) {
  const seiten = [];
  for (const datei of dateien) {
    if (!datei.type.startsWith('image/')) continue;
    seiten.push(await aufbereiten(datei, optionen));
  }
  if (!seiten.length) throw new Error('Keine Bilder erhalten');
  return { pdf: bauePdf(seiten, optionen), seiten: seiten.length };
}

export const lesbareGroesse = bytes =>
  bytes > 1048576 ? (bytes / 1048576).toFixed(1) + ' MB'
    : Math.max(1, Math.round(bytes / 1024)) + ' KB';
