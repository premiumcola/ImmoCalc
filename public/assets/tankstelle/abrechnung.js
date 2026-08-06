/* abrechnung.js — die Abrechnungs-Karte: Kopf mit Automatik-Schalter (N193),
   der Ø-Satz-Block links (N148/N186/N195: Netz·kWh × Netzsatz = Netz·€,
   Eigen·kWh × Eigensatz = Eigen·€), die Zeitraum-Matrix rechts (aus matrix.js),
   die Nutzerliste mit Betragen + Sende-Buttons (N202: Zeitraum + Betrag im
   Knopf), Vorschau (aus blatt.js) und die Summe.

   Zusaetzlich orchestriert dieses Modul den Autoversand-Schalter, das Setzen
   und Loeschen der „abgerechnet"-Marker (N182) und laedt die Objekt-
   Einstellungen (Autoversand, Mehrnutzer-Regeln). Die Matrix-UI selbst und die
   abgerechnet-Marker-Helfer wohnen in matrix.js, weil sie logisch zur
   Zeitraum-Auswahl gehoeren. */
import { S, kwh, zahl, satzText, datum, zeigeFehler } from './state.js';
import { api, esc, eur, melde } from '../immo.js';
import { infoKnopfText, INFOS } from './infos.js';
import { zeitraumWahl, zeitraumParams, aktiveMonate, periodeKurz,
         nutzerPeriodeAbgerechnet, periodeAbgerechnet, jahrWert }
  from './matrix.js';
import { periodeMonate, periodeSumme, vorschauEntprellt } from './blatt.js';
import { ladungenZeigen } from './zuordnen.js';

/* N165/2 — der Autoversand-Schalter. Standardmaessig aus; eingeschaltet geht
   die Abrechnung einen Tag nach Quartalsende automatisch an jeden Nutzer mit
   Adresse, Ladung und Satz — als Mail mit PDF. Ein ruhiger Schalter, kein
   Warnton: es ist eine Erleichterung. */
export function abrechnungKopf() {
  // N193 — eine Kopfzeile statt Titel + separatem Schalter: „E-Tankstelle
  // Abrechnung" mit EINEM Info-i (die zwei früheren Erklärtexte zusammengeführt),
  // rechts der kompakte Automatik-Schalter. Das i steht neben dem <h3>, nicht im
  // <label> — sonst schaltete ein Klick darauf die Checkbox mit.
  const info = infoKnopfText('E-Tankstelle Abrechnung',
    INFOS.abrechnung.text + '\n\n' + INFOS.autoversand.text);
  return `<div class="abkopf">
    <span class="abkopf-t"><h3>E-Tankstelle Abrechnung</h3>${info}</span>
    <label class="switch">
      <span class="sw-label">Automatische Abrechnung</span>
      <input type="checkbox" data-autoversand ${S.einst.autoversand ? 'checked' : ''}>
      <span class="sw-track" aria-hidden="true"></span>
    </label>
  </div>`;
}

export async function einstellungenLaden() {
  try {
    const d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/einstellungen`);
    S.einst = { autoversand: !!d.autoversand, regeln: d.regeln || [],
                ausschluss: d.ausschluss || [] };
  } catch { S.einst = { autoversand: false, regeln: [], ausschluss: [] }; }
}

/* N182 — die abgerechnet-Marker des gewählten Jahres holen. Wird zu Beginn von
   `abrechnungZeigen` gerufen, damit Chips und Versand-Knöpfe zum Jahr passen. */
export async function abgerechnetLaden() {
  // N187 — ALLE Jahre holen (ohne `?jahr`), damit auch ein nicht gewähltes Jahr
  // seinen ✓ tragen kann. Ein Marker kann quartals- (monat==null) oder
  // monatsgenau (monat gesetzt) sein.
  try {
    const d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/abgerechnet`);
    S.abgerechnet = d.abgerechnet || [];
  } catch { S.abgerechnet = []; }
}

/* N182 — die gewählte Periode von Hand als abgerechnet setzen oder die Markierung
   entfernen (für den Initialstand der alten 4-Monats-Abrechnungen und für
   Korrekturen). Gilt für alle gelisteten Nutzer. */
export async function abgerechnetUmschalten() {
  if (!S.nutzerListe.length) {
    melde('Erst einen Nutzer anlegen', 'neg');
    return;
  }
  const monate = aktiveMonate();
  if (!monate.length) { melde('Kein Monat gewählt', 'neg'); return; }
  const setzen = !periodeAbgerechnet();
  try {
    // N193 — GENAU die wirksamen Monate markieren (nicht ganze Quartale): so
    // bleibt Nicht-Angewähltes unberührt. Das Backend setzt bei nicht-leerem
    // `monate` monatsgenaue Marker; `quartale` ist nur der Fallback (altes Backend).
    await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/abgerechnet`, {
      method: 'PUT',
      body: { jahr: jahrWert(), quartale: S.quartaleGewaehlt, monate,
              nutzer_id: 0, abgerechnet: setzen } });
    melde(setzen ? `${monate.length} Monat${monate.length === 1 ? '' : 'e'} als `
            + 'abgerechnet markiert' : 'Markierung entfernt', 'pos');
    await abrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function autoversandUmschalten(aktiv) {
  try {
    await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/autoversand`,
              { method: 'PUT', body: { aktiv } });
    S.einst.autoversand = aktiv;
    melde(aktiv ? 'Automatischer Versand eingeschaltet'
                : 'Automatischer Versand ausgeschaltet', 'pos');
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    await abrechnungZeigen();               // Schalter zuruecksetzen
  }
}

/* Der Kern des Fehlers „ich druecke und nichts passiert": abgerechnet wird
   nur, was einer Person zugeordnet ist. Die Wallbox weiss, WIE VIEL geladen
   wurde, aber nicht von WEM. Ohne eine einzige Zuordnung zeigt jedes Quartal
   dieselben 0,00 € — und bisher stand nirgends, warum. Also: die Luecke
   zwischen geladen und zugeordnet benennen, statt sie stumm zu rendern. */
function offeneNotiz(d) {
  if (!(d.offen_kwh > 0.05)) return '';
  const nichts = !(d.kwh_gesamt > 0);
  return `<div class="notiz"><span class="wi">◔</span><span>Im Zeitraum
    ${esc(d.label)} wurden ${zahl(d.geladen_kwh)} kWh geladen, davon
    ${nichts ? 'keine einzige' : `nur ${zahl(d.kwh_gesamt)} kWh`} einer Person
    zugeordnet. Abgerechnet wird nur, was zugeordnet ist — die Wallbox weiß
    nicht, wer geladen hat. Das geht unten unter „Ladungen zuordnen“.</span></div>`;
}

/* N165 — ist nur eine Person angelegt, gehoeren ihr automatisch alle Ladungen
   des Zeitraums. Das ist eine Erleichterung, keine Stoerung: ein ruhiger
   Hinweis, kein Warnbalken — und die Zeile traegt zusaetzlich den Chip
   „automatisch", damit die Zuordnung nicht wie eine Handeingabe aussieht. */
function autoNotiz() {
  return `<div class="notiz auto"><span class="wi">⤳</span><span>Automatisch
    zugeordnet — nur eine Person angelegt, alle Ladungen gehen auf sie.</span></div>`;
}

/* Der Satz je kWh wird abgeleitet, nicht eingegeben (N148). An der Stelle, an
   der frueher ein Eingabefeld stand, steht jetzt die Zahl mit ihrer Herkunft:
   welcher Betrag, welche Menge, aus welcher Position welchen Zeitraums.
   Steht kein Satz fest, gibt es keine 0,00 € — sondern die Aussage, wodurch
   er entsteht. */
export function satzBlock(d) {
  // N187 — der Zeitraum, für den der Durchschnittssatz gilt, steht jetzt AM
  // Satz statt in einer eigenen Zeile darüber („dieser Ø-Wert gilt für …").
  const zr = `gilt für ${esc(d.label)} · ${datum(d.von)} – ${datum(d.bis)}`;
  if (d.satz == null) {
    return `<div class="notiz"><span class="wi">◔</span><span>${esc(
      d.satz_grund || 'Der Satz je kWh lässt sich noch nicht ermitteln.')}
      </span></div>
      <span class="satz-zr solo">${zr}</span>`;
  }
  // Jede Ergaenzung einzeln geprueft: fehlt eine, bleibt sie weg. Ein „NaN %"
  // oder ein „undefined" waere schlimmer als eine Zeile weniger.
  const rabatt = d.satz_rabatt == null ? ''
    : ` (${Math.round(d.satz_rabatt * 100)} % darunter)`;
  const hatTeile = d.satz_netz != null && d.satz_eigen != null;
  // N195 — statt nur der zwei Sätze zeigen die Karten die MENGEN und BETRÄGE des
  // gewählten Zeitraums: Netz-kWh × Netzsatz = Netz-€, Eigen-kWh × Eigensatz =
  // Eigen-€. So füllt der linke Block sinnvoll und die Herkunft des Mischsatzes
  // ist ablesbar. Fehlt die Aufteilung (unbekannt), bleibt die Menge „—".
  const s = periodeSumme(periodeMonate(d));
  const teil = (klasse, label, menge, satzc) => {
    const betrag = (menge != null && satzc != null) ? menge * satzc : null;
    return `<div class="satz-teil ${klasse}"><i></i>
      <div class="st-kopf"><span class="st-l">${label}</span>
        <span class="st-s">${satzText(satzc)}</span></div>
      <div class="st-rechnung"><span class="st-m">${menge == null ? '—' : kwh(menge)}</span>
        <span class="st-eq">→</span>
        <span class="st-v">${betrag == null ? '—' : eur(betrag)}</span></div></div>`;
  };
  const teile = !hatTeile ? '' : `<div class="satz-teile">
      ${teil('netz', 'Netz', s.extern_kwh, d.satz_netz)}
      ${teil('eigen', 'Eigen' + (rabatt ? ' · −10 %' : ''), s.eigen_kwh, d.satz_eigen)}
    </div>`;
  // Mischregel und Herkunft wandern ins i neben die Hero-Zahl (N186) — beide
  // bestehende Texte, nur an einem Ort statt als graue Textwand.
  const regel = !hatTeile ? ''
    : `Netz ${satzText(d.satz_netz)} · eigener Strom ${satzText(d.satz_eigen)}`
      + `${rabatt}. Der Satz einer Ladung mischt beide nach den Mengen des Zeitraums.`;
  const infoText = [regel, d.satz_herkunft || ''].filter(Boolean).join('\n\n');
  return `<div class="satz">
    <div class="satz-hero"><span class="sw">${satzText(d.satz)}</span>
      ${infoKnopfText('Satz je kWh', infoText)}</div>
    ${teile}
    <span class="satz-zr">${zr}</span></div>`;
}

export async function abrechnungZeigen() {
  const ziel = document.getElementById('abrechnung');
  if (!ziel) return;
  const vorher = S.offeneVorschau;         // eine offene Vorschau ueberlebt das Neuzeichnen
  let d;
  try {
    d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/abrechnung`
                  + `?${zeitraumParams()}`);
  } catch (fehler) {
    zeigeFehler(ziel, 'Abrechnung nicht verfügbar', fehler);
    return;
  }
  S.letzteAbrechnung = d;                  // die HTML-Vorschau liest daraus (N179)
  await abgerechnetLaden();                // N182 — Marker fürs gewählte Jahr

  const zeilen = (d.nutzer || []).map(n => `
    <div class="az" data-nutzer="${n.nutzer_id || 0}">
      <div class="ak">
        <span class="an">${esc(n.name)}${n.automatisch
          ? '<span class="chip teal" style="margin-left:8px">automatisch</span>' : ''}${
          n.angelegt ? ''
          : '<span class="chip amber" style="margin-left:8px">nicht angelegt</span>'}${
          nutzerPeriodeAbgerechnet(n.nutzer_id)
          ? '<span class="chip teal" style="margin-left:8px">✓ abgerechnet</span>' : ''}</span>
        <span class="ab">${n.betrag == null ? '—' : eur(n.betrag)}</span>
      </div>
      <span class="ad">${kwh(n.kwh)} · ${n.satz == null
          ? 'Satz steht noch nicht fest' : satzText(n.satz)}
        ${n.anzahl ? ` · ${n.anzahl} ${n.anzahl === 1 ? 'Ladung' : 'Ladungen'}` : ''}
        ${n.email ? ` · ${esc(n.email)}` : ''}</span>
      ${n.km != null ? `<div class="eco"><span class="ecar">🚗</span>
        <span class="ecochip"><span class="ev">${zahl(n.km, 0)}</span>
          <span class="eu">km</span></span>${
        n.preis_100km != null ? `<span class="ecochip">
          <span class="ev">${eur(n.preis_100km)}</span>
          <span class="eu">/ 100 km</span></span>` : ''}${
        n.liter_100km != null ? `<span class="ecochip">
            <span class="ev">≈ ${zahl(n.liter_100km, 1)} l</span>
            <span class="eu">/ 100 km</span></span>`
          + infoKnopfText('Benzin-Vergleich',
              `Annahme ${zahl(d.benzin_kwh_pro_liter, 1)} kWh je Liter · `
              + `reiner Energievergleich, kein Kostenvergleich`) : ''}</div>` : ''}
      ${n.email ? '' : `<div class="notiz fehlt"><span class="wi">✉</span>
        <span>Ohne E-Mail-Adresse lässt sich nichts verschicken.</span></div>`}
      ${n.kwh > 0 && n.nutzer_id ? `<div class="aw">
        <button class="btn leise" data-vorschau="${n.nutzer_id}">Vorschau</button>
        ${n.email && n.betrag != null
          ? (nutzerPeriodeAbgerechnet(n.nutzer_id)
            ? `<button class="btn gesperrt" disabled aria-disabled="true"
                 title="Diese Periode ist bereits abgerechnet">
                 <span class="bs-t">${periodeKurz()} · bereits abgerechnet</span>
                 <span class="bs-e">${eur(n.betrag)}</span></button>`
            : `<button class="btn btn-send" data-senden="${n.nutzer_id}">
                 <span class="bs-t">${periodeKurz()} · per Mail senden</span>
                 <span class="bs-e">${eur(n.betrag)}</span></button>`)
          : ''}
      </div>` : ''}
      <div data-mail="${n.nutzer_id || 0}"></div>
    </div>`).join('');

  ziel.innerHTML = `${abrechnungKopf()}
    <div class="absel">${zeitraumWahl()}${satzBlock(d)}</div>
    ${d.automatisch ? '' : offeneNotiz(d)}
    ${zeilen || `<div class="leer"><b>Noch nichts abzurechnen</b>
        Für ${esc(d.label)} gibt es weder Nutzer noch Ladungen.</div>`}
    ${d.automatisch && d.nutzer?.length ? autoNotiz() : ''}
    ${(d.nutzer?.length > 1 || d.offen_kwh > 0.05) ? `<div class="kpi" style="margin-top:14px">
      <div class="k"><span class="kl">${esc(d.label)}</span>
        <span class="kv">${kwh(d.kwh_gesamt)}</span></div>
      <div class="k"><span class="kl">Summe</span>
        <span class="kv teal">${d.betrag_gesamt == null ? '—'
          : eur(d.betrag_gesamt)}</span></div>
    </div>` : ''}`;
  // War eine Vorschau offen und gibt es den Nutzer noch, wird sie mit dem
  // neuen Ausschnitt neu geladen — entprellt, damit rasche Klicks (Monat an/aus)
  // nicht bei jedem Schritt ein PDF nachladen.
  S.offeneVorschau = 0;
  if (vorher && document.querySelector(`[data-mail="${vorher}"]`)) {
    S.offeneVorschau = vorher;
    vorschauEntprellt(vorher);
  }
  await ladungenZeigen();
}
