"""Werkzeuge rund um die Dokumentenablage — modular gehalten.

Der eigentliche FastAPI-Router lebt weiter in `app.routers.dokumente`; hier
liegen die kleinen, klar abgegrenzten Bausteine, aus denen er sich bedient
(Namensbildung, KI-Wertparser, Datumsrechnung, Strom-Auslese-Formatter,
Darstellungshelfer). Der Router zieht sie über `from ..dokumente.<modul>`
zu sich und stellt sie am eigenen Namensraum bereit — so bleibt jeder
bestehende `from app.routers.dokumente import …`-Zugriff unverändert lesbar,
während die Fachlogik pro Baustein an einer Stelle wohnt.

Bewusst kein Sammel-Re-Export auf Paketebene: jeder Baustein wird gezielt
importiert, wo er gebraucht wird. So bleibt die Import-Reihenfolge einfach
und Zirkelbezüge werden vermieden.
"""
