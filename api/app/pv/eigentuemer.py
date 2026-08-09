"""Die Personen zur Auswahl für die PV-Anteile (N112/N139/N216).

Die PV-Anlage ist ein eigenes Investment mit eigenen Tausendsteln; gewählt wird
aber aus derselben Personenliste wie überall (:class:`app.models.Eigentuemer`).
Geliefert werden alle Personen, die am Objekt beteiligten zuerst und mit ihrem
Objekt-Anteil als Vorschlag. Die gesetzten Anteile kommen aus den Stammdaten
der Anlage (N139), nicht mehr aus einem Jahr.
"""
from __future__ import annotations

from sqlmodel import Session, select

from .. import strom
from ..models import Anteil, Eigentuemer, Objekt
from .amortisation import verlauf_daten
from .stammdaten import (_anteile_dict, _anteile_hinweise, _anteile_tupel,
                         _stammdaten)


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


def jahres_verteilung(session: Session, o: Objekt, jahr: int) -> dict:
    """N308 — die jährliche PV-Eigentümer-Abrechnung: was die Anlage GENAU in
    diesem Jahr zur Amortisation beigetragen hat (die Jahreszeile aus
    :func:`amortisation.verlauf_daten`, `summe` — nicht der kumulierte Stand),
    verteilt auf die Eigentümer nach ihren PV-‰ (`stammdaten._anteile_tupel`),
    cent-genau über `strom.verteile_eigentuemer` (Größte-Reste-Verfahren).

    Formel je Eigentümer: `Jahresertrag € × eigene ‰ / 1000` (mit
    Rundungsausgleich über die größten Reste, damit die Summe exakt aufgeht).

    Gibt es für dieses Jahr keine Zeile (noch kein Zeitraum angelegt, oder ein
    Jahr außerhalb des erfassten Verlaufs), entsteht kein erfundener Betrag:
    `ertrag` bleibt `None` und `hinweis` sagt, woran es liegt.

    Je Eigentümer steht zusätzlich `kumuliert_anteil` dabei — dieselbe
    Verteilregel auf den seit Beginn kumulierten Ertrag angewandt, damit die
    Jahresmitteilung auch den Stand seit Beginn nennt (nicht Teil der
    Jahresrechnung selbst; der Anteil an der Anschaffung steht bereits als
    Investitions-Chip in der ‰-Liste darüber — hier nicht doppelt)."""
    v = verlauf_daten(session, o)
    zeile = next((z for z in v["jahre"] if z["jahr"] == jahr), None)
    anlage = _stammdaten(session, o.id)
    anteile = _anteile_tupel(anlage)
    gewichte = dict(anteile)
    personen = {e.name: e for e in session.exec(select(Eigentuemer)).all()}
    jahre_verfuegbar = [z["jahr"] for z in v["jahre"]]
    if zeile is None:
        return {"jahr": jahr, "ertrag": None, "kumuliert_bis_jahr": None,
                "offen": None, "eigentuemer": [],
                "jahre_verfuegbar": jahre_verfuegbar,
                "hinweis": (f"Für {jahr} gibt es keinen erfassten "
                           "Abrechnungszeitraum — kein Betrag zu verteilen.")}
    verteilt = strom.verteile_eigentuemer(zeile["summe"], anteile)
    kum_je_person = {e["anteil"]: e["betrag"] for e in
                     strom.verteile_eigentuemer(zeile["kumuliert"], anteile)}
    eigentuemer = [
        {"name": e["anteil"], "promille": gewichte.get(e["anteil"]),
         "betrag": e["betrag"],
         "kumuliert_anteil": kum_je_person.get(e["anteil"], 0.0),
         "eigentuemer_id": personen[e["anteil"]].id
                          if e["anteil"] in personen else None,
         "email": personen[e["anteil"]].email
                 if e["anteil"] in personen else ""}
        for e in verteilt]
    return {"jahr": jahr, "ertrag": zeile["summe"],
            "kumuliert_bis_jahr": zeile["kumuliert"], "offen": zeile["offen"],
            "eigentuemer": eigentuemer, "jahre_verfuegbar": jahre_verfuegbar,
            "hinweis": None}
