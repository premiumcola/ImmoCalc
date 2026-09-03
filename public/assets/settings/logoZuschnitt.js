/* N471 — Familienlogo/Anmeldefoto zuschneiden, statt es blind mittig zu
   kappen. Nutzer: „das Profilbild soll sich im runden Bereich korrekt
   einschieben, ausrichten und zoomen lassen — nicht nur fest gesetzt werden
   ohne eine Einpassung von mir. Drehen wäre vermutlich auch nicht schlecht."

   Vorher schnitt `als_logo()` (Server) IMMER stur das größte mittige Quadrat
   aus — bei einem Hochformat-Foto lag das Gesicht der Person oft am oberen
   oder unteren Rand statt in der Mitte, ohne jede Möglichkeit, das zu
   korrigieren. Dieses Modul liefert stattdessen ein bereits quadratisches
   Ausschnitt-PNG, das der Nutzer selbst durch Ziehen (Ausschnitt), Regler
   (Zoom) und zwei Knöpfe (90°-Drehung) bestimmt hat — der Server macht damit
   unverändert weiter (rund, weicher Rand, siehe `pdfbild.py`), sein
   Mitte-Zuschnitt wird an einem bereits quadratischen Bild zum No-Op. */
import { baueDialog } from '../immo.js';

// Editier-Bühne (Bildschirm-Pixel) und Export-Auflösung (an die Kante, die
// `als_logo()` ohnehin wieder auf 256px herunterrechnet — mit Reserve, damit
// auch ein Zoom in einen kleinen Bildausschnitt nicht schon vorher unscharf
// hochgerechnet werden muss).
const BUEHNE = 280;
const EXPORT = 640;
const MAX_ZOOM = 4;

const klemmen = (wert, min, max) => Math.min(max, Math.max(min, wert));

/**
 * Öffnet den Zuschnitt-Dialog für eine ausgewählte Bilddatei.
 * Gibt eine Promise auf ein quadratisches PNG als Data-URL zurück, oder
 * `null`, wenn abgebrochen wurde.
 */
export function logoZuschneiden(datei) {
  return new Promise((resolve) => {
    const bildUrl = URL.createObjectURL(datei);
    const bild = new Image();

    bild.onerror = () => {
      URL.revokeObjectURL(bildUrl);
      resolve(null);
    };

    bild.onload = () => {
      const dlg = baueDialog(`
        <div class="dt">Foto einpassen</div>
        <p>Ziehen zum Verschieben, mit dem Regler zoomen.</p>
        <div class="logo-crop-buehne">
          <canvas class="logo-crop-canvas" width="${BUEHNE}" height="${BUEHNE}"></canvas>
        </div>
        <div class="logo-crop-werkzeuge">
          <button type="button" class="logo-crop-dreh" data-dreh="-1"
                  aria-label="90 Grad nach links drehen"><span class="sym">⟲</span></button>
          <input type="range" class="logo-crop-zoom" min="0" max="100" value="0"
                 aria-label="Zoom">
          <button type="button" class="logo-crop-dreh" data-dreh="1"
                  aria-label="90 Grad nach rechts drehen"><span class="sym">⟳</span></button>
        </div>
        <button type="button" class="btn" id="logoCropOk">Übernehmen</button>`);

      const canvas = dlg.querySelector('.logo-crop-canvas');
      const ctx = canvas.getContext('2d');
      const regler = dlg.querySelector('.logo-crop-zoom');

      // 0..3 Vierteldrehungen im Uhrzeigersinn — bei Vielfachen von 90° bleibt
      // das Deckungsrechteck achsenparallel, ein Klemmen ohne Sinus/Kosinus
      // reicht damit aus (ein beliebiger Winkel bräuchte eine Drehmatrix, um
      // Verschieben innerhalb der Bildgrenzen zu halten).
      let drehSchritte = 0;
      let panX = 0, panY = 0;

      const abmessungen = () => {
        const quer = drehSchritte % 2 === 0;
        return {
          breite: quer ? bild.naturalWidth : bild.naturalHeight,
          hoehe: quer ? bild.naturalHeight : bild.naturalWidth,
        };
      };

      // Kleinstmöglicher Zoom, bei dem das Bild den eingeschriebenen Kreis
      // noch vollständig deckt — der Regler fängt genau hier an.
      const basisSkala = () => {
        const { breite, hoehe } = abmessungen();
        return BUEHNE / Math.min(breite, hoehe);
      };

      const skala = () => basisSkala() * (1 + (regler.value / 100) * (MAX_ZOOM - 1));

      /* Ein Kreis mit Radius r, mittig in einem achsenparallelen Rechteck mit
         Halbmaßen (a, b), bleibt genau dann vollständig gedeckt, wenn der
         Bildmittelpunkt höchstens (a·skala − r) bzw. (b·skala − r) vom
         Bühnenmittelpunkt absteht — sonst schaut eine Bildkante in den Kreis
         hinein. */
      const grenzenAnwenden = () => {
        const { breite, hoehe } = abmessungen();
        const s = skala();
        const r = BUEHNE / 2;
        const maxX = Math.max(0, (breite / 2) * s - r);
        const maxY = Math.max(0, (hoehe / 2) * s - r);
        panX = klemmen(panX, -maxX, maxX);
        panY = klemmen(panY, -maxY, maxY);
      };

      const aufZeichnen = (zielCtx, groesse) => {
        const faktor = groesse / BUEHNE;
        zielCtx.clearRect(0, 0, groesse, groesse);
        // Die Ecken ausserhalb des einbeschriebenen Kreises sind zwar
        // garantiert innerhalb der Bühne gedeckt, aber NICHT zwingend bis in
        // die quadratischen Ecken hinein (das Foto muss nur den Kreis decken,
        // nicht das ganze Quadrat) — ohne Füllung blieben sie transparent,
        // und der weiche Rand aus `als_logo()` würde dort gegen puren
        // Transparenz-Schwarz statt gegen Bildinhalt weichzeichnen. Der Ton
        // selbst ist irrelevant: `als_logo()` blendet ohnehin alles ab
        // Kreisradius auf 0 % Deckkraft — die Füllung ist nur eine
        // Nachbarschaft für den Weichzeichner, kein sichtbares Ergebnis.
        zielCtx.fillStyle = '#E8ECEC';
        zielCtx.fillRect(0, 0, groesse, groesse);
        zielCtx.save();
        zielCtx.translate(groesse / 2 + panX * faktor, groesse / 2 + panY * faktor);
        zielCtx.rotate((drehSchritte * Math.PI) / 2);
        zielCtx.scale(skala() * faktor, skala() * faktor);
        zielCtx.drawImage(bild, -bild.naturalWidth / 2, -bild.naturalHeight / 2);
        zielCtx.restore();
      };

      const neuZeichnen = () => {
        grenzenAnwenden();
        aufZeichnen(ctx, BUEHNE);
      };

      neuZeichnen();

      // ---- Verschieben: ein Finger/Zeiger zieht, zwei zoomen (Kneifgeste) ----
      const zeiger = new Map();
      let ziehStart = null;
      let kneifAbstand = 0, kneifStartWert = 0;

      const kneifDistanz = () => {
        const [a, b] = [...zeiger.values()];
        return Math.hypot(a.x - b.x, a.y - b.y);
      };

      canvas.addEventListener('pointerdown', (e) => {
        try { canvas.setPointerCapture(e.pointerId); } catch { /* ohne Erfassung weiter */ }
        zeiger.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (zeiger.size === 1) {
          ziehStart = { x: e.clientX, y: e.clientY, panX, panY };
        } else if (zeiger.size === 2) {
          kneifAbstand = kneifDistanz();
          kneifStartWert = Number(regler.value);
        }
      });

      canvas.addEventListener('pointermove', (e) => {
        if (!zeiger.has(e.pointerId)) return;
        zeiger.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (zeiger.size === 1 && ziehStart) {
          panX = ziehStart.panX + (e.clientX - ziehStart.x);
          panY = ziehStart.panY + (e.clientY - ziehStart.y);
          neuZeichnen();
        } else if (zeiger.size === 2 && kneifAbstand > 0) {
          regler.value = String(klemmen(
            kneifStartWert + (kneifDistanz() / kneifAbstand - 1) * 150, 0, 100));
          neuZeichnen();
        }
      });

      const zeigerWeg = (e) => {
        zeiger.delete(e.pointerId);
        kneifAbstand = 0;
        if (zeiger.size === 1) {
          const rest = [...zeiger.values()][0];
          ziehStart = { x: rest.x, y: rest.y, panX, panY };
        } else {
          ziehStart = null;
        }
      };
      canvas.addEventListener('pointerup', zeigerWeg);
      canvas.addEventListener('pointercancel', zeigerWeg);

      // Mausrad auf dem Desktop — zusätzlich zum Regler, nicht als Ersatz.
      canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        regler.value = String(klemmen(Number(regler.value) - e.deltaY * 0.15, 0, 100));
        neuZeichnen();
      }, { passive: false });

      regler.addEventListener('input', neuZeichnen);

      dlg.querySelectorAll('.logo-crop-dreh').forEach((knopf) => {
        knopf.addEventListener('click', () => {
          drehSchritte = (drehSchritte + Number(knopf.dataset.dreh) + 4) % 4;
          neuZeichnen();
        });
      });

      let entschieden = false;
      const abschliessen = (ergebnis) => {
        if (entschieden) return;
        entschieden = true;
        URL.revokeObjectURL(bildUrl);
        resolve(ergebnis);
      };

      dlg.querySelector('#logoCropOk').addEventListener('click', () => {
        const export_ = document.createElement('canvas');
        export_.width = EXPORT;
        export_.height = EXPORT;
        aufZeichnen(export_.getContext('2d'), EXPORT);
        abschliessen(export_.toDataURL('image/png'));
        dlg.close();
      });
      // Abbrechen: das Kreuz von `baueDialog` UND Escape lösen beide das
      // native `close`-Ereignis aus — ein Ergebnis ist bis dahin nicht
      // gesetzt, `abschliessen` greift also nur hier mit `null`.
      dlg.addEventListener('close', () => abschliessen(null));
    };

    bild.src = bildUrl;
  });
}
