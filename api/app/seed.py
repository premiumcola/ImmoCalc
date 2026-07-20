"""Seed mit den zwei echten Objekten (Musterstraße 5, Beispielweg 6a)."""
from datetime import date
from sqlmodel import Session, select
from .models import (Objekt, Einheit, Partei, Kostenart, Zeitraum,
                     Kostenposition, Vorauszahlung)


def seed(engine):
    with Session(engine) as s:
        if s.exec(select(Objekt)).first():
            return  # bereits geseedet

        # ---------------- Objekt 1: Musterstraße 5 ----------------
        laufer = Objekt(slug="obj-a", name="Musterstraße 5", ort="Mixed-Use · 7 Einheiten",
                        typ="lg-mfhB", nutzung="Gemischt", turnus="individuell", start_monat=10)
        s.add(laufer); s.commit(); s.refresh(laufer)
        for b, art, fl in [("1. OG", "Wohnen", 78), ("2. OG", "WG", 85),
                           ("EG / Büro", "Gewerbe", 40), ("Garage", "Stellplatz", None)]:
            s.add(Einheit(objekt_id=laufer.id, bezeichnung=b, nutzungsart=art, flaeche=fl))
        for name in ["Partei OG", "WG", "Büro"]:
            s.add(Partei(objekt_id=laufer.id, name=name, personen=2))
        for name, aktiv, s35 in [("Wasser", True, False), ("Heizöl", True, False),
                ("Grundsteuer", True, False), ("Müll", True, False), ("Kaminkehrer", True, True),
                ("Hausmeisterdienste", True, True), ("Gartenwasser", True, False),
                ("Allgemeinstrom", True, False), ("Gebäudeversicherung", True, False),
                ("Aufzug", False, False), ("Straßenreinigung / Winterdienst", False, True)]:
            s.add(Kostenart(objekt_id=laufer.id, name=name, aktiv=aktiv, s35=s35))
        z1 = Zeitraum(objekt_id=laufer.id, start=date(2024,10,1), ende=date(2025,9,30),
                      typ="regulär", status="in Arbeit")
        s.add(z1); s.commit(); s.refresh(z1)
        # Wasser 847.52 nach interpoliertem Verbrauch (Büro / R&A inkl. Garten / WG-Rest)
        s.add(Kostenposition(zeitraum_id=z1.id, kostenart="Wasser", betrag=847.52,
              schluessel="verbrauch", wertquelle="Zähler", status="erledigt",
              anteile={"Büro": 4.1398, "Partei OG": 59.3016, "WG": 79.136}))
        s.add(Kostenposition(zeitraum_id=z1.id, kostenart="Hausmeisterdienste", betrag=640.0,
              schluessel="bewohnermonate", wertquelle="Scan", status="erledigt", s35=True,
              anteile={"Partei OG": 12, "WG": 12, "Büro": 12}))
        s.add(Kostenposition(zeitraum_id=z1.id, kostenart="Grundsteuer", betrag=0.0,
              schluessel="flaeche", wertquelle="Scan", status="offen",
              anteile={"Partei OG": 78, "WG": 85, "Büro": 40}))
        for p, v in [("Partei OG", 1320.0), ("WG", 1380.0), ("Büro", 1560.0)]:
            s.add(Vorauszahlung(zeitraum_id=z1.id, partei=p, betrag=v))

        # ---------------- Objekt 2: Beispielweg 6a ----------------
        einh = Objekt(slug="obj-b", name="Beispielweg 6a",
                      ort="Musterstadt · 1 Wohnung", typ="lg-wohnung", nutzung="Wohnen",
                      turnus="kalender", start_monat=1)
        s.add(einh); s.commit(); s.refresh(einh)
        s.add(Einheit(objekt_id=einh.id, bezeichnung="1. OG", nutzungsart="Wohnen", flaeche=95))
        s.add(Partei(objekt_id=einh.id, name="Partei Wohnung", personen=2))
        for name, aktiv, s35 in [("Heizkosten", True, False), ("Warmwasser", True, False),
                ("Wasser", True, False), ("Abwasser", True, False), ("Niederschlagswasser", True, False),
                ("Müll", True, False), ("Versicherungen", True, False), ("Hausmeister", True, True),
                ("Rauchwarnmelder", True, True), ("Kaltwasserzähler", True, False),
                ("Allgemeinstrom", True, False), ("Grundsteuer", True, False),
                ("Bankspesen", False, False), ("Gartenpflege", False, True)]:
            s.add(Kostenart(objekt_id=einh.id, name=name, aktiv=aktiv, s35=s35))
        z2 = Zeitraum(objekt_id=einh.id, start=date(2024,1,1), ende=date(2024,12,31),
                      typ="regulär", status="abgeschlossen")
        s.add(z2); s.commit(); s.refresh(z2)
        einzel = [("Heizkosten",925.13,"extern",False),("Warmwasser",282.70,"extern",False),
                  ("Wasserkosten",94.22,"Scan",False),("Abwasserkosten",130.11,"Scan",False),
                  ("Müllgebühren",152.14,"Scan",False),("Versicherungen",406.93,"Scan",False),
                  ("Hausmeister",722.43,"Scan",True),("Rauchwarnmelder + Prüfung",22.49,"Scan",True),
                  ("Grundsteuer",116.33,"Scan",False),("Kaltwasserzähler",51.41,"Scan",False),
                  ("Allgemeinstrom",217.44,"Scan",False)]
        for art, betrag, q, s35 in einzel:
            s.add(Kostenposition(zeitraum_id=z2.id, kostenart=art, betrag=betrag,
                  schluessel="individuell", wertquelle=q, status="erledigt", s35=s35,
                  anteile={"Partei Wohnung": 1.0}))
        s.add(Vorauszahlung(zeitraum_id=z2.id, partei="Partei Wohnung", betrag=2640.0))
        s.commit()
