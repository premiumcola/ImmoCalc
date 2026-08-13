/* zeitraum/checkliste.js — Haupt-Rendering des Zeitraum-Bildschirms.

   Hier laufen die drei zentralen Kettengriffe zusammen:
   - `laden()`  holt Zeitraum + Beiwerk (Schlüssel, Ablesungen, Öl, HKV,
                Stromkette, Deckung, E-Auto) und ruft danach `zeichnen()`.
   - `zeichnen()` baut das ganze HTML: Fortschritt, Tabs, Sortierleiste,
                Bereiche (Wasser/Heizung/Strom/Reinigung/…), Ergebnis,
                Belege — sowie die inline geladenen Detailblöcke (Wasser,
                Öl, Stromkette).
   - `initHandlers()` hängt die zentrale Click-/Change-/Input-Delegation
                sowie das drag&drop und den Scan-Feld-Handler an. Wird
                einmal beim App-Start aus dem HTML-Rumpf gerufen.

   Zeilen-HTML (`zeileHtml` / `zeileInner`) baut jede Kostenzeile —
   aufgeklappte Karte enthält je Modus (Wasser/Öl/Warmwasser/Wärme/Strom/
   Standard) den passenden Detailblock. */

import { api, eur, eurKurz, esc, melde, frage, belegAnsehen, baueDialog,
         installNav, leerHtml } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { sankey } from '../charts.js';
import { kostenIcon } from '../kostenicons.js';
import { lesbareGroesse } from '../scan.js';
import { belegVorbereiten } from '../belegscan.js';

import * as state from './state.js';
import { neuerLauf, einmal } from './holen.js';
import {
  BEREICHE, BEREICH_IKON, SORTIERUNG, HAKEN, ABGELEITET,
  NUR_EINHEIT_WAHL, WEG_ART,
} from './state.js';
import { ANH_ICON, FOTO_ICON, UPLOAD_ICON, WOLKE_ICON } from './icons.js';
import {
  normUml, bereichIndex, kostenartAnzeige,
  istImDetailPopup, istHeizoelSammel, istWarmwasserPos, istHeizwaermePos,
  istWasserSammel, istStromPos, istStromKettePos,
  wasserArt,
} from './modell.js';
import {
  zahl, chipHtml, vkeyChip, schluesselWort, schluesselMeta,
  prozentText, monatText, m3, kurzBeleg, belegDatumText,
  belegLinks, belegeZu, belegGeschwister, zusammensetzungHtml,
  feldZahl,
  sonderEinheiten, alleEinheiten, artOptionen,
  wasserGesamtBetrag, wasserHatRechnung,
  positionsBetrag, effektivErledigt, fortschrittRechnen,
  stromKetteVerteilt, heizwaermeVerteilt,
  stromMengen, stromAufteilung, stromChipsHtml, stromKopfHtml,
  stromPosFeldHtml, stromKetteHtml,
  vorabAktiv, vorabBrutto, bruttoAnzeige,
  baueChipMap, generischeLabels, zaehlerBloecke,
  fristChipSetzen, rolleUnterDieKopfzeile,
} from './helpers.js';
import {
  zaehlerPanelHtml, endstandSpeichern, anfangstandSpeichern,
  datumGeaendert, datumUebernehmen, einheitToggle, zaehlerUmbenennen,
} from './zaehler.js';
import {
  fuelleWasserInline, wasserBetragSpeichern, wasserRechnungsmengeSpeichern,
  wasserPositionLeeren,
} from './wasser.js';
import {
  fuelleHeizoelInline, heizoelHinzufuegen, heizoelEntfernen,
} from './heizoel.js';
import {
  stromMengeSpeichern, stromHerkunftSetzen, stromJahreswertSpeichern,
  stromZaehlerAnlegen, stromRolleSetzen, stromZaehlerEntfernen,
  gartenAnlegen,
} from './strom.js';
import {
  fuelleStromketteInline, stromAnteilSpeichern, stromBelegLoesen,
  geeichteMengeSpeichern,
} from './stromkette.js';
import {
  belegAblageHtml, belegLoesen, belegAbschluss,
  anhaengen, anhaengerEntfernen, initBelegDrop,
} from './belege.js';
import {
  wegLaden, wegSchalterHtml, wegAnsichtHtml, wegSchalten, wegAufnehmen,
  vorauszahlungNeu, vorauszahlungBearbeiten, vorauszahlungEntfernen,
} from './weg.js';
import {
  konfigModusUmschalten, konfigAnsichtHtml, konfSichtSetzen, konfOptSetzen,
  konfS35Setzen,
} from './konfigmodus.js';
// N349 — die Zähler-Konfiguration lebt jetzt auf der Immobilien-Seite
// (objekt.html, Knopf „Zähler" über den Abrechnungszeiträumen).

const { inhalt, zid, titel, sub, KEINE_KAMERA } = state;

/* ---------- Verteilung ------------------------------------------------- */

function doppelteEinheit(namen) {
  const einheit = new Map(
    (state.schluessel?.parteien || []).map(p => [p.partei, p.einheit]));
  const doppelt = namen.filter(n => state.leerstaende.has(n) && einheit.get(n)
    && namen.some(m => m !== n && einheit.get(m) === einheit.get(n)));
  if (!doppelt.length) return '';
  return `<div class="hinweis">${doppelt.map(esc).join(', ')}: vermietete Zeit
    und Leerstand getrennt.</div>`;
}

function einheitChips(pid, aktuell) {
  if (state.daten.status !== 'in Arbeit') return '';
  return sonderEinheiten().map(e => `
    <button type="button" class="ewahl${e.einheit === aktuell ? ' an' : ''}"
        data-einzel-pid="${pid}" data-einzel-einheit="${esc(e.einheit)}"
        aria-pressed="${e.einheit === aktuell}">
      <span class="ename">${esc(e.einheit)}</span>
      ${e.parteien.length
        ? `<span class="epartei">${esc(e.parteien.join(' · '))}</span>` : ''}
    </button>`).join('');
}

function vorabZeileHtml(k) {
  if (!vorabAktiv(k)) return '';
  return `<div class="rz vorab-zeile">
      <span>→ ${esc(k.vorab_einheit)}${k.vorab_s35
        ? '<span class="rzp"> · §35a</span>' : ''}</span>
      <span>− ${eur(k.vorab_betrag)}</span>
    </div>`;
}

function vorabHtml(k) {
  if (state.daten.status !== 'in Arbeit') return '';
  const offenJetzt = (k.vorab_betrag || 0) > 0 || (k.vorab_netto || 0) > 0
    || state.vorabOffen.has(k.position_id);
  if (!offenJetzt) {
    return `<button class="vorab-link" data-vorab-oeffnen="${k.position_id}"
      >＋ Teilbetrag direkt auf eine Einheit</button>`;
  }
  const chips = sonderEinheiten().map(e => `
    <button type="button" class="ewahl${e.einheit === k.vorab_einheit ? ' an' : ''}"
        data-vorab-einheit-pid="${k.position_id}" data-vorab-einheit="${esc(e.einheit)}"
        aria-pressed="${e.einheit === k.vorab_einheit}">
      <span class="ename">${esc(e.einheit)}</span>
      ${e.parteien.length
        ? `<span class="epartei">${esc(e.parteien.join(' · '))}</span>` : ''}
    </button>`).join('');
  const netto = k.vorab_netto || 0;
  const brutto = k.vorab_betrag || 0;
  const hat = netto > 0 || brutto > 0;
  return `<div class="vorab">
      <div class="vorab-kopf">
        <span class="vorab-t">Teilbetrag direkt auf eine Einheit</span>
        <button class="vorab-x" data-vorab-entfernen="${k.position_id}"
          data-hat="${hat ? '1' : ''}" aria-label="Teilbetrag entfernen">×</button>
      </div>
      <div class="vorab-betrag">
        <input type="number" step="0.01" min="0" inputmode="decimal"
               placeholder="Netto" value="${netto > 0 ? netto : ''}"
               data-vorab-netto="${k.position_id}"
               aria-label="Teilbetrag netto in Euro">
        <span class="vorab-eur">€ netto</span>
      </div>
      <div class="vorab-brutto" data-vorab-brutto="${k.position_id}"
        >${bruttoAnzeige(netto)}</div>
      <div class="einzel-wahl">${chips}</div>
      <label class="vorab-s35">
        <input type="checkbox" data-vorab-s35="${k.position_id}"
               ${k.vorab_s35 ? 'checked' : ''}>
        <span>§35a absetzbar</span>
      </label>
    </div>`;
}

/* Verteilung einer Position: Schlüssel + Aufteilung. */
function verteilungHtml(k) {
  if (!k.position_id) return '';
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const einzelOffen = k.nur_einheit || state.einzelWahl === k.position_id;
  const wahlWert = einzelOffen ? NUR_EINHEIT_WAHL : (k.schluessel || '');
  const wahl = bearbeitbar
    ? `<div class="wahl" data-schluesselwahl="${k.position_id}"
         data-wert="${esc(wahlWert)}"></div>` : '';

  if (einzelOffen) {
    const traeger = Object.keys(k.anteile || {});
    return `<div class="vt" data-pid="${k.position_id}">
        <div class="zk">Verteilen nach</div>
        ${wahl}
        <div class="einzel-wahl">${einheitChips(k.position_id, k.nur_einheit)}</div>
        ${k.nur_einheit ? `<div class="zsumme">Zu 100 % auf ${esc(k.nur_einheit)}${
          traeger.length ? ` · ${traeger.map(esc).join(' · ')}` : ''}</div>` : ''}
        ${k.nur_einheit && !traeger.length ? `<div class="warnung"><span>▲</span>
          <span><b>Keine Partei für ${esc(k.nur_einheit)}.</b></span></div>` : ''}
      </div>`;
  }

  const meta = schluesselMeta(k.schluessel);
  const eintraege = Object.entries(k.anteile || {});
  const summe = eintraege.reduce((s, [, w]) => s + Number(w || 0), 0);
  const einheit = k.anteile_einheit || meta?.einheit || '';
  const einheitTag = einheit ? `<span class="mini-einheit">${esc(einheit)}</span>` : '';
  const ganzzahl = k.schluessel === 'personen';
  const schritt = ganzzahl ? '1' : '0.0001';
  const imode = ganzzahl ? 'numeric' : 'decimal';
  const wZahl = w => ganzzahl ? Math.round(Number(w) || 0) : (Number(w) || 0);
  const abzuleiten = meta?.moeglich ? Object.entries(meta.gewichte) : [];
  const gleich = abzuleiten.length === eintraege.length &&
    abzuleiten.every(([p, w]) => Number(k.anteile?.[p] ?? NaN) === Number(w));
  const felder = eintraege.length || !bearbeitbar ? eintraege
    : (state.schluessel?.parteien || []).map(p => [p.partei, 0]);
  const rest = (k.betrag || 0) - (vorabAktiv(k) ? k.vorab_betrag : 0);

  const anteilSub = p => {
    const d = (k.anteil_details || []).find(x => x.partei === p);
    const teile = [];
    if (d) {
      if (d.leerstand) teile.push('Leerstand · Eigentümer');
      else if (d.einheit) teile.push(esc(d.einheit));
      if (d.zeitraum_monate && d.monate < d.zeitraum_monate - 0.05)
        teile.push(`${monatText(d.monate)} von ${monatText(d.zeitraum_monate)} Monaten`);
    } else if (state.leerstaende.has(p)) {
      teile.push('Leerstand · Eigentümer');
    }
    return teile.length ? `<span class="gsub">${teile.join(' · ')}</span>` : '';
  };

  const gwRows = felder.map(([p, w]) => `
    <div class="gw">
      <span class="gn">${esc(p)}${anteilSub(p)}</span>
      <span class="mini-wrap">${bearbeitbar
        ? `<input type="number" step="${schritt}" min="0" inputmode="${imode}"
                 value="${wZahl(w)}" data-gewicht="${esc(p)}"
                 aria-label="Gewicht ${esc(p)}${einheit ? ` in ${esc(einheit)}` : ''}">`
        : `<span class="gv">${wZahl(w).toLocaleString('de-DE')}</span>`}${einheitTag}</span>
      <span class="gp" data-anteil>${prozentText(w, summe)}</span>
    </div>`).join('');

  const ableiten = bearbeitbar && abzuleiten.length && !gleich
    ? `<button class="minilink" data-ableiten="${k.position_id}"
        data-fuer="${esc(k.schluessel || '')}">${eintraege.length
          ? 'Aus Stammdaten neu ableiten' : 'Aus Stammdaten ableiten'}</button>` : '';

  const abgeleitet = ABGELEITET.has(k.schluessel);
  let aufteilung;
  if (abgeleitet && eintraege.length) {
    const euroRows = felder.map(([p, w]) => {
      const euro = summe > 0 ? rest * (Number(w) || 0) / summe : 0;
      return `<div class="rz vt-abg"><span class="gn">${esc(p)}${anteilSub(p)}</span>
        <span class="vt-euro"><span class="euro-z" data-euro>${eur(euro)}</span>
          <span class="rzp" data-anteil>${prozentText(w, summe)}</span></span>
        ${bearbeitbar
          ? `<span class="mini-wrap"><input class="anteil-mini" type="number" step="${schritt}" min="0"
                    inputmode="${imode}" value="${wZahl(w)}" data-gewicht="${esc(p)}"
                    aria-label="Anteil ${esc(p)}${einheit ? ` in ${esc(einheit)}` : ''}">${einheitTag}</span>`
          : `<span class="mini-wrap"><span class="gv">${wZahl(w).toLocaleString('de-DE')}</span>${einheitTag}</span>`}
      </div>`;
    }).join('');
    aufteilung = `<div class="vt-ergebnis">${euroRows}</div>${
      bearbeitbar ? ableiten : ''}`;
  } else {
    aufteilung = `<div class="vt-gewichte">${gwRows}${ableiten}</div>`;
  }

  const basis = esc(JSON.stringify(Object.fromEntries(
    felder.map(([p, w]) => [p, Number(w) || 0]))));

  return `<div class="vt" data-pid="${k.position_id}" data-basis="${basis}"
      data-rest="${rest}">
      <div class="zk">Verteilen nach</div>
      ${wahl}
      ${k.ohne_verteilung ? `<div class="warnung"><span>▲</span>
        <span><b>Ohne Gewichte fließen die ${eur(k.betrag)} mit 0,00 € ein.</b>
        </span></div>` : ''}
      <div class="vt-aufteilung">
        <div class="zk">Aufteilung</div>
        ${vorabZeileHtml(k)}
        ${aufteilung}
        ${doppelteEinheit(felder.map(([p]) => p))}
      </div>
      ${vorabHtml(k)}
    </div>`;
}

/* Eine Kostenzeile der Checkliste. */
function zeileHtml(k, i) {
  // N189/N198a/N222 — Signal je nach Zustand. Zwei Warn-Fälle, beide „Betrag
  // ist da, zählt aber noch nicht wirklich in der Abrechnung mit":
  // Heizöl/Heizkörper-Wärmemenge (noch nicht auf Einheiten verteilt, HKV
  // fehlt) und Strom/Warmwasser (automatisch berechnet, aber noch nicht auf
  // die Kostenposition zurückgeschrieben — siehe `stromBetragSichern`).
  const erl = effektivErledigt(k);
  const heizWarn = !erl && (istHeizwaermePos(k) || istHeizoelSammel(k))
    && positionsBetrag(k) > 0.005;
  const umlageWarn = !erl && (istStromKettePos(k) || istWarmwasserPos(k))
    && positionsBetrag(k) > 0.005;
  const nichtUmgelegt = heizWarn || umlageWarn;
  const [farbe, zeichen] = erl ? HAKEN.erledigt
    : nichtUmgelegt ? HAKEN.warnung
    : (k.optional ? HAKEN.fehlt : HAKEN.offen);
  const zeigeHaken = erl || nichtUmgelegt || !k.optional;
  // N101 — die Wasser-Sammelzeile trägt die Summe ihrer drei Bestandteile.
  const oelBetrag = istHeizoelSammel(k) && !k.betrag ? state.heizoelKosten
    : (istWarmwasserPos(k) && !k.betrag ? state.wwKosten
    : (istHeizwaermePos(k) && !k.betrag
       ? Math.round((state.heizoelKosten - state.wwKosten) * 100) / 100 : 0));
  const wert = eur(istWasserSammel(k) ? wasserGesamtBetrag()
    : (istStromKettePos(k) ? positionsBetrag(k)
    : (oelBetrag || k.betrag)));
  const aufgeklappt = state.offen.has(i);

  const infos = [
    k.zustand === 'offen' ? 'Betrag fehlt' : null,
    k.ohne_verteilung ? 'Verteilung fehlt' : null,
    istWasserSammel(k)
      ? 'Fasst Frisch-, Schmutz- & Niederschlagswasser zusammen' : null,
    heizWarn ? 'Heizkosten noch nicht auf Einheiten verteilt' : null,
    umlageWarn ? 'Betrag berechnet, wird gerade in die Abrechnung übernommen' : null,
  ].filter(Boolean).join(' · ');

  return zeileInner(k, i, aufgeklappt, infos, wert, farbe, zeichen, zeigeHaken);
}

function zeitraumFussHtml() {
  const v = state.daten.verknuepft || {};
  const chips = [
    ['Positionen', v.positionen || 0],
    ['Belege', v.belege || 0],
  ];
  const leer = chips.every(([, n]) => n === 0);
  return `<div class="zr-fuss">
    <div class="zeilen">${chips.map(([l, n]) =>
      `<span class="chip${n > 0 ? ' hat' : ''}">${n}&nbsp;${l}</span>`).join('')}</div>
    <div class="hinweis">${leer
      ? 'An diesem Zeitraum hängt nichts mehr — beim nächsten Aufräumen verschwindet er automatisch.'
      : 'Nimmst du die letzte Position und den letzten Beleg heraus, wird der dann leere Zeitraum von selbst entfernt. Einen Löschknopf gibt es bewusst nicht.'}</div>
  </div>`;
}

/* N237 — kostenfreie Zusatzbelege (Anhänger) dieser Kostenart: sichtbar direkt
   in der aufgeklappten Karte, nicht nur im separaten „Belege"-Tab. Ein
   Anhänger trägt keine Kostenposition und darf die Position nie erledigt
   setzen (das bleibt allein der Betrag, siehe `effektivErledigt`/N238). */
/* Die Anhänger dieser Kostenart — reine Info-Belege ohne Kostenposition. */
function anhaengerListe(k) {
  return state.anhaenger?.angehaengt?.[k.kostenart] || [];
}

/* N283(f) — welche Belege zu einer Zeile gehören: über die **Id**, nicht über
   den Dateinamen.

   Bisher lief das über `belegeZu` und endete dort im Rückfall
   `dateiname.includes(<erstes Wort der Kostenart>)` — der einzige Weg, der
   praktisch griff, sobald ein Beleg noch nicht in eine Kostenposition
   eingerechnet war (`belege_je_art` ist nach Kategorie geschlüsselt, nicht nach
   Kostenart, und trifft eine NK-Zeile nie). Wer in der Bestätigungsmaske frei
   umbenennt — genau das, wofür sie da ist —, liess seinen Beleg damit aus der
   Zeile fallen: „Abfallgebühren 2024.pdf" enthält kein „müllabfuhr".
   Umgekehrt zog „Versicherung" jede Datei mit diesem Wort an sich.

   Seit N290/N298 gibt es stabile Kennzeichen. Zwei davon reichen hier:
     1. `k.belege` — die in die Kostenposition eingerechneten Belege. Der Server
        hängt sie über `Dokument.position_id` an; nichts daran ist Text.
     2. `d.kostenart` am Dokument selbst — ein gepflegtes Feld, das ein
        Umbenennen der Datei nicht anfasst.

   Der Dateiname bleibt der letzte Rückfall und greift nur, wenn KEIN Kennzeichen
   etwas findet: für Altbestände, an denen nie eine Kostenart gepflegt wurde.
   Eine falsch zugeordnete Zeile ist schlimmer als eine leere, deshalb steht er
   zuletzt und nie neben den anderen. */
function belegeStabil(k) {
  const ausPosition = k.belege || [];
  const ausKostenart = (state.daten?.dokumente || [])
    .filter(d => (d.kostenart || '') === k.kostenart);
  const zusammen = [...ausPosition, ...ausKostenart]
    .filter((d, i, a) => d && a.findIndex(x => x.id === d.id) === i);
  return zusammen.length ? zusammen : (belegeZu(k) || []);
}

/* Der Belege-Kasten der aufgeklappten Karte. Inhaltlich `helpers.belegeHtml`,
   nur ohne den Dateinamen-Rückfall.

   Hat die Kostenposition eigene Belege, stehen GENAU die darin und sonst
   nichts: darüber sitzt die Zusammensetzung („Summe aus 2 Belegen · 300 €"),
   und eine Liste mit fünf Zeilen unter dieser Überschrift wäre dieselbe Angabe
   zweimal — einmal falsch. Die übrigen Belege derselben Kostenart erscheinen
   an der Belege-Badge und im Zusatzbelege-Kasten (`belegeGruppen`), wo sie
   hingehören. Nur wenn die Position gar keine Belege trägt, greift die
   id-basierte Zuordnung. */
function belegeKastenHtml(k, extra = '') {
  const alle = k.belege?.length ? k.belege : belegeStabil(k);
  if (!alle.length) {
    return `<div class="belege"><span class="kein">Kein Beleg hinterlegt —
      im Eingang lässt sich einer übernehmen.</span>${extra}</div>`;
  }
  return zusammensetzungHtml(k)
    + belegLinks(alle, extra, state.daten?.status === 'in Arbeit');
}

/* N257 — alle Belege einer Kostenart, getrennt nach dem, was sie unterscheidet:
   ob sie auf die Kostenposition zahlen oder nur danebenliegen. Beide Quellen
   sind die schon vorhandenen — `belegeZu` (die Belege der Position) und die
   Anhänger. Nichts wird hier neu erraten. Nach `id` entdoppelt.

   N259 — entscheidend ist der BETRAG, nicht die Verknüpfung: ein SEPA-Mandat
   war an der Müll-Position angehängt und stand deshalb unter „mit
   Kostenzuordnung", obwohl es keinen Euro trägt (die Erkennung sagt selbst
   „ohne konkrete Kostenangaben"). Verknüpft-aber-betraglos ist ein Info-Beleg,
   und genau das soll die Trennung zeigen. */
function belegeGruppen(k) {
  const alle = belegeStabil(k);
  const mit = alle.filter(d => Number(d.betrag) > 0.005);
  const gesehen = new Set(mit.map(d => d.id));
  const ohne = [...alle.filter(d => !gesehen.has(d.id)),
                ...anhaengerListe(k).filter(d => !gesehen.has(d.id))]
    .filter((d, i, a) => a.findIndex(x => x.id === d.id) === i);
  return { mit, ohne, anzahl: mit.length + ohne.length };
}

/* N258(d) — in der geöffneten Karte stehen die Kostenbelege oben (sie tragen
   den Rechenweg), die Zusatzbelege darunter und eingerückt: sie gehören dazu,
   zahlen aber nicht auf den Betrag ein. Eingerückt wie die Unter-Belege in der
   Eintrags-Detailansicht (`.dd-beleg.unter`), damit die Staffelung im ganzen
   Produkt dieselbe Sprache spricht. */
function zusatzBelegeHtml(k) {
  const { ohne } = belegeGruppen(k);
  if (!ohne.length) return '';
  const loesbar = state.daten.status === 'in Arbeit';
  return `<div class="zusatzbelege">
      <span class="zb-t">Zusätzliche Belege ohne Kostenzuordnung</span>
      ${ohne.map(d => `<span class="beleg-zeile">
        <a href="#" data-beleg="${d.id}" data-name="${esc(d.dateiname)}"
           data-pfad="${esc(d.pfad || '')}" title="${esc(d.dateiname)}"
           >${ANH_ICON}${esc(kurzBeleg(d.dateiname))}</a>
        ${loesbar ? `<button class="beleg-weg" data-anh-loesen="${d.id}"
          data-was="${esc(d.dateiname || '')}"
          title="Beleg herausnehmen (Datei bleibt)"
          aria-label="Beleg herausnehmen">×</button>` : ''}
      </span>`).join('')}
    </div>`;
}

/* N252 — statt der Chips im aufgeklappten Bereich sitzt jetzt eine Badge am
   Kopf der Karte: „2 Belege". Sie ist der einzige Hinweis darauf, dass zu
   dieser Kostenart etwas hinterlegt ist, solange keine Kostenposition da ist
   (die Karte klappt dann gar nicht mehr auf). Ein Tippen öffnet die Belege. */
function anhaengerBadgeHtml(k, aufgeklappt) {
  // N257(b) — nur an der ZUGEKLAPPTEN Karte. Ist sie offen, stehen die Belege
  // ohnehin ausführlich darunter; die Badge wäre dieselbe Information zweimal.
  if (aufgeklappt) return '';
  const n = belegeGruppen(k).anzahl;
  if (!n) return '';
  // Auf schmalen Schirmen bleibt nur Symbol + Zahl sichtbar (CSS): mit dem Wort
  // „Belege" blieb dem Positionsnamen so wenig Breite, dass er buchstabenweise
  // umbrach. Die volle Beschriftung steht im aria-label.
  return `<button type="button" class="anh-badge" data-anh-zeigen="${esc(k.kostenart)}"
      title="Belege dieser Position ansehen"
      aria-label="${n} ${n === 1 ? 'Beleg' : 'Belege'} ansehen"
      >${ANH_ICON}<span class="anh-b-n">${n}</span
      ><span class="anh-b-w">&nbsp;${n === 1 ? 'Beleg' : 'Belege'}</span></button>`;
}

/* Das Fenster hinter der Badge: die Info-Belege dieser Kostenart mit ihrem
   ECHTEN Dateinamen (N249c), zum Ansehen und Herausnehmen. Bewusst ein eigenes
   Fenster statt eines Sprungs in den Belege-Tab: dort stehen ALLE Belege des
   Zeitraums, der Bezug zur Kostenart ginge verloren — und der Nutzer bleibt
   hier, wo er gerade war. */
function anhaengerFenster(kostenart) {
  const k = (state.daten.checkliste || []).find(x => x.kostenart === kostenart);
  if (!k) return null;
  const { mit, ohne, anzahl } = belegeGruppen(k);
  const bearbeitbar = state.daten.status === 'in Arbeit';
  // Ein Beleg der Position darf hier nicht „herausgenommen" werden — dafür ist
  // die aufgeklappte Karte da, wo auch der Rechenweg steht. Nur Anhänger
  // tragen das ×.
  const zeile = (d, loesbar) => `
    <div class="anh-zeile">
      <button type="button" class="anh-z-name" data-beleg="${d.id}"
        data-name="${esc(d.dateiname)}" data-pfad="${esc(d.pfad || '')}"
        title="${esc(d.dateiname)}">
        <span class="anh-z-dn">${esc(d.dateiname)}</span>
        ${d.pfad ? `<span class="anh-z-pf"><bdi dir="ltr">${esc(d.pfad)}</bdi></span>` : ''}
      </button>
      ${d.betrag ? `<span class="anh-z-b">${eur(d.betrag)}</span>` : ''}
      ${loesbar && bearbeitbar ? `<button type="button" class="anh-z-x"
        data-anh-loesen="${d.id}" data-was="${esc(d.dateiname || '')}"
        title="Beleg herausnehmen" aria-label="Beleg herausnehmen">×</button>` : ''}
    </div>`;
  const gruppe = (titel, liste, loesbar) => liste.length
    ? `<div class="anh-gruppe"><span class="anh-g-t">${titel}</span>
        ${liste.map(d => zeile(d, loesbar)).join('')}</div>` : '';
  const dlg = baueDialog(
    `<div class="beleg-kopf">
       <span class="bt">${esc(kostenartAnzeige(kostenart))}<span class="bpfad"
         >${anzahl} ${anzahl === 1 ? 'Beleg' : 'Belege'}</span></span>
       <button class="bx" data-zu title="Schließen" aria-label="Schließen">✕</button>
     </div>
     <div class="anh-liste">${
       gruppe('Mit Kostenzuordnung', mit, false)
       + gruppe('Ohne Kostenzuordnung', ohne, true)
       || '<div class="anh-leer">Keine Belege hinterlegt.</div>'}</div>`);
  dlg.classList.add('beleg-dlg', 'anh-dlg');
  dlg.querySelector('[data-zu]').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  // Die Klick-Handler der Checkliste hängen an `inhalt`; dieses Fenster steht
  // am `body` und wird davon nicht erreicht. Also hier direkt verdrahten —
  // dieselben Funktionen, nur ohne den Umweg über die Delegation.
  dlg.addEventListener('click', e => {
    const ansehen = e.target.closest('[data-beleg]');
    if (ansehen) {
      e.preventDefault();
      dlg.close();
      // N257(d) — die ganze Reihe mitgeben: aus dem geöffneten Beleg heraus
      // lässt sich dann zu den übrigen desselben Elements blättern.
      const reihe = [...mit, ...ohne].map(d => ({
        id: d.id, dateiname: d.dateiname, pfad: d.pfad || '' }));
      belegAnsehen(`/api/dokumente/${ansehen.dataset.beleg}/inhalt`,
                   ansehen.dataset.name || 'Beleg', ansehen.dataset.pfad || '',
                   Number(ansehen.dataset.beleg), reihe);
      return;
    }
    const weg = e.target.closest('[data-anh-loesen]');
    if (weg) {
      e.preventDefault();
      dlg.close();
      anhaengerEntfernen(weg.dataset.anhLoesen, weg.dataset.was);
    }
  });
  return dlg;
}

function zeileInner(k, i, aufgeklappt, infos, wert, farbe, zeichen, zeigeHaken = true) {
  const erl = effektivErledigt(k);
  // N222 — dieselben vier Positionen wie in `zeileHtml`: ein berechneter Wert
  // soll sichtbar bleiben, auch solange er (noch) nicht als „erledigt" zählt.
  const heizWaermeBerechnet = (istHeizwaermePos(k) || istHeizoelSammel(k)
    || istStromKettePos(k) || istWarmwasserPos(k)) && positionsBetrag(k) > 0.005;
  const zustandKlasse = k.vorlaeufig ? ' entwurf' : (erl ? ' gefuellt' : '');
  const bearbeitbar = state.daten.status === 'in Arbeit';

  const wasserSammel = istWasserSammel(k);
  const wasserBill = wasserSammel && wasserHatRechnung(k);
  const heizoelSammel = istHeizoelSammel(k);
  const heizModus = heizoelSammel ? 'oel'
    : istWarmwasserPos(k) ? 'warmwasser'
    : istHeizwaermePos(k) ? 'waerme' : '';
  // N252 — eine Karte klappt nur auf, wenn dahinter auch etwas steckt: eine
  // zugeordnete Kostenposition, eine der Sammel-/Rechenansichten (Wasser,
  // Heizung) oder die Stromkette. Ohne Kostenposition bot die Karte früher nur
  // eine Eingabemaske („Beleg hier ablegen" + „Betrag (optional)" + „Anlegen").
  // Die ist überflüssig: zugeordnet wird über den Scan, nicht von Hand — und
  // die Scan-Knöpfe sitzen ohnehin an der zugeklappten Karte. Als Kriterium
  // dient dieselbe Kostenposition, an der auch `effektivErledigt` hängt (N238);
  // keine zweite, abweichende Regel.
  // N256 — es genügt NICHT, dass eine Kostenposition existiert: eine mit
  // `betrag = 0` (nur ein Infobeleg wie ein SEPA-Mandat daran) ist keine echte
  // Position. Aufgeklappt wird nur, was auch Kosten trägt — dieselbe Schwelle
  // wie bei `effektivErledigt`/N238, damit es EINEN Begriff von „diese Position
  // ist echt" gibt und nicht zwei.
  const hatPosition = positionsBetrag(k) > 0.005 || !!heizModus
    || istStromKettePos(k);
  const kannAuf = wasserSammel ? wasserBill : hatPosition;
  const auf = aufgeklappt && kannAuf;

  let koerper = '';
  if (auf && wasserSammel) {
    const anbau = bearbeitbar
      ? `<button class="anh-anbau" data-anhaengen="${esc(k.kostenart)}"
          >${ANH_ICON} Beleg anhängen</button>` : '';
    const leeren = bearbeitbar
      ? `<div class="kartenfuss"><button class="minilink gefahr"
          data-wasser-leeren="1">Position leeren — für neuen Beleg</button></div>`
      : '';
    koerper = `<div class="wd-inline" data-wasser-inline="${zid}">
        <div class="wd-lade">Detailübersicht wird geladen …</div></div>
      <div class="zk">Belege</div>${belegeKastenHtml(k, anbau)}${leeren}`;
  } else if (auf && heizModus) {
    const anbau = bearbeitbar
      ? `<button class="anh-anbau" data-anhaengen="${esc(k.kostenart)}"
          >${ANH_ICON} ${heizModus === 'oel' ? 'Öl-Rechnung' : 'Beleg'} anhängen</button>` : '';
    koerper = `<div class="ho-inline" data-heizoel-inline="${zid}"
        data-heiz-modus="${heizModus}" data-pid="${k.position_id || ''}"
        data-art="${esc(k.kostenart)}"
        data-schluessel="${esc(k.schluessel || '')}">
        <div class="wd-lade">Wird geladen …</div></div>
      <div class="zk">Belege</div>${belegeKastenHtml(k, anbau)}`;
  } else if (auf && k.position_id) {
    const anbau = bearbeitbar
      ? `<button class="anh-anbau" data-anhaengen="${esc(k.kostenart)}"
          >${ANH_ICON} Beleg anhängen</button>` : '';
    const belege = `<div class="zk">Belege</div>${belegeKastenHtml(k, anbau)}`;
    const fuss = k.vorlaeufig
      ? `<button class="hauptaktion ja" data-entwurf-ja="${k.position_id}"
          >✓ Bestätigen</button>
         <button class="minilink" data-entwurf-nein="${k.position_id}"
          data-art="${esc(k.kostenart)}">Zurück zum Prüfen</button>`
      : `<button class="hauptaktion" data-fertig="${i}">Fertig</button>
         ${bearbeitbar ? `<button class="minilink gefahr"
          data-entfernen="${k.position_id}"
          data-art="${esc(k.kostenart)}">Entfernen</button>` : ''}`;
    const anbieterFeld = (bearbeitbar && k.kostenart_id)
      ? `<div class="anbieterzeile"><label>Anbieter / Gewerk</label>
          <input type="text" data-anbieter="${k.kostenart_id}"
            value="${esc(k.anbieter || '')}" data-wert="${esc(k.anbieter || '')}"
            placeholder="z. B. WWK, Zweckverband, Firma …"></div>` : '';
    const kostenartFeld = bearbeitbar
      ? `<div class="kostenartzeile"><label>Kostenart</label>
          <select data-kostenart-pos="${k.position_id}" data-wert="${esc(k.kostenart)}"
            aria-label="Kostenart dieser Position">${artOptionen(k.kostenart)}</select>
          <input class="ka-neu" data-kostenart-neu="${k.position_id}" hidden
            placeholder="Neue Kostenart …" aria-label="Neue Kostenart"></div>` : '';
    koerper = `${kostenartFeld}${anbieterFeld}${stromPosFeldHtml(k)}
      ${stromKetteHtml(k)}${verteilungHtml(k)}${belege}${zusatzBelegeHtml(k)}
      <div class="kartenfuss">${fuss}</div>`;
  } else if (auf) {
    // N249 — das Feld „Betrag (optional)" samt „Anlegen" ist ersatzlos weg: der
    // Betrag entsteht aus dem Beleg, nicht aus einer zweiten Eingabemaske.
    const zu = bearbeitbar ? '' : `<div class="zu-kein">Für diese Kostenart wurde
      in diesem Zeitraum nichts erfasst — und er ist abgeschlossen.</div>`;
    const ablage = (istStromKettePos(k) && stromKetteVerteilt())
      ? '' : belegAblageHtml(k, bearbeitbar);
    koerper = `${stromKetteHtml(k)}${zu}${ablage}`;
  }

  // N356 — die Heizwärme bekommt KEIN Betragsfeld: ihr Wert entsteht aus den
  // Öl-Litern (FIFO) abzüglich des Warmwasseranteils und steht darüber. Ein
  // Eingabefeld daneben lud dazu ein, ihn von Hand zu überschreiben — zwei
  // Wahrheiten für dieselbe Zahl.
  const betragEl = (auf && k.position_id && bearbeitbar && !wasserSammel
                    && !heizoelSammel && !istHeizwaermePos(k))
    ? `<span class="kopf-betrag-box"><input class="kopf-betrag" type="number" step="0.01"
         inputmode="decimal" placeholder="Betrag" value="${k.betrag ?? ''}"
         data-betrag="${k.position_id}" data-wert="${k.betrag ?? ''}"
         aria-label="Betrag für ${esc(k.kostenart)}"><span class="kbe">€</span></span>`
    : ((erl || heizWaermeBerechnet) ? `<span class="wert">${wert}</span>` : '');
  const quickScan = (!erl && !aufgeklappt && !heizWaermeBerechnet)
    ? (KEINE_KAMERA
      ? `<button class="scanmini" data-scan="${esc(k.kostenart)}"
            title="Beleg-PDF von diesem Rechner wählen" aria-label="Beleg-Datei wählen">
            ${UPLOAD_ICON}<span class="st">Datei wählen</span>
          </button>`
      : `<button class="scanmini" data-scan="${esc(k.kostenart)}"
            title="Beleg für ${esc(k.kostenart)} abfotografieren" aria-label="Beleg abfotografieren">
            ${FOTO_ICON}<span class="st">Foto</span>
          </button>
          <button class="scanmini ablage" data-ablage="${esc(k.kostenart)}"
            title="Beleg aus der Ablage / Nextcloud wählen" aria-label="Beleg aus der Ablage wählen">
            ${WOLKE_ICON}<span class="st">Aus Ablage</span>
          </button>`) : '';

  return `<div class="pruef${zustandKlasse}" data-kostenart="${esc(k.kostenart)}">
      <div class="kopf">
        <button class="zeile" data-auf="${i}"${kannAuf ? '' : ' data-noexpand'} aria-expanded="${auf}">
          <span class="ikon ${erl ? 'fertig' : 'warte'}">${
            kostenIcon(k.kostenart)}</span>
          <span class="name">${esc(kostenartAnzeige(k.kostenart))}${chipHtml(k)}${
            k.vorlaeufig ? '<span class="entw-badge">Entwurf aus Beleg</span>' : ''}${
            (k.anbieter && !aufgeklappt && k.zustand !== 'fehlt')
              ? `<span class="anbieter-tag" title="Anbieter / Gewerk">${esc(k.anbieter)}</span>`
              : ''}${stromKopfHtml(k)}${
            infos ? `<span class="unter">${esc(infos)}</span>` : ''}</span>
        </button>
        <span class="kopf-belege">${anhaengerBadgeHtml(k, auf)}</span>
        <span class="kopf-rechts">${betragEl}${vkeyChip(k)}</span>
        ${quickScan}
        ${zeigeHaken
          ? `<span class="haken ${farbe}">${zeichen}</span>` : ''}
      </div>
      ${auf ? `<div class="auf">${koerper}</div>` : ''}
    </div>`;
}

/* ---------- Ergebnis + Abschluss --------------------------------------- */

function empfaengerHtml(p) {
  if (!p) return '';
  if (p.leerstand) {
    return '<div class="wemgeht">Bleibt beim Eigentümer — kein Versand.</div>';
  }
  if (p.adressen?.length) {
    return `<div class="wemgeht">Geht an ${p.adressen.map(esc).join(' · ')}</div>`;
  }
  return `<div class="wemgeht fehlt">Keine Mailadresse hinterlegt —
    ausdrucken und mit der Post schicken.</div>`;
}

/**
 * N314(g) — eine Vorauszahlung, deren Partei zu keinem Bezug dieses Zeitraums
 * passt (Tippfehler, ausgezogener Mieter unter altem Namen). Sie steckt in
 * `gesamt.abschlaege`, taucht aber in keiner Partei-Zeile auf — ohne diesen
 * Hinweis unsichtbar. Der Betrag ist nicht Teil der API-Antwort und wird
 * daher aus der Differenz Gesamt-Abschläge ./. Summe der bekannten
 * Vorauszahlungen abgeleitet (bei genau einem unbekannten Namen exakt sein
 * Betrag).
 */
function vorauszahlungOhnePartei(a) {
  const namen = a.vorauszahlungen_ohne_partei;
  if (!namen?.length) return '';
  const bekannt = Object.values(a.parteien || {})
    .reduce((s, w) => s + (w.vorauszahlungen || 0), 0);
  const betrag = (a.gesamt?.abschlaege || 0) - bekannt;
  const satz = namen.length === 1
    ? `Der Name passt zu keiner Partei dieses Zeitraums.`
    : `Diese Namen passen zu keiner Partei dieses Zeitraums.`;
  return `<div class="karte">
      <h3>Vorauszahlung ohne Partei</h3>
      <div class="weg-warn"><span class="ww-z">${eur(betrag)}</span>
        <span><b>${esc(namen.join(', '))}</b> — ${satz} Sie fließen in die
        Gesamtsumme ein, aber in keine Partei-Zeile. Name in den
        Mieterstammdaten prüfen und richtigstellen.</span>
      </div>
    </div>`;
}

async function ergebnisHtml() {
  const [rechnung, versand] = await Promise.allSettled([
    einmal(`/zeitraeume/${zid}/abrechnung`),
    api(`/zeitraeume/${zid}/versand`),
  ]);
  if (rechnung.status !== 'fulfilled') {
    return '<div class="empty"><div class="big">Ergebnis nicht verfügbar</div></div>';
  }
  const a = rechnung.value;
  const wer = new Map((versand.value?.parteien || []).map(p => [p.partei, p]));

  const zeilen = Object.entries(a.parteien || {}).map(([partei, w]) => `
    <div class="karte">
      <h3>${esc(partei)}${wer.get(partei)?.leerstand || state.leerstaende.has(partei)
        ? '<span class="marke">Leerstand</span>' : ''}</h3>
      ${empfaengerHtml(wer.get(partei))}
      <div class="summe"><span>Umlagefähige Kosten</span><b>${eur(w.kosten)}</b></div>
      <div class="summe"><span>Vorauszahlungen</span><b>${eur(w.vorauszahlungen)}</b></div>
      ${w.s35 ? `<div class="summe"><span>davon § 35a</span><b>${eur(w.s35)}</b></div>`
        : ''}
      <div class="summe gesamt"><span>Saldo</span>
        <b class="${(w.saldo ?? 0) >= 0 ? 'pos' : 'neg'}">${eur(w.saldo)}</b></div>
      <a class="pdflink" target="_blank" rel="noopener"
         href="/api/zeitraeume/${zid}/abrechnung.pdf?partei=${
           encodeURIComponent(partei)}">▤ Abrechnung als PDF ansehen</a>
    </div>`).join('');

  const g = a.gesamt || {};
  return `<div class="karte">
      <h3>Gesamt</h3>
      <div class="summe"><span>Auslagen</span><b>${eur(g.auslagen)}</b></div>
      <div class="summe"><span>Abschläge</span><b>${eur(g.abschlaege)}</b></div>
      <div class="summe gesamt"><span>Saldo</span>
        <b class="${(g.saldo ?? 0) >= 0 ? 'pos' : 'neg'}">${eur(g.saldo)}</b></div>
    </div>${zeilen}
    ${vorauszahlungOhnePartei(a)}
    ${a.offen?.length ? `<div class="karte"><h3>Noch offen</h3>
      ${a.ohne_betrag?.length ? `<div class="summe">
        <span>Ohne Betrag</span><b>${a.ohne_betrag.map(esc).join(', ')}</b></div>` : ''}
      ${a.ohne_verteilung?.length ? `<div class="summe">
        <span>Ohne Verteilung</span>
        <b class="neg">${a.ohne_verteilung.map(esc).join(', ')}</b></div>` : ''}
      </div>` : ''}`;
}

function abschlussHtml() {
  if (state.daten.status !== 'in Arbeit') {
    return `<div class="abschluss fertig">
        <div class="at">Abgeschlossen</div>
        <p>Dieser Zeitraum ist abgerechnet und versendet.</p>
        <button class="wiederauf" data-oeffnen="1">Wieder öffnen</button>
      </div>`;
  }
  // N280 — im WEG-Modus gibt es keine Positionen zu jagen: gezählt wird, was
  // aus der Abrechnung übernommen wurde. Die Checkliste des Objekts stünde hier
  // sonst als „12 Positionen ohne Betrag" — genau die Mahnung, die im
  // WEG-Modus falsch ist.
  if (state.wegDaten?.aktiv) {
    const stand = state.wegDaten.stand || {};
    const anzahl = (stand.positionen || []).length;
    if (!anzahl) {
      return `<div class="abschluss offen">
          <div class="at">Noch keine Abrechnung übernommen</div>
          <p>Nimm oben die Abrechnung der Abrechnungsfirma auf — daraus
             entstehen die Positionen dieses Zeitraums.</p>
        </div>`;
    }
    return `<div class="abschluss bereit">
        <div class="at">✓ Abrechnung übernommen</div>
        <p>${anzahl} ${anzahl === 1 ? 'Position' : 'Positionen'} ·
           ${eur(stand.umlagefaehig_summe)} umlagefähig.
           Die Abrechnung kann erstellt und verschickt werden.</p>
        <button class="losbutton" data-abschluss="1">Abrechnungen erstellen und versenden</button>
      </div>`;
  }
  const f = state.daten.fortschritt;
  const rest = f.gesamt - f.fertig;
  const ohne = state.daten.checkliste.filter(k => k.ohne_verteilung)
    .map(k => k.kostenart);

  if (rest === 0 && !ohne.length) {
    return `<div class="abschluss bereit">
        <div class="at">✓ Alles erfasst</div>
        <p>${f.gesamt} Positionen vollständig · ${eur(f.summe)} umlagefähig.
           Die Abrechnungen können erstellt und verschickt werden.</p>
        <button class="losbutton" data-abschluss="1">Abrechnungen erstellen und versenden</button>
      </div>`;
  }
  const teile = [
    rest ? `${rest} ${rest === 1 ? 'Position' : 'Positionen'} ohne Betrag` : null,
    ohne.length ? `${ohne.length} ohne Verteilung` : null,
  ].filter(Boolean).join(' · ');

  return `<div class="abschluss offen">
      <div class="at">Noch nicht vollständig</div>
      <p>${teile}. Trage die fehlenden Angaben ein — oder bestätige, dass die
         restlichen Posten für diesen Zeitraum nicht anfallen.</p>
      ${ohne.length ? `<div class="warnung"><span>▲</span>
        <span><b>${esc(ohne.join(', '))}</b> ${ohne.length === 1 ? 'hat' : 'haben'}
        einen Betrag, aber keine Verteilungsgewichte — ${ohne.length === 1
          ? 'er zählt' : 'sie zählen'} in der Abrechnung mit 0,00 €.</span>
        </div>` : ''}
      <label class="uebergehen">
        <input type="checkbox" id="uebergehen">
        <span>Restliche Positionen fallen nicht an</span>
      </label>
      <button class="losbutton" data-abschluss="1" disabled
              id="abschlussKnopf">Abrechnungen erstellen und versenden</button>
    </div>`;
}

/* CCVIII — Mieter-Direkteintrag für ein WEG-Objekt. */
function wegDirektHtml() {
  if (!state.daten.weg) return '';
  const einheiten = sonderEinheiten();
  const bereit = state.daten.status === 'in Arbeit';
  const bestehende = new Map((state.daten.checkliste || []).map(k => [k.kostenart, k]));

  const zeilen = einheiten.map(e => {
    const vorhanden = bestehende.get(WEG_ART(e.einheit));
    const betrag = vorhanden && vorhanden.betrag != null ? vorhanden.betrag : '';
    return `<div class="gw">
        <span class="gn">${esc(e.einheit)}${e.parteien.length
          ? `<span class="gsub">${esc(e.parteien.join(' · '))}</span>` : ''}</span>
        ${bereit
          ? `<input type="number" step="0.01" min="0" value="${betrag}"
                   data-weg-betrag="${esc(e.einheit)}" placeholder="NK-Summe"
                   aria-label="Umlagefähige NK-Summe ${esc(e.einheit)}">`
          : `<span class="gv">${betrag !== '' ? eur(betrag) : '—'}</span>`}
      </div>`;
  }).join('');

  const koerper = einheiten.length
    ? zeilen + (bereit ? `<div class="nachtrag" style="margin-top:12px">
        <button data-weg-speichern="1">Werte je Mieter übernehmen</button>
      </div>` : '')
    : `<div class="belege"><span class="kein">Noch keine vermietete Einheit —
        lege auf der Objektseite Einheiten und Mieter an, dann steht hier je
        Mieter ein Feld für die NK-Summe.</span></div>`;

  return `<div class="karte sonder">
      <h3>Nebenkosten laut Hausverwaltung <span class="marke post">WEG</span></h3>
      <span class="erklaer">Diese Wohnung gehört zu einer WEG — die
        Hausverwaltung verteilt die Nebenkosten. Trage je Mieter die
        umlagefähige NK-Summe vom Abrechnungszettel direkt ein. ImmoCalc
        verteilt nichts, sondern rechnet sie gegen die Vorauszahlung und erstellt
        Saldo, PDF und Versand wie gewohnt.</span>
      ${koerper}</div>`;
}

/* N222 — sobald der §9-Split einen Warmwasser-Anteil errechnet, den Betrag
   auf die Warmwasser-Kostenposition schreiben. Dieselbe Lücke wie bei der
   Stromkette (siehe `stromkette.js` `stromBetragSichern`): ohne das zählt
   die tatsächliche Abrechnung diesen berechneten Betrag nie mit. */
async function warmwasserBetragSichern() {
  const betrag = Math.round((state.wwKosten || 0) * 100) / 100;
  if (betrag <= 0.005) return;
  const pos = (state.daten?.checkliste || []).find(istWarmwasserPos);
  if (!pos) return;
  if (pos.erledigt && Math.abs((pos.betrag || 0) - betrag) < 0.005) return;
  try {
    // Ohne eigene Kostenposition (Warmwasser entsteht rein aus dem §9-Split,
    // nie aus einem Beleg) muss sie hier erst angelegt werden.
    if (pos.position_id) {
      await api(`/positionen/${pos.position_id}`, { method: 'PATCH', body: { betrag } });
    } else {
      const neu = await api(`/zeitraeume/${state.daten.id}/positionen`,
        { method: 'POST', body: { kostenart: pos.kostenart, betrag } });
      pos.position_id = neu.id;
    }
    pos.betrag = betrag;
    pos.erledigt = true;
  } catch { /* nächster Aufruf versucht es erneut — kein Fehlerbanner nötig */ }
}

/* Die Deckung (Umgelegt/Abschläge) frisch vom Server holen und im Zustand
   ablegen — ohne den Rest der Seite neu zu laden. */
async function deckungLaden() {
  try {
    const ab = await einmal(`/zeitraeume/${zid}/abrechnung`);
    state.setDeckungAbschlaege(ab?.gesamt?.abschlaege ?? null);
    state.setDeckungUmgelegt(ab?.gesamt?.auslagen ?? null);
  } catch {
    state.setDeckungAbschlaege(null);
    state.setDeckungUmgelegt(null);
  }
}

/* N222 — nachdem Strom/Warmwasser ihren Betrag nachträglich in eine
   Kostenposition geschrieben haben (siehe `stromkette.js`), zeigt die
   „Umgelegt"-Karte sonst bis zum nächsten vollen Laden einen veralteten
   Wert — obwohl die echte Abrechnung längst den neuen Betrag zählt. */
export async function deckungAktualisieren() {
  await deckungLaden();
  if (state.ansicht === 'pruef') zeichnen();
}

/* Deckung am Kostenfluss. */
function deckungHtml() {
  const kosten = (state.daten.checkliste || []).reduce((s, k) => s + (k.betrag || 0), 0);
  const abschlaege = state.deckungAbschlaege != null ? state.deckungAbschlaege
    : (state.daten.vorauszahlungen || []).reduce((s, v) => s + (v.betrag || 0), 0);
  if (kosten <= 0) return '';
  if (abschlaege <= 0) {
    return `<div class="deckung"><div class="dstat"><span class="dl">Kosten erfasst</span>
        <span class="dv">${eur(kosten)}</span></div>
      <div class="dhinweis">Noch keine Abschläge erfasst — Deckung nicht bezifferbar.</div></div>`;
  }
  const umgelegt = state.deckungUmgelegt != null ? state.deckungUmgelegt : kosten;
  const saldo = abschlaege - umgelegt;
  const quote = Math.round(umgelegt / abschlaege * 100);
  const nach = saldo < 0;
  const rest = Math.round((kosten - umgelegt) * 100) / 100;
  return `<div class="deckung ${nach ? 'neg' : 'pos'}">
    <div class="dstat"><span class="dl">Abschläge der Mieter</span>
      <span class="dv pos">${eur(abschlaege)}</span></div>
    <div class="dstat"><span class="dl">Umgelegt · Deckung</span>
      <span class="dv neg">${eur(umgelegt)} · ${quote}%</span></div>
    <div class="dstat"><span class="dl">${nach ? 'Nicht gedeckt · Nachzahlung' : 'Überdeckt · Guthaben'}</span>
      <span class="dv ${nach ? 'neg' : 'pos'}">${eur(Math.abs(saldo))}</span></div>
    ${rest > 0.01 ? `<div class="dhinweis">Von ${eur(kosten)} erfassten Kosten sind
      ${eur(rest)} noch nicht verteilt (fehlender Schlüssel oder nicht umlagefähig).</div>` : ''}
  </div>`;
}

/* ---------- Haupt-Rendering ------------------------------------------- */

const GEAR_SVG = `<svg viewBox="-2 -2 28 28" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2
  2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0
  0 1-4 0v-.09A1.65 1.65 0 0 0 8.6 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1
  1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H2a2 2 0 0
  1 0-4h.09A1.65 1.65 0 0 0 3.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1
  2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H8a1.65 1.65 0 0 0 1-1.51V2a2 2 0 0 1
  4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83
  2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.2.63.77 1.06 1.43 1.09H22a2 2 0 0 1 0
  4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>`;

export async function zeichnen() {
  const f = fortschrittRechnen();
  const anteil = f.gesamt ? Math.round((f.fertig / f.gesamt) * 100) : 0;
  // N280 — im WEG-Modus gibt es keine Belegjagd: der Fortschrittsbalken würde
  // Positionen anmahnen, die dieser Zeitraum gar nicht mehr selbst erfasst.
  const wegAn = !!state.wegDaten?.aktiv;

  const kopf = `
    ${wegAn ? '' : `<div class="fortschritt">
      <div class="kopf">
        <span class="gross">${f.fertig} von ${f.gesamt}</span>
        <span class="klein">Positionen vollständig</span>
      </div>
      <div class="bahn"><i style="width:${anteil}%"></i></div>
    </div>`}
    <div class="tabs" role="tablist">
      <button data-tab="pruef" aria-selected="${state.ansicht === 'pruef'}">Checkliste</button>
      <button data-tab="ergebnis" aria-selected="${state.ansicht === 'ergebnis'}">Ergebnis</button>
      <button data-tab="belege" aria-selected="${state.ansicht === 'belege'}">Belege</button>
    </div>`;

  let rumpf = '';
  if (state.ansicht === 'pruef' && wegAn) {
    // N280 — die Dateiübernahme tritt an die Stelle der ganzen Checkliste:
    // keine Zeilen, keine Ausrufezeichen, keine Zählerkonfiguration.
    inhalt.innerHTML = kopf + wegAnsichtHtml() + abschlussHtml()
      + zeitraumFussHtml();
    return;
  }
  if (state.ansicht === 'pruef') {
    const zListe = state.ablesungMaske?.zaehler || [];
    if (zListe.length) state.setZLabels(generischeLabels(zListe));
    const zBlock = zListe.length ? zaehlerBloecke(zListe) : new Map();

    if (state.konfigModus) {
      rumpf = konfigAnsichtHtml(zListe, zBlock);
      inhalt.innerHTML = kopf + rumpf;
      return;
    }

    const fluss = state.daten.sankey || { knoten: [], fluss: [] };
    const flussKarte = fluss.fluss.length
      ? `<div class="karte"><h3>Kostenfluss · erfasste Positionen</h3>
          ${sankey(fluss.knoten, fluss.fluss,
                   { format: eurKurz, breite: window.innerWidth < 520 ? 260 : 540 })}
          ${deckungHtml()}
         </div>`
      : '';

    const sortWahl = `<div class="sortleiste">
        <span>Sortieren</span>
        ${Object.entries({ status: 'Offen', betrag: 'Größe', name: 'Name' })
          .map(([k, l]) => `<button data-sort="${k}"
            aria-pressed="${state.sortierung === k}">${l}</button>`).join('')}
        <button class="pos-konfig" data-pos-konfig
          title="Positionen konfigurieren"
          aria-label="Positionen konfigurieren">${GEAR_SVG}</button>
      </div>`;

    const sortiert = state.daten.checkliste
      .map((k, i) => ({ k, i }))
      .filter(({ k }) => !istImDetailPopup(k))
      .sort((a, b) => SORTIERUNG[state.sortierung](a.k, b.k));
    const bereiche = BEREICHE.map(() => []);
    for (const eintrag of sortiert) {
      bereiche[bereichIndex(eintrag.k.kostenart)].push(eintrag);
    }
    // N91 — im Heizungs-Kapitel fachliche Reihenfolge.
    const heizRang = k => istHeizoelSammel(k) ? 0
      : istWarmwasserPos(k) ? 1 : istHeizwaermePos(k) ? 2
      : normUml(k.kostenart).includes('wartung') ? 4 : 3;
    bereiche[1].sort((a, b) => heizRang(a.k) - heizRang(b.k));
    // N342 — im Heizungs-Kapitel je EIGENES Panel für Heizöl, Warmwasser und
    // Heizkörper & Wärmemenge, jedes unter seiner passenden Position
    // eingehängt — vorher lagen alle 24 Zähler in einem einzigen Panel unter
    // „Heizöl & Lieferungen", auch die 21 Heizkörperzähler und der
    // Warmwassermengenzähler.
    const zeilen = bereiche.map((liste, bi) => {
      if (bi === 1) {
        const panels = {
          oel: zaehlerPanelHtml('Heizung', zListe, zBlock, 'Heizöl'),
          ww: zaehlerPanelHtml('Heizung', zListe, zBlock, 'Warmwasser'),
          heiz: zaehlerPanelHtml('Heizung', zListe, zBlock, 'Heizkörper & Wärmemenge'),
        };
        const angehaengt = { oel: false, ww: false, heiz: false };
        if (!liste.length && !Object.values(panels).some(Boolean)) return '';
        const kopfKat = `<div class="kat-kopf"><span class="kat-ikon">${
            kostenIcon(BEREICH_IKON[bi])}</span><span class="kat-t">${
            esc(BEREICHE[bi].titel)}</span></div>`;
        // Je Panel-Art nur bei der ERSTEN passenden Position einhängen — gibt
        // es (unüblich) zwei Heizöl-Positionen, würde das Panel sonst doppelt
        // erscheinen.
        const zeilenHtml = liste.map(({ k, i }) => {
          let panel = '';
          if (istHeizoelSammel(k) && panels.oel && !angehaengt.oel) {
            panel = panels.oel; angehaengt.oel = true;
          } else if (istWarmwasserPos(k) && panels.ww && !angehaengt.ww) {
            panel = panels.ww; angehaengt.ww = true;
          } else if (istHeizwaermePos(k) && panels.heiz && !angehaengt.heiz) {
            panel = panels.heiz; angehaengt.heiz = true;
          }
          return zeileHtml(k, i) + panel;
        }).join('');
        // Kein passender Kartentyp gefunden (z. B. Wartung ohne eigene
        // Öl-/WW-/Heiz-Position) — nichts stillschweigend verlieren, ans Ende.
        const uebrig = ['oel', 'ww', 'heiz']
          .filter(k => panels[k] && !angehaengt[k]).map(k => panels[k]).join('');
        return kopfKat + zeilenHtml + uebrig;
      }
      const wz = bi < 3 ? zaehlerPanelHtml(BEREICH_IKON[bi], zListe, zBlock) : '';
      if (!liste.length && !wz) return '';
      const kopfKat = `<div class="kat-kopf"><span class="kat-ikon">${
          kostenIcon(BEREICH_IKON[bi])}</span><span class="kat-t">${
          esc(BEREICHE[bi].titel)}</span></div>`;
      return kopfKat + liste.map(({ k, i }) => zeileHtml(k, i)).join('') + wz;
    }).join('');

    rumpf = wegSchalterHtml() + wegDirektHtml() + flussKarte + sortWahl +
      zeilen + abschlussHtml() + zeitraumFussHtml();
  } else if (state.ansicht === 'ergebnis') {
    rumpf = '<div class="karte"><h3>Wird gerechnet …</h3></div>';
  } else {
    const gruppen = Object.entries(state.daten.belege_je_art || {})
      .filter(([, liste]) => liste.length)
      .sort(([a], [b]) => a.localeCompare(b, 'de'));
    rumpf = state.daten.dokumente.length
      ? gruppen.map(([art, liste]) => `<div class="karte">
          <h3>${esc(art || 'Ohne Art')} · ${liste.length}</h3>
          ${belegLinks(liste)}</div>`).join('')
      : `<div class="empty"><div class="big">Noch keine Belege</div>
          <p>Fotografiere in der Checkliste einen Beleg zu einer Position ab —
             er wird in der Cloud abgelegt und erscheint dann hier.</p></div>`;
  }

  inhalt.innerHTML = kopf + rumpf;

  if (state.ansicht === 'ergebnis') {
    inhalt.innerHTML = kopf + await ergebnisHtml();
  } else if (state.ansicht === 'pruef') {
    montiereSchluessel();
    // N108 (Fund 11) — mehrere Positionen können offen sein.
    inhalt.querySelectorAll('[data-wasser-inline]').forEach(fuelleWasserInline);
    inhalt.querySelectorAll('[data-heizoel-inline]').forEach(fuelleHeizoelInline);
    inhalt.querySelectorAll('[data-strom-kette]')
      .forEach(el => fuelleStromketteInline(el));
  }
}

/* Die Auswahlfelder werden nach dem Zeichnen gesetzt. */
function montiereSchluessel() {
  if (!state.schluessel) return;
  const WAHL = ['flaeche', 'personen', 'einheiten', 'prozentual', 'verbrauch'];
  const titelMap = new Map(state.schluessel.schluessel.map(s => [s.wert, s.titel]));
  const basis = WAHL.filter(w => titelMap.has(w))
    .map(w => ({ wert: w, text: titelMap.get(w) }));
  inhalt.querySelectorAll('[data-schluesselwahl]').forEach(ziel => {
    const pid = ziel.dataset.schluesselwahl;
    const jetzt = ziel.dataset.wert || '';
    const optionen = basis.slice();
    if (jetzt === NUR_EINHEIT_WAHL) {
      optionen.push({ wert: NUR_EINHEIT_WAHL, text: '1 Einheit' });
    } else if (jetzt && !WAHL.includes(jetzt)) {
      optionen.push({ wert: jetzt, text: titelMap.get(jetzt) || jetzt });
    }
    auswahlfeld(ziel, {
      optionen, wert: jetzt, label: 'Verteilen nach',
      aenderung: async neu => {
        if (neu === NUR_EINHEIT_WAHL) {
          state.setEinzelWahl(Number(pid));
          return zeichnen();
        }
        try {
          await api(`/positionen/${pid}`,
                    { method: 'PATCH', body: { schluessel: neu, nur_einheit: '' } });
          state.setEinzelWahl(null);
          await laden();
        } catch (fehler) {
          melde(String(fehler.message || fehler), 'neg');
        }
      },
    });
  });
}

/* Verteilung auto-speichern. */
async function verteilungAutoSpeichern(vt) {
  const felder = [...vt.querySelectorAll('[data-gewicht]')];
  if (!felder.length) return;
  const anteile = {};
  felder.forEach(f => { anteile[f.dataset.gewicht] = feldZahl(f) || 0; });

  let basis = {};
  try { basis = JSON.parse(vt.dataset.basis || '{}'); } catch { basis = {}; }
  const unveraendert = Object.keys(anteile).length === Object.keys(basis).length
    && Object.entries(anteile).every(([p, w]) => Number(basis[p]) === w);
  if (unveraendert) return;
  if (!Object.values(anteile).some(w => w > 0)) return;

  vt.dataset.basis = JSON.stringify(anteile);
  try {
    await api(`/positionen/${vt.dataset.pid}`,
              { method: 'PATCH', body: { anteile, abgeleitet: false } });
    melde('✓ Verteilung gespeichert', 'pos');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function verteilungAbleiten(knopf) {
  const meta = schluesselMeta(knopf.dataset.fuer);
  if (!meta?.moeglich) return;
  knopf.disabled = true;
  try {
    await api(`/positionen/${knopf.dataset.ableiten}`,
              { method: 'PATCH', body: { anteile: meta.gewichte, abgeleitet: true } });
    melde(`Gewichte aus den Stammdaten übernommen · ${meta.titel}`, 'pos');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    melde(String(fehler.message || fehler), 'neg');
  }
}


async function einzelSetzen(pid, einheit) {
  try {
    await api(`/positionen/${pid}`,
              { method: 'PATCH', body: { nur_einheit: einheit } });
    state.setEinzelWahl(null);
    melde(`Zu 100 % auf ${einheit}`, 'pos');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function betragSpeichern(feld) {
  const pid = feld.dataset.betrag;
  if (String(feld.value ?? '').trim() === '') return;
  const betrag = feldZahl(feld);
  if (betrag == null) return;
  if (String(feld.dataset.wert) === String(betrag)) return;
  feld.dataset.wert = String(betrag);
  try {
    await api(`/positionen/${pid}`, { method: 'PATCH', body: { betrag } });
    melde('✓ Betrag gespeichert', 'pos');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function anbieterSpeichern(feld) {
  const kid = feld.dataset.anbieter;
  if (!kid) return;
  const wert = feld.value.trim();
  if (String(feld.dataset.wert || '') === wert) return;
  feld.dataset.wert = wert;
  try {
    await api(`/kostenarten/${kid}`, { method: 'PATCH', body: { lieferant: wert } });
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

async function kostenartWechseln(sel) {
  const pid = sel.dataset.kostenartPos;
  const neuFeld = sel.parentElement.querySelector('.ka-neu');
  if (sel.value === '__neu__') {
    if (neuFeld) { neuFeld.hidden = false; neuFeld.value = ''; neuFeld.focus(); }
    return;
  }
  if (neuFeld) neuFeld.hidden = true;
  if (sel.value === String(sel.dataset.wert || '')) return;
  try {
    await api(`/positionen/${pid}`, { method: 'PATCH', body: { kostenart: sel.value } });
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    sel.value = sel.dataset.wert || sel.value;
  }
}

async function kostenartNeu(feld) {
  const pid = feld.dataset.kostenartNeu;
  const neu = feld.value.trim();
  if (!neu) return;
  try {
    await api(`/positionen/${pid}`, { method: 'PATCH', body: { kostenart: neu } });
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

async function vorabPatch(pid, body) {
  try {
    await api(`/positionen/${pid}`, { method: 'PATCH', body });
    melde('✓ Teilbetrag gespeichert', 'pos');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function vorabNettoSpeichern(feld) {
  const pid = feld.dataset.vorabNetto;
  const netto = String(feld.value ?? '').trim() === '' ? 0 : feldZahl(feld);
  if (netto == null || netto < 0) return;
  if (netto === 0) {
    state.vorabOffen.delete(Number(pid));
    return vorabPatch(pid, { vorab_netto: 0, vorab_betrag: 0, vorab_einheit: '' });
  }
  return vorabPatch(pid, { vorab_netto: netto, vorab_betrag: vorabBrutto(netto) });
}

async function vorabEntfernen(knopf) {
  const pid = Number(knopf.dataset.vorabEntfernen);
  state.vorabOffen.delete(pid);
  if (knopf.dataset.hat === '1') {
    return vorabPatch(pid, { vorab_netto: 0, vorab_betrag: 0, vorab_einheit: '' });
  }
  return zeichnen();
}

async function wegDirektSpeichern(knopf) {
  const eingaben = [...inhalt.querySelectorAll('[data-weg-betrag]')]
    .map(f => ({ einheit: f.dataset.wegBetrag, betrag: feldZahl(f) ?? 0 }))
    .filter(x => x.betrag > 0);
  if (!eingaben.length) {
    return melde('Trage mindestens eine NK-Summe ein', 'neg');
  }
  knopf.disabled = true;
  knopf.textContent = 'Übernehme …';
  const bestehende = new Map((state.daten.checkliste || []).map(k => [k.kostenart, k]));
  try {
    for (const { einheit, betrag } of eingaben) {
      const art = WEG_ART(einheit);
      const vorhanden = bestehende.get(art);
      if (vorhanden && vorhanden.position_id) {
        await api(`/positionen/${vorhanden.position_id}`,
                  { method: 'PATCH', body: { betrag } });
      } else {
        await api(`/zeitraeume/${zid}/positionen`, {
          method: 'POST',
          body: { kostenart: art, betrag, nur_einheit: einheit },
        });
      }
    }
    melde(`NK-Summe je Mieter übernommen · ${eingaben.length} ${
      eingaben.length === 1 ? 'Mieter' : 'Mieter'}`, 'pos');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = 'Werte je Mieter übernehmen';
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function positionEntfernen(knopf) {
  const art = knopf.dataset.art;
  const ja = await frage(`„${art}“ entfernen?`,
    'Betrag und Verteilung dieser Position werden gelöscht. Die Kostenart '
    + 'bleibt im Katalog der Immobilie stehen und lässt sich jederzeit neu '
    + 'erfassen. Hinterlegte Belege bleiben unangetastet.',
    { knopf: 'Entfernen', gefahr: true });
  if (!ja) return;
  knopf.disabled = true;
  try {
    await api(`/positionen/${knopf.dataset.entfernen}`, { method: 'DELETE' });
    melde(`„${art}“ entfernt`, '');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function entwurfBestaetigen(pid, knopf) {
  knopf.disabled = true;
  knopf.textContent = 'Bestätige …';
  try {
    await api(`/entwuerfe/kostenposition/${pid}/bestaetigen`, { method: 'POST' });
    melde('Position bestätigt', 'pos');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = '✓ Bestätigen';
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function entwurfVerwerfen(pid, art, knopf) {
  knopf.disabled = true;
  knopf.textContent = 'Setze zurück …';
  try {
    await api(`/entwuerfe/kostenposition/${pid}/verwerfen`, { method: 'POST' });
    melde(`„${art}“ zurück im Prüfmodus — der Beleg bleibt erhalten`, '');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = '↩ Zurück zum Prüfen';
    melde(String(fehler.message || fehler), 'neg');
  }
}

async function wiederOeffnen(knopf) {
  const ja = await frage('Zeitraum wieder öffnen?',
    'Der Zeitraum wird wieder bearbeitbar und taucht in Fristen und '
    + 'Erinnerungen erneut auf. Wer die Abrechnung schon bekommen hat, '
    + 'bekommt sie dadurch nicht noch einmal.', { knopf: 'Wieder öffnen' });
  if (!ja) return;
  knopf.disabled = true;
  try {
    const antwort = await api(`/zeitraeume/${zid}/oeffnen`, { method: 'POST' });
    const schon = antwort.bereits_versendet.length;
    melde(schon
      ? `Wieder geöffnet · ${schon} Partei(en) haben ihre Abrechnung bereits`
      : 'Wieder geöffnet', 'pos');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    melde(String(fehler.message || fehler), 'neg');
  }
}

function versandWahl(plan, rechnung) {
  const zeile = (p, marke, klasse, unter) => `
    <div class="vz">
      <span class="vn">${esc(p.partei)}
        <span class="vs">${esc(unter)}</span></span>
      <span class="marke vm ${klasse}">${marke}</span>
    </div>`;

  const bereit = plan.parteien.filter(p => p.versandbereit);
  const ohne = plan.parteien.filter(p => !p.versandbereit && !p.leerstand);
  const leer = plan.parteien.filter(p => p.leerstand);
  const mieter = bereit.length + ohne.length;

  const liste = [
    ...bereit.map(p => zeile(p, 'Mail', 'gut', p.adressen.join(' · '))),
    ...ohne.map(p => zeile(p, 'Post', 'post',
      'Keine Mailadresse — ausdrucken und schicken')),
    ...leer.map(p => zeile(p, 'Leerstand', '', 'Bleibt beim Eigentümer')),
  ].join('');

  const satz = mieter
    ? `${bereit.length} von ${mieter} ${mieter === 1 ? 'Mietpartei bekommt'
        : 'Mietparteien bekommen'} die Abrechnung als PDF per Mail.`
    : 'Es gibt keine Mietpartei zu beliefern — der Zeitraum lässt sich '
      + 'trotzdem abschließen.';

  // N314(g) — dieselbe Vorauszahlung-ohne-Partei-Lücke, hier noch vor dem
  // Versand: gerade jetzt lohnt der Hinweis am meisten, bevor die Abrechnung
  // verschickt wird, ohne dass diese Zahlung irgendwo ankommt.
  const namen = rechnung?.vorauszahlungen_ohne_partei;
  let ungeklaert = '';
  if (namen?.length) {
    const bekannt = Object.values(rechnung.parteien || {})
      .reduce((s, w) => s + (w.vorauszahlungen || 0), 0);
    const betrag = (rechnung.gesamt?.abschlaege || 0) - bekannt;
    ungeklaert = `<div class="weg-warn"><span class="ww-z">${eur(betrag)}</span>
        <span><b>${esc(namen.join(', '))}</b> — passt zu keiner Partei
        dieses Zeitraums und wird so an niemanden zugeordnet. Name in den
        Mieterstammdaten prüfen, bevor verschickt wird.</span>
      </div>`;
  }

  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg vdlg';
    dlg.innerHTML = `
      <div class="dt">Abrechnung abschließen</div>
      <p>${esc(plan.zeitraum)} · ${esc(satz)}</p>
      ${ungeklaert}
      <div class="vliste">${liste}</div>
      ${bereit.length ? `<button class="btn"
        data-wahl="senden">Abschließen und verschicken</button>` : ''}
      <button class="btn leise" data-wahl="nur">Nur abschließen, nicht
        verschicken</button>
      <button class="btn leise" data-nein>Abbrechen</button>`;
    document.body.appendChild(dlg);
    dlg.addEventListener('close', () => dlg.remove());
    dlg.addEventListener('cancel', () => fertig(null));
    dlg.addEventListener('click', e => {
      const knopf = e.target.closest('[data-wahl]');
      if (knopf) { fertig(knopf.dataset.wahl); dlg.close(); }
      else if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); }
    });
    dlg.showModal();
  });
}

async function abschliessen(knopf) {
  const uebergehen = document.getElementById('uebergehen')?.checked || false;
  knopf.disabled = true;
  knopf.textContent = 'Prüfe Empfänger …';

  let plan, rechnung;
  try {
    plan = await api(`/zeitraeume/${zid}/versand`);
    // N314(g) — `vorauszahlungen_ohne_partei` steckt nur in `/abrechnung`,
    // nicht in `/versand`; separat geholt, damit der Hinweis auch hier steht.
    rechnung = await einmal(`/zeitraeume/${zid}/abrechnung`).catch(() => null);
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = 'Abrechnungen erstellen und versenden';
    melde(String(fehler.message || fehler), 'neg');
    return;
  }

  const weg = await versandWahl(plan, rechnung);

  if (!weg) {
    knopf.disabled = false;
    knopf.textContent = 'Abrechnungen erstellen und versenden';
    return;
  }

  knopf.textContent = weg === 'senden' ? 'Verschicke …' : 'Schließe ab …';
  try {
    const antwort = await api(`/zeitraeume/${zid}/abschliessen`, {
      method: 'POST', body: { versenden: weg === 'senden',
                              offene_uebergehen: uebergehen },
    });
    melde(antwort.versendet.length
      ? `${antwort.versendet.length} Abrechnung(en) verschickt an ${antwort.versendet.join(', ')}`
      : 'Zeitraum abgeschlossen — versendet wurde nichts.',
      antwort.versendet.length ? 'pos' : '');
    await laden();
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = 'Abrechnungen erstellen und versenden';
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* ---------- Laden ------------------------------------------------------ */

/* N295 — leerer Zustand mit Weg heraus. Die Kopfzeile stand sonst dauerhaft
   auf „wird geladen …", obwohl längst feststeht, dass nichts mehr kommt. */
function leerZeigen(gross) {
  inhalt.innerHTML = leerHtml(gross, '',
    { text: 'Zu den Abrechnungen', href: 'nebenkosten.html' });
  const sub = document.getElementById('sub');
  if (sub) sub.textContent = '';
}

export async function laden() {
  // N369 — jeder Ladevorgang startet mit frischem Anfrage-Bündel: innerhalb
  // eines Laufs wird dieselbe URL nur einmal geholt, über Läufe hinweg nie
  // wiederverwendet.
  neuerLauf();
  if (!zid) {
    // N295 — eine Sackgasse ohne Ausweg war das vorher: weisse Karte, ein
    // Satz, und der Rest der Seite leer. Der gemeinsame Baustein bringt den
    // Weg zurück mit.
    leerZeigen('Kein Zeitraum gewählt');
    return;
  }
  try {
    state.setDaten(await api(`/zeitraeume/${zid}`));
  } catch {
    leerZeigen('Zeitraum nicht gefunden');
    return;
  }
  try {
    state.setSchluessel(await api(`/zeitraeume/${zid}/schluessel`));
  } catch {
    state.setSchluessel(null);
  }
  state.setLeerstaende(new Set(
    (state.schluessel?.schluessel || []).flatMap(s => s.leerstand || [])));
  // N280 — der WEG-Stand entscheidet, ob dieser Zeitraum die Checkliste zeigt
  // oder die Dateiübernahme.
  await wegLaden();
  try {
    state.setAnhaenger(await api(`/dokumente/anhaenger/${zid}`));
  } catch {
    state.setAnhaenger(null);
  }
  try {
    state.setAblesungMaske(await api(`/zeitraeume/${zid}/ablesung`));
  } catch {
    state.setAblesungMaske(null);
  }
  // N213 — Öl/Warmwasser nur im Laufer-Modell.
  state.setHeizoelKosten(0);
  state.setWwKosten(0);
  const { istLaufer } = await import('./modell.js');
  if (istLaufer()) {
    try {
      const b = await einmal(`/objekte/${encodeURIComponent(state.daten.objekt)}`
        + `/heizoel/bewertung?zeitraum_id=${zid}`);
      state.setHeizoelKosten(b?.verbrauch_kosten || 0);
      const zl = state.ablesungMaske?.zaehler || [];
      const wwH = zl.find(z => wasserArt(z) === 'Warmwasser' && !z.hauptzaehler_id);
      const vol = wwH?.verbrauch != null ? wwH.verbrauch
        : zl.filter(z => wasserArt(z) === 'Warmwasser' && z.hauptzaehler_id)
            .reduce((su, z) => su + (z.verbrauch || 0), 0);
      const sp = state.heizoelKosten > 0 ? await einmal(
        `/objekte/${encodeURIComponent(state.daten.objekt)}/waerme/split`
        + `?oel_kosten=${state.heizoelKosten}&oel_liter=${b?.verbrauch_liter || 0}`
        + `&ww_volumen_m3=${vol}`).catch(() => null) : null;
      state.setWwKosten(sp?.ww_kosten || 0);
      await warmwasserBetragSichern();
    } catch { state.setHeizoelKosten(0); state.setWwKosten(0); }
  }
  // N213 — HKV nur im Laufer-Modell.
  state.setHeizverteiler([]);
  if (istLaufer()) {
    try {
      const hv = await einmal(`/objekte/${encodeURIComponent(state.daten.objekt)}/heizverteiler`);
      state.setHeizverteiler(hv?.heizverteiler || []);
    } catch { state.setHeizverteiler([]); }
  }
  await deckungLaden();
  try {
    const o = await api(`/objekte/${state.daten.objekt}`);
    state.setObjektEinheiten((o.einheiten || [])
      .filter(e => typeof e === 'string' || e.nk_abrechnung !== false)
      .map(e => typeof e === 'string'
        ? e : (e.bezeichnung || e.name || e.einheit || '')).filter(Boolean));
  } catch {
    state.setObjektEinheiten([]);
  }
  state.setEautoZug(null);
  if ((state.ablesungMaske?.zaehler || []).some(z => z.eauto)) {
    try {
      state.setEautoZug(await api(`/zeitraeume/${zid}/eauto`, { method: 'POST' }));
      if (state.eautoZug?.gespeichert) {
        state.setAblesungMaske(await api(`/zeitraeume/${zid}/ablesung`));
      }
    } catch (fehler) {
      state.setEautoZug({ ok: false, hinweis: String(fehler.message || fehler),
                          nutzer: [] });
    }
  }
  state.setStromketteDaten(
    (istLaufer() && (state.daten.checkliste || []).some(istStromPos))
      ? await api(`/zeitraeume/${zid}/stromkette`).catch(() => null) : null);
  state.setChipMap(baueChipMap());
  const jahrLabel = state.daten.jahr || Number((state.daten.ende || '').slice(0, 4)) || '';
  // N327 — "Abrechnungszeitraum" lief mit dem neuen Kopfzeilen-Fristchip und
  // den Kopfzeilen-Aktionen (Suche/„…") auf dem iPhone auf "Abrechnungszeitra…"
  // zusammen; der Zeitraum selbst steht ohnehin schon im Untertitel darunter.
  titel.textContent = `Zeitraum ${jahrLabel}`.trim();
  sub.textContent = `${state.daten.label} · ${state.daten.objekt_name}`;
  fristChipSetzen();
  await zeichnen();
}

/* ---------- Event-Delegation ------------------------------------------ */

export function initHandlers() {
  document.getElementById('back').addEventListener('click', () => history.length > 1
    ? history.back() : location.href = 'index.html');

  // Rollen: sieben Einträge sind hoch — Feld hochscrollen, wenn Platz fehlt.
  inhalt.addEventListener('click', e => {
    const knopf = e.target.closest('.vt .auswahl-knopf');
    if (!knopf || knopf.getAttribute('aria-expanded') === 'true') return;
    const noetig = (state.schluessel?.schluessel.length || 7) * 44 + 120;
    if (window.innerHeight - knopf.getBoundingClientRect().bottom < noetig) {
      rolleUnterDieKopfzeile(knopf, 150);
    }
  }, true);

  // Gewichts-focusout speichert die Verteilung.
  inhalt.addEventListener('focusout', e => {
    // N353 — Datumsfeld verlassen: jetzt sofort speichern, ohne die kurze
    // Tipp-Ruhe abzuwarten (die gibt es nur, damit `change` beim Tippen der
    // Jahreszahl nicht zwischendurch feuert).
    if (e.target.matches?.('[data-anfangdatum],[data-enddatum]')) {
      datumGeaendert(e.target, true);
      return;
    }
    const feld = e.target.closest?.('[data-gewicht]');
    if (!feld) return;
    const vt = feld.closest('.vt');
    if (!vt || vt.contains(e.relatedTarget)) return;
    verteilungAutoSpeichern(vt);
  });

  // Prozente beim Tippen mitrechnen.
  inhalt.addEventListener('input', e => {
    if (e.target.matches('[data-vorab-netto]')) {
      const netto = feldZahl(e.target) || 0;
      const ziel = e.target.closest('.vorab')?.querySelector('[data-vorab-brutto]');
      if (ziel) ziel.textContent = bruttoAnzeige(netto);
      return;
    }
    if (!e.target.matches('[data-gewicht]')) return;
    const vt = e.target.closest('.vt');
    const felder = [...vt.querySelectorAll('[data-gewicht]')];
    const summe = felder.reduce((s, f) => s + (feldZahl(f) || 0), 0);
    const rest = Number(vt.dataset.rest || 0);
    felder.forEach(f => {
      const w = feldZahl(f) || 0;
      const ziel = f.parentElement.querySelector('[data-anteil]');
      if (ziel) ziel.textContent = prozentText(w, summe);
      const euroZiel = f.parentElement.querySelector('[data-euro]');
      if (euroZiel) euroZiel.textContent = eur(summe > 0 ? rest * w / summe : 0);
    });
  });

  // change: die vielen Feld-Speicherwege.
  inhalt.addEventListener('change', e => {
    if (e.target.id === 'uebergehen') {
      const knopf = document.getElementById('abschlussKnopf');
      if (knopf) knopf.disabled = !e.target.checked;
      return;
    }
    if (e.target.matches('[data-konf-sicht]')) return konfSichtSetzen(e.target);
    if (e.target.matches('[data-betrag]')) betragSpeichern(e.target);
    if (e.target.matches('[data-anbieter]')) anbieterSpeichern(e.target);
    if (e.target.matches('[data-endstand]')) endstandSpeichern(e.target);
    if (e.target.matches('[data-anfangstand]')) anfangstandSpeichern(e.target);
    if (e.target.matches('[data-anfangdatum],[data-enddatum]')) datumGeaendert(e.target);
    if (e.target.matches('[data-strom-jahr]')) stromJahreswertSpeichern(e.target);
    if (e.target.matches('[data-strom-rolle-set]')) stromRolleSetzen(e.target);
    if (e.target.matches('[data-strom-menge]')) stromMengeSpeichern(e.target);
    if (e.target.matches('[data-sk-anteil]')) stromAnteilSpeichern(e.target);
    if (e.target.matches('[data-wasser-pid],[data-wasser-ka]')) wasserBetragSpeichern(e.target);
    if (e.target.matches('[data-wasser-rechnung]')) {
      wasserRechnungsmengeSpeichern(e.target);
    }
    if (e.target.matches('[data-kostenart-pos]')) kostenartWechseln(e.target);
    if (e.target.matches('[data-kostenart-neu]')) kostenartNeu(e.target);
    if (e.target.matches('[data-vorab-netto]')) vorabNettoSpeichern(e.target);
    if (e.target.matches('[data-vorab-s35]')) {
      vorabPatch(e.target.dataset.vorabS35, { vorab_s35: e.target.checked });
    }
  });

  // click: die zentrale Dispatch-Zeile.
  inhalt.addEventListener('click', async e => {
    const tab = e.target.closest('[data-tab]');
    if (tab) { state.setAnsicht(tab.dataset.tab); return zeichnen(); }

    const sort = e.target.closest('[data-sort]');
    if (sort) { state.setSortierung(sort.dataset.sort); return zeichnen(); }
    if (e.target.closest('[data-pos-konfig]')) return konfigModusUmschalten();
    const kOpt = e.target.closest('[data-konf-opt]');
    if (kOpt) return konfOptSetzen(kOpt);
    const kS35 = e.target.closest('[data-konf-s35]');
    if (kS35) return konfS35Setzen(kS35);

    // N361 — Einheiten-Gruppe in der Jahreswert-Tabelle auf/zu.
    const ztE = e.target.closest('[data-zt-einheit]');
    if (ztE) {
      const name = ztE.dataset.ztEinheit;
      const gruppe = ztE.closest('.zt-gruppe');
      const jetztAuf = !gruppe.classList.contains('offen');
      if (jetztAuf) state.zaehlerEinheitZu.delete(name);
      else state.zaehlerEinheitZu.add(name);
      gruppe.classList.toggle('offen', jetztAuf);
      ztE.setAttribute('aria-expanded', String(jetztAuf));
      return;
    }
    const zt = e.target.closest('[data-zu-toggle]');
    if (zt) {
      const panel = zt.closest('.zu-panel');
      const block = panel?.dataset.zuBlock || '';
      const jetztOffen = !panel.classList.contains('offen');
      if (jetztOffen) state.zaehlerOffen.add(block); else state.zaehlerOffen.delete(block);
      panel.classList.toggle('offen', jetztOffen);
      zt.setAttribute('aria-expanded', String(jetztOffen));
      return;
    }
    const eToggle = e.target.closest('[data-einheit-toggle]');
    if (eToggle) return einheitToggle(eToggle);

    const dUeb = e.target.closest('[data-datum-uebernehmen]');
    if (dUeb) return datumUebernehmen(dUeb);

    const abschluss = e.target.closest('[data-abschluss]');
    if (abschluss) return abschliessen(abschluss);

    const oeffnen = e.target.closest('[data-oeffnen]');
    if (oeffnen) return wiederOeffnen(oeffnen);

    const ableiten = e.target.closest('[data-ableiten]');
    if (ableiten) return verteilungAbleiten(ableiten);


    const einzel = e.target.closest('[data-einzel-einheit]');
    if (einzel) return einzelSetzen(einzel.dataset.einzelPid,
                                    einzel.dataset.einzelEinheit);

    const vorabAuf = e.target.closest('[data-vorab-oeffnen]');
    if (vorabAuf) {
      state.vorabOffen.add(Number(vorabAuf.dataset.vorabOeffnen));
      return zeichnen();
    }
    const vorabE = e.target.closest('[data-vorab-einheit-pid]');
    if (vorabE) return vorabPatch(vorabE.dataset.vorabEinheitPid,
                                  { vorab_einheit: vorabE.dataset.vorabEinheit });
    const vorabWeg = e.target.closest('[data-vorab-entfernen]');
    if (vorabWeg) return vorabEntfernen(vorabWeg);

    const fertig = e.target.closest('[data-fertig]');
    if (fertig) { state.offen.delete(Number(fertig.dataset.fertig)); return zeichnen(); }

    const wegSpeichern = e.target.closest('[data-weg-speichern]');
    if (wegSpeichern) return wegDirektSpeichern(wegSpeichern);

    const entwJa = e.target.closest('[data-entwurf-ja]');
    if (entwJa) return entwurfBestaetigen(entwJa.dataset.entwurfJa, entwJa);

    const entwNein = e.target.closest('[data-entwurf-nein]');
    if (entwNein) return entwurfVerwerfen(entwNein.dataset.entwurfNein,
                                          entwNein.dataset.art, entwNein);

    const entfernen = e.target.closest('[data-entfernen]');
    if (entfernen) return positionEntfernen(entfernen);

    const auf = e.target.closest('[data-auf]');
    if (auf) {
      if (auf.hasAttribute('data-noexpand')) return;
      const i = Number(auf.dataset.auf);
      state.offen.has(i) ? state.offen.delete(i) : state.offen.add(i);
      return zeichnen();
    }

    const anhZeigen = e.target.closest('[data-anh-zeigen]');
    if (anhZeigen) { e.preventDefault(); return anhaengerFenster(anhZeigen.dataset.anhZeigen); }

    const anhaengenKnopf = e.target.closest('[data-anhaengen]');
    if (anhaengenKnopf) return anhaengen(anhaengenKnopf.dataset.anhaengen);

    const anhWeg = e.target.closest('[data-anh-loesen]');
    if (anhWeg) { e.preventDefault();
      return anhaengerEntfernen(anhWeg.dataset.anhLoesen, anhWeg.dataset.was); }

    const hoAdd = e.target.closest('[data-heizoel-add]');
    if (hoAdd) return heizoelHinzufuegen(hoAdd);
    const hoWeg = e.target.closest('[data-heizoel-weg]');
    if (hoWeg) return heizoelEntfernen(hoWeg.dataset.heizoelWeg, hoWeg.dataset.was);
    // N364 — Abschluss-Haken für Heizöl: der Nutzer bestätigt, dass alle
    // Lieferungen und der Zähler-Endstand drin sind. Für Öl gibt es keinen
    // Beleg, der die Periode abschließt — nur er weiß, wann die Erfassung
    // vollständig ist. Beim ersten Haken existiert die Sammelposition oft noch
    // gar nicht, dann wird sie angelegt (mit Betrag 0, siehe `abschlussHtml`).
    const hoFertig = e.target.closest('[data-heizoel-fertig]');
    if (hoFertig) {
      const an = hoFertig.checked;
      try {
        let pid = hoFertig.dataset.pid;
        if (!pid) {
          const neu = await api(`/zeitraeume/${state.zid}/positionen`, {
            method: 'POST', body: { kostenart: hoFertig.dataset.art, betrag: 0 } });
          pid = neu.id;
        }
        await api(`/positionen/${pid}`, { method: 'PATCH',
          body: { bestaetigt: an } });
        await laden();
      } catch (fehler) {
        hoFertig.checked = !an;
        melde(String(fehler.message || fehler), 'neg');
      }
      return;
    }
    // N358 — Verteilerschlüssel für Heizwärme/Warmwasser direkt in ihrer
    // Ansicht (dieselbe Wirkung wie der Wähler in der Aufteilung, den diese
    // beiden Karten nicht zeigen, weil ihr Rumpf die Öl-Ansicht ist).
    const hsch = e.target.closest('[data-heiz-schluessel]');
    if (hsch) {
      try {
        await api(`/positionen/${hsch.dataset.pid}`, { method: 'PATCH',
          body: { schluessel: hsch.dataset.heizSchluessel, nur_einheit: '' } });
        await laden();
      } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
      return;
    }
    const wsch = e.target.closest('[data-wasser-schluessel]');
    if (wsch) {
      state.setWasserSchluessel(wsch.dataset.wasserSchluessel);
      const box = wsch.closest('[data-wasser-inline]');
      if (box) return fuelleWasserInline(box);
      return zeichnen();
    }
    const belegWeg = e.target.closest('[data-beleg-loesen]');
    if (belegWeg) { e.preventDefault(); return belegLoesen(belegWeg.dataset.belegLoesen); }
    const stBelegWeg = e.target.closest('[data-strom-beleg-weg]');
    if (stBelegWeg) { e.preventDefault();
      return stromBelegLoesen(stBelegWeg.dataset.stromBelegWeg,
                              stBelegWeg.dataset.stromBelegName); }
    const gmSpeichern = e.target.closest('[data-geeichte-menge-speichern]');
    if (gmSpeichern) { e.preventDefault(); return geeichteMengeSpeichern(gmSpeichern); }
    const wLeer = e.target.closest('[data-wasser-leeren]');
    if (wLeer) { e.preventDefault(); return wasserPositionLeeren(); }
    const herk = e.target.closest('[data-herkunft]');
    if (herk) return stromHerkunftSetzen(herk);
    const stAdd = e.target.closest('[data-strom-add]');
    if (stAdd) return stromZaehlerAnlegen(stAdd);
    const stWeg = e.target.closest('[data-strom-weg]');
    if (stWeg) return stromZaehlerEntfernen(stWeg);
    const gAdd = e.target.closest('[data-garten-anlegen]');
    if (gAdd) return gartenAnlegen(gAdd);
    const umb = e.target.closest('[data-zaehler-umbenennen]');
    if (umb) { e.preventDefault(); e.stopPropagation();
      return zaehlerUmbenennen(umb.dataset.zaehlerUmbenennen); }

    const beleg = e.target.closest('[data-beleg]');
    if (beleg) {
      e.preventDefault();
      // N245 — der Ablagepfad kommt bevorzugt aus `data-pfad` (Muster aus N232,
      // wie im Dokumente-Baum und in der Eintrags-Detailansicht). Der Rückfall
      // auf `title` hält die Stromketten-Belege am Laufen, die ihn dort tragen;
      // die Anhänger-Chips können das nicht, weil ihr `title` die Erklärung
      // „Infobeleg — zählt nicht als Kosten" trägt.
      // N288 — die übrigen Belege desselben Kastens gehen mit: im Fenster
      // lässt sich dann blättern, statt für jeden Beleg zurückzumüssen.
      belegAnsehen(`/api/dokumente/${beleg.dataset.beleg}/inhalt`,
                   beleg.dataset.name
                   || beleg.textContent.replace(/^PDF · /, '').trim(),
                   beleg.dataset.pfad || beleg.getAttribute('title') || '',
                   Number(beleg.dataset.beleg), belegGeschwister(beleg));
      return;
    }

    // N280 — WEG-Abrechnung: Schalter, Aufnahme, Vorauszahlungs-Abschnitte.
    const wSchalter = e.target.closest('[data-weg-schalter]');
    if (wSchalter) { e.preventDefault();
      return wegSchalten(wSchalter.dataset.wegSchalter === '1'); }
    const wScan = e.target.closest('[data-weg-scan]');
    if (wScan) {
      e.preventDefault();
      state.setScanZiel({ weg: true });
      document.getElementById('scanFeld').click();
      return;
    }
    if (e.target.closest('[data-weg-vz-neu]')) { e.preventDefault();
      return vorauszahlungNeu(); }
    const wVzB = e.target.closest('[data-weg-vz-bearbeiten]');
    if (wVzB) { e.preventDefault();
      return vorauszahlungBearbeiten(wVzB.dataset.wegVzBearbeiten); }
    const wVzW = e.target.closest('[data-weg-vz-weg]');
    if (wVzW) { e.preventDefault();
      return vorauszahlungEntfernen(wVzW.dataset.wegVzWeg); }

    const scan = e.target.closest('[data-scan]');
    if (scan) {
      state.setScanZiel({ kostenart: scan.dataset.scan, knopf: scan });
      document.getElementById('scanFeld').click();
      return;
    }

    const ablage = e.target.closest('[data-ablage]');
    if (ablage) {
      const jahr = Number((state.daten.ende || '').slice(0, 4)) || new Date().getFullYear();
      const p = new URLSearchParams({
        objekt: state.daten.objekt, kostenart: ablage.dataset.ablage,
        zuordnenZeitraum: String(state.daten.id), jahr: String(jahr),
        zurueck: location.pathname + location.search,
      });
      location.href = 'eingang.html?' + p.toString();
      return;
    }
  });

  // Scan-Feld: nach Aufnahme Beleg direkt an der Position ablegen.
  document.getElementById('scanFeld').addEventListener('change', async e => {
    const feld = e.target;
    const dateien = [...feld.files];
    feld.value = '';
    const ziel = state.scanZiel;
    state.setScanZiel(null);
    if (!dateien.length || !ziel) return;

    // N280 — die WEG-Abrechnung nimmt denselben Eingang (ein Dateifeld für die
    // ganze Seite), läuft danach aber ihren eigenen Weg: sie wird gelesen und
    // als Ganzes übernommen, nicht als einzelner Beleg verbucht.
    if (ziel.weg) return wegAufnehmen(dateien);

    // N268 — der Anhänger-Weg startet aus einem Dialog, der beim Scannen schon
    // wieder zu ist: dort gibt es keinen Knopf zum Ausgrauen. Ein Blindobjekt
    // statt eines `if` an fünf Stellen — der Ablauf bleibt genau einer.
    const knopf = ziel.knopf
      || { disabled: false, querySelector: () => null };
    const beschriftung = knopf.querySelector('.st');
    const urText = beschriftung ? beschriftung.textContent : '';
    knopf.disabled = true;
    if (beschriftung) beschriftung.textContent = 'Verarbeite …';

    const jahr = Number((state.daten.ende || '').slice(0, 4)) || new Date().getFullYear();
    // N254 — Griff auf die Wartedecke; das `finally` unten nimmt sie in JEDEM
    // Fall wieder weg, auch bei einem Fehler. Eine hängende Vollbild-Sperre
    // wäre schlimmer als die Lücke, die sie schliesst.
    let deckeWeg = null;

    try {
      // N250 — zwei Schritte statt einem: erst aufnehmen und auslesen, dann
      // dem Nutzer den vorgeschlagenen Dateinamen zeigen, dann ablegen. Auf
      // dem Telefon ist das die einzige Gelegenheit, einen falsch erkannten
      // Namen zu korrigieren — danach liegt die Datei benannt in der Cloud.
      // N254 — die Decke über der Wartezeit. Sie wird erst NACH dem Zuschnitt
      // gelegt (vorher liegt das Zuschnitt-Fenster oben) und im `finally`
      // sicher wieder abgeräumt, auch wenn etwas schiefgeht.
      const { analyseDecke } = await import('../belegbestaetigung.js');
      const vorbereitet = await belegVorbereiten(dateien, {
        objekt: state.daten.objekt, kategorie: 'Nebenkosten',
        kostenart: ziel.kostenart, jahr, zeitraumId: state.daten.id,
        titel: ziel.kostenart,
        // N263/N280 — die gemeinte Eingabemaske nennen; gibt es für
        // „nebenkosten" noch keine Feldzuordnung, kommt nichts zurück und alles
        // bleibt wie zuvor. Rein additiv.
        bereich: 'nebenkosten',
        // N255 — die Auslese steckt in `vorbereitet.ki` und wird von dort
        // weitergereicht. Kein zweiter `/erkennen`-Aufruf auf dieselbe Datei;
        // der kostete den Nutzer früher doppelt Tokens für denselben Wert.
      }, () => { deckeWeg = analyseDecke(); });
      if (!vorbereitet) {
        knopf.disabled = false;
        if (beschriftung) beschriftung.textContent = urText;
        return;
      }
      const { belegBestaetigen } = await import('../belegbestaetigung.js');
      // N283(b) — was danach passiert, steht jetzt IN der Maske statt als Toast
      // dahinter: dass ein betragloser Beleg als Infobeleg an seine Zeile geht
      // (N268). Vor dem Bestätigen ist das bedienbar — das Betragsfeld steht
      // direkt darüber —, hinterher ist es nur noch eine Mitteilung über eine
      // Entscheidung, die niemand mehr treffen kann. Der Knopf sagt dazu, was
      // er tut, statt überall „Ablegen" zu heissen.
      const entscheidung = await belegBestaetigen(vorbereitet, deckeWeg, {
        knopf: ziel.anhaengerFuer ? 'Anhängen' : 'Ablegen',
        hinweis: ziel.anhaengerFuer
          ? { text: `Ohne Betrag wird der Beleg als Infobeleg an `
              + `„${ziel.anhaengerFuer}“ gehängt — mit Betrag zählt er als `
              + `Kostenposition dieser Zeile.` }
          : null,
      });
      if (!entscheidung) {                       // abgebrochen — nichts abgelegt
        knopf.disabled = false;
        if (beschriftung) beschriftung.textContent = urText;
        return;
      }
      // N280 — ab hier läuft der Knopf durch GENAU denselben Abschluss wie der
      // Drop auf die Karte (`belege.js`): Wasser-Rückfrage, Ablage, gelernter
      // Anbieter, Verbuchung. N267 — der Betrag aus der Maske schlägt die
      // Erkennung; er steht im Dateinamen, am Beleg und in der Kostenposition.
      const ergebnis = await belegAbschluss({
        kostenart: ziel.kostenart, vorbereitet, entscheidung });
      if (!ergebnis) {
        knopf.disabled = false;
        if (beschriftung) beschriftung.textContent = urText;
        return;
      }
      const seiten = ergebnis.seiten || 1;
      if (beschriftung) {
        beschriftung.textContent = `✓ ${seiten} Seite${seiten > 1 ? 'n' : ''}`
          + (ergebnis.groesse ? ` · ${lesbareGroesse(ergebnis.groesse)}` : '');
      }
      const uebernommen = ergebnis.betrag != null;
      // N268 — aus dem „Beleg anhängen"-Dialog heraus gescannt: trägt der Beleg
      // keinen Betrag, ist er ein Infobeleg und wird als Anhänger gesetzt —
      // genau das, wofür der Nutzer den Dialog geöffnet hat. Mit Betrag bleibt
      // es eine gewöhnliche Kostenposition; ein Anhänger daneben wäre dieselbe
      // Datei zweimal am selben Thema.
      if (ziel.anhaengerFuer && !uebernommen) {
        await api(`/dokumente/${ergebnis.id}/anhaenger`, {
          method: 'POST',
          body: { zeitraum_id: Number(state.zid), kostenart: ziel.anhaengerFuer },
        }).catch(() => {});
      }
      // N283(b) — der Toast „kein Betrag automatisch erkannt, bitte von Hand
      // eintragen" stand hier bis eben ein zweites Mal: die Maske sagt genau
      // das schon, und zwar an der Stelle, an der sich der Betrag auch
      // eintragen lässt („Betrag eintragen"). Ein Hinweis hinterher, den
      // niemand mehr befolgen kann, ist keiner.
      await laden();
    } catch (fehler) {
      if (beschriftung) beschriftung.textContent = 'Fehlgeschlagen';
      knopf.disabled = false;
      melde(String(fehler.message || fehler), 'neg');
    } finally {
      if (deckeWeg) deckeWeg();
    }
  });

  // Drag&Drop-Overlay pro Zeile initialisieren.
  initBelegDrop();
}
