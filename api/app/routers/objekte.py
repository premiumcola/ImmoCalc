"""Objekt-Router (Dach) — sammelt die Themen aus `api/app/objekt/` unter `/api`.

N216: Der frühere Monolith (~1980 Zeilen) ist in `..objekt/` zerlegt. Dieser
Modul-Kopf hält den Dach-Router, hängt die Sub-Router in einer definierten
Reihenfolge ein und re-exportiert die Symbole, die andere Router und der
Test `test_zeitraum_label.py` weiter über `.objekte` bzw.
`app.routers.objekte` beziehen.
"""
from fastapi import APIRouter

# Der Dach-Router trägt das `/api`-Präfix und den Objekt-Tag. Sub-Router in
# `..objekt/` sind bewusst ohne Präfix definiert, damit `include_router` sie
# unter `/api` einreiht (Prefixe konkatenieren würden sonst `/api/api/…`).
router = APIRouter(prefix="/api", tags=["objekte"])

# Sub-Router (jedes Modul trägt eine kohärente Gruppe von Endpunkten).
from ..objekt import (abrechnung as _abrechnung,    # noqa: E402
                      checkliste as _checkliste,    # noqa: E402
                      einheiten as _einheiten,      # noqa: E402
                      entwuerfe as _entwuerfe,      # noqa: E402
                      erinnerungen as _erinnerungen,  # noqa: E402
                      kostenarten as _kostenarten,  # noqa: E402
                      loeschen as _loeschen,        # noqa: E402
                      positionen as _positionen,    # noqa: E402
                      stammdaten as _stammdaten,    # noqa: E402
                      zeitraeume as _zeitraeume)    # noqa: E402

# Re-Exports für Fremd-Aufrufer (`cloud`, `dokumente`, `strom`, `stromkette`,
# `tests/test_zeitraum_label.py`). Die Namen bleiben stabil; wandern die
# Definitionen später weiter, greifen die Aufrufer weiterhin über `.objekte`.
from ..objekt.entwuerfe import _ENTWURF_MODELLE     # noqa: F401, E402
from ..objekt.loeschen import SICHERUNGSORDNER      # noqa: F401, E402
from ..objekt.zeitraeume import (_zeitraum_grenzen,  # noqa: F401, E402
                                 _zeitraum_jahr,
                                 _zeitraum_leer_entfernen,
                                 zeitraum_label_jahr)

# Reihenfolge: gleichartige Konfliktfälle gibt es unter den Sub-Routern nicht
# (jede Route ist auf genau einem Modul definiert). Trotzdem wird `stammdaten`
# zuerst eingehängt, weil es die Objektliste liefert und beim App-Start
# implizit als erstes angefragt wird.
router.include_router(_stammdaten.router)
router.include_router(_loeschen.router)
router.include_router(_einheiten.router)
router.include_router(_kostenarten.router)
router.include_router(_zeitraeume.router)
router.include_router(_checkliste.router)
router.include_router(_positionen.router)
router.include_router(_abrechnung.router)
router.include_router(_entwuerfe.router)
router.include_router(_erinnerungen.router)

# CCCXXVI: Lageplan-Router aus `dokumente.py` — die Endpunkte
# (`/api/einheiten/{id}/lageplan`, `…/lageplaene`) leben dort, wo die
# Upload-/Ablagelogik zu Hause ist. Sein Router trägt nur `/einheiten`; hier
# wird er unter den `/api`-Router gehängt, damit `/api/einheiten/…` entsteht —
# ohne die Ablagelogik zu doppeln und ohne `main.py` anzufassen.
from .dokumente import lageplan_router              # noqa: E402  (zirkelfrei:
router.include_router(lageplan_router)              # dokumente ist beim Laden
                                                    # von main.py schon importiert)
