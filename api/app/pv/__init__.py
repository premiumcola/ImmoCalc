"""app.pv — Fachlogik rund um die PV-Anlage (N216).

Der Router :mod:`app.routers.strom` bleibt schmal (Routen, Pydantic, dünne
Orchestrierung) und delegiert an dieses Paket. Externe Aufrufer und Tests, die
weiterhin ``from app.routers import strom as rs`` schreiben und ``rs.<name>``
benutzen, funktionieren durch Re-Exports am Router-Kopf unverändert weiter.

Aufteilung:

* :mod:`.stammdaten` — die einmal-je-Anlage-Daten (PVAnlage): Anschaffung,
  Vorlauf (mit Aufschlüsselung), kWp, Anteile.
* :mod:`.jahre` — Zugriff auf ein `Stromjahr` (lesen/speichern, Zuordnung der
  Verbrauchsgruppen).
* :mod:`.ertrag` — die Rechenlogik der Amortisation: Kategorien-€/kWh,
  Ertrag je Jahr aus den Nebenkostenpositionen.
* :mod:`.tanken_bridge` — der Live-Beitrag der E-Tankstelle aus derselben
  Quelle wie ihre Abrechnung (N200).
* :mod:`.amortisation` — Zusammenbau des Verlaufs über alle Jahre, samt
  Prognose (N127/N200/N204).
* :mod:`.eigentuemer` — Personenliste + gesetzte PV-Anteile für die Auswahl
  (N112/N139).

Namenskonflikt bewusst beachtet: :mod:`app.strom` ist die Engine für die
Stromkette; :mod:`app.routers.strom` ist der Router; :mod:`app.pv` ist die
PV-Fachlogik. Alle drei bleiben strikt getrennt.
"""
