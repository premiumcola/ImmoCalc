"""Live-Beitrag der E-Tankstelle zur PV-Amortisation (N200/N216).

Bis N200 kam der E-Tanken-Ertrag aus ``Tankladung.kwh × Tankladung.preis``. Der
Handpreis ist aber seit N148 stillgelegt (die Preisbildung ist abgeleitet): in
den echten Daten steht dort 0, und die Ladungen liegen ohnehin in der Wallbox,
nicht als ``Tankladung``-Sätze. Der Verlauf zeigte für 2025/2026 deshalb 0,
obwohl an der Station längst geladen wird.

Was der PV-ANLAGE aus dem Laden zufließt, ist der **eigene** Strom (PV + Akku),
den die Fahrer zum abgeleiteten Eigen-Satz zahlen: dieser Strom hat die Anlage
nichts gekostet, jede Kilowattstunde davon trägt die Anschaffung ab. Der
Netzanteil ist ein Durchlaufposten (er deckt den Zukauf) und zählt hier NICHT.
Menge und Satz kommen aus derselben Quelle wie die Abrechnung der E-Tankstelle
(``routers.tankstelle``): die Wallbox, ersatzweise die erfassten Ladungen.

Der Zugriff auf :mod:`app.routers.tankstelle` bleibt bewusst LAZY: die dortigen
Test-Monkeypatches (``tk._posten_holen``, ``tk.satz_ableiten``) müssen weiter
greifen, und ein Import am Modulkopf würde einen Zirkelbezug erzeugen.
"""
from __future__ import annotations

from datetime import date

from sqlmodel import Session

from ..models import Objekt


def tanken_beitrag_eur(eigen_kwh: float | None,
                       eigen_satz: float | None) -> float:
    """Was der geladene Eigenstrom (PV + Akku) zur Amortisation beiträgt: Menge
    mal abgeleitetem Eigen-Satz.

    Fehlt die Menge (die Aufteilung Netz/eigen ist unbekannt) oder der Satz
    (keine ableitbaren Stromkosten), ist der Beitrag 0 — nie eine erfundene
    Zahl. Genau dieselbe Zurückhaltung wie beim Satz selbst (N148)."""
    if not eigen_kwh or not eigen_satz:
        return 0.0
    return round(float(eigen_kwh) * float(eigen_satz), 2)


def _tanken_je_jahr(session: Session, o: Objekt) -> dict[int, dict]:
    """Der E-Tanken-Beitrag je Kalenderjahr — aus den tatsächlich geladenen
    Mengen, nicht aus einem Handpreis (N200).

    Je Jahr mit Ladung: die eigene Lademenge (PV + Akku) aus dem Verlauf der
    E-Tankstelle und der für dieses Jahr abgeleitete Eigen-Satz. Wallbox zuerst,
    ersatzweise die erfassten Ladungen — dieselbe Quelle wie die Abrechnung, mit
    denselben ehrlichen Lücken: ist die Aufteilung eines Jahres unbekannt oder
    fehlt der Satz, bleibt `eur` 0 und die Menge sagt, warum.

    Rückgabe: {Jahr: {eigen_kwh, extern_kwh, geladen_kwh, satz_eigen, satz_netz,
    eur, quelle, satz_grund}}. Leer, wenn nie geladen wurde."""
    # Lazy: die Test-Monkeypatches greifen an `app.routers.tankstelle`; ein
    # Import am Modulkopf würde außerdem einen Zirkelbezug erzeugen.
    from ..routers import tankstelle as tk

    von, bis = tk.suchfenster()
    posten, quelle, _hinweis = tk._posten_holen(session, o, von, bis)
    out: dict[int, dict] = {}
    for jahr in tk.jahre_mit_verbrauch(posten):
        jvon, jbis = date(jahr, 1, 1), date(jahr, 12, 31)
        monate = tk.verlauf([p for p in posten
                             if p.tag and jvon <= p.tag <= jbis], jvon, jbis)
        summe = tk.verlauf_summe(monate)
        eigen_kwh = summe.get("eigen_kwh")
        extern_kwh = summe.get("extern_kwh")
        satz = tk.satz_ableiten(session, o.id, jvon, jbis, extern_kwh, eigen_kwh)
        out[jahr] = {
            "eigen_kwh": eigen_kwh,
            "extern_kwh": extern_kwh,
            "geladen_kwh": summe.get("kwh"),
            "satz_eigen": satz.eigen,
            "satz_netz": satz.netz,
            "eur": tanken_beitrag_eur(eigen_kwh, satz.eigen),
            "quelle": quelle,
            "satz_grund": satz.grund,
        }
    return out
