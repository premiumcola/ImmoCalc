/* N216 — Rechenlogik-Übersicht (statischer Inhalt, nur öffnen).

   Der Dialoginhalt ist statisch im HTML — die einzige Aufgabe hier ist, ihn
   beim Klick auf die Zeile anzuzeigen. Verhaltensgleich zum bisherigen
   Inline-Skript in settings.html. */

export function rechenlogikInit() {
  const rlDlg = document.getElementById('rlDlg');
  document.getElementById('rlRow').addEventListener('click', () => rlDlg.showModal());
}
