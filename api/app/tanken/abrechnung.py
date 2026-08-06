"""Abrechnung der E-Tankstelle — die Zusammenführung von Menge, Satz und
Zuordnung zu einer nutzerweisen Rechnung.

`_abrechnung` ist die eine Stelle, aus der Vorschau, Liste, PDF und Versand
schöpfen — damit alle dasselbe sagen."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import HTTPException
from sqlmodel import Session

from .. import eauto
from ..models import Objekt
from .einstellungen import zuordnung_lesen
from .nutzer import nutzer_lesen, schluessel
from .perioden import abrechnungs_label, aktive_monate
from .posten import _posten_holen, buchungen, posten_als_buchungen
from .satz import EIGEN_RABATT, satz_ableiten
from .typen import Buchung
from .verlauf import verlauf, verlauf_summe
from .versand import _benzin_verbrauch


def abrechne(buchungen: list[Buchung], nutzer: list[dict],
             satz: float | None) -> list[dict]:
    """Je Nutzer: geladene Menge, Satz und Betrag.

    Der Satz ist abgeleitet (N148) und gilt für alle Ladungen des Zeitraums
    gleichermaßen — es gibt keinen Preis je Ladung mehr. Ist er ``None``,
    bleiben `betrag` und `satz` ebenfalls ``None``: die Mengen stehen da, aber
    kein Geldbetrag, den niemand belegen kann. **Eine 0,00 € wäre hier eine
    Behauptung**, keine Rechnung.

    Angelegte Nutzer ohne Ladung erscheinen mit 0 — sonst verschwände jemand
    aus der Liste, nur weil er ein Quartal lang nicht geladen hat. Ladungen auf
    Namen, die (noch) nicht in der Liste stehen, stehen am Ende mit
    ``angelegt: false``: übergehen wäre stilles Verschlucken von Geld."""
    zeilen: dict[str, dict] = {}
    for n in nutzer:
        zeilen[schluessel(n["name"])] = {
            "nutzer_id": n["id"], "name": n["name"], "email": n.get("email", ""),
            "angelegt": True, "anzahl": 0, "kwh": 0.0, "betrag": 0.0,
            "ladungen": []}

    for b in buchungen:
        s = schluessel(b.person)
        zeile = zeilen.get(s)
        if zeile is None:
            zeile = zeilen[s] = {
                "nutzer_id": None, "name": b.person or "—", "email": b.email,
                "angelegt": False, "anzahl": 0, "kwh": 0.0, "betrag": 0.0,
                "ladungen": []}
        zeile["anzahl"] += 1
        zeile["kwh"] += b.kwh
        if satz is not None:
            zeile["betrag"] += b.kwh * satz
        if not zeile["email"] and b.email:
            zeile["email"] = b.email
        zeile["ladungen"].append({
            "datum": b.tag.isoformat() if b.tag else None,
            "kwh": round(b.kwh, 3),
            "preis": None if satz is None else round(satz, 4),
            "betrag": None if satz is None else round(b.kwh * satz, 2)})

    fertig = []
    for zeile in zeilen.values():
        fertig.append({**zeile, "kwh": round(zeile["kwh"], 3),
                       "betrag": None if satz is None
                                 else round(zeile["betrag"], 2),
                       "satz": None if satz is None else round(satz, 4)})
    # Wer geladen hat, steht oben; danach alphabetisch — eine Reihenfolge, die
    # sich zwischen zwei Aufrufen nicht von selbst ändert.
    fertig.sort(key=lambda z: (-z["kwh"], schluessel(z["name"])))
    return fertig


def _abrechnung(session: Session, o: Objekt, slug: str, jahr: int,
                quartal: int, quartale: list[int] | None = None,
                aus: set[int] | None = None) -> dict:
    """Die Abrechnung eines Zeitraums — von Vorschau, Liste und Versand
    gemeinsam benutzt, damit alle drei dasselbe sagen.

    Abgerechnet wird ausschliesslich, was einer Person zugeordnet ist: die
    Wallbox weiss, wie viel geladen wurde, aber nicht von wem. Damit eine
    Abrechnung über 0 € nicht rätselhaft bleibt, steht daneben, wie viel im
    Zeitraum überhaupt geladen wurde (`geladen_kwh`) — die Lücke zwischen
    beiden Zahlen ist die Antwort auf „wieso passiert da nichts" (N143).

    Der Satz kommt aus der Stromkette (N148); die Mengen des Zeitraums sagen,
    wie stark Netz und eigener Strom darin gewichtet sind.

    `quartale` (mehrere zusammen) und `aus` (einzeln abgewählte Monate) sind der
    Quartals-Feinschliff aus N169. Ohne sie bleibt es beim einzelnen `quartal`
    — der bisherige Weg (auch der Autoversand ruft so)."""
    quartale = list(quartale) if quartale is not None else [quartal]
    aus = set(aus or ())
    try:
        monate = aktive_monate(quartale, aus)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    if not monate:
        raise HTTPException(400, "Für die Abrechnung ist kein Monat ausgewählt "
                                 "— mindestens ein Monat muss bleiben.")
    aktiv = set(monate)
    von = date(jahr, monate[0], 1)
    bis = date(jahr, monate[-1], monthrange(jahr, monate[-1])[1])
    label = abrechnungs_label(jahr, quartale, aus)
    liste = nutzer_lesen(session, o)
    posten_roh, quelle, _ = _posten_holen(session, o, von, bis)
    # Ein aus dem Quartal abgewählter Monat fällt aus Menge und Betrag heraus
    # (N169) — nicht nur aus der Anzeige. Darum hier an der Quelle filtern.
    posten = [p for p in posten_roh
              if p.tag is None or p.tag.month in aktiv]
    zeilen_verlauf = [z for z in verlauf(posten, von, bis) if z["monat"] in aktiv]
    summe = verlauf_summe(zeilen_verlauf) if posten else {}
    satz = satz_ableiten(session, o.id, von, bis,
                         summe.get("extern_kwh"), summe.get("eigen_kwh"))
    # N165 — mit genau einem Nutzer gehören ihm automatisch alle Ladungen des
    # Zeitraums (aus den geladenen Mengen, nicht nur aus den namentlich
    # erfassten Sätzen). Bei mehreren bleibt es bei der Zuordnung über den Namen.
    auto_buch, automatisch = posten_als_buchungen(posten, liste)
    if automatisch:
        quelle_buch = auto_buch
    else:
        # Mehrere Nutzer: Zuordnung über den Zeitraum, wenn Regeln hinterlegt
        # sind; sonst wie bisher über den Namen. Ausgeschlossene Ladungen fallen
        # in beiden Fällen heraus (N165/2), abgewählte Monate ebenso (N169).
        regeln, ausschluss = zuordnung_lesen(session, o.slug, liste)
        quelle_buch = buchungen(session, o.id, von, bis, liste, regeln,
                                ausschluss, aktiv)
    zeilen = abrechne(quelle_buch, liste, satz.misch)
    if automatisch:
        for z in zeilen:
            z["automatisch"] = z["kwh"] > 0
    # N170 — je Nutzer aus geladenen kWh und seinem Verbrauch die gefahrenen km,
    # den Preis je 100 km und das energetische Benzin-Äquivalent. Ohne
    # hinterlegten Verbrauch bleiben die Größen None (keine erfundene Zahl).
    nach_id = {n["id"]: n for n in liste}
    for z in zeilen:
        n = nach_id.get(z.get("nutzer_id")) or {}
        modell = n.get("e_auto_modell", "")
        verbrauch = n.get("verbrauch_kwh_100km", 0.0)
        kz = eauto.kennzahlen(z["kwh"], z["betrag"], verbrauch or None)
        z["e_auto_modell"] = modell
        z["verbrauch_kwh_100km"] = verbrauch or 0.0
        z["km"], z["preis_100km"], z["liter_100km"] = (
            kz["km"], kz["preis_100km"], kz["liter_100km"])
        # N184b — die Empfänger-Anschrift, damit die Inline-Vorschau sie unter
        # dem Namen zeigen kann (wie das PDF). Eine noch nicht angelegte Person
        # (nutzer_id None) hat keine.
        z["strasse"] = n.get("strasse", "")
        z["plz"] = n.get("plz", "")
        z["ort"] = n.get("ort", "")
        # N184b — der Benzin-Kostenvergleich je Nutzer, exakt wie ihn das PDF
        # baut (`_pdf_und_name`): realer Verbrauch eines vergleichbaren Benziners
        # aus der KI (gecacht über `_benzin_verbrauch`) gegen den echten
        # E-Auto-Preis je 100 km. Ohne Verbrauch oder ohne belastbaren
        # Benzinwert bleibt er None — kein Vergleich, keine erfundene Zahl.
        z["benzin"] = (eauto.benzin_vergleich(
            _benzin_verbrauch(session, modell), kz["preis_100km"], kz["km"])
            if verbrauch and verbrauch > 0 else None)
    # N184b — die Objekt-Bankverbindung (der Betreiber, an den überwiesen wird);
    # None, wenn ungepflegt. Dieselbe Quelle wie das PDF (`_pdf_und_name`).
    konto = {"kontoinhaber": o.kontoinhaber or "", "iban": o.iban or "",
             "bank": o.bank or ""}
    zugeordnet = round(sum(z["kwh"] for z in zeilen), 3)
    return {"objekt": o.name, "jahr": jahr, "quartal": quartal,
            "quartale": sorted(set(quartale)), "aus_monate": sorted(aus),
            "monate_aktiv": monate,
            "label": label,
            "von": von.isoformat(), "bis": bis.isoformat(),
            "automatisch": automatisch,
            "satz": satz.misch, "satz_netz": satz.netz,
            "satz_eigen": satz.eigen, "satz_rabatt": EIGEN_RABATT,
            "satz_herkunft": satz.herkunft, "satz_grund": satz.grund,
            "nutzer": zeilen,
            "kwh_gesamt": zugeordnet,
            "betrag_gesamt": (None if satz.misch is None
                              else round(sum(z["betrag"] for z in zeilen), 2)),
            "geladen_kwh": summe.get("kwh"), "quelle": quelle,
            "offen_kwh": (None if not summe
                          else round(summe["kwh"] - zugeordnet, 2)),
            "eigen_prozent": summe.get("eigen_prozent"),
            # N170 — die Annahme des Benzin-Äquivalents, sichtbar mitgeführt.
            "benzin_kwh_pro_liter": eauto.BENZIN_KWH_PRO_LITER,
            # N184b — die Objekt-Bankverbindung für den Konto-Block der
            # Inline-Vorschau; None, wenn keine der drei Angaben gepflegt ist.
            "konto": (konto if any(konto.values()) else None)}


def _zeile_holen(daten: dict, nutzer_id: int, name: str) -> dict:
    """Die Abrechnungszeile eines Nutzers — über die Kennung oder den Namen."""
    for z in daten["nutzer"]:
        if (nutzer_id and z["nutzer_id"] == nutzer_id) or \
           (name and schluessel(z["name"]) == schluessel(name)):
            return z
    raise HTTPException(404, "Für diesen Nutzer gibt es keine Abrechnung.")
