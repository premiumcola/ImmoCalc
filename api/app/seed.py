"""Seed mit den zwei echten Objekten (Musterstraße 5, Beispielweg 6a)."""
from datetime import date
from sqlmodel import Session, select
from .models import (Objekt, Einheit, Partei, Kostenart, Zeitraum,
                     Kostenposition, Vorauszahlung, Dokument, Miete, Kredit,
                     Versicherung, Zahlung)


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
        s.add(Kostenposition(zeitraum_id=z1.id, kostenart="Müll", betrag=0.0,
              schluessel="personen", wertquelle="Scan", status="offen",
              anteile={"Partei OG": 2, "WG": 3, "Büro": 1}))
        for p, v in [("Partei OG", 1320.0), ("WG", 1380.0), ("Büro", 1560.0)]:
            s.add(Vorauszahlung(zeitraum_id=z1.id, partei=p, betrag=v))
        for art, jahr, name in [
            ("Nebenkosten", 2025, "2025_Nebenkosten_Wasser-Stadtwerke.pdf"),
            ("Nebenkosten", 2025, "2025_Nebenkosten_Hausmeister-Rechnung.pdf"),
        ]:
            s.add(Dokument(pfad=f"/[010]_Immobilien/Musterstraße 5/60_Nebenkosten/{name}",
                           dateiname=name, groesse=184_000, objekt_id=laufer.id,
                           zeitraum_id=z1.id, kategorie=art, jahr=jahr,
                           status="zugeordnet", erkannt_am=date(2025, 10, 12)))

        # abgeschlossener Vorjahreszeitraum — zeigt den fertigen Zustand
        z0 = Zeitraum(objekt_id=laufer.id, start=date(2023, 10, 1),
                      ende=date(2024, 9, 30), typ="regulär", status="abgeschlossen")
        s.add(z0); s.commit(); s.refresh(z0)
        for art, betrag, quelle, s35 in [
                ("Wasser", 812.40, "Zähler", False),
                ("Heizöl", 2140.85, "Scan", False),
                ("Grundsteuer", 486.20, "Scan", False),
                ("Müll", 318.60, "Scan", False),
                ("Hausmeisterdienste", 620.00, "Scan", True),
                ("Allgemeinstrom", 244.18, "Scan", False)]:
            s.add(Kostenposition(zeitraum_id=z0.id, kostenart=art, betrag=betrag,
                  schluessel="flaeche", wertquelle=quelle, status="erledigt", s35=s35,
                  anteile={"Partei OG": 78, "WG": 85, "Büro": 40}))
        for p, v in [("Partei OG", 1260.0), ("WG", 1320.0), ("Büro", 1500.0)]:
            s.add(Vorauszahlung(zeitraum_id=z0.id, partei=p, betrag=v))
        for name in ["2024_Nebenkosten_Heizoel-Lieferung.pdf",
                     "2024_Nebenkosten_Grundsteuerbescheid.pdf",
                     "2024_Nebenkosten_Muellgebuehren.pdf"]:
            s.add(Dokument(pfad=f"/[010]_Immobilien/Musterstraße 5/60_Nebenkosten/{name}",
                           dateiname=name, groesse=206_000, objekt_id=laufer.id,
                           zeitraum_id=z0.id, kategorie="Nebenkosten", jahr=2024,
                           status="zugeordnet", erkannt_am=date(2024, 11, 5)))

        # Mieten, Kredit und Versicherung — damit die Auswertung ab Werk
        # etwas zu zeigen hat und der Kostenfluss sichtbar wird.
        for einheit, partei, kalt, nk, stell in [
                ("1. OG", "Partei OG", 780.0, 160.0, 0.0),
                ("2. OG", "WG", 845.0, 175.0, 0.0),
                ("EG / Büro", "Büro", 690.0, 190.0, 0.0),
                ("Garage", "Stellplatz", 0.0, 0.0, 55.0)]:
            s.add(Miete(objekt_id=laufer.id, einheit=einheit, partei=partei,
                        kaltmiete=kalt, nebenkosten_vz=nk, stellplatz=stell,
                        email=f"{partei.lower().replace(' ', '.')}@example.org",
                        telefon="0170 1234567", ab_datum=date(2024, 1, 1)))
        s.add(Kredit(objekt_id=laufer.id, bezeichnung="Ankaufsdarlehen",
                     bank="Sparkasse", restschuld=212_400.0, zinssatz=3.4,
                     rate_monatlich=980.0, zinsbindung_bis=date(2031, 6, 30)))
        s.add(Versicherung(objekt_id=laufer.id, art="Gebäude", anbieter="Provinzial",
                           police_nr="GB-4412-9", jahresbeitrag=742.0))
        for jahr in (2025, 2026):
            s.add(Zahlung(objekt_id=laufer.id, jahr=jahr, art="Grundsteuer",
                          kategorie="Steuer", betrag=486.20))
            s.add(Zahlung(objekt_id=laufer.id, jahr=jahr, art="Instandhaltung",
                          kategorie="Instandhaltung", betrag=1250.0))

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
