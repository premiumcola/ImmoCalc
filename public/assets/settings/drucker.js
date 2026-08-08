/* N275 — Drucker im Haus: Name, IP, Port und Standort selbst pflegen.

   Warum per IP statt über einen Druckdienst: der Weg über CUPS legt die
   Aufträge zwar sauber in die Warteschlange, bringt sie aber nicht bis zum
   Gerät. Direkt auf Port 9100 kommt der Ausdruck heraus. Deshalb steht hier
   die Adresse des Geräts, nicht die eines Zwischendienstes.

   Der Prüfknopf öffnet nur eine TCP-Verbindung und schliesst sie wieder — er
   druckt nichts. Papier und Toner gehören dem Nutzer. */
import { api, esc, frage } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';

const VORGABE_PORT = 9100;
/* Dieselbe Form, die der Server erlaubt (`drucker.py::pruefe_ziel`): nur was
   IPv4 oder Hostname sein kann. Hier steht sie nur, damit die Absage sofort
   kommt statt nach einer abgewiesenen Anfrage — massgeblich bleibt der
   Server. */
const ADRESSE = /^[A-Za-z0-9]([A-Za-z0-9.\-]{0,60}[A-Za-z0-9])?$/;

let dlg, formDlg, form, listeEl, meldungEl, formMeldungEl;
let statusEl, ikonEl, formTitelEl;
let drucker = [];
/* Name des Eintrags, der gerade geändert wird — null heisst „neu anlegen". */
let bearbeitet = null;
/* Ergebnis des letzten Prüfens je Drucker: true/false. Bewusst nicht
   gespeichert — Erreichbarkeit ist ein Momentwert, kein Stammdatum. */
const erreichbar = new Map();

function zeile(d) {
  const stand = erreichbar.get(d.name);
  const punkt = stand === true ? ' gut' : stand === false ? ' schlecht' : '';
  const pruefText = stand === true ? 'Erreichbar'
    : stand === false ? 'Nicht erreichbar' : 'Erreichbar?';
  return `<div class="drk">
    <div class="drk-kopf">
      <span class="drk-punkt${punkt}"></span>
      <span class="drk-n">${esc(d.name)}</span>
    </div>
    <span class="drk-o">${d.standort ? esc(d.standort) + ' · ' : ''}${esc(d.ip)}:${d.port}</span>
    <div class="drk-akt">
      <button type="button" class="drk-pruef${punkt}" data-pruefen="${esc(d.name)}">${pruefText}</button>
      <button type="button" class="drk-b" data-bearbeiten="${esc(d.name)}"
              aria-label="${esc(d.name)} bearbeiten" title="Bearbeiten">✎</button>
      <button type="button" class="drk-b" data-weg="${esc(d.name)}"
              aria-label="${esc(d.name)} entfernen" title="Entfernen">×</button>
    </div>
  </div>`;
}

function zeichne() {
  listeEl.innerHTML = drucker.length
    ? drucker.map(zeile).join('')
    : `<div class="empty">Noch kein Drucker eingetragen.<br>
         Mit <b>＋</b> oben rechts einen anlegen — Name und IP genügen.</div>`;
}

/* Statuszeile und Kachelfarbe. „Grün" nur, wenn wirklich einer gepflegt ist —
   die Warteschlangen eines Druckdienstes zählen hier nicht, die kann man auf
   dieser Seite nicht bearbeiten. */
export async function druckerLaden() {
  try {
    const daten = await api('/drucker');
    const eigene = daten.quelle === 'eigene' ? (daten.drucker || []) : [];
    drucker = eigene;
    if (eigene.length) {
      const orte = eigene.map(d => d.standort || d.name).join(', ');
      statusEl.textContent = `${eigene.length} ${eigene.length === 1 ? 'Gerät' : 'Geräte'} · ${orte}`;
    } else if ((daten.drucker || []).length) {
      statusEl.textContent = 'Zurzeit über den Druckdienst';
    } else {
      statusEl.textContent = 'Noch keiner eingetragen';
    }
    ikonEl.className = 'ic' + (eigene.length ? ' aktiv' : '');
  } catch {
    statusEl.textContent = 'Status nicht abrufbar';
  }
  if (listeEl) zeichne();
}

/* Anlegen, Ändern und Entfernen sind derselbe Vorgang: die vollständige
   Liste geht an den Server, er prüft jede Adresse vor dem Speichern. */
async function sichern(liste) {
  const antwort = await api('/drucker', { method: 'PUT', body: liste });
  drucker = antwort.drucker || [];
  zeichne();
  await druckerLaden();
}

function formOeffnen(d) {
  bearbeitet = d ? d.name : null;
  formTitelEl.textContent = d ? 'Drucker ändern' : 'Drucker anlegen';
  document.getElementById('drkName').value = d ? d.name : '';
  document.getElementById('drkIp').value = d ? d.ip : '';
  document.getElementById('drkPort').value = d ? d.port : VORGABE_PORT;
  document.getElementById('drkOrt').value = d ? d.standort || '' : '';
  meldungWeg(formMeldungEl);
  formDlg.showModal();
  document.getElementById('drkName').focus();
}

export function druckerInit() {
  dlg = document.getElementById('druckerDlg');
  formDlg = document.getElementById('druckerFormDlg');
  form = document.getElementById('druckerForm');
  listeEl = document.getElementById('druckerListe');
  meldungEl = document.getElementById('druckerMeldung');
  formMeldungEl = document.getElementById('druckerFormMeldung');
  formTitelEl = document.getElementById('druckerFormTitel');
  statusEl = document.getElementById('druckerStatus');
  ikonEl = document.getElementById('druckerIkon');

  document.getElementById('druckerRow').addEventListener('click', () => {
    meldungWeg(meldungEl);
    zeichne();
    dlg.showModal();
  });

  document.getElementById('druckerNeu').addEventListener('click',
    () => formOeffnen(null));

  listeEl.addEventListener('click', async e => {
    const pruefen = e.target.closest('[data-pruefen]');
    const aendern = e.target.closest('[data-bearbeiten]');
    const weg = e.target.closest('[data-weg]');

    if (aendern) {
      const d = drucker.find(x => x.name === aendern.dataset.bearbeiten);
      if (d) formOeffnen(d);
      return;
    }

    if (weg) {
      const name = weg.dataset.weg;
      const ok = await frage('Drucker entfernen',
        `„${name}" verschwindet aus der Liste. Am Gerät selbst ändert das nichts.`,
        { knopf: 'Entfernen', gefahr: true });
      if (!ok) return;
      meldungWeg(meldungEl);
      try {
        await sichern(drucker.filter(x => x.name !== name)
          .map(({ name: n, ip, port, standort }) => ({ name: n, ip, port, standort })));
      } catch (fehler) {
        feldmeldung(meldungEl, String(fehler.message || fehler));
      }
      return;
    }

    if (pruefen) {
      const name = pruefen.dataset.pruefen;
      pruefen.disabled = true;
      pruefen.textContent = 'Prüfe …';
      meldungWeg(meldungEl);
      try {
        const antwort = await api(`/drucker/${encodeURIComponent(name)}/pruefen`,
                                  { method: 'POST' });
        /* Das Ergebnis steht danach am Knopf und am Punkt — kein zusätzliches
           Banner, das dieselbe Auskunft ein zweites Mal gibt. */
        erreichbar.set(name, !!antwort.erreichbar);
      } catch (fehler) {
        erreichbar.set(name, false);
        feldmeldung(meldungEl, String(fehler.message || fehler));
      } finally {
        zeichne();
      }
    }
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const knopf = document.getElementById('drkSpeichern');
    if (knopf.disabled) return;
    const eintrag = {
      name: document.getElementById('drkName').value.trim(),
      ip: document.getElementById('drkIp').value.trim(),
      port: Number(document.getElementById('drkPort').value) || VORGABE_PORT,
      standort: document.getElementById('drkOrt').value.trim(),
    };
    if (!eintrag.name) return feldmeldung(formMeldungEl, 'Bitte einen Namen angeben');
    if (!ADRESSE.test(eintrag.ip)) {
      return feldmeldung(formMeldungEl, 'Das ist keine gültige IP-Adresse — etwa '
        + '192.168.178.20');
    }
    if (eintrag.port < 1 || eintrag.port > 65535) {
      return feldmeldung(formMeldungEl, 'Der Port muss zwischen 1 und 65535 liegen');
    }
    /* Zwei Geräte mit demselben Namen liessen sich später nicht mehr
       auseinanderhalten — der Name ist der Schlüssel für Prüfen und Drucken. */
    const doppelt = drucker.some(d => d.name === eintrag.name
                                   && d.name !== bearbeitet);
    if (doppelt) return feldmeldung(formMeldungEl, 'Diesen Namen gibt es schon');

    const neu = bearbeitet
      ? drucker.map(d => (d.name === bearbeitet ? eintrag : d))
      : [...drucker, eintrag];
    knopf.disabled = true;
    knopf.textContent = 'Speichere …';
    meldungWeg(formMeldungEl);
    try {
      erreichbar.delete(bearbeitet || eintrag.name);
      await sichern(neu.map(({ name, ip, port, standort }) =>
        ({ name, ip, port, standort })));
      formDlg.close();
    } catch (fehler) {
      feldmeldung(formMeldungEl, String(fehler.message || fehler));
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Übernehmen';
    }
  });
}
