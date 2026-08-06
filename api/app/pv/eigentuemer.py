"""Die Personen zur Auswahl für die PV-Anteile (N112/N139/N216).

Die PV-Anlage ist ein eigenes Investment mit eigenen Tausendsteln; gewählt wird
aber aus derselben Personenliste wie überall (:class:`app.models.Eigentuemer`).
Geliefert werden alle Personen, die am Objekt beteiligten zuerst und mit ihrem
Objekt-Anteil als Vorschlag. Die gesetzten Anteile kommen aus den Stammdaten
der Anlage (N139), nicht mehr aus einem Jahr.
"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import Anteil, Eigentuemer, Objekt
from .stammdaten import _anteile_dict, _anteile_hinweise, _stammdaten


def eigentuemer_daten(session: Session, o: Objekt) -> dict:
    """Personenliste + gesetzte PV-Anteile + Summenhinweis für die Auswahl."""
    alle = session.exec(select(Eigentuemer).order_by(Eigentuemer.name)).all()
    am_objekt = {a.eigentuemer_id: a.promille for a in session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id)).all()}
    personen = sorted(
        ({"id": e.id, "name": e.name, "email": e.email,
          "am_objekt": am_objekt.get(e.id)} for e in alle),
        key=lambda p: (p["am_objekt"] is None, p["name"]))
    gesetzt = _anteile_dict(_stammdaten(session, o.id).anteile)
    summe = round(sum(gesetzt.values()), 3)
    return {"personen": personen, "pv_anteile": gesetzt,
            "anteile_summe": summe,
            "hinweise": _anteile_hinweise(gesetzt, summe)}
