"""Objekt-Domäne — Router, Modelle und Helfer für Immobilien.

N216: Der frühere Monolith `routers/objekte.py` (~1980 Zeilen) ist hier nach
Themen zerlegt. Jedes Modul trägt einen eigenen `APIRouter` ohne Präfix — der
Dach-Router in `routers/objekte.py` sammelt sie unter `/api`. Öffentliche
Symbole, die andere Router/Tests weiter über `.objekte` beziehen, sind dort
re-exportiert.
"""
