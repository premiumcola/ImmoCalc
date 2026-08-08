"""Werkzeuge rund um die Dokumentenablage — modular gehalten.

Der eigentliche FastAPI-Router lebt weiter in `app.routers.dokumente`; hier
liegen die klar abgegrenzten Bausteine, aus denen er sich bedient —
Namensbildung, KI-Wertparser, Datumsrechnung, Strom-Auslese-Formatter,
Darstellungshelfer (N216) sowie Ablage, Cloud-Abgleich, Grabsteine,
Pfad-Heilung, Duplikat-Mechanik, Entwurfs-Baupläne, Zuordnung, KI-Raster am
Beleg und „zurück ins Warten" (N288). Der Router zieht sie über
`from ..dokumente.<modul>` zu sich und stellt sie am eigenen Namensraum
bereit — so bleibt jeder bestehende `from app.routers.dokumente import …`-
Zugriff unverändert lesbar, während die Fachlogik pro Baustein an einer Stelle
wohnt. Welches Modul was hält, steht in `_TOPICS.md`.

Die Abhängigkeit läuft nur in eine Richtung: die Bausteine kennen den Router
nicht. Wo eine Funktion doch einen Router-Namen braucht (`routers.objekte`),
geschieht das als Import zur Laufzeit, innerhalb der Funktion.

Bewusst kein Sammel-Re-Export auf Paketebene: jeder Baustein wird gezielt
importiert, wo er gebraucht wird. So bleibt die Import-Reihenfolge einfach
und Zirkelbezüge werden vermieden.
"""
