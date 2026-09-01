"""Erinnerungen — was ansteht: Abrechnungsfristen und erwartete Jahresbelege.

Wandert objekt- und zeitraumübergreifend; Grundstücke bleiben draußen, sie
haben weder Mieter noch eine § 556-Frist. Leere, automatisch angelegte
Zeiträume (ohne Position) sind ebenfalls draußen — sie sind keine echte
Abrechnung in Arbeit.
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..deps import aktuelle_familie
from ..erinnerungen import beleg_erinnerung, frist_erinnerung, in_sicht
from ..frist import frist_tage
from ..models import (Familie, Kostenart, Kostenposition, Objekt, Zeitraum,
                      ist_grundstueck)

router = APIRouter(tags=["objekte"])


@router.get("/erinnerungen")
def erinnerungen(session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Was ansteht: Abrechnungsfristen und erwartete Jahresabrechnungen.
    Grundlage für Benachrichtigungen — nur für die Objekte dieser Familie."""
    heute = date.today()
    offen = []
    for o in session.exec(
            select(Objekt).where(Objekt.familie_id == familie.id)).all():
        # Ein Grundstück rechnet mit niemandem ab — weder eine Frist nach
        # § 556 BGB noch ein erwarteter Versorgerbeleg ergibt dort einen Sinn.
        # Bestandsgrundstücke haben noch einen Zeitraum aus früheren Anlagen.
        if not o.aktiv or ist_grundstueck(o):
            continue
        # Was in irgendeinem offenen Zeitraum schon erledigt ist, gilt als
        # vorhanden: die Beleg-Erinnerung kennt keinen Zeitraum, sie fragt nur
        # „ist die Jahresabrechnung dieser Kostenart da?".
        vorhanden: set[str] = set()
        in_arbeit = False
        for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
            if z.status != "in Arbeit":
                continue
            positionen = list(session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id == z.id)).all())
            # N51 — leere, automatisch angelegte Zeiträume (keine Kostenposition)
            # sind keine echte Abrechnung in Arbeit: keine § 556-Fristwarnung und
            # keine Beleg-Erinnerung. Sie sind auch in der Liste ausgeblendet.
            if not positionen:
                continue
            in_arbeit = True
            label = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
            hinweis = frist_erinnerung(label, frist_tage(z),
                                       zeitraum_beendet=z.ende <= heute)
            if in_sicht(hinweis):
                offen.append({"objekt": o.slug, "name": o.name, **hinweis})
            vorhanden |= {p.kostenart for p in positionen
                          if p.status == "erledigt"}

        # Beleg-Erinnerungen hängen an der Kostenart, nicht am Zeitraum — der
        # Text nennt weder Zeitraum noch Jahr. Standen sie in der Zeitraum-
        # Schleife, erschien bei zwei offenen Zeiträumen (der Regelfall im
        # Januar: Vorjahr noch offen, laufendes Jahr schon angelegt) jeder
        # Hinweis wortgleich doppelt. Deshalb einmal je Objekt.
        if not in_arbeit:
            continue
        for k in session.exec(
                select(Kostenart).where(Kostenart.objekt_id == o.id)).all():
            if not k.aktiv:
                continue
            hinweis = beleg_erinnerung(k.name, k.beleg_monat, k.erinnerung_tage,
                                       k.name in vorhanden, heute)
            if in_sicht(hinweis):
                offen.append({"objekt": o.slug, "name": o.name, **hinweis})

    offen.sort(key=lambda e: (not e["faellig"], e["tage"]))
    return {"heute": heute.isoformat(),
            "faellig": sum(1 for e in offen if e["faellig"]),
            "erinnerungen": offen}
