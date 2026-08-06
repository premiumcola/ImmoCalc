/* blatt.js — die Vorschau der Abrechnung als vollstaendiges HTML-Blatt (N179/
   N184): dieselben Bloecke und Zahlen wie das PDF, in derselben Reihenfolge,
   nur responsiv. Kopf, Empfaenger (mit Anschrift, N184b), Diagramm je Monat mit
   Legende, Monatstabelle mit Kosten oder E-Auto, Benzin-Kostenvergleich (N184b,
   gruen hervorgehobene Ersparnis), Satz mit Herkunft, Fakten-Bubbles (N194) und
   der Rechnungsbetrag samt Objekt-Bankverbindung (N184b).

   Warum ein HTML-Nachbau statt eines eingebetteten PDFs? Das native
   iframe-PDF skalierte auf iOS/Safari nicht auf die Rahmenbreite — es blieb
   waagerecht scrollbar und rechts abgeschnitten. Der HTML-Nachbau nimmt
   dieselben Daten (aus der geholten Abrechnung `S.letzteAbrechnung` und dem
   bereits geladenen Verlauf `S.verlaufMonate`), passt sich jeder Breite an und
   scrollt nie seitwaerts. Das vollstaendige PDF bleibt fuer Download und
   Versand. */
import { S, NETZ, PV, AKKU, EIGEN, kwh, zahl, satzText, datum } from './state.js';
import { api, esc, eur, melde } from '../immo.js';
import { legende } from '../charts.js';
import { grafik } from './verlauf.js';
import { zeitraumParams } from './matrix.js';

/* Die Vorschau: das Abrechnungs-PDF, wie es als Anhang ausssaehe — eingebettet
   auf der Seite (N169), nicht in einem neuen Tab. Sie aktualisiert sich, sobald
   sich die Auswahl aendert (Jahr, Quartale, Monate): `abrechnungZeigen` merkt
   sich die offene Vorschau und laedt sie mit dem neuen Ausschnitt entprellt neu.
   Verschickt wird dabei nichts. */
export async function vorschauZeigen(nid) {
  nid = Number(nid);
  const feld = document.querySelector(`[data-mail="${nid}"]`);
  if (!feld) return;
  if (S.offeneVorschau === nid) {              // zweiter Klick schliesst wieder
    feld.innerHTML = '';
    S.offeneVorschau = 0;
    clearTimeout(S.vorschauTimer);
    return;
  }
  document.querySelectorAll('[data-mail]').forEach(f => { f.innerHTML = ''; });
  S.offeneVorschau = nid;
  await vorschauRendern(nid);
}

export function vorschauEntprellt(nid) {
  clearTimeout(S.vorschauTimer);
  S.vorschauTimer = setTimeout(() => vorschauRendern(nid), 350);
}

export async function vorschauRendern(nid) {
  const feld = document.querySelector(`[data-mail="${nid}"]`);
  if (!feld || S.offeneVorschau !== Number(nid)) return;
  const slug = encodeURIComponent(S.objektSlug);
  let v;
  try {
    v = await api(`/tankstelle/${slug}/vorschau?${zeitraumParams()}&nutzer_id=${nid}`);
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); return; }
  // Der Kopf traegt An/Betreff und ein klares × (N178): die Vorschau bleibt
  // inline, der Schliessen-Weg sitzt direkt am Blatt. Das × ist derselbe
  // Vorschau-Umschalter — bei offener Vorschau schliesst ein Klick sie wieder.
  const kopf = `<div class="vorschau-kopf">
      <span class="mailkopf">An ${esc(v.an || '— keine Adresse —')}
        · ${esc(v.betreff)}</span>
      <button class="vorschau-x" data-vorschau="${nid}"
              aria-label="Vorschau schließen" title="Vorschau schließen">×</button>
    </div>`;
  // N179/N184 — statt des eingebetteten A4-PDFs ein responsiver HTML-Nachbau
  // der VOLLSTÄNDIGEN Abrechnung. Ohne Betrag bleibt es beim Mailtext. Die
  // Blattbreite wird an die Grafik gereicht (abzüglich der Innenabstände von
  // Vorschau- und Blattrahmen).
  const breite = Math.max(240, (feld.clientWidth || 300) - 56);
  const koerper = v.betrag == null
    ? `<pre class="mailtext">${esc(v.text)}</pre>`
    : abrechnungBlatt(nid, v.text, breite);
  feld.innerHTML = `<div class="vorschau">${kopf}${koerper}</div>`;
}

/* N184 — die Monate des Abrechnungszeitraums, aus dem bereits geholten Verlauf
   (`S.verlaufMonate`) gefiltert auf Jahr und die aktiven Monate der Abrechnung.
   `/abrechnung` liefert die Monatsaufteilung nicht selbst mit; sie steht aber
   identisch im Verlauf, der beim Seitenaufbau schon geladen wurde — dieselben
   Zahlen, keine erfundenen. Ein Monat ohne Ladung bleibt als leere Stelle
   stehen (Diagramm) bzw. mit Strich (Tabelle). */
export function periodeMonate(d) {
  const aktiv = new Set(d.monate_aktiv || []);
  return (S.verlaufMonate || []).filter(
    m => m.jahr === d.jahr && aktiv.has(m.monat));
}

/* Die Summenzeile des Zeitraums — dieselben Regeln wie im Backend
   (`verlauf_summe`): unbekannte Aufteilung bleibt ``null`` statt einer 0, und
   die Prozentwerte kommen aus den summierten Mengen. */
export function periodeSumme(monate) {
  const r2 = n => Math.round(n * 100) / 100;
  const summe = k => r2(monate.reduce((s, m) => s + (m[k] || 0), 0));
  const kwhSum = summe('kwh');
  const voll = monate.length > 0 && monate.every(m => m.aufteilung);
  const drei = monate.length > 0 && monate.every(m => m.dreiteilig);
  const wert = (k, unbekannt) => unbekannt ? null : summe(k);
  const s = { kwh: kwhSum, aufteilung: voll, dreiteilig: drei,
    extern_kwh: wert('extern_kwh', !voll), eigen_kwh: wert('eigen_kwh', !voll),
    pv_kwh: wert('pv_kwh', !drei), speicher_kwh: wert('speicher_kwh', !drei) };
  for (const feld of ['extern', 'eigen', 'pv', 'speicher']) {
    const v = s[feld + '_kwh'];
    s[feld + '_prozent'] = (v == null || !(kwhSum > 0)) ? null
      : Math.round(v / kwhSum * 1000) / 10;
  }
  return s;
}

/* N194 — der Ø-Verbrauch je Monat im Vergleich zur Vorperiode: die gleich lange
   Spanne unmittelbar VOR dem gewählten Zeitraum (aus dem Gesamtverlauf). So sieht
   man, ob im Schnitt mehr oder weniger geladen wurde. Ohne Vorperiode → null. */
export function verbrauchsTrend(periodMonate) {
  if (!periodMonate.length || !(S.verlaufMonate || []).length) return null;
  const key = m => m.jahr * 12 + m.monat;
  const chrono = [...S.verlaufMonate].sort((a, b) => key(a) - key(b));
  const ersterKey = Math.min(...periodMonate.map(key));
  const startIdx = chrono.findIndex(m => key(m) === ersterKey);
  if (startIdx <= 0) return null;                        // keine Vorperiode
  const vorher = chrono.slice(Math.max(0, startIdx - periodMonate.length), startIdx);
  if (!vorher.length) return null;
  const schnitt = arr => arr.reduce((sum, m) => sum + (m.kwh || 0), 0) / arr.length;
  const jetzt = schnitt(periodMonate), vor = schnitt(vorher);
  if (!(vor > 0)) return null;
  return { jetzt, vor, delta: (jetzt - vor) / vor };
}

/* Die Monatstabelle mit E-Auto (Monat · Geladen · km · Kosten) — wie im PDF,
   wenn ein Verbrauch hinterlegt ist. km = kWh ÷ Verbrauch × 100, Kosten =
   kWh × Satz. Die frühere Spalte „Preis/100 km" ist raus (N194): sie war über
   die Periode konstant (Ø-Satz × Verbrauch) und monatlich ohne Aussage. */
export function blattTabelleEauto(monate, summe, verbrauch, satz) {
  const km = k => (k > 0 && verbrauch > 0) ? k / verbrauch * 100 : null;
  const kosten = k => satz == null ? null : k * satz;
  const zeile = (label, k) => {
    const kmv = km(k), ko = kosten(k);
    return `<tr>
      <td>${esc(label)}</td>
      <td class="${k ? '' : 'leise'}">${zahl(k)}</td>
      <td class="${kmv == null ? 'leise' : ''}">${kmv == null ? '—' : zahl(kmv, 0)}</td>
      <td class="${ko == null ? 'leise' : ''}">${ko == null ? '—' : eur(ko)}</td></tr>`;
  };
  return `<div class="tabrahmen"><table class="mt bl-mt">
    <thead><tr><th>Monat</th><th>Geladen</th><th>km</th><th>Kosten</th></tr></thead>
    <tbody>${monate.map(m => zeile(m.label, m.kwh || 0)).join('')}</tbody>
    <tfoot>${zeile('Summe', summe.kwh || 0)}</tfoot>
  </table></div>`;
}

/* Die Monatstabelle ohne E-Auto: Monat · Geladen · Netz · (PV · Akku | Eigen) —
   wie der Verlauf, nur für den Zeitraum und ohne Pager. */
export function blattTabelleStrom(monate, summe) {
  const drei = summe.dreiteilig;
  const zelle = v => v == null ? '<td class="leise">—</td>' : `<td>${zahl(v)}</td>`;
  const zeile = (label, m) => `<tr>
    <td>${esc(label)}</td>
    <td class="${m.kwh ? '' : 'leise'}">${zahl(m.kwh)}</td>
    ${zelle(m.extern_kwh)}
    ${drei ? zelle(m.pv_kwh) + zelle(m.speicher_kwh) : zelle(m.eigen_kwh)}</tr>`;
  return `<div class="tabrahmen"><table class="mt bl-mt">
    <thead><tr><th>Monat</th><th>Geladen</th><th>Netz</th>
      ${drei ? '<th>PV</th><th>Akku</th>' : '<th>Eigen</th>'}</tr></thead>
    <tbody>${monate.map(m => zeile(m.label, m)).join('')}</tbody>
    <tfoot>${zeile('Summe', summe)}</tfoot>
  </table></div>`;
}

/* N179/N184 — die Abrechnung als vollständiges HTML-Blatt: dieselben Blöcke und
   Zahlen wie das PDF, in derselben Reihenfolge, nur responsiv. Kopf, Empfänger,
   Diagramm je Monat mit Legende, Monatstabelle mit Kosten, E-Auto, Satz mit
   Herkunft und der Rechnungsbetrag. Grundlage ist die zuletzt geholte Abrechnung
   (`S.letzteAbrechnung`) und die Nutzerzeile daraus, ergänzt um die Monate aus
   dem Verlauf. Fehlt die Zeile wider Erwarten, fällt es auf den Mailtext zurück.

   N184b — die Vorschau spiegelt das PDF jetzt vollständig: Empfänger-Anschrift
   unter dem Namen, der Benzin-Kostenvergleich (mit grün hervorgehobener
   Ersparnis) nach dem E-Auto-Block und die Objekt-Bankverbindung unter dem
   Rechnungsbetrag. Fehlt ein Datum (kein KI-Benzinwert, kein Konto, keine
   Anschrift), entfällt der jeweilige Block ersatzlos — wie im PDF, nie ein
   Platzhalter, nie eine erfundene Zahl. */
export function abrechnungBlatt(nid, fallbackText, breite) {
  const d = S.letzteAbrechnung;
  const row = d && (d.nutzer || []).find(n => Number(n.nutzer_id) === Number(nid));
  if (!d || !row) return `<pre class="mailtext">${esc(fallbackText || '')}</pre>`;

  // Diagramm + Legende + Monatstabelle aus den Monaten des Zeitraums.
  const monate = periodeMonate(d);
  const summe = periodeSumme(monate);
  const verbrauch = row.verbrauch_kwh_100km || 0;
  let verlaufBlock = '';
  if (monate.length) {
    const drei = summe.dreiteilig;
    const leg = legende(drei
      ? [{ name: 'Netz', farbe: NETZ }, { name: 'PV direkt', farbe: PV },
         { name: 'Akku', farbe: AKKU }]
      : [{ name: 'Netz', farbe: NETZ },
         { name: 'Eigener Strom (PV + Akku)', farbe: EIGEN }]);
    const tabelle = verbrauch > 0
      ? blattTabelleEauto(monate, summe, verbrauch, d.satz)
      : blattTabelleStrom(monate, summe);
    verlaufBlock = `<div class="bl-block">
      <span class="bl-abschnitt">Geladene Energie je Monat</span>
      ${grafik(monate, breite)}${leg}${tabelle}</div>`;
  }

  // E-Auto: Modell, Verbrauch, energetisches Benzin-Äquivalent (kein Kosten-
  // vergleich — der bräuchte den Vergleichsbenziner, den `/abrechnung` nicht
  // liefert).
  let eautoBlock = '';
  if (verbrauch > 0) {
    const liter = d.benzin_kwh_pro_liter ? verbrauch / d.benzin_kwh_pro_liter : null;
    eautoBlock = `<div class="bl-block">
      <span class="bl-abschnitt">E-Auto${row.e_auto_modell
        ? ' · ' + esc(row.e_auto_modell) : ''}</span>
      <span class="bl-sd">Verbrauch ${zahl(verbrauch, 1)} kWh/100 km. Defensive
        Fahrweise, Ladeverluste eingerechnet.</span>
      ${liter != null ? `<span class="bl-sq">Energie-Äquivalent:
        ${zahl(verbrauch, 1)} kWh entsprechen rund ${zahl(liter, 1)} l Benzin
        (Annahme ${zahl(d.benzin_kwh_pro_liter, 1)} kWh je Liter).</span>` : ''}</div>`;
  }

  // N184b — der Kosten-Benzinvergleich mit der grün hervorgehobenen Ersparnis,
  // wie im PDF. `row.benzin` kommt aus `eauto.benzin_vergleich`; fehlt der
  // Vergleich (kein KI-Benzinwert), ist es null und der Block entfällt.
  let benzinBlock = '';
  const bz = row.benzin;
  if (bz) {
    const spar = bz.ersparnis_100km == null ? '' : `<span class="bl-spar">
      Ersparnis Elektro: ${eur(bz.ersparnis_100km)} je 100 km${
        bz.ersparnis_gesamt != null && bz.km != null
          ? ` — für rund ${zahl(bz.km, 0)} km im Quartal rund ${eur(bz.ersparnis_gesamt)}`
          : ''}</span>`;
    benzinBlock = `<div class="bl-block">
      <span class="bl-abschnitt">Kostenvergleich mit Benzin</span>
      <span class="bl-sd">Ein vergleichbarer Benziner braucht rund
        ${zahl(bz.verbrauch_l, 1)} l/100 km (Annahme ${eur(bz.preis_liter)} je
        Liter). Benzin ${eur(bz.benzin_100km)} je 100 km · Ihr E-Auto
        ${eur(bz.e_100km)} je 100 km.</span>
      ${spar}</div>`;
  }

  // N184b — die Objekt-Bankverbindung (der Betreiber, an den überwiesen wird).
  // `d.konto` ist null, solange keine der drei Angaben gepflegt ist — dann
  // entfällt der Block ersatzlos, kein leerer Platzhalter.
  let kontoBlock = '';
  if (d.konto) {
    const teile = [];
    if ((d.konto.kontoinhaber || '').trim()) teile.push(esc(d.konto.kontoinhaber));
    if ((d.konto.iban || '').trim()) teile.push('IBAN ' + esc(d.konto.iban));
    if ((d.konto.bank || '').trim()) teile.push(esc(d.konto.bank));
    if (teile.length) kontoBlock = `<div class="bl-block bl-konto">
      <span class="bl-abschnitt">Bitte überweisen Sie den Betrag auf:</span>
      <span class="bl-sd">${teile.join(' · ')}</span></div>`;
  }

  // N184b — die Empfänger-Anschrift unter dem Namen (Straße, dann PLZ + Ort).
  // Fehlt sie (noch nicht angelegte Person), bleibt es beim Namen.
  const anschrift = [row.strasse,
    [row.plz, row.ort].filter(s => (s || '').trim()).join(' ')]
    .filter(s => (s || '').trim())
    .map(s => `<span class="bl-adr">${esc(s)}</span>`).join('');

  // Satz je kWh mit Herkunft (der lange „Rechnung … ÷ … Netzbezug"-Satz ist
  // raus, N194 — er wiederholte die Herleitung; die Aufteilung steht in den
  // Fakten unten).
  const rabatt = d.satz_rabatt == null ? ''
    : ` (${Math.round(d.satz_rabatt * 100)} % darunter)`;
  const regel = d.satz_netz == null || d.satz_eigen == null ? ''
    : `<span class="bl-sd">Netz ${satzText(d.satz_netz)} · eigener Strom
        ${satzText(d.satz_eigen)}${rabatt}. Der Satz einer Ladung mischt beide
        nach den Mengen des Zeitraums.</span>`;

  // N194 — die Fakten des Zeitraums als Bubbles: Menge Netz/Eigen, die Ersparnis
  // gegenüber Benzin und der Ø-Verbrauch je Monat mit dem Trend zur Vorperiode.
  const oMonat = monate.length ? summe.kwh / monate.length : null;
  const tr = verbrauchsTrend(monate);
  const trChip = !tr ? '' : `<span class="bl-trend ${
      tr.delta < -0.005 ? 'pos' : (tr.delta > 0.005 ? 'neg' : '')}">${
      tr.delta < -0.005 ? '↓' : (tr.delta > 0.005 ? '↑' : '±')} ${
      Math.abs(Math.round(tr.delta * 100))} % ggü. Vorperiode</span>`;
  const bubble = (label, wert, extra = '') => `<div class="bl-fakt">
      <span class="bl-fl">${label}</span>
      <span class="bl-fv">${wert}</span>${extra}</div>`;
  const fakten = [];
  if (summe.extern_kwh != null) fakten.push(bubble('Netz', kwh(summe.extern_kwh)));
  if (summe.eigen_kwh != null) fakten.push(bubble('Eigen', kwh(summe.eigen_kwh)));
  if (row.benzin && row.benzin.ersparnis_gesamt != null) {
    fakten.push(bubble('Ersparnis ggü. Benzin', eur(row.benzin.ersparnis_gesamt)));
  }
  if (oMonat != null) fakten.push(bubble('Ø / Monat', kwh(oMonat), trChip));
  const faktenBlock = fakten.length
    ? `<div class="bl-block"><div class="bl-fakten">${fakten.join('')}</div></div>` : '';

  return `<div class="blatt">
    <div class="bl-kopf">
      <span class="bl-titel">Abrechnung E-Tankstelle</span>
      <span class="bl-meta">${esc(d.objekt)} · ${esc(d.label)}</span>
      <span class="bl-meta">Ladezeitraum ${datum(d.von)} – ${datum(d.bis)}</span>
    </div>
    <div class="bl-empf"><span class="bl-name">${esc(row.name)}</span>
      ${anschrift}
      ${row.email ? `<span class="bl-mail">${esc(row.email)}</span>` : ''}</div>
    ${verlaufBlock}
    ${eautoBlock}
    ${benzinBlock}
    <div class="bl-block">
      <span class="bl-abschnitt">Satz je kWh</span>
      <div class="bl-satz"><span class="bl-sw">${satzText(row.satz)}</span>
        ${regel}</div>
    </div>
    ${faktenBlock}
    <div class="bl-betrag">
      <span class="bl-bl"><span class="bl-bk">Rechnungsbetrag</span>
        <span class="bl-bkwh">${kwh(row.kwh)} geladen</span></span>
      <span class="bl-bb">${row.betrag == null ? '—' : eur(row.betrag)}</span></div>
    ${kontoBlock}
  </div>`;
}
