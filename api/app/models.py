"""Datenmodell (SQLModel/SQLite) — abgeleitet aus dem ER-Diagramm."""
from __future__ import annotations
from datetime import date
from typing import Optional
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


class Objekt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    ort: str = ""
    typ: str = "lg-mfhA"          # Logo-/Gebäudetyp
    nutzung: str = "Wohnen"
    turnus: str = "kalender"      # 'kalender' | 'individuell'
    start_monat: int = 1
    aktiv: bool = True
    # Stammdaten für die Auswertung (alles optional — Objekte funktionieren auch ohne)
    strasse: str = ""
    plz: str = ""
    flaeche: Optional[float] = None
    kaufpreis: Optional[float] = None
    kaufdatum: Optional[date] = None
    verkehrswert: Optional[float] = None
    nc_ordner: str = ""           # verknüpfter Nextcloud-Ordner
    # Konto, von dem die Kosten dieses Objekts abgebucht werden
    bank: str = ""
    iban: str = ""
    kontoinhaber: str = ""


class Einheit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None          # Wohn-/Nutzfläche in m²
    terrasse: Optional[float] = None         # Terrasse/Balkon in m²
    nebenflaeche: Optional[float] = None     # Keller, Abstellraum in m²
    stellplaetze: int = 0


class Partei(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    name: str
    einzug: Optional[date] = None
    auszug: Optional[date] = None
    personen: int = 1


class Kostenart(SQLModel, table=True):
    """Katalog + Konfiguration: was gehört je Objekt zur Jahresabrechnung.

    Jede Kostenart hat ihren eigenen Turnus — der Stromabrechnungszeitraum
    kann Juni–Juni laufen, während das Objekt nach Kalenderjahr abrechnet.
    `beleg_monat` sagt, wann die Jahresabrechnung des Versorgers erfahrungs-
    gemäß eintrifft; daraus wird die Erinnerung abgeleitet."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    name: str
    umlagefaehig: bool = True
    s35: bool = False
    aktiv: bool = True
    turnus_start_monat: int = 1        # 1 = Januar; eigener Zeitraum der Kostenart
    beleg_monat: Optional[int] = None  # Monat, in dem die Abrechnung vorliegt
    erinnerung_tage: int = 7           # so viele Tage danach erinnern
    lieferant: str = ""
    kundennummer: str = ""


class Zeitraum(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    start: date
    ende: date
    typ: str = "regulär"          # 'regulär' | 'Rumpf' | 'Zwischen'
    status: str = "in Arbeit"     # 'in Arbeit' | 'abgeschlossen'


class Kostenposition(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    zeitraum_id: int = Field(foreign_key="zeitraum.id", index=True)
    kostenart: str
    betrag: float
    schluessel: str = "individuell"
    wertquelle: str = "manuell"   # 'Scan'|'Zähler'|'extern'|'manuell'
    status: str = "erledigt"      # 'erledigt' | 'offen'
    s35: bool = False
    # Partei -> Gewicht (Verbrauch/Fläche/Personen/Bewohnermonate/%/1)
    anteile: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Vorauszahlung(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    zeitraum_id: int = Field(foreign_key="zeitraum.id", index=True)
    partei: str
    betrag: float


# --------------------------------------------------------------------------
# Immobilien-Informationen jenseits der Nebenkostenabrechnung.
# Speisen die Auswertung: Einnahmen (Miete) gegen Ausgaben (Kredit,
# Versicherung, Steuer) je Objekt und Jahr.
# --------------------------------------------------------------------------

class Versicherung(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    art: str                       # 'Gebäude' | 'Haftpflicht' | 'Elementar' | ...
    anbieter: str = ""
    police_nr: str = ""
    jahresbeitrag: float = 0.0
    versicherungswert: Optional[float] = None
    beginn: Optional[date] = None
    ende: Optional[date] = None
    umlagefaehig: bool = True
    notiz: str = ""


class Miete(SQLModel, table=True):
    """Ein Eintrag je Mietverhältnis/Mietstand. Historie entsteht durch mehrere
    Einträge mit unterschiedlichem `ab_datum` — daraus wird der Mietverlauf.
    Ein Eintrag mit `bis_datum` ist ein beendetes Mietverhältnis und bleibt als
    Teil der Mieterhistorie erhalten.

    Die Kontaktdaten hängen am Mietverhältnis, nicht an der Einheit: Beim
    Mieterwechsel bleibt so nachvollziehbar, an wen welche Abrechnung ging."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    einheit: str = ""              # Bezeichnung der Einheit, leer = ganzes Objekt
    partei: str = ""
    kaltmiete: float = 0.0
    nebenkosten_vz: float = 0.0    # monatliche Vorauszahlung
    stellplatz: float = 0.0
    sonstige: float = 0.0          # Möblierung, Werbefläche, Sonstiges
    ab_datum: date
    bis_datum: Optional[date] = None
    # Kontakt für den Versand der Abrechnung
    email: str = ""
    telefon: str = ""
    anschrift: str = ""
    personen: int = 1
    kaution: Optional[float] = None
    notiz: str = ""


class Kredit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    bezeichnung: str
    bank: str = ""
    darlehensnummer: str = ""
    urspruenglich: Optional[float] = None
    restschuld: Optional[float] = None
    zinssatz: Optional[float] = None       # Prozent p. a.
    rate_monatlich: float = 0.0            # Annuität
    zinsbindung_bis: Optional[date] = None
    beginn: Optional[date] = None
    notiz: str = ""


class Zahlung(SQLModel, table=True):
    """Steuer- und sonstige Zahlungen je Jahr — Grundlage für die Steuer-
    zusammenstellung und die Auswertung."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    jahr: int = Field(index=True)
    art: str                       # 'Grundsteuer' | 'Einkommensteuer' | 'Instandhaltung' | ...
    kategorie: str = "Steuer"      # 'Steuer' | 'Kredit' | 'Instandhaltung' | 'Sonstiges'
    betrag: float = 0.0
    absetzbar: bool = True
    notiz: str = ""


class Einstellung(SQLModel, table=True):
    """Schlüssel/Wert-Ablage für Verbindungsdaten. Geheimnisse werden nie
    über die API zurückgegeben."""
    schluessel: str = Field(primary_key=True)
    wert: str = ""


class Dokument(SQLModel, table=True):
    """Datei in der Nextcloud. `status` steuert die Inbox: was noch nicht
    zugeordnet ist, wartet in der App auf eine Entscheidung."""
    id: Optional[int] = Field(default=None, primary_key=True)
    pfad: str = Field(index=True)          # WebDAV-Pfad relativ zum Benutzer-Root
    dateiname: str
    groesse: int = 0
    objekt_id: Optional[int] = Field(default=None, foreign_key="objekt.id", index=True)
    zeitraum_id: Optional[int] = Field(default=None, foreign_key="zeitraum.id")
    kategorie: str = ""                    # entspricht der Kostenart
    jahr: Optional[int] = None
    status: str = "neu"                    # 'neu' | 'zugeordnet'
    erkannt_am: Optional[date] = None
