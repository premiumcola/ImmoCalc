/* N479 — die Zeichen der Dienst-Kacheln.

   Je Dienst ein eigener Umriss: die Kachel ist am Zeichen zu erkennen, nicht
   erst an der Beschriftung. Gezeichnet im 24×24-Feld, im flachen Strichstil
   der App (1.7 px, runde Enden, keine Flächen) — dieselbe Sprache wie die
   übrigen Sprites.

   Bewegliche Teile tragen die Klasse `sy` plus einen eigenen Namen. Die
   Animationen dazu stehen in settings.html und laufen NUR im Zustand
   „verbunden" (grün) oder „gestört" (rot); eine Kachel, die gar nicht
   eingerichtet ist, bleibt still — sonst zappelte die halbe Seite grundlos.

   Keine <defs> und keine IDs: dieselben Zeichen stehen mehrfach auf einer
   Seite, IDs würden kollidieren. Alles, was sich bewegt, geht deshalb über
   `transform` — und über `transform-box:fill-box`, damit sich jedes Teil um
   seine EIGENE Mitte dreht und nicht um die Ecke des 24er-Feldes. */

/* Gemeinsame Strichattribute. Steht hier statt in state.js, weil es nur die
   Zeichen betrifft. */
const VSTRICH = 'stroke="currentColor" stroke-width="1.7" fill="none" '
  + 'stroke-linecap="round" stroke-linejoin="round"';

const FLAECHE = 'fill="currentColor" stroke="none"';

export const VSYMBOLE = {
  /* Nextcloud — eine Wolke, darunter steigen drei Päckchen hinauf.
     Die Verschiebung nach oben steht als Attribut an einer ÄUSSEREN Gruppe:
     eine CSS-Animation auf derselben Gruppe würde sie sonst überschreiben
     (transform-Attribut und transform-Eigenschaft teilen sich einen Platz). */
  wolke: `
    <g transform="translate(0 -2.6)">
      <g class="sy sy-wolke">
        <path ${VSTRICH} d="M7.6 18.5h9a3.9 3.9 0 0 0 .5-7.8 5.4 5.4 0 0
              0-10.4 1.1 3.5 3.5 0 0 0 .9 6.7Z"/>
      </g>
    </g>
    <circle class="sy sy-auf sy-auf1" cx="8.8" cy="20.4" r="1.05" ${FLAECHE}/>
    <circle class="sy sy-auf sy-auf2" cx="12"  cy="20.4" r="1.05" ${FLAECHE}/>
    <circle class="sy sy-auf sy-auf3" cx="15.2" cy="20.4" r="1.05" ${FLAECHE}/>`,

  /* Belegerkennung — ein Beleg mit geknickter Ecke, darüber wandert der
     Lesestrahl; der Funke an der Ecke blitzt dazu auf. Im Ruhezustand steht
     der Strahl in der Mitte und liest sich schlicht als Textzeile. */
  beleg: `
    <path ${VSTRICH} d="M12.4 3.5H7.5A2 2 0 0 0 5.5 5.5v13a2 2 0 0 0 2 2h7a2 2
          0 0 0 2-2V7.6Z"/>
    <path ${VSTRICH} d="M12.4 3.5v4.1h4.1"/>
    <path class="sy sy-scan" stroke="currentColor" stroke-width="1.5" fill="none"
          stroke-linecap="round" d="M8.2 13.4h5.6"/>
    <path class="sy sy-glanz" ${VSTRICH} d="M19 14.2c.5 2 1.15 2.65 3.15
          3.15-2 .5-2.65 1.15-3.15 3.15-.5-2-1.15-2.65-3.15-3.15 2-.5 2.65-1.15
          3.15-3.15Z"/>`,

  /* SolarEdge — Sonne über dem Modul. Die Strahlen sind bewusst symmetrisch um
     (12 | 6.5) gesetzt, damit `transform-origin:center` genau die Sonnenmitte
     trifft und die Drehung nicht eiert. */
  solar: `
    <path ${VSTRICH} d="M3.5 20.5h17l-2.6-7.4H6.1Z"/>
    <path ${VSTRICH} d="M12 13.1v7.4M5.4 16.8h13.2"/>
    <g class="sy sy-sonne">
      <circle ${VSTRICH} cx="12" cy="6.5" r="2.6"/>
      <path ${VSTRICH} d="M12 1.9v1.3M12 11.1V9.8M6.1 6.5h1.3M17.9 6.5h-1.3
            M8.46 2.96 9.38 3.88M15.54 10.04 14.62 9.12
            M15.54 2.96 14.62 3.88M8.46 10.04 9.38 9.12"/>
    </g>`,

  /* Mailversand — die Klappe hebt sich, ein Brief fliegt oben rechts hinaus.
     Der Brief ist im Ruhezustand unsichtbar; das Standbild der Kachel bleibt
     ein sauberer Umschlag. */
  brief: `
    <g class="sy sy-umschlag">
      <rect ${VSTRICH} x="3.5" y="7" width="17" height="12.5" rx="2.2"/>
      <rect class="sy sy-zettel" x="9.2" y="9.4" width="5.6" height="4.4" rx="1.1"
            ${FLAECHE}/>
      <path class="sy sy-klappe" ${VSTRICH} d="m4.5 8.4 7.5 5.5 7.5-5.5"/>
    </g>`,

  /* Drucker — Blatt um Blatt schiebt sich unten heraus, die Leuchte blinkt
     dazu. Im Fehlerfall rüttelt das ganze Gerät: Papierstau. */
  drucker: `
    <g class="sy sy-gehaeuse">
      <path ${VSTRICH} d="M7 10V4.6a1.1 1.1 0 0 1 1.1-1.1h7.8A1.1 1.1 0 0 1 17
            4.6V10"/>
      <rect ${VSTRICH} x="3.5" y="10" width="17" height="7.4" rx="2.2"/>
      <circle class="sy sy-led" cx="17.3" cy="12.7" r="1" ${FLAECHE}/>
    </g>
    <path class="sy sy-druck" ${VSTRICH} d="M7 17.4h10v3.1H7Z"/>`,

  /* Sicherung — ein Tresor. Das Rad dreht eine Vierteldrehung und wieder
     zurück, als würde jemand abschließen. Speichen und Kreis sind symmetrisch
     um (10.6 | 12), damit die Drehmitte stimmt. */
  tresor: `
    <g class="sy sy-schrank">
      <rect ${VSTRICH} x="3.5" y="4" width="17" height="16" rx="2.6"/>
      <path ${VSTRICH} d="M17.7 9.7v4.6"/>
    </g>
    <g class="sy sy-rad">
      <circle ${VSTRICH} cx="10.6" cy="12" r="3.5"/>
      <path ${VSTRICH} d="M10.6 7.2v1.6M10.6 16.8v-1.6M5.8 12h1.6M15.4 12h-1.6"/>
    </g>`,

  /* openWB — die Säule mit dem Blitz. Lädt sie, pulst der Blitz; ist sie
     gestört, flackert er wie ein Kontakt, der nicht sitzt. */
  wallbox: `
    <rect ${VSTRICH} x="4.5" y="3.5" width="10.5" height="17" rx="2.5"/>
    <path class="sy sy-blitz" ${VSTRICH} d="M10.8 7.5 8.5 11.6h3.1l-2.3 4.4"/>
    <path ${VSTRICH} d="M15 9.5h2.6a1.9 1.9 0 0 1 1.9 1.9V16a1.75 1.75 0 0 1-3.5
          0v-2.2"/>`,
};
