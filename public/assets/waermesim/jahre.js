/* N340l — die Eckdaten jeder geprüften Delta-t-Abrechnung: Brennstoff,
   Nebenkosten- und Zusatzkosten-Blöcke, Warmwasservolumen. Das ist alles, was
   NICHT aus den Zählerständen kommt — die Zählerstände selbst liefert
   `zaehler.js` (`staende` je Gerät), die H1/H2-Aufteilung leitet
   `waermesim.rechne()` daraus ab (überschreibbar über `h2_anteil`).

   Jahr = Ende der Abrechnungsperiode (01.10.Vorjahr–30.09.Jahr), wie überall
   sonst in diesem Werkzeug. Nur Jahre mit einer echten, gelesenen Abrechnung
   stehen hier — 2020 und 2022 fehlen (nur Ableseformulare, keine
   Kostenaufstellung dazu). */
export const JAHRESDATEN = {
  2019: {
    zeitraum: '01.10.2018 – 30.09.2019',
    bestaende: [
      { datum: '2018-10-01', liter: 1990.0, eur: 1430.21 },
      { datum: '2019-01-04', liter: 1000.0, eur: 765.17 },
      { datum: '2019-02-11', liter: 1000.0, eur: 777.07 },
      { datum: '2019-04-29', liter: 2000.0, eur: 1560.09 },
    ],
    rest: { datum: '2019-09-30', liter: 1544.0, eur: 1204.39 },
    ww_m3: 30.110,
    bloecke: [
      { name: 'Nebenkosten Heizung', betrag: 572.20 },
      { name: 'Zusatzkosten Heizung', betrag: 295.36, nur_heizung: true },
    ],
    fest_anteil: 0.30,
    soll_gesamt: { heizkosten: 3865.53, warmwasser: 330.18 },
  },
  2021: {
    zeitraum: '01.10.2020 – 30.09.2021',
    bestaende: [
      { datum: '2020-10-01', liter: 3483.0, eur: 2097.04 },
      { liter: 3000.0, eur: 2027.76 },
    ],
    rest: { datum: '2021-09-30', liter: -2434.0, eur: -1645.19 },
    ww_m3: 28.140,
    bloecke: [
      { name: 'Nebenkosten Heizung', betrag: 398.15 },
      { name: 'Zusatzkosten Heizung', betrag: 295.36, nur_heizung: true },
    ],
    fest_anteil: 0.30,
    soll_gesamt: { heizkosten: 2923.12, warmwasser: 250.00 },
  },
  2023: {
    zeitraum: '01.10.2022 – 30.09.2023',
    bestaende: [
      { datum: '2022-10-01', liter: 2646.0, eur: 2549.00 },
      { datum: '2023-02-16', liter: 1000.0, eur: 1060.29 },
    ],
    rest: { datum: '2023-09-30', liter: -518.0, eur: -549.23 },
    ww_m3: 18.470,
    bloecke: [
      { name: 'Nebenkosten Heizung', betrag: 353.75 },
      { name: 'Zusatzkosten Heizung', betrag: 295.36, nur_heizung: true },
      { name: 'Zusatzkosten Warmwasser', betrag: 26.18, nur_heizung: false },
    ],
    fest_anteil: 0.30,
    soll_gesamt: { heizkosten: 3457.39, warmwasser: 277.96 },
  },
  2024: {
    zeitraum: '01.10.2023 – 30.09.2024',
    bestaende: [
      { datum: '2023-10-01', liter: 518.0, eur: 511.06 },
      { liter: 3000.0, eur: 3235.50 },
    ],
    rest: { datum: '2024-09-30', liter: -261.0, eur: -281.50 },
    ww_m3: 9.800,
    bloecke: [
      { name: 'Nebenkosten Heizung', betrag: 519.78 },
      { name: 'Zusatzkosten Heizung', betrag: 295.36, nur_heizung: true },
      { name: 'Zusatzkosten Warmwasser', betrag: 26.18, nur_heizung: false },
    ],
    fest_anteil: 0.30,
    // N340k — für 2023/24 ist nur die addierte WMZ-Menge beider Anbau-Zähler
    // bekannt (7.316 kWh), keine Aufteilung je Gerät. Ohne diesen Wert wäre
    // der H2-Anteil hier nicht ableitbar; ihn zu raten wäre schlimmer als ihn
    // wegzulassen — also bleibt 2024 ohne automatischen H2-Anteil, bis die
    // beiden Zähler eigene Stände für dieses Jahr bekommen.
    anbau_kwh_addiert: 7316,
  },
};

export const JAHRE_ABSTEIGEND = Object.keys(JAHRESDATEN).map(Number).sort((a, b) => b - a);
