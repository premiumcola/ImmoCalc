/* N215 — Modul-Zustand fuer die Strom-Seite.

   Die Fach-Module (stammdaten, jahre, verlauf, kringel, eigentuemer,
   solaredge) teilen sich hier ihre mutierten Werte. Ein exportiertes
   Primitiv waere in jedem importierenden Modul eine eigene Kopie — deshalb
   liegen alle veraenderlichen Zustaende auf einem Objekt `S`, dessen
   Eigenschaften ueberall dieselben sind (`S.objektSlug`, `S.pvGeladen`
   etc.).

   Verhaltensgleich zum bisherigen Inline-Skript in strom.html — nur der
   Ort aendert sich. */
export const S = {
  objektSlug: '',
  jahresSatz: {},
  stammStand: {},
  letzteWerte: '',
  letzteStamm: '',
  speicherZeit: null,
  stammZeit: null,
  // PV-Eigentuemer (N204)
  pvPersonen: [],
  pvAnteile: {},
  pvGeladen: false,
  pvNeuWahl: null,
  pvAnschaffung: 0,
  pvAddOffen: false,
  // SolarEdge — Screenshot je Objekt/Jahr (N131/N155/N161)
  seWerte: {},
  seBilder: new Map(),
  // Kopf oben; wird beim Start (in strom.html) gesetzt.
  jahrWahl: null,
};

/* Die zwei DOM-Referenzen, die fast jedes Modul braucht. Das <div id="inhalt">
   steht im HTML vor dem <script type="module">, existiert also schon beim
   Laden dieses Moduls. */
export const inhalt = document.getElementById('inhalt');
export const sub = document.getElementById('sub');
