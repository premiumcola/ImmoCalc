/* N216 — `laden()`: die Seite frisch aus der API aufbauen. Ruft alle Detail-
   Renderer aus den themenreinen Modulen (stammdaten, einheiten, miete,
   diagramm, eigentuemer, cloud, grundschulden, lageplan, anfangsstaende) auf.

   Reihenfolge auf der Hausebene:
     Chart → Einheiten → Abrechnungszeiträume → Stammdaten →
     Dokumentenablage → Eigentümer → Miete → Notarverträge → Grundschulden →
     Erwerbsnebenkosten → Versicherungen → Kredite → Finanzamt → Hinweise.
   Auf der Einheitenebene:
     Chart → Einheit-Stamm → Mieten → Abrechnungszeiträume. */

import { esc, melde, api, logoSvg, installHilfe, fristKlasse, fristText, eur } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { flaecheText, proJahr } from '../objekt-format.js?v=2';
import { BEREICHE, ERWERB_KATEGORIE } from '../objekt-felder.js?v=2';
import { objekt, slug, setObjekt, setObjektEigentuemer, setAlleEigentuemer,
         istGrundstueck } from '../objekt-state.js?v=2';
import { grundStammHtml, erwerbKopfHtml, grundsteuerHtml,
         pachtErtragHtml } from '../objekt-grundstueck.js?v=2';
import * as ObjState from './state.js';
import { setDaten, setEinheiten, setFokus, setGrundschulden, setBereicheDaten,
         setZaehlerListe, setErststandZiel } from './state.js';
import { effektiveFlaeche, nachpflegeHtml, kennzahlenHtml, zuEinheit } from './helpers.js';
import { stammHtml, wegHtml } from './stammdaten.js';
import { einheitenHtml, einheitStammHtml, objektSummenHtml } from './einheiten.js';
import { mietDiagrammHtml } from './diagramm.js';
import { abschnitt } from './miete.js';
import { erststandHtml } from './anfangsstaende.js';
import { eigentuemerHtml } from './eigentuemer.js';
import { grundschuldenHtml } from './grundschulden.js';
import { cloudZeigen } from './cloud.js';
import { lageplanVorschauAufraeumen, lageplanVorschauFuellen } from './lageplan.js';

const anfrage = new URLSearchParams(location.search);
/* CLXVIII — dieselbe Seite, zwei Ebenen: ohne `e` das ganze Haus, mit `e` die
   eine Einheit im Fokus. Als zweite Datei wären Mietverhältnis, Kontakte und
   Abrechnung ein zweites Mal zu pflegen und liefen mit der Zeit auseinander. */
const fokusWunsch = anfrage.get('e');

export async function laden() {
  const inhalt = document.getElementById('inhalt');
  const titel = document.getElementById('titel');
  const sub = document.getElementById('sub');
  // Beim Neuaufbau die Object-URLs der Lageplan-Vorschau freigeben.
  lageplanVorschauAufraeumen();
  if (!slug) {
    inhalt.innerHTML = `<div class="empty"><div class="big">Kein Objekt gewählt</div>
      <p>Zurück zur Übersicht und eine Immobilie antippen.</p></div>`;
    return;
  }
  let det;
  try {
    det = await api(`/objekte/${encodeURIComponent(slug)}`);
  } catch (fehler) {
    inhalt.innerHTML = `<div class="empty"><div class="big">Objekt nicht gefunden</div>
      <p>${esc(String(fehler.message || 'Die Daten konnten nicht geladen werden.'))}</p></div>`;
    return;
  }

  // Die Nebenabrufe duerfen einzeln danebengehen — dass eine Versicherungsliste
  // hakt, heisst nicht, dass es das Objekt nicht gibt. Fehlende Bereiche bleiben
  // leer, gemeldet wird einmal am Ende.
  const luecken = [];
  const zweig = async (was, ruf, ersatz) => {
    try { return await ruf(); }
    catch (fehler) { luecken.push(`${was}: ${fehler.message || fehler}`); return ersatz; }
  };
  const [bereiche, anteile, vermoegen, einheitenRoh, grundschuldenRoh,
         eigentuemerAlle, zaehlerRoh] = await Promise.all([
    Promise.all(Object.keys(BEREICHE).map(async b =>
      [b, await zweig(BEREICHE[b].titel,
                      () => api(`/objekte/${encodeURIComponent(slug)}/${b}`), [])]))
      .then(Object.fromEntries),
    zweig('Eigentümer', () => api(`/objekte/${encodeURIComponent(slug)}/anteile`), null),
    zweig('Vermögen',
          async () => (await api('/vermoegen')).objekte.find(z => z.slug === slug),
          null),
    zweig('Einheiten',
          () => api(`/objekte/${encodeURIComponent(slug)}/einheiten`), []),
    zweig('Grundschulden',
          () => api(`/objekte/${encodeURIComponent(slug)}/grundschulden`), []),
    // CCCXXXV — alle Personen für die Nießbrauch-Auswahl; darf leer bleiben.
    zweig('Eigentümerliste', () => api('/eigentuemer'), []),
    // CCCLXXX (a) — Zähler des Objekts für die Anfangszählerstand-Rubrik. Beiwerk:
    // scheitert der Abruf, bleibt die Rubrik einfach weg.
    zweig('Zähler', () => api(`/objekte/${encodeURIComponent(slug)}/zaehler`), []),
  ]);
  if (luecken.length) melde(`Nicht alles konnte geladen werden — ${luecken[0]}`, 'neg');

  setObjekt(det.objekt);
  setDaten(det);
  // Ein Grundstück hat keine Einheiten — dort darf die zweite Ebene gar nicht
  // erst auftauchen, auch nicht über einen alten Link.
  setEinheiten(istGrundstueck() ? [] : (einheitenRoh || []));
  setGrundschulden(grundschuldenRoh || []);
  setBereicheDaten(bereiche || {});
  setZaehlerListe(Array.isArray(zaehlerRoh) ? zaehlerRoh : []);
  setObjektEigentuemer([...new Set((anteile?.anteile || [])
    .map(a => a.name).filter(Boolean))]);
  // CCCXXXV — Namen aller app-weit geführten Eigentümer (Personen).
  setAlleEigentuemer([...new Set((Array.isArray(eigentuemerAlle) ? eigentuemerAlle : [])
    .map(e => e && e.name).filter(Boolean))]);
  // einheiten kommt jetzt aus state — Live-Binding via Namespace-Import:
  const einheiten = ObjState.einheiten;
  const fokusWert = fokusWunsch
    ? (einheiten.find(e => String(e.id) === String(fokusWunsch)) || null)
    : null;
  setFokus(fokusWert);
  if (fokusWunsch && !fokusWert) {
    melde('Diese Einheit gibt es nicht mehr — hier steht das ganze Haus.', '');
  }

  // N70 — im Kopf steht der kanonische Immobilientitel „(Ort) Straße", nie ein
  // versehentlich als `name` gespeicherter Einheitenname („Wohnung 1.OG").
  // Im Einheiten-Fokus zeigt der Kopf weiterhin die Einheit.
  titel.textContent = fokusWert ? fokusWert.bezeichnung : (objekt.titel || objekt.name);
  document.getElementById('barlogo').innerHTML = logoSvg(objekt.typ);
  // Der Ort enthaelt oft schon die Einheitenzahl ("Mixed-Use · 7 Einheiten") —
  // dann nicht zusaetzlich zaehlen, sonst steht es doppelt und die Zeile bricht um.
  const ortText = (objekt.ort || objekt.strasse || '').trim();
  if (fokusWert) {
    // Im Fokus beschreibt die Unterzeile die Einheit. Das Haus steht in der
    // Karte darunter — hier stünde es ein zweites Mal.
    sub.textContent = [fokusWert.nutzungsart,
                       fokusWert.flaeche ? flaecheText(fokusWert.flaeche) : '',
                       fokusWert.mieter].filter(Boolean).join(' · ') || 'Einheit';
  } else if (istGrundstueck()) {
    // CCCXXXVI — der Objektname allein sagt beim Grundstück wenig. Die Unterzeile
    // trägt deshalb die Flurnummer: Ort · Gemarkung · Flur · Nutzungsart · Fläche.
    // Einzeilig gekürzt (siehe #sub im <style>), damit nichts umbricht.
    const flaeche = objekt.grundstueck_flaeche
      ? `${Number(objekt.grundstueck_flaeche).toLocaleString('de-DE')} m²` : '';
    sub.textContent = [ortText,
                       objekt.gemarkung && `Gemarkung ${objekt.gemarkung}`,
                       objekt.flurstueck && `Flur ${objekt.flurstueck}`,
                       objekt.grundstueck_nutzungsart, flaeche]
      .filter(Boolean).join(' · ') || 'Grundstück';
  } else {
    sub.textContent = /einheit|wohnung/i.test(ortText) || !ortText
      ? (ortText || `${det.einheiten.length} Einheit${det.einheiten.length === 1 ? '' : 'en'}`)
      : `${ortText} · ${det.einheiten.length} Einheit${det.einheiten.length === 1 ? '' : 'en'}`;
  }

  const laufend = det.zeitraeume.find(z => z.status === 'in Arbeit');
  // N… — leere Zeiträume (0 Kostenpositionen) blenden wir aus: sie sind
  // automatisch beim Verknüpfen von Belegen entstanden (alle mit Status
  // „in Arbeit") und drängen sich sonst (2010–2024) in die Liste. Sichtbar
  // bleibt, was Positionen hat — plus der EINE aktuelle Arbeitsstand, der
  // jüngste offene Zeitraum, damit man immer eine laufende Abrechnung hat.
  // Die verborgenen (mit Belegen) bietet ein dezenter Aufklapper an, damit sie
  // erreichbar bleiben. Kein Löschen, reine Anzeige-Logik.
  const arbeitsstand = det.zeitraeume
    .filter(z => z.status === 'in Arbeit')
    .reduce((a, z) => (a && a.ende >= z.ende ? a : z), null);
  const sichtbar = det.zeitraeume.filter(z =>
    (z.positionen || 0) > 0 || (arbeitsstand && z.id === arbeitsstand.id));
  const verborgen = det.zeitraeume.filter(z => !sichtbar.includes(z));
  const zeitraumEintrag = (z, alt) => {
    // Beim Grundstück gilt keine § 556-Mietrechtsfrist — dort steht ein
    // neutraler Zustand statt „noch X Tage" (CCC). Verborgene tragen statt der
    // Frist ihre Belegzahl, damit klar ist, warum sie hier angeboten werden.
    const chip = alt
      ? `<span class="chip">${z.belege || 0} Beleg${z.belege === 1 ? '' : 'e'}</span>`
      : z.status !== 'in Arbeit'
        ? '<span class="chip">abgeschlossen</span>'
        : istGrundstueck()
          ? '<span class="chip">in Arbeit</span>'
          : `<span class="chip ${fristKlasse(z.frist_tage)}">${esc(fristText(z.frist_tage) || 'in Arbeit')}</span>`;
    // N49 — Stand je Zeitraum: erfasste NK (Σ Positionen) und, wenn vorhanden,
    // die eingezahlten Abschläge samt Prozent + über-/unterlaufen. Nur an
    // sichtbaren (bearbeiteten) Zeiträumen; bei verborgenen wäre es 0.
    const k = z.kosten_summe || 0, a = z.abschlag_summe || 0;
    let stand = '';
    if (!alt && (k || a)) {
      const teile = [`NK erfasst <b>${eur(k)}</b>`];
      if (a > 0) {
        const pct = Math.round(k / a * 100);
        const farbe = k > a ? 'var(--neg)' : 'var(--pos)';
        teile.push(`Abschläge ${eur(a)}`,
          `<b style="color:${farbe}">${pct}%${k > a ? ' · über' : ''}</b>`);
      }
      stand = `<span class="ed" style="margin-top:3px;font-family:var(--mono);font-size:11px">${teile.join(' · ')}</span>`;
    }
    return `<button class="eintrag klick" data-zeitraum="${z.id}"
                    style="cursor:pointer${alt ? ';opacity:.66' : ''}">
        <span class="et">
          <span class="en">${z.jahr ? `Abrechnungszeitraum ${z.jahr}` : esc(z.label)}</span>
          <span class="ed">${z.jahr ? `${esc(z.label)} · ${esc(z.typ)}` : esc(z.typ)}</span>
          ${stand}</span>${chip}
        <span class="ew" style="color:var(--soft);font-family:var(--body)">›</span>
      </button>`;
  };
  const aufklapper = verborgen.length
    ? `<button class="eintrag klick" data-alte-zeitraeume="1"
              style="cursor:pointer;color:var(--soft)">
        <span class="et">
          <span class="en" style="font-weight:500;color:var(--soft)">${verborgen.length} ${verborgen.length === 1 ? 'Zeitraum' : 'Zeiträume'} mit Belegen, ohne Positionen</span>
          <span class="ed" data-alte-label>Anzeigen</span></span>
        <span class="ew" data-alte-pfeil style="color:var(--soft);font-family:var(--body)">▾</span>
      </button>
      <div data-alte-liste hidden>${verborgen.map(z => zeitraumEintrag(z, true)).join('')}</div>`
    : '';
  const zr = det.zeitraeume.length
    ? (sichtbar.map(z => zeitraumEintrag(z, false)).join('') + aufklapper)
      || `<div class="leerzeile">Noch kein Abrechnungszeitraum</div>`
    : `<div class="leerzeile">Noch kein Abrechnungszeitraum</div>`;

  // Was heute läuft: beendete Stände zählen nicht, geplante noch nicht.
  const jahresmiete = (bereiche.mieten || [])
    .filter(m => !m.beendet && !m.geplant)
    .reduce((s, m) => s + (m.kaltmiete || 0) * proJahr(m.turnus), 0);

  // Schulden und Guthaben getrennt: `restschuld_aktuell` ist beim
  // Bausparvertrag 0 und `guthaben_aktuell` beim Darlehen — die API trennt
  // beides, damit hier nichts zusammenfällt, was gegensätzlich ist.
  const restschuld = (bereiche.kredite || []).reduce(
    (s, k) => s + (k.restschuld_aktuell ?? k.restschuld ?? 0), 0);
  const guthaben = (bereiche.kredite || []).reduce(
    (s, k) => s + (k.guthaben_aktuell || 0), 0);

  // Ein Grundstück rechnet keine Mieter-Nebenkosten ab: § 556-Frist und
  // Abrechnungszeiträume gehören nicht hierher. Die Grundsteuer ist so gering,
  // dass sie ohne eigenen Zeitraum direkt im Grundstücksblock verrechnet wird
  // (CCCIII, ersetzt CCC).
  // Die Zähler-Konfig (samt Anfangsstand-Erfassung) liegt in zeitraum.html und
  // ist über einen Abrechnungszeitraum erreichbar — bevorzugt der laufende.
  const erststandZielId = (laufend && laufend.id != null) ? laufend.id
    : (det.zeitraeume[0] && det.zeitraeume[0].id != null ? det.zeitraeume[0].id : null);
  // N141 — der Dialog braucht das Ziel auch später noch (Weg in die
  // Zähler-Konfig, Auffrischen der Rubrik nach dem Speichern).
  setErststandZiel(erststandZielId);
  const zeitraumBlock = istGrundstueck() ? '' : `
    <div class="sekopf"><h2 class="sec">Abrechnungszeiträume</h2>
      ${fokusWert ? '' : `<span class="sekopf-akt">
        <button data-zeitraum-werkzeug="1">Umstellen</button>
        <button data-zeitraum-neu="1">Anlegen</button></span>`}</div>
    <div class="liste">${zr}</div>
    ${fokusWert ? `<div class="fussnote">Abgerechnet wird immer das ganze Haus;
      im Zeitraum steht, was davon auf diese Einheit entfällt.</div>` : ''}
    ${erststandHtml(erststandZielId)}`;

  if (fokusWert) {
    // CLXVIII — im Fokus zählen die Mieterthemen. Stammdaten, Eigentümer,
    // Kredite, Versicherungen, Steuer und Ablage gehören dem Haus und werden
    // hier bewusst nicht wiederholt.
    const eigene = (bereiche.mieten || [])
      .filter(m => zuEinheit(m) === fokusWert.bezeichnung);
    // CCCXLVI — keine zweite „Zurück zum Haus"-Titelkarte mehr: die Kopfzeile
    // bezieht sich auf die Einheit (das aktuelle Element), und „‹ Zurück" oben
    // führt ohnehin ans Haus. Die geschachtelte Titelzeile entfällt.
    // N20 — kein penetranter § 556-Fristbanner mehr oben in der Einheit; die
    // Frist steht weiterhin an den Abrechnungszeiträumen. Statt der drei
    // Kennzahl-Kacheln der grafische Einstieg: Miete/NK-Verlauf mit €/m²-Linie.
    inhalt.innerHTML = `
      ${mietDiagrammHtml(eigene, effektiveFlaeche(fokusWert))}
      ${einheitStammHtml(fokusWert)}
      ${abschnitt('mieten', eigene, { imFokus: true })}
      ${zeitraumBlock}`;
    // Die ?-Icons an Wohnfläche, Terrasse, Nebenfläche und Stellplätzen dieser
    // Einheit brauchen dieselbe Verdrahtung wie die Hausansicht.
    installHilfe(inhalt);
    // Die Inline-Vorschau des ersten Lageplans nachladen (asynchron, stört den
    // Aufbau der Seite nicht).
    lageplanVorschauFuellen(inhalt);
    return;
  }

  // Mietverhältnisse, die auf keine Einheit zeigen. Sie fallen aus der
  // Kostenverteilung (Fund XCII) — deshalb stehen sie am Haus, nicht im
  // Nirgendwo. Gibt es überhaupt keine Einheiten, ist das der Normalfall und
  // die Liste heisst schlicht „Mieten & Mieter".
  const bekannt = new Set(einheiten.map(e => e.bezeichnung));
  const heimatlos = (bereiche.mieten || []).filter(m => !bekannt.has(zuEinheit(m)));
  const mietBlock = !einheiten.length
    ? abschnitt('mieten', bereiche.mieten)
    : (heimatlos.length ? abschnitt('mieten', heimatlos, {
        kopf: 'Ohne Einheit',
        vorspann: `<div class="merker"><span class="hi">!</span><span class="ht">
            <span class="t">${heimatlos.length === 1
              ? 'Ein Mietverhältnis gehört zu keiner Einheit'
              : `${heimatlos.length} Mietverhältnisse gehören zu keiner Einheit`}</span>
            <span class="d">Ohne Einheit fällt die Partei aus der
              Kostenverteilung: sie bekommt keine Kosten und ihre Vorauszahlung
              voll erstattet. Eintrag öffnen und die Einheit antippen.</span>
          </span></div>`,
      }) : '');

  // CCCXIX — die Zahlungen teilen sich auf: das Finanzamt (Steuern u. Ä.) und
  // die einmaligen Erwerbsnebenkosten stehen in getrennten Rubriken.
  const erwerbZahlungen = (bereiche.zahlungen || [])
    .filter(z => z.kategorie === ERWERB_KATEGORIE);
  const finanzZahlungen = (bereiche.zahlungen || [])
    .filter(z => z.kategorie !== ERWERB_KATEGORIE);

  // Gemeinsame Bausteine — Ablage/Cloud und der Sicherungs-/Löschblock stehen in
  // beiden Ansichten gleich.
  const ablageBlock = `
    <div class="sekopf ablage-kopf"><span class="seikon">${kostenIcon('Dokument')}</span><h2 class="sec">Dokumentenablage</h2></div>
    <div class="ablage-pfad" id="ablagePfad"></div>
    <div id="cloudbereich"><div class="cloudbox"><div class="zeile">
      <span class="sym offen">…</span>
      <span class="txt"><span class="t">wird geprüft …</span></span>
    </div></div></div>`;
  const gefahrBlock = `
    <div class="gefahr-block">
      <div class="gt">Sicherung und Löschen</div>
      <p>Die Sicherung enthält alle Daten dieser Immobilie und lässt sich
         wieder einlesen. Beim Löschen wird sie zusätzlich in die Nextcloud
         geschrieben — die dort abgelegten Unterlagen bleiben unberührt.</p>
      <button class="btn leise" data-export="1">Sicherung herunterladen</button>
      <button class="btn gefahr" data-loeschen="1">Immobilie löschen</button>
    </div>`;

  if (istGrundstueck()) {
    // CCCXXXVI — das Grundstück in drei logischen Blöcken, von grob nach fein:
    //   A) Stammdaten — was es ist (Objektart, Adresse+Flur, Fläche, Nutzungsart,
    //      Grundstückswert).
    //   B) Erwerb & Kosten — wie erworben (Erwerbsart, Kaufpreis/-datum) und die
    //      Rubriken Notar, einmalige Erwerbsnebenkosten, Finanzamt/Grundsteuer.
    //   C) Nutzung & Pacht — die Pacht und die kleine Ertragsrechnung.
    // Eigentümer und Ablage folgen den drei Blöcken.
    inhalt.innerHTML = `
      ${nachpflegeHtml(det.nachpflege)}
      ${kennzahlenHtml(vermoegen, jahresmiete, restschuld, guthaben)}
      ${grundStammHtml(objekt)}
      ${erwerbKopfHtml(objekt)}
      ${abschnitt('notarvertraege', bereiche.notarvertraege)}
      ${abschnitt('erwerbskosten', erwerbZahlungen)}
      ${grundsteuerHtml(objekt)}
      ${abschnitt('zahlungen', finanzZahlungen)}
      ${mietBlock}
      ${pachtErtragHtml(objekt, jahresmiete)}
      ${eigentuemerHtml(anteile)}
      ${ablageBlock}
      ${gefahrBlock}`;
    installHilfe(inhalt);
    cloudZeigen();
    return;
  }

  // N21 — grafischer Einstieg GANZ OBEN: Miete/NK über alle Einheiten summiert,
  // die €/m²-Linie über die effektive Gesamtfläche (Ø €/m²). Der obere
  // KPI-Streifen entfällt: Verkehrswert und Eigenkapital gehören in die
  // Eigentümerübersicht, die Jahresmiete steckt jetzt im Diagramm. Die
  // §-556-Fristleiste ist oben raus (die Frist steht an den Zeiträumen), und der
  // „Angaben fehlen noch"-Hinweis rückt zu den sonstigen Hinweisen nach unten.
  // Reihenfolge: Chart → Einheiten → Abrechnungszeiträume → Stammdaten →
  // Dokumente/sonstige Hinweise.
  const gesamtFlaeche = einheiten.reduce((s, e) => s + effektiveFlaeche(e), 0);

  inhalt.innerHTML = `
    ${mietDiagrammHtml(bereiche.mieten, gesamtFlaeche, objektSummenHtml())}
    ${einheitenHtml()}
    ${zeitraumBlock}
    ${stammHtml(objekt)}
    ${wegHtml(objekt)}
    ${ablageBlock}
    ${eigentuemerHtml(anteile)}
    ${mietBlock}
    ${abschnitt('notarvertraege', bereiche.notarvertraege)}
    ${grundschuldenHtml()}
    ${abschnitt('erwerbskosten', erwerbZahlungen)}
    ${abschnitt('versicherungen', bereiche.versicherungen, {
      vorspann: `<p class="sehinweis">Gebäude- und Haftpflichtversicherung laufen
        als jährliche Kostenart über die <strong>Nebenkosten</strong> — hier stehen
        nur <strong>zusätzliche</strong> Policen (z. B. Rechtsschutz, Elementar).</p>` })}
    ${abschnitt('kredite', bereiche.kredite)}
    ${abschnitt('zahlungen', finanzZahlungen)}
    ${nachpflegeHtml(det.nachpflege)}
    ${gefahrBlock}`;

  installHilfe(inhalt);
  cloudZeigen();
}
