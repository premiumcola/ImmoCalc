"""Die Rechenlogik der PV-Amortisation je Jahr und Kategorie (N127/N200/N204/N216).

Anders als ``/pv/amortisation`` (rechnet aus den Strom-Eingaben) zieht der
Verlauf sein Geld aus der NEBENKOSTENABRECHNUNG des Objekts. Drei Quellen, und
ausdrücklich nur echte Zahlungsflüsse — eine kalkulatorische „Ersparnis
Zukauf" ist kein Ertrag:

  1. PV-Strom, den die Mieter bezahlt haben — Kostenpositionen mit
     ``herkunft == "eigen"``.
  2. Einspeisevergütung — Positionen einer NICHT umlagefähigen Kostenart. Sie
     steht im Zeitraum, damit sie zeitlich richtig sitzt, wird aber nicht auf
     die Mieter verteilt (siehe ``objekte.abrechnung_endpoint``, N125).
  3. E-Tanken — live abgeleitet (siehe :mod:`.tanken_bridge`), nicht mehr aus
     ``Tankladung.preis`` (seit N148 stillgelegt).

N204 — die kWh-Basis folgt exakt der €-Basis: eine spätere Eigenverbrauchsmenge
ohne abgerechnete Kosten darf den €/kWh-Wert NICHT verwässern.
"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import Kostenart, Kostenposition, Stromjahr, Zeitraum
from ..routers.objekte import zeitraum_label_jahr

_HERKUNFT_EIGEN = "eigen"
_QUELLEN_LEER: dict[str, float] = {"pv_strom": 0.0, "einspeisung": 0.0,
                                   "tanken": 0.0}

# N200 — die Kategorien der Amortisation, unter denen Grafik, Prozent-Aufteilung
# und Ringdiagramm dasselbe benennen. Dieselben drei Quellen wie `_QUELLEN_LEER`.
_KAT_LABEL: dict[str, str] = {"pv_strom": "PV-Eigenverbrauch",
                              "einspeisung": "Netz-Einspeisung",
                              "tanken": "E-Tanken"}


def _kat_beitrag(z: dict, feld: str, vorlauf_jahr: int | None) -> float:
    """Der €-Beitrag EINES Jahres zu einer Kategorie: der Jahreswert und, im
    Vorlaufjahr, der Vorlaufanteil — aufgeschlüsselt zur jeweiligen Kategorie,
    sonst ganz auf PV-Strom (N174).

    Eine einzige Quelle für Tabelle/Summe (`_kat_eur`) UND kWh-Basis
    (`_kategorie_kwh`), damit € und kWh exakt dieselben Jahre zählen (N204)."""
    w = float(z.get(feld) or 0.0)
    if z["jahr"] == vorlauf_jahr:
        teile = z.get("vorlauf_teile")
        if teile:
            w += float(teile.get(feld) or 0.0)
        elif feld == "pv_strom":
            w += float(z.get("vorlauf") or 0.0)
    return round(w, 2)


def _kategorie_kwh(session: Session, objekt_id: int, jahre: list[dict],
                   vorlauf_jahr: int | None,
                   tanken: dict[int, dict]) -> dict[str, float | None]:
    """Die physische Energiemenge je Kategorie — die Grundlage des Ringdiagramms
    und von `eur_pro_kwh` (N200/N204).

    Entscheidend (N204): die kWh zählen NUR die Jahre, deren Kosten auch
    verrechnet wurden — also die Jahre, die zu derselben Kategorie einen
    abgerechneten € beitragen (`_kat_beitrag`), samt Vorlaufjahr für seinen
    Vorlaufanteil. Sonst verwässerte die Eigenverbrauchsmenge noch nicht
    abgerechneter Jahre (z. B. 2025/2026) den €/kWh-Wert: ein abgerechnetes Jahr
    an € geteilt durch mehrere Jahre an kWh ergab einen viel zu niedrigen Satz.
    Die kWh-Basis folgt damit exakt der €-Basis aus `_ertraege_je_jahr`/`_kat_eur`.

    PV-Eigenverbrauch ist der im Haus direkt genutzte Solar-/Akku-Strom
    (`solar_kwh + akku_kwh`), Netz-Einspeisung die ins Netz gegebene Menge
    (`einspeisung_kwh`) — beide je Jahr aus dem `Stromjahr`, gekeyt mit demselben
    Label-Jahr wie die Erträge. E-Tanken ist die eigene Lademenge (PV + Akku) aus
    der Station, die ohnehin schon je abgerechnetem Jahr vorliegt.

    Eine Kategorie, deren abgerechnete Jahre keine Menge hergeben (z. B. ein
    Vorlauf-€ ohne erfasste kWh), ergibt `None` — nie eine erfundene 0 und nie
    eine aus unabgerechneten Jahren zusammengeliehene Zahl."""
    kwh_jahr: dict[int, dict[str, float]] = {}
    for sj in session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == objekt_id)).all():
        kwh_jahr[sj.jahr] = {
            "pv_strom": float(getattr(sj, "solar_kwh", 0.0) or 0.0)
                        + float(getattr(sj, "akku_kwh", 0.0) or 0.0),
            "einspeisung": float(getattr(sj, "einspeisung_kwh", 0.0) or 0.0),
        }

    def menge(feld: str) -> float | None:
        total = sum(kwh_jahr.get(z["jahr"], {}).get(feld, 0.0)
                    for z in jahre if _kat_beitrag(z, feld, vorlauf_jahr) > 0)
        return round(total, 2) or None

    # E-Tanken liegt bereits je abgerechnetem Jahr vor (Lademenge + abgeleiteter
    # Satz aus `_tanken_je_jahr`); die eigene kWh bleibt sichtbar, auch wenn ein
    # Jahr keinen ableitbaren Satz hat (dann € 0 auf echte kWh, nichts erfunden).
    tank = round(sum(t["eigen_kwh"] for t in tanken.values()
                     if t.get("eigen_kwh")), 2)
    return {"pv_strom": menge("pv_strom"),
            "einspeisung": menge("einspeisung"),
            "tanken": tank or None}


def _kat_eur(jahre: list[dict], feld: str, vorlauf_jahr: int | None) -> float:
    """Der Amortisations-Beitrag EINER Kategorie über alle Jahre — die Summe der
    Jahresbeiträge (`_kat_beitrag`) inklusive des einmaligen Vorlaufs.

    So ist die Summe der drei Kategorien exakt der kumulierte Ertrag — kein
    Cent liegt neben der Kurve."""
    return round(sum(_kat_beitrag(z, feld, vorlauf_jahr) for z in jahre), 2)


def _kategorien(jahre: list[dict], vorlauf_jahr: int | None,
                kwh: dict[str, float | None]) -> dict:
    """N200 — die Aufteilung der Amortisation auf ihre drei Kategorien: je
    Kategorie der Beitrag in €, sein Anteil in % (woraus die Amortisation
    besteht) und die physische Energiemenge in kWh dahinter.

    `eur_pro_kwh` macht den Kern sichtbar: die Einspeisung bringt viele kWh zu
    wenigen Cent, Direktnutzung und E-Tanken weniger kWh zu einem Vielfachen je
    kWh. Der Prozentsatz ist der €-Anteil an der Amortisation, das Ringdiagramm
    zeigt die kWh — zwei Blicke auf dieselben drei Kategorien."""
    eur = {f: _kat_eur(jahre, f, vorlauf_jahr)
           for f in ("pv_strom", "einspeisung", "tanken")}
    gesamt_eur = round(sum(eur.values()), 2)
    posten = []
    for feld in ("pv_strom", "einspeisung", "tanken"):
        e, k = eur[feld], kwh.get(feld)
        posten.append({
            "feld": feld, "label": _KAT_LABEL[feld],
            "eur": e, "kwh": k,
            "prozent": round(e / gesamt_eur * 100, 1) if gesamt_eur > 0 else None,
            "eur_pro_kwh": round(e / k, 4) if k else None,
        })
    gesamt_kwh = round(sum(p["kwh"] for p in posten if p["kwh"]), 2) or None
    return {"gesamt_eur": gesamt_eur, "gesamt_kwh": gesamt_kwh, "posten": posten}


def _nicht_umlagefaehig(session: Session, objekt_id: int) -> set[str]:
    """Die Namen der nicht umlagefähigen Kostenarten eines Objekts, klein
    geschrieben — der Vergleichsschlüssel für die Positionen."""
    return {k.name.strip().lower() for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == objekt_id)).all()
        if not k.umlagefaehig}


def _ertraege_je_jahr(session: Session, objekt_id: int,
                      tanken: dict[int, dict]) -> dict[int, dict]:
    """Die drei Ertragsquellen je Kalenderjahr einsammeln.

    Das Jahr eines Zeitraums ist sein Label-Jahr (`zeitraum_label_jahr`) —
    dasselbe Jahr, unter dem die Abrechnung überall sonst geführt wird. Offene
    Positionen (Betrag noch nicht da) bleiben außen vor, genau wie in der
    Abrechnung selbst. Eine Position zählt nur einmal: ist sie „eigen", ist sie
    PV-Strom, sonst gegebenenfalls Einspeisevergütung.

    N200 — der E-Tanken-Beitrag kommt nicht mehr aus `Tankladung.preis` (seit
    N148 stillgelegt), sondern live aus der eigenen Lademenge zum abgeleiteten
    Satz (`tanken`, vorberechnet in `_tanken_je_jahr`). Ein Jahr, in dem nur
    geladen wurde, bekommt trotzdem seine Zeile."""
    nicht_umlegen = _nicht_umlagefaehig(session, objekt_id)
    jahr_von_zeitraum = {
        z.id: zeitraum_label_jahr(z.start, z.ende) for z in session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all()}
    werte: dict[int, dict] = {j: dict(_QUELLEN_LEER)
                              for j in jahr_von_zeitraum.values()}
    if jahr_von_zeitraum:
        positionen = session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id.in_(list(jahr_von_zeitraum)))).all()
        for p in positionen:
            if p.status != "erledigt":
                continue
            eintrag = werte[jahr_von_zeitraum[p.zeitraum_id]]
            betrag = round(float(p.betrag or 0), 2)
            if (p.herkunft or "").strip().lower() == _HERKUNFT_EIGEN:
                eintrag["pv_strom"] = round(eintrag["pv_strom"] + betrag, 2)
            elif (p.kostenart or "").strip().lower() in nicht_umlegen:
                eintrag["einspeisung"] = round(eintrag["einspeisung"] + betrag, 2)
    # N200 — der live abgeleitete E-Tanken-Beitrag. Ladungen hängen am Jahr,
    # nicht am Zeitraum — ein Jahr, in dem nur geladen wurde, bekommt trotzdem
    # eine Zeile, sonst ginge der Erlös verloren.
    for jahr, t in tanken.items():
        eintrag = werte.setdefault(jahr, dict(_QUELLEN_LEER))
        eintrag["tanken"] = round(eintrag["tanken"] + float(t.get("eur") or 0.0), 2)
    return werte


def _abrechnungsjahre(session: Session, objekt_id: int) -> list[int]:
    """Die Label-Jahre der Abrechnungszeiträume — dieselben Jahre, unter denen
    die Abrechnung überall sonst geführt wird."""
    return [zeitraum_label_jahr(z.start, z.ende) for z in session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all()]


def _vorlauf_jahr(session: Session, objekt_id: int,
                  quellen: dict[int, dict]) -> int | None:
    """N153b — das Jahr, unter dem der Vorlauf steht: das Jahr VOR dem ersten
    Abrechnungsjahr.

    Beim Nutzer beginnt die erste Abrechnung am 01.10.2024 und läuft als Jahr
    2025 — der Vorlauf gehört damit auf 2024. Abgeleitet aus den Daten, nie
    gesetzt. Gibt es noch keinen Zeitraum, tut es das erste Jahr mit Erträgen;
    gibt es gar nichts, gibt es auch keine Zeile."""
    jahre = _abrechnungsjahre(session, objekt_id) or list(quellen)
    return min(jahre) - 1 if jahre else None
