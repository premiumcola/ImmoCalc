# Referenz: iPhone-Menüleiste (Frosted Dock + Top-Fog)

Vom Nutzer aus einem anderen Projekt mitgebracht (N327-b), als Antwort auf
"passt den Radius bitte iPhone-dynamisch an" und "der Schatten soll nicht
nach oben zeigen". Quelle dort: `app/web/static/css/05-chrome-dock.css`.

**Stand hier:** der **untere** Teil (Dock/Pille) ist mit diesen Techniken in
`public/assets/immo.css` (`.nav`) umgesetzt — Details unten unter
"Was schon übernommen wurde". Der **obere** Teil (Top-Fog über der
Statuszeile) ist **bewusst noch nicht angefasst** — nur hier notiert, bis der
Nutzer sagt, dass die Kopfzeile das auch bekommen soll.

## Die zwei Bausteine im Original

1. **Der Dock** — schwebende, pillenförmige untere Leiste, Frosted Glass.
2. **Der Top-Fog** — ein `body::before`, fest über der Statusleiste/Dynamic
   Island montiert. Kein HTML, kein Scroll-JS — blurt Seiteninhalt rein durch
   `backdrop-filter`, während er darunter durchscrollt.

Dazu ein `body::after` als reine Farbverlauf-Tiefenblende ohne
`backdrop-filter` (Fallback-Tiefe). Alle drei `position: fixed`, immer an.

## Nicht verhandelbare Werte (Original, dunkles Theme)

| Eigenschaft | Wert | Warum |
|---|---|---|
| Dock-Eckenradius | 47px | iPhone-15-Pro-Bildschirmradius (~55px) minus 8px Rand |
| Button-Pillenradius | 39px (= 47 − 8) | konzentrisch zum Dock-Radius bei 8px Innenabstand |
| Blur (beide Flächen) | `blur(22px) saturate(1.05)` | fest verdrahtet, kein Token |
| Dock-Hintergrund | `rgba(31,31,35,.72)` | neutrales Grau |
| Top-Fog-Hintergrund | `rgba(31,31,35,.55)` | gleicher Ton, heller |
| Dock-Rand | 8px seitlich, unten `max(8px, env(safe-area-inset-bottom)+6px)` | safe-area-bewusst |
| z-index | Dock 90, Top-Fog 91, `body::after` 89 | geschichtet |

**Wichtig für ImmoCalc:** die konkreten Farben (`rgba(31,31,35,…)`, dunkles
Glas) passen nicht zur hellen Designsprache dieser App (`--paper`/`--sheet`/
`--ink`, siehe CLAUDE.md) — übernommen werden die **Techniken** (Blur-Rezept,
konzentrischer Radius, safe-area-Formel, der iOS-Kompositionstrick), nicht
die dunklen Farbwerte wörtlich.

## Der iOS-Stolperstein (kritisch)

```css
isolation: isolate;
will-change: backdrop-filter, transform;
transform: translateZ(0);
```

Muss auf **beiden** Flächen (Dock UND `body::before`) stehen. `html`/`body`
haben dort `overflow-x: hidden` — auf WebKit lässt das `backdrop-filter`
sonst aus einem leeren/beschnittenen Puffer lesen → das Frosted Glass wird zu
einer flachen Vollfarbe ohne jede Unschärfe. Dieses Trio zwingt WebKit auf
eine eigene Compositing-Ebene, die den echten Viewport-Puffer sieht. Bricht
das Blur auf dem iPhone weg, ist **das** die Ursache — nicht der Blur-Wert.

## Top-Fog — Original-CSS, für eine spätere Kopfzeilen-Umsetzung

Noch NICHT in ImmoCalc übernommen. Zum späteren Nachbauen (Farben dann an
`--paper`/`--sheet` anpassen, nicht das dunkle Grau übernehmen):

```css
@media (max-width: 768px) {
  body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0;
    height: calc(env(safe-area-inset-top, 0px) + 24px);
    background: rgba(31, 31, 35, 0.55);
    -webkit-backdrop-filter: blur(22px) saturate(1.05);
    backdrop-filter: blur(22px) saturate(1.05);
    /* verläuft über die untere Hälfte, damit keine harte Kante entsteht */
    -webkit-mask-image: linear-gradient(to bottom, #000 0%, #000 55%, transparent 100%);
    mask-image: linear-gradient(to bottom, #000 0%, #000 55%, transparent 100%);
    isolation: isolate;
    will-change: backdrop-filter, transform;
    transform: translateZ(0);
    pointer-events: none;
    z-index: 91;
  }
}
```

Das `mask-image` (0–55% voll deckend, dann Verlauf bis 100% transparent) ist
der Grund, warum das wie Nebel statt wie ein harter Balken wirkt. Es
"erscheint beim Scrollen", weil Inhalt darunter wegzieht — kein Schwellwert,
kein Scroll-Listener nötig.

Ergänzend ein `body::after` als reine Tiefenblende ohne Blur (im Original
zwischen Dock-Oberkante und Inhalt):

```css
body::after {
  content: '';
  position: fixed; left: 0; right: 0;
  bottom: calc(env(safe-area-inset-bottom, 0px) + 2px + 70px);
  height: 80px;
  background: linear-gradient(to top,
    rgba(17,17,17,0.85) 0%, rgba(17,17,17,0.55) 30%, rgba(17,17,17,0) 100%);
  pointer-events: none;
  z-index: 89;
}
```

## Was das Scroll-JS macht — und was NICHT

Im Original (`mobile-dock.js`) ist der Scroll-Handler ein **Scroll-Spy**
(welcher Abschnitt ist gerade aktiv → passenden Dock-Button markieren),
**kein Blur-Umschalter**. Beide Frosted-Flächen sind immer an, `position:
fixed`. Für ImmoCalc heisst das: falls die Kopfzeile das später bekommt,
braucht es **keinen** Scroll-Listener für den Blur selbst — nur ggf. für eine
aktive-Seite-Markierung, die `installNav()` ohnehin schon anders löst
(`aria-current`, keine Scroll-Position nötig).

## Was schon übernommen wurde (Dock/untere Leiste, `.nav` in `immo.css`)

- Konzentrischer Radius: Pille 26px, aktive Fläche/Buttons 18px (= 26 − 8px
  Innenabstand) — exakt dasselbe Verhältnis wie im Original (47/39 bei 8px).
- `bottom`-Formel nach demselben Muster wie `max(8px, safe-area+6px)`,
  angepasst auf unseren 14px-Rand.
- Der iOS-Kompositions-Trio (`isolation`/`will-change`/`transform`) — auch
  ohne eigenes `backdrop-filter` schadet er nicht und steht bereit, falls
  hier später echtes Frosted Glass dazukommt.
- Frosted-Glass-Rezept (`blur(22px) saturate(1.05)`) mit **hellen** Werten
  (`rgba(255,255,255,.8)` statt des dunklen Originaltons) — Technik
  übernommen, Farbe an die App angepasst.
- Touch-Ziele auf 54px angehoben (über dem 44px-Minimum der App).

**Nicht übernommen und bewusst anders:** die Schatten-Richtung. Das Original
hat auch nach oben gerichtete Schattenanteile (negative Y-Offsets); für
ImmoCalc gilt die explizite Nutzer-Vorgabe "kein Schatten nach oben" — die
Schatten-Ebenen bleiben ausschliesslich nach unten/seitlich gerichtet.
