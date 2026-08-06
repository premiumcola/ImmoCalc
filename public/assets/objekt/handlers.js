/* N216 — zentrale Klick-/Change-/Submit-Delegation der Objektseite.

   Verdrahtet ein Mal an die drei Wurzeln:
   - `#inhalt` (Seiteninhalt) — Klicks für Rubriken, Zeiträume, Einheiten,
     Lageplan, Grundschulden, Löschen, Cloud, Export …
   - `#inhalt change`         — Lageplan-Upload
   - `#dlgForm click`         — Blasenwahl, Bewohner/Gemein/Nutz-Zeilen,
     Kredit-Stand-Werkzeuge, Miet-Vorschlag übernehmen
   - `#dlgForm submit`        — Speichern (alle Absichten in einem Zug)
   - `#dlg close`             — Formatierungen/Auswahlfelder abräumen
   - `#back`                  — Zurück (Fokus → Haus, Haus → Übersicht)

   Nichts anderes registriert Listener auf diese Wurzeln — so bleibt eine
   einzige Quelle, in der die data-Attribute konsequent behandelt werden. */

import { api, esc, melde, frage, schiebeFrage, wahl, belegAnsehen } from '../immo.js';
import { endpunktBereich, felderFuer, cfgFuer, RUBRIK_FESTWERTE,
         WEGFELDER, EINHEITFELDER, stammfelder } from '../objekt-felder.js?v=2';
import { tagDavor } from '../objekt-format.js?v=2';
import { objekt, slug, istGrundstueck } from '../objekt-state.js?v=2';
import { getBaumDaten, baumFilterUmschalten, baumMehrZeigen,
         baumAstUmschalten, baumJahrSetzen } from '../objekt-baum.js?v=2';
import * as ObjState from './state.js';
import { ZEITRAUMFELDER, GRUNDSCHULDFELDER,
         dialogFelder, dialogUmbau, ANTEILFELDER,
         pushBewohnerWeg, setDialogUmbau } from './state.js';
import { laden } from './laden.js';
import { formular, formateLoesen, auswahlLoesen, datumwahlLoesen, ausFormular } from './formular.js';
import { anfangsstaendeDialog } from './anfangsstaende.js';
import { eintragDetail, oeffneEintragFormular } from './eintrag-detail.js';
import { zuordnenDialog } from './zuordnen.js';
import { anteilFormular } from './eigentuemer.js';
import { grundschuldFormular } from './grundschulden.js';
import { zeitraumWerkzeug } from './zeitraum-werkzeug.js';
import { cloudZeigen } from './cloud.js';
import { mietExtra, erhoehungFormular } from './miete-extras.js';
import { standFormular } from './kredit-extras.js';
import { bewohnerZeile, bewohnerSpeichern, gemeinZeile, gemeinBlock,
         gemeinAusFormular, nutzZeile, nutzBlock, nutzAusFormular } from './bewohner.js';
import { lageplanUmbenennen, lageplanEntfernen, lageplanAnsehen,
         lageplanHochladen } from './lageplan.js';

const hausUrl = () => `objekt.html?o=${encodeURIComponent(slug)}`;
const einheitUrl = id => `${hausUrl()}&e=${id}`;

export function initHandlers() {
  const inhalt = document.getElementById('inhalt');
  const dlg = document.getElementById('dlg');
  const dlgForm = document.getElementById('dlgForm');

  /* CCCXLVII — „Zurück" navigiert immer zum logischen Elternteil, NIE über
     history.back(): aus der Einheit ans Haus, vom Haus zur Objektliste. Das
     frühere history.back() im Haus sprang zur gerade verlassenen Einheit zurück
     (die Einheit-Zurück fügte per location.href einen History-Eintrag hinzu) —
     Ergebnis war eine Endlosschleife Einheit⇄Haus, man kam nie zur Startseite. */
  document.getElementById('back').addEventListener('click', () => {
    location.href = ObjState.fokus ? hausUrl() : 'index.html';
  });

  dlg.addEventListener('close', () => {
    formateLoesen();
    auswahlLoesen();
    datumwahlLoesen();
    setDialogUmbau(null);   // sonst baut ein später Klick einen toten Dialog um
  });

  dlgForm.addEventListener('click', async e => {
    if (e.target.closest('[data-abbruch]')) return dlg.close('abbruch');

    // CCXXIX — Mehrfachauswahl der gesicherten Kredite: jede Blase schaltet
    // nur sich selbst, im Unterschied zu den Einzelauswahl-Blasen unten.
    const gsKredit = e.target.closest('[data-gs-kredit]');
    if (gsKredit) {
      const an = !gsKredit.classList.contains('gewaehlt');
      gsKredit.classList.toggle('gewaehlt', an);
      gsKredit.setAttribute('aria-pressed', String(an));
      return;
    }

    const wahlEl = e.target.closest('[data-wahl]');
    if (wahlEl) {
      const gruppe = wahlEl.closest('[data-wahlfeld]');
      const form = document.getElementById('dlgForm');
      form.elements[gruppe.dataset.wahlfeld].value = wahlEl.dataset.wahl;
      // Blasen (Einheitenwahl) und der Ja/Nein-Schalter (CXCIII) teilen sich
      // diese Verdrahtung — jeder trägt seine eigene Aktiv-Klasse.
      for (const knopf of gruppe.querySelectorAll('[data-wahl]')) {
        const an = knopf === wahlEl;
        knopf.classList.toggle(
          knopf.classList.contains('schaltknopf') ? 'an' : 'gewaehlt', an);
        knopf.setAttribute('aria-pressed', String(an));
      }
      // Ein Schalter mit Umbau (CCCI: Nießbrauch) baut das Formular neu auf, sobald
      // er umgelegt wird — dann kommen/gehen die abhängigen Felder.
      if (gruppe.dataset.umbau && dialogUmbau) setTimeout(dialogUmbau, 0);
      return;
    }

    const weg = e.target.closest('[data-bw-weg]');
    if (weg) {
      // Erst beim Speichern wirklich löschen — bis dahin nur gemerkt.
      const zeile = weg.closest('.bwzeile');
      if (zeile.dataset.bid) pushBewohnerWeg(zeile.dataset.bid);
      zeile.remove();
      return;
    }
    if (e.target.closest('[data-bw-neu]')) {
      e.target.closest('[data-bw-neu]').insertAdjacentHTML('beforebegin',
        bewohnerZeile({}));
      return;
    }

    // CCCXXVII — Gemeinschaftsflächen-Zeilen hinzufügen/entfernen.
    const gfWeg = e.target.closest('[data-gf-weg]');
    if (gfWeg) { gfWeg.closest('.gfzeile').remove(); return; }
    if (e.target.closest('[data-gf-neu]')) {
      e.target.closest('[data-gf-neu]').insertAdjacentHTML('beforebegin', gemeinZeile({}));
      return;
    }

    // CCCXXIX — Zusatz-Nutzflächen-Zeilen hinzufügen/entfernen.
    const nfWeg = e.target.closest('[data-nf-weg]');
    if (nfWeg) { nfWeg.closest('.nfzeile').remove(); return; }
    if (e.target.closest('[data-nf-neu]')) {
      e.target.closest('[data-nf-neu]').insertAdjacentHTML('beforebegin', nutzZeile({}));
      return;
    }

    const standWeg = e.target.closest('[data-stand-weg]');
    if (standWeg) {
      const kid = document.getElementById('dlgForm').dataset.id;
      try {
        await api(`/kreditstaende/${standWeg.dataset.standWeg}`, { method: 'DELETE' });
      } catch (fehler) {
        return melde(String(fehler.message || fehler), 'neg');
      }
      await laden();
      return standFormular(kid);
    }

    const staende = e.target.closest('[data-staende]');
    if (staende) return standFormular(staende.dataset.staende);

    const erhoehung = e.target.closest('[data-erhoehung]');
    if (erhoehung) return erhoehungFormular(erhoehung.dataset.erhoehung);

    // CCCXXXIII — den hergeleiteten Kaltmiete-Vorschlag ins Feld übernehmen. Das
    // Kaltmiete-Feld ist ein geld-formatiertes Feld: der Name wandert dabei auf
    // ein verstecktes Feld, der rohe Wert wird auf dem sichtbaren (#f_kaltmiete)
    // gesetzt, das sich selbst neu formatiert. Überschreibbar bleibt es.
    const vorschlag = e.target.closest('[data-miete-vorschlag]');
    if (vorschlag) {
      const sicht = document.getElementById('f_kaltmiete');
      if (sicht) {
        sicht.value = vorschlag.dataset.mieteVorschlag;
        sicht.dispatchEvent(new Event('input', { bubbles: true }));
        sicht.focus();
      }
      return;
    }
  });

  dlgForm.addEventListener('submit', async e => {
    // Der Dialog schliesst sich nicht mehr von selbst (siehe Kommentar am
    // <form>): erst wenn gespeichert ist, geht er zu. Schlaegt es fehl, bleibt
    // alles Eingetippte stehen und laesst sich verbessern.
    e.preventDefault();
    const form = e.target;
    const { absicht, bereich, id } = form.dataset;
    const knopf = form.querySelector('button[value="ok"]');
    const beschriftung = knopf ? knopf.textContent : '';
    if (knopf) { knopf.disabled = true; knopf.textContent = 'Wird gespeichert …'; }

    try {
      if (absicht === 'stamm') {
        // dialogFelder statt stammfelder(): nur die tatsächlich gezeigten Felder,
        // inkl. der beim Nießbrauch-Umschalten dazugekommenen (CCCI).
        await api(`/objekte/${encodeURIComponent(slug)}`,
                  { method: 'PATCH', body: ausFormular(form, dialogFelder) });
      } else if (absicht === 'weg') {
        await api(`/objekte/${encodeURIComponent(slug)}`,
                  { method: 'PATCH', body: ausFormular(form, WEGFELDER) });
      } else if (absicht === 'anteil') {
        const werte = ausFormular(form, ANTEILFELDER);
        await api(`/objekte/${encodeURIComponent(slug)}/anteile`, {
          method: 'POST',
          body: { eigentuemer_id: Number(werte.eigentuemer_id),
                  promille: Number(werte.promille) || 1000,
                  einheit: werte.einheit || '',
                  notiz: werte.notiz || '' },
        });
      } else if (absicht === 'einheit') {
        const werte = { ...ausFormular(form, EINHEITFELDER),
                        nutzflaechen: nutzAusFormular(form),
                        gemeinflaechen: gemeinAusFormular(form) };
        if (id) {
          await api(`/einheiten/${id}`, { method: 'PATCH', body: werte });
        } else {
          await api(`/objekte/${encodeURIComponent(slug)}/einheiten`,
                    { method: 'POST', body: werte });
        }
      } else if (absicht === 'zeitraum') {
        const werte = ausFormular(form, ZEITRAUMFELDER);
        await api(`/objekte/${encodeURIComponent(slug)}/zeitraeume`,
                  { method: 'POST', body: { jahr: Number(werte.jahr) } });
      } else if (absicht === 'stand') {
        const werte = ausFormular(form, dialogFelder);
        await api(`/kredite/${id}/staende`, {
          method: 'POST',
          body: { jahr: Number(werte.jahr), restschuld: werte.restschuld || 0,
                  ...(werte.zinsen_ist != null ? { zinsen_ist: werte.zinsen_ist } : {}) },
        });
        await laden();
        // Gleich weiter: Jahresstände werden meist mehrere auf einmal gepflegt.
        return standFormular(id);
      } else if (absicht === 'grundschuld') {
        const werte = ausFormular(form, GRUNDSCHULDFELDER);
        // Immer mitgeschickt, nie weggelassen: die Blasen zeigen den Stand, den
        // der Nutzer gerade bestätigt hat — „unangetastet lassen" gibt es in
        // dieser Maske nicht, hier wird stets neu gesetzt.
        const kredit_ids = [...form.querySelectorAll('[data-gs-kredit].gewaehlt')]
          .map(b => Number(b.dataset.gsKredit));
        const body = { ...werte, kredit_ids };
        if (id) {
          await api(`/grundschulden/${id}`, { method: 'PATCH', body });
        } else {
          await api(`/objekte/${encodeURIComponent(slug)}/grundschulden`,
                    { method: 'POST', body });
        }
      } else {
        // Nicht `cfgFuer(bereich).felder`: bei den Verträgen entscheidet die
        // Vertragsart, welche Felder überhaupt dastanden.
        // Pseudo-Rubriken (Erwerbsnebenkosten) schicken feste Werte mit und
        // sprechen den geteilten Endpunkt an (CCCXIX).
        const werte = { ...ausFormular(form, dialogFelder),
                        ...(RUBRIK_FESTWERTE[bereich] || {}) };
        const ep = endpunktBereich(bereich);
        let miete_id = id;
        if (id) {
          await api(`/stammdaten/${ep}/${id}`, { method: 'PATCH', body: werte });
        } else {
          // N228 — eine geplante Mieterhöhung verknüpft den neuen Mietstand mit
          // dem, den sie ablöst — nur so gelten dessen Dokumente auch hier.
          const anlegeWerte = (bereich === 'mieten' && form.dataset.vorgaenger)
            ? { ...werte, vorgaenger_id: Number(form.dataset.vorgaenger) } : werte;
          const neu = await api(`/objekte/${encodeURIComponent(slug)}/${ep}`,
                                { method: 'POST', body: anlegeWerte });
          miete_id = neu.id;
        }
        if (bereich === 'mieten') {
          await bewohnerSpeichern(form, miete_id);
          // Die Erhöhung löst den bisherigen Stand ab — er endet am Tag davor.
          if (form.dataset.vorgaenger && werte.ab_datum) {
            await api(`/stammdaten/mieten/${form.dataset.vorgaenger}`, {
              method: 'PATCH', body: { bis_datum: tagDavor(werte.ab_datum) } });
          }
        }
      }
      dlg.close();
      await laden();
    } catch (fehler) {
      melde(String(fehler.message || 'Konnte nicht gespeichert werden.'), 'neg');
    } finally {
      if (knopf) { knopf.disabled = false; knopf.textContent = beschriftung; }
    }
  });

  inhalt.addEventListener('click', async e => {
    /* ---- Dokumentenbaum (CCXCIX) ---- */
    const bf = e.target.closest('[data-bfilter]');
    if (bf) { baumFilterUmschalten(bf.dataset.bfilter); return; }
    const bm = e.target.closest('[data-bmehr]');
    if (bm) { baumMehrZeigen(bm.dataset.bmehr); return; }
    // CCCXXXI — Ordnerkopf antippen: auf-/zuklappen.
    const ba = e.target.closest('[data-bast]');
    if (ba) { baumAstUmschalten(ba.dataset.bast); return; }
    // CCCXXXI — Jahres-Filter im Nebenkosten-Ordner.
    const bj = e.target.closest('[data-bjahr]');
    if (bj) { baumJahrSetzen(bj.dataset.bjahr); return; }
    // CCCXXI — auf das Statuszeichen eines zugeordneten Belegs tippen: umhängen.
    // Erst die alte Zuordnung lösen, dann den Zuordnen-Dialog wie sonst.
    const um = e.target.closest('[data-umhaengen]');
    if (um) {
      const dokId = Number(um.dataset.umhaengen);
      const dok = (getBaumDaten()?.aeste || []).flatMap(a => a.dokumente)
        .find(d => d.id === dokId) || { dateiname: 'Dokument' };
      const gewaehlt = await zuordnenDialog(dok, um.dataset.rubrik || '', true);
      if (!gewaehlt) return;
      try {
        await api(`/dokumente/${dokId}/loese-zuordnung`, { method: 'POST' });
        if (gewaehlt.entfernen) {
          melde('Zuordnung gelöst — der Beleg ist wieder offen', '');
        } else {
          const r = await api(`/dokumente/${dokId}/zuordnen`,
                              { method: 'POST', body: gewaehlt });
          const wo = (r.angelegt || []).map(a => a.wo).filter(Boolean).join(' · ');
          melde(wo ? `Umgehängt: ${wo}` : 'Neu zugeordnet', 'pos');
        }
        await laden();
      } catch (fehler) { melde(fehler.message || 'Umhängen fehlgeschlagen', 'neg'); }
      return;
    }

    const zu = e.target.closest('[data-zuordnen]');
    if (zu) {
      const dokId = Number(zu.dataset.zuordnen);
      const dok = (getBaumDaten()?.aeste || []).flatMap(a => a.dokumente)
        .find(d => d.id === dokId) || { dateiname: 'Dokument' };
      const gewaehlt = await zuordnenDialog(dok, zu.dataset.rubrik || '');
      if (!gewaehlt) return;
      zu.disabled = true; zu.textContent = '…';
      try {
        const r = await api(`/dokumente/${dokId}/zuordnen`,
                            { method: 'POST', body: gewaehlt });
        const wo = (r.angelegt || []).map(a => a.wo).filter(Boolean).join(' · ');
        melde(wo ? `Angelegt: ${wo} — unten als Entwurf bestätigen`
                  : 'Aus diesem Beleg liess sich kein Eintrag ableiten', wo ? 'pos' : '');
        await laden();
      } catch (fehler) {
        zu.disabled = false; zu.textContent = 'zuordnen';
        melde(fehler.message || 'Zuordnen fehlgeschlagen', 'neg');
      }
      return;
    }

    const einheitWeg = e.target.closest('[data-einheit-weg]');
    if (einheitWeg) {
      e.stopPropagation();
      const eintrag = ObjState.einheiten.find(x =>
        String(x.id) === einheitWeg.dataset.einheitWeg);
      const ja = await frage(`„${eintrag ? eintrag.bezeichnung : 'Einheit'}“ entfernen?`,
        'Die Einheit wird gelöscht. Mietverhältnisse, die daran hängen, müssen '
        + 'vorher weg — sonst gehörten sie zu keiner Wohnung mehr.',
        { knopf: 'Entfernen', gefahr: true });
      if (!ja) return;
      try {
        await api(`/einheiten/${einheitWeg.dataset.einheitWeg}`, { method: 'DELETE' });
      } catch (fehler) {
        return melde(String(fehler.message || 'Konnte nicht entfernt werden.'), 'neg');
      }
      return laden();
    }

    const einheitEdit = e.target.closest('[data-einheit-edit]');
    if (einheitEdit) {
      const eintrag = ObjState.einheiten.find(x =>
        String(x.id) === einheitEdit.dataset.einheitEdit);
      if (!eintrag) return;
      return formular({ titel: 'Einheit bearbeiten', felder: EINHEITFELDER,
                        werte: eintrag, absicht: 'einheit',
                        extra: nutzBlock(eintrag.nutzflaechen || [])
                          + gemeinBlock(eintrag.gemeinflaechen || []) });
    }

    // N217 — Info-Popup für die Einheiten-Erklärung (was früher als Fußnote unten stand).
    const infoBtn = e.target.closest('[data-info]');
    if (infoBtn) { frage('Einheiten', infoBtn.dataset.info, { knopf: 'Alles klar' }); return; }

    if (e.target.closest('[data-einheit-neu]')) {
      return formular({ titel: 'Einheit anlegen', felder: EINHEITFELDER,
                        absicht: 'einheit', knopf: 'Anlegen',
                        extra: nutzBlock([]) + gemeinBlock([]),
                        hinweis: 'Wohnung, Büro oder Stellplatz — die Bezeichnung '
                          + 'steht später auf den Mietverhältnissen und in der '
                          + 'Abrechnung.' });
    }

    const einheit = e.target.closest('[data-einheit]');
    if (einheit) {
      location.href = einheitUrl(einheit.dataset.einheit);
      return;
    }

    // N… — der dezente Aufklapper blendet die verborgenen (leeren, aber
    // belegbehafteten) Zeiträume ein bzw. wieder aus. Reine Anzeige, kein Reload.
    const alteSchalter = e.target.closest('[data-alte-zeitraeume]');
    if (alteSchalter) {
      const liste = alteSchalter.parentElement.querySelector('[data-alte-liste]');
      if (liste) {
        const auf = liste.hasAttribute('hidden');
        liste.toggleAttribute('hidden', !auf);
        const label = alteSchalter.querySelector('[data-alte-label]');
        if (label) label.textContent = auf ? 'Ausblenden' : 'Anzeigen';
        const pfeil = alteSchalter.querySelector('[data-alte-pfeil]');
        if (pfeil) pfeil.textContent = auf ? '▴' : '▾';
      }
      return;
    }

    const zeitraum = e.target.closest('[data-zeitraum]');
    if (zeitraum) {
      location.href = `zeitraum.html?z=${zeitraum.dataset.zeitraum}`;
      return;
    }

    // N141 — die Anfangszählerstand-Rubrik öffnet die Übersicht: alle Zähler des
    // Objekts mit ihrem Erststand, die fehlenden oben, erfasst wird gleich dort.
    // Nur wenn es überhaupt noch keine Zähler gibt, führt der Weg weiterhin in
    // die Zähler-Konfig des Zeitraums — angelegt werden Zähler dort (CCCLXXX (a)).
    const erststand = e.target.closest('[data-erststand]');
    if (erststand) {
      if (ObjState.zaehlerListe.length) return anfangsstaendeDialog();
      if (erststand.dataset.z) {
        location.href = `zeitraum.html?z=${encodeURIComponent(erststand.dataset.z)}`;
      } else {
        formular({ titel: 'Abrechnungszeitraum anlegen', felder: ZEITRAUMFELDER,
                   absicht: 'zeitraum' });
      }
      return;
    }

    if (e.target.closest('[data-zeitraum-werkzeug]')) {
      return zeitraumWerkzeug(laden);
    }

    if (e.target.closest('[data-zeitraum-neu]')) {
      return formular({ titel: 'Abrechnungszeitraum anlegen', felder: ZEITRAUMFELDER,
                        absicht: 'zeitraum' });
    }

    if (e.target.closest('[data-stamm]')) {
      // CCCXXXVI — beim Grundstück bearbeitet dieses eine Formular auch die
      // Grundstücks- und Grundsteuer-Angaben (GRUND_STAMMFELDER). Der Kopfhinweis
      // erklärt die Grundsteuer-Kette; die Feld-Notizen tun das je Feld.
      return formular({ titel: 'Stammdaten bearbeiten', felder: stammfelder(),
                        werte: objekt, absicht: 'stamm',
                        hinweis: istGrundstueck()
                          ? 'Reihenfolge der Grundsteuer: Grundsteuerwert '
                            + '(Finanzamt) × Steuermesszahl = Steuermessbetrag '
                            + '(Finanzamt) × Hebesatz (Gemeinde) = Grundsteuer/Jahr. '
                            + 'Der Grundstückswert ist der Marktwert und steht nicht '
                            + 'im Bescheid.'
                          : '' });
    }

    if (e.target.closest('[data-weg]')) {
      return formular({ titel: 'WEG-Ebene bearbeiten', felder: WEGFELDER,
                        werte: objekt, absicht: 'weg',
                        hinweis: 'Ist die Wohnung Teil einer '
                          + 'Wohnungseigentümergemeinschaft, verteilt die '
                          + 'Hausverwaltung die Nebenkosten. ImmoCalc verteilt '
                          + 'dann nicht selbst — du trägst die fertigen Werte je '
                          + 'Mieter direkt ein. Hausgeld ist ein '
                          + 'Eigentümerkosten.' });
    }

    if (e.target.closest('[data-anteil-neu]')) return anteilFormular();

    const anteilWeg = e.target.closest('[data-anteil]');
    if (anteilWeg) {
      const ja = await frage('Zuordnung entfernen?',
        'Der Eigentümer bleibt erhalten — nur die Beteiligung an dieser '
        + 'Immobilie wird gelöst.', { knopf: 'Entfernen', gefahr: true });
      if (!ja) return;
      try {
        await api(`/anteile/${anteilWeg.dataset.anteil}`, { method: 'DELETE' });
      } catch (fehler) {
        return melde(String(fehler.message || 'Konnte nicht entfernt werden.'), 'neg');
      }
      return laden();
    }

    const cloud = e.target.closest('[data-cloud]');
    if (cloud && cloud.dataset.cloud === 'status') return cloudZeigen();
    if (cloud) {
      cloud.disabled = true;
      cloud.textContent = 'Lege an …';
      try {
        const antwort = await api(
          `/nextcloud/objekte/${encodeURIComponent(slug)}/struktur`, { method: 'POST' });
        cloud.textContent = antwort.neu_angelegt.length
          ? `${antwort.neu_angelegt.length} Ordner angelegt`
          : 'Alles schon vorhanden';
        setTimeout(cloudZeigen, 1600);
      } catch (fehler) {
        cloud.disabled = false;
        cloud.textContent = 'Fehlgeschlagen — nochmal';
        melde(String(fehler.message || fehler), 'neg');
      }
      return;
    }

    if (e.target.closest('[data-export]')) {
      location.href = `/api/objekte/${encodeURIComponent(slug)}/export`;
      return;
    }

    const weg = e.target.closest('[data-loeschen]');
    if (weg) {
      // Schieben statt klicken: Löschen ist nicht rückgängig zu machen, und ein
      // zweiter Klick an derselben Stelle passiert zu leicht aus Versehen.
      const ja = await schiebeFrage(`„${objekt.titel || objekt.name}“ löschen`,
        'Alle Eingaben zu dieser Immobilie werden entfernt. Die Unterlagen in '
        + 'der Nextcloud bleiben bestehen; eine Sicherung wird vorher dort '
        + 'abgelegt.', 'Zum Löschen schieben');
      if (!ja) return;
      weg.disabled = true;
      weg.textContent = 'Sichere und lösche …';
      try {
        const antwort = await api(`/objekte/${encodeURIComponent(slug)}`,
                                  { method: 'DELETE' });
        // Erst melden, dann zurück: sonst wäre die Bestätigung schon weg,
        // bevor sie jemand gelesen hat.
        melde(antwort.sicherung?.gesichert
          ? `„${antwort.name}“ gelöscht · Sicherung: ${antwort.sicherung.pfad}`
          : `„${antwort.name}“ gelöscht — ohne Sicherung in der Nextcloud `
            + `(${antwort.sicherung?.grund || 'kein Grund genannt'})`,
          antwort.sicherung?.gesichert ? 'pos' : '');
        setTimeout(() => { location.href = 'index.html'; }, 2600);
      } catch (fehler) {
        weg.disabled = false;
        weg.textContent = 'Immobilie löschen';
        melde(String(fehler.message || fehler), 'neg');
      }
      return;
    }

    // CCCLXXXI — einen Lageplan umbenennen (nur der Anzeigename am Datensatz).
    const lpUm = e.target.closest('[data-lageplan-rename]');
    if (lpUm) {
      e.stopPropagation();
      return lageplanUmbenennen(lpUm.dataset.e, lpUm.dataset.lageplanRename,
                                lpUm.dataset.name, laden);
    }

    // CCCLXXXI — einen Lageplan entfernen. Nur der Eintrag geht; die Datei in der
    // Nextcloud bleibt (der Endpunkt fasst die Cloud gar nicht an).
    const lpWeg = e.target.closest('[data-lageplan-weg]');
    if (lpWeg) {
      e.stopPropagation();
      return lageplanEntfernen(lpWeg.dataset.e, lpWeg.dataset.lageplanWeg, laden);
    }

    // CCCXXVI — einen hinterlegten Lageplan als Bild-Vorschau öffnen (dieselbe
    // Ansicht wie ein Beleg, über den Dokument-Inhalt).
    const lageplan = e.target.closest('[data-lageplan]');
    if (lageplan) {
      e.stopPropagation();
      lageplanAnsehen(lageplan.dataset.lageplan, lageplan.dataset.name, lageplan.dataset.pfad);
      return;
    }

    // CCLXXVIII — Orange-Entwürfe: den Beleg ansehen, bestätigen, verwerfen.
    const beleg = e.target.closest('[data-beleg]');
    if (beleg) {
      e.stopPropagation();
      belegAnsehen(`/api/dokumente/${beleg.dataset.beleg}/inhalt`,
                   beleg.dataset.name || 'Beleg', beleg.dataset.pfad || '');
      return;
    }

    const ok = e.target.closest('[data-ok]');
    if (ok) {
      e.stopPropagation();
      const [typ, id] = ok.dataset.ok.split(':');
      ok.disabled = true;
      try {
        await api(`/entwuerfe/${typ}/${id}/bestaetigen`, { method: 'POST' });
      } catch (fehler) {
        ok.disabled = false;
        return melde(String(fehler.message || 'Konnte nicht bestätigt werden.'), 'neg');
      }
      return laden();
    }

    const zurueck = e.target.closest('[data-zurueck]');
    if (zurueck) {
      e.stopPropagation();
      const [typ, id] = zurueck.dataset.zurueck.split(':');
      const ja = await frage('Zurück zum Prüfen?',
        'Der Entwurf wird verworfen. Der Beleg bleibt erhalten und geht zurück in '
        + 'den Prüfmodus, wo du ihn neu zuordnen kannst.',
        { knopf: 'Verwerfen', gefahr: true });
      if (!ja) return;
      try {
        await api(`/entwuerfe/${typ}/${id}/verwerfen`, { method: 'POST' });
      } catch (fehler) {
        return melde(String(fehler.message || 'Konnte nicht verworfen werden.'), 'neg');
      }
      return laden();
    }

    const del = e.target.closest('[data-del]');
    if (del) {
      e.stopPropagation();
      const [bereich, id] = del.dataset.del.split(':');
      const ja = await frage(`${cfgFuer(bereich).einzahl} löschen?`,
        'Der Eintrag wird entfernt. Rückgängig machen lässt sich das nicht.',
        { knopf: 'Löschen', gefahr: true });
      if (!ja) return;
      try {
        await api(`/stammdaten/${endpunktBereich(bereich)}/${id}`, { method: 'DELETE' });
      } catch (fehler) {
        return melde(String(fehler.message || 'Konnte nicht gelöscht werden.'), 'neg');
      }
      return laden();
    }

    const add = e.target.closest('[data-add]');
    if (add) {
      const bereich = add.dataset.add;
      const cfg = cfgFuer(bereich);
      // Im Fokus ist die Einheit schon entschieden — die Blase steht vorgewählt da.
      const werte = bereich === 'mieten' && ObjState.fokus
        ? { einheit: ObjState.fokus.bezeichnung } : {};
      return formular({ titel: `${cfg.einzahl} hinzufügen`,
                        felder: felderFuer(bereich, werte), bereich, werte,
                        absicht: 'eintrag',
                        extra: bereich === 'mieten' ? mietExtra(null) : '' });
    }

    // CCCXIII — Klick auf einen Eintrag öffnet die Detailansicht (Daten links,
    // Beleg rechts). Das Bearbeiten-Formular ist von dort aus erreichbar.
    const edit = e.target.closest('[data-edit]');
    if (edit) {
      const [bereich, id] = edit.dataset.edit.split(':');
      return eintragDetail(bereich, id, laden);
    }

    // CCXXIX — Grundschulden hängen nicht an BEREICHE (eigene Endpunkte), daher
    // eigene data-Attribute statt data-add/-edit/-del.
    if (e.target.closest('[data-gs-neu]')) return grundschuldFormular(null);

    const gsEdit = e.target.closest('[data-gs-edit]');
    if (gsEdit) {
      const g = ObjState.grundschulden.find(x => String(x.id) === gsEdit.dataset.gsEdit);
      return g ? grundschuldFormular(g) : undefined;
    }

    const gsWeg = e.target.closest('[data-gs-weg]');
    if (gsWeg) {
      e.stopPropagation();
      const ja = await frage('Grundschuld löschen?',
        'Der Eintrag wird entfernt. Rückgängig machen lässt sich das nicht.',
        { knopf: 'Löschen', gefahr: true });
      if (!ja) return;
      try {
        await api(`/grundschulden/${gsWeg.dataset.gsWeg}`, { method: 'DELETE' });
      } catch (fehler) {
        return melde(String(fehler.message || 'Konnte nicht gelöscht werden.'), 'neg');
      }
      return laden();
    }
  });

  inhalt.addEventListener('change', async e => {
    const feld = e.target.closest('[data-lageplan-neu]');
    if (!feld) return;
    return lageplanHochladen(feld, laden);
  });
}
