"""Mail- und PDF-Vorbereitung der E-Tankstelle.

Alles, was für den Versand einer Abrechnung an einen Nutzer aufgebaut werden
muss, **ohne** die eine Stelle, die dann wirklich verschickt: `_sende_abrechnung`
bleibt in :mod:`app.routers.tankstelle`, damit die Test-Monkeypatches auf
`t.zugang` weiter greifen (der Mailversand ist die Grenze zur Außenwelt).

Hier drin: Mailtext, PDF-Zusammenbau, Empfängerdaten, Benzin-Vergleichscache
(N177)."""
from __future__ import annotations

from datetime import date

from sqlmodel import Session

from .. import eauto
from ..cloudkern import _lies
from ..models import Objekt, Tanknutzer
from ..routers.ki import ki_key, ki_modell
from ..tankabrechnung_pdf import tank_pdf_dateiname, tankabrechnung_pdf
from .einstellungen import _setze
from .posten import _posten_holen
from .satz import EIGEN_RABATT, deutsch
from .verlauf import verlauf, verlauf_summe

# N177 — Cache des von der KI ermittelten Benzinverbrauchs je E-Auto-Modell.
# Der Kostenvergleich im PDF braucht ihn; ein Cache spart wiederholte
# Netz-Aufrufe beim erneuten Ansehen desselben Quartals. Additiv, eigener
# Namensraum — kein bestehender Schlüssel wird angefasst.
S_BENZIN = "tankstelle_benzin"


def abrechnungstext(objekt_name: str, zeile: dict, von: date, bis: date,
                    label: str, eigen_prozent: float | None,
                    herkunft: str = "") -> str:
    """Die Abrechnung als Text für die Mail — dieselbe Grundlage wie die
    Vorschau auf der Seite, damit niemand etwas anderes verschickt, als er
    gesehen hat.

    `herkunft` sagt, woraus der Satz entstanden ist. Sie steht in der Mail,
    weil der Empfänger sonst eine Zahl bekäme, die er nicht nachprüfen kann.
    Ohne Satz nennt der Text die Menge und sagt offen, dass der Preis noch
    aussteht — statt eine 0,00-€-Forderung zu stellen."""
    def tag(d: date) -> str:
        return d.strftime("%d.%m.%Y")

    def geld(wert: float | None) -> str:
        return "—" if wert is None else f"{deutsch(wert)} €"

    def menge(wert: float) -> str:
        return f"{deutsch(wert)} kWh"

    zeilen = [f"Hallo {zeile['name']},", "",
              f"hier die Abrechnung deiner Ladungen an der E-Tankstelle "
              f"{objekt_name} für {label} ({tag(von)} – {tag(bis)}).", "",
              f"Geladen    {menge(zeile['kwh'])}"]
    if zeile["satz"] is None:
        zeilen += ["Satz       steht noch nicht fest",
                   "Zu zahlen  —", ""]
    else:
        zeilen += [f"Satz       {deutsch(zeile['satz'], 4)} € je kWh",
                   f"Zu zahlen  {geld(zeile['betrag'])}", ""]

    if zeile["ladungen"]:
        zeilen.append("Einzelne Ladungen:")
        for l in zeile["ladungen"]:
            datum = (date.fromisoformat(l["datum"]).strftime("%d.%m.%Y")
                     if l["datum"] else "ohne Datum")
            zeilen.append(f"  {datum}   {menge(l['kwh'])}   {geld(l['betrag'])}")
        zeilen.append("")

    if eigen_prozent is not None:
        zeilen.append(f"{deutsch(eigen_prozent, 1)} % des Stroms kamen im "
                      "Zeitraum aus der eigenen Photovoltaik-Anlage.")
        zeilen.append("")

    if herkunft:
        zeilen.append(f"Der Satz ist nicht gesetzt, sondern gerechnet: "
                      f"{herkunft}. Eigener Strom aus PV und Akku kostet "
                      f"{deutsch(EIGEN_RABATT * 100, 0)} % weniger als "
                      "zugekaufter.")
        zeilen.append("")

    zeilen.append("Viele Grüße")
    return "\n".join(zeilen) + "\n"


def _mailtext(o: Objekt, daten: dict, zeile: dict) -> tuple[str, str]:
    """Betreff und Text der Abrechnungsmail — von Vorschau, Versand und
    Autoversand gemeinsam benutzt, damit alle drei dasselbe sagen."""
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    betreff = f"E-Tankstelle {o.name} — Abrechnung {daten['label']}"
    text = abrechnungstext(o.name, zeile, von, bis, daten["label"],
                           daten["eigen_prozent"], daten["satz_herkunft"])
    return betreff, text


def _empfaenger(session: Session, zeile: dict) -> dict:
    """Anschrift und Name des Empfängers für das PDF — aus dem Tanknutzer,
    soweit vorhanden. Eine noch nicht angelegte Person hat keine Anschrift; dann
    steht nur ihr Name."""
    empf = {"name": zeile["name"], "email": zeile.get("email", ""),
            "strasse": "", "plz": "", "ort": ""}
    n = session.get(Tanknutzer, zeile["nutzer_id"]) if zeile.get("nutzer_id") else None
    if n is not None:
        empf.update(strasse=n.strasse or "", plz=n.plz or "", ort=n.ort or "",
                    kontoinhaber=n.kontoinhaber or "", iban=n.iban or "")
    return empf


def _quartal_verlauf(session: Session, o: Objekt, von: date, bis: date,
                     aktiv: set[int] | None = None) -> tuple[list[dict], dict]:
    """Die Monatszeilen des Quartals plus ihre Summe — die Grundlage von
    Diagramm und Tabelle im PDF.

    `aktiv` grenzt auf die nicht abgewählten Monate ein (N169), damit ein
    ausgeschlossener Monat auch aus Diagramm, Tabelle und Summe des PDF
    verschwindet — nicht nur aus dem Rechnungsbetrag."""
    posten, _, _ = _posten_holen(session, o, von, bis)
    if aktiv is not None:
        posten = [p for p in posten if p.tag is None or p.tag.month in aktiv]
    monate = [z for z in verlauf(posten, von, bis)
              if aktiv is None or z["monat"] in aktiv]
    return monate, verlauf_summe(monate)


def _benzin_verbrauch(session: Session, modell: str) -> float | None:
    """N177 — der Verbrauch eines vergleichbaren Benziners (l/100km) zum
    E-Auto-Modell, für den Kostenvergleich im PDF.

    Erst im Cache nachsehen (je Modell einer), sonst die KI fragen und einen
    plausiblen Wert merken. Scheitert die Ermittlung, gibt es **keinen**
    Vergleich (``None``) statt einer erfundenen Zahl — der einzige Netz-Aufruf
    liegt in :func:`eauto.verbrauch_benzin_ermitteln` und wirft nie."""
    name = " ".join((modell or "").split())
    if not name:
        return None
    key = f"{S_BENZIN}:{name.casefold()}"
    roh = _lies(session, key)
    if roh:
        try:
            return float(roh)
        except ValueError:
            pass
    verbrauch, _hinweis = eauto.verbrauch_benzin_ermitteln(
        name, schluessel=ki_key(session), ki_modell=ki_modell(session))
    if verbrauch is not None:
        _setze(session, key, str(verbrauch))
        session.commit()
    return verbrauch


def _pdf_und_name(session: Session, o: Objekt, daten: dict,
                  zeile: dict) -> tuple[bytes, str]:
    """Das Quartals-PDF eines Nutzers und sein Dateiname — die eine Stelle, die
    das PDF baut. Ansehen (`abrechnung.pdf`) und Versand-Anhang teilen sie sich.

    Setzt einen ermittelten Satz und einen Betrag voraus; die Aufrufer prüfen
    das vorher (kein PDF über 0 €)."""
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    monate, summe = _quartal_verlauf(session, o, von, bis,
                                     set(daten.get("monate_aktiv") or []) or None)
    satz = {"netz": daten["satz_netz"], "eigen": daten["satz_eigen"],
            "misch": daten["satz"], "herkunft": daten["satz_herkunft"],
            "grund": daten["satz_grund"], "rabatt": daten["satz_rabatt"]}
    # N170 — hat der Nutzer ein E-Auto mit Verbrauch, trägt das PDF km und
    # Preis/100 km statt der Netz/PV/Akku-Spalten; ohne bleibt es beim Alten.
    verbrauch = zeile.get("verbrauch_kwh_100km") or 0.0
    ea = None
    if verbrauch > 0:
        modell = zeile.get("e_auto_modell", "")
        ea = {"modell": modell, "verbrauch": verbrauch, "satz": daten["satz"]}
        # N177 — der Kosten-Benzinvergleich: realer Verbrauch eines
        # vergleichbaren Benziners (KI) gegen den echten E-Auto-Preis je 100 km.
        # Ohne belastbaren Benzinwert entfällt der Vergleich (None).
        ea["benzin"] = eauto.benzin_vergleich(
            _benzin_verbrauch(session, modell),
            zeile.get("preis_100km"), zeile.get("km"))
    konto = {"bank": o.bank, "iban": o.iban, "kontoinhaber": o.kontoinhaber}
    inhalt = tankabrechnung_pdf(o.name, _empfaenger(session, zeile),
                                daten["label"], von, bis, monate, summe, satz,
                                zeile["kwh"], zeile["betrag"], eauto=ea,
                                konto=konto)
    return inhalt, tank_pdf_dateiname(o.name, daten["label"], zeile["name"])
