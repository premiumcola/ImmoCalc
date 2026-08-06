/* N127/N200 — die Farbpalette der Amortisation.

   Kurve, Ring und die Prozent-Aufteilung teilen sich diese Toene: eine
   Aenderung wirkt an allen drei Stellen gleichzeitig. Bewusst als eigenes
   Modul, damit weder verlauf.js noch kringel.js die Farben vor der Nase
   des anderen aendern kann. */
export const C_DIREKT = '#0F6E5C';   // PV-Strom / Direktnutzung
export const C_EINSP  = '#916212';   // Einspeisung — kommt als Schraffur
export const C_TANK   = '#7A9E94';   // E-Tanken
export const C_VOR    = '#5C6B70';   // Vorlauf ohne Aufschluesselung
export const C_OFFEN  = '#B24229';   // noch offener Rest
export const C_PLUS   = '#2E7D4F';   // Ueberschuss / amortisiert
