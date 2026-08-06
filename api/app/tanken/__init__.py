"""Rechenkern und Datenzugriff der E-Tankstelle — als Paket getrennt vom Router.

Der Router (``app.routers.tankstelle``) bleibt schmal und delegiert an dieses
Paket. Für externe Aufrufer, die bisher aus dem Router importierten, hält der
Router die alten Namen als Re-Export bereit — dieses Paket ist der neue Ort
der Rechenlogik, kein Ersatz-Import-Pfad.

Aufteilung (siehe ``_TOPICS.md``):

* :mod:`.typen`       — Posten, Buchung, RohLadung
* :mod:`.perioden`    — Quartale, Monatsfolge, Suchfenster, Fälligkeit
* :mod:`.satz`        — Preis je kWh aus der Stromkette (N148)
* :mod:`.posten`      — Wallbox + erfasste Ladungen, Zuordnung
* :mod:`.verlauf`     — Monatsverlauf (kWh) + €/km-Anreicherung (N188)
* :mod:`.nutzer`      — Tanknutzer-Tabelle (lesen, migrieren, prüfen)
* :mod:`.einstellungen` — Autoversand-Schalter, Mehrnutzer-Zuordnung
* :mod:`.marker`      — abgerechnet-/versendet-Marker (N182/N187)
* :mod:`.versand`     — Mailtext, PDF-Zusammenbau, Benzin-Vergleichscache
* :mod:`.abrechnung`  — die eine Zusammenführung zu einer Nutzerrechnung
"""
