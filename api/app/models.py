"""Datenmodell (SQLModel/SQLite) — abgeleitet aus dem ER-Diagramm."""
from __future__ import annotations
from datetime import date
from typing import Optional
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field

# Ein Grundstück ist kein Haus mit weniger Feldern, sondern ein eigener Fall:
# keine Einheiten, keine Mieter, keine Nebenkostenabrechnung. Erkannt wird es
# am Logo-/Gebäudetyp, damit nichts Zusätzliches gepflegt werden muss.
GRUNDSTUECK = "lg-grundstueck"


def ist_grundstueck(objekt) -> bool:
    """Ist dieses Objekt ein (landwirtschaftliches) Grundstück?"""
    return getattr(objekt, "typ", "") == GRUNDSTUECK


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
    # Amtlicher Gemeindeschlüssel. Bleibt leer; erkannt wird die Gemeinde
    # sonst über PLZ und Ortsname (`kappungsgrenze.gemeinde_fuer`). Das Feld
    # ist die Notbremse für Fälle, in denen beides nicht trägt — etwa weil
    # eine Verordnung die Gemeinde anders schreibt als der Ort im Objekt.
    ags: str = ""
    flaeche: Optional[float] = None
    kaufpreis: Optional[float] = None
    kaufdatum: Optional[date] = None
    verkehrswert: Optional[float] = None
    nc_ordner: str = ""           # verknüpfter Nextcloud-Ordner
    # Konto, von dem die Kosten dieses Objekts abgebucht werden
    bank: str = ""
    iban: str = ""
    kontoinhaber: str = ""
    # ----------------------------------------------------------------------
    # Grundstück (typ == GRUNDSTUECK). Bei jedem anderen Objekt bleiben diese
    # Felder leer und werden nirgends gezeigt.
    #
    # `grundstueck_flaeche` ist bewusst NICHT `flaeche`: letzteres ist die
    # Wohn-/Nutzfläche und geht in den Verteilungsschlüssel „Fläche" ein. Eine
    # Ackerfläche dort einzutragen würde jede Nebenkostenabrechnung verfälschen.
    #
    # Der Grundstückswert ist der `verkehrswert` weiter oben — beim Grund und
    # Boden ist das derselbe Wert. So rechnet die Vermögensübersicht ein
    # Grundstück mit, ohne dass sie von ihm wissen muss; der Preis je m² ergibt
    # sich aus Wert und Fläche und wird deshalb nicht gespeichert.
    # ----------------------------------------------------------------------
    grundstueck_flaeche: Optional[float] = None    # m² Grund und Boden
    grundstueck_nutzungsart: str = ""              # Ackerland | Grünland | Wald | …
    # Wortlaut aus dem Liegenschaftskataster, z. B. „Steigäcker, Waldfläche,
    # Landwirtschaftsfläche" — passt in keine Auswahlliste und steht deshalb frei.
    grundstueck_wirtschaftsart: str = ""
    flurstueck: str = ""
    gemarkung: str = ""
    # Grundsteuer: der Bescheid des Finanzamts weist Wert und Messbetrag aus,
    # den Hebesatz setzt die Gemeinde. Grundsteuer im Jahr = Messbetrag ×
    # Hebesatz / 100 — abgeleitet, nicht gespeichert.
    grundsteuerwert: Optional[float] = None        # § 219 BewG, zum Stichtag
    grundsteuer_messbetrag: Optional[float] = None  # Steuermessbetrag in €
    grundsteuer_hebesatz: Optional[float] = None   # Hebesatz der Gemeinde in %


class Einheit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None          # Wohn-/Nutzfläche in m²
    terrasse: Optional[float] = None         # Terrasse/Balkon in m²
    nebenflaeche: Optional[float] = None     # Keller, Abstellraum in m²
    stellplaetze: int = 0
    # CXCIII: eine Einheit ganz aus der Nebenkostenabrechnung nehmen —
    # selbstgenutzt, separat abgerechnet, gewerblich mit eigenem Zähler. Der
    # Vorgabewert True hält jeden Bestand unverändert; steht er auf False,
    # zählt die Einheit in keinem Verteilungsschlüssel mehr mit.
    nk_abrechnung: bool = True
    # CLXXXVI: ein Verkehrswert je Einheit — nur gepflegt, wo er bekannt ist.
    # Die Vermögenssicht am Haus bleibt maßgeblich, die Einheit ergänzt.
    verkehrswert: Optional[float] = None


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
    # CXCIV: ein Sonderposten, der ganz einer Einheit gehört (Reparatur nur in
    # Wohnung 2, eigener Warmwasserboiler). Ist eine Einheit genannt, geht der
    # Schlüssel leer aus und diese eine Einheit trägt 100 %. Leer = normal,
    # über alle verteilt.
    nur_einheit: str = ""
    wertquelle: str = "manuell"   # 'Scan'|'Zähler'|'extern'|'manuell'
    status: str = "erledigt"      # 'erledigt' | 'offen'
    s35: bool = False
    # Partei -> Gewicht (Verbrauch/Fläche/Personen/Bewohnermonate/%/1)
    anteile: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # CLXXXII: eine Position je Kostenart und Zeitraum bleibt die Regel — auf
    # dieselbe Zeile laufen aber vier Abschlagsrechnungen zu. `betrag` bleibt
    # die Wahrheit, mit der gerechnet wird; hier steht, welcher Teil davon aus
    # verknüpften Belegen stammt. Die Differenz ist das, was von Hand
    # eingetragen wurde — nur so lässt sich ein weiterer Beleg addieren, ohne
    # den Handeintrag zu überschreiben oder doppelt zu zählen.
    beleg_summe: float = 0.0


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
    # Betrag je Turnus. Vorgabe 'jaehrlich' — so bleiben Altbestände korrekt,
    # bei denen das Feld noch als reiner Jahresbeitrag gepflegt wurde.
    jahresbeitrag: float = 0.0
    turnus: str = "jaehrlich"
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
    Mieterwechsel bleibt so nachvollziehbar, an wen welche Abrechnung ging.

    Ein Pachtverhältnis über ein Grundstück ist derselbe Satz: Pächter statt
    Partei, Pachtzins statt Kaltmiete, Turnus meist jährlich statt monatlich.
    Alles, was eine Pacht braucht — Laufzeit, Kontakt, Kaution, Historie beim
    Pächterwechsel — steht hier bereits. Ein zweites, fast gleiches Modell
    daneben hätte nur bedeutet, dass Auswertung, Cashflow und Sicherung jede
    Einnahme künftig an zwei Stellen suchen müssen. Die Oberfläche beschriftet
    die Felder beim Grundstück anders; gespeichert wird derselbe Satz."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    einheit: str = ""              # Bezeichnung der Einheit, leer = ganzes Objekt
    partei: str = ""
    kaltmiete: float = 0.0
    nebenkosten_vz: float = 0.0    # Vorauszahlung je Turnus
    turnus: str = "monatlich"
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


# Vertragsarten unter „Kredite". Ein Bausparvertrag steht dort mit, weil er
# an derselben Immobilie hängt und dieselbe Rate im Monat kostet — gerechnet
# wird er aber umgekehrt: was eingezahlt ist, ist Guthaben, keine Schuld.
DARLEHEN = "Darlehen"
BAUSPARVERTRAG = "Bausparvertrag"
VERTRAGSARTEN = (DARLEHEN, BAUSPARVERTRAG)


def ist_bausparer(kredit) -> bool:
    """Ist dieser Vertrag ein Bausparvertrag (statt eines Darlehens)?

    Grosszügig geprüft: Bestandszeilen haben `art = 'Darlehen'` (Vorgabe der
    Migration), neu angelegte den vollen Namen. Ein leeres Feld ist ein
    Darlehen — so bleibt jede gewachsene Datenbank unverändert richtig."""
    return str(getattr(kredit, "art", "") or "").strip().lower().startswith("bauspar")


class Kredit(SQLModel, table=True):
    """Ein Finanzierungsvertrag am Objekt — Darlehen oder Bausparvertrag.

    Beide teilen sich Bank, Rate, Turnus und Zinssatz; sie unterscheiden sich
    in dem, was der Vertrag über die Jahre aufbaut:

    * **Darlehen** — `restschuld` sinkt, jede Rate besteht aus Zins und
      Tilgung. Die Restschuld mindert das Eigenkapital.
    * **Bausparvertrag** — `angespart` wächst auf `bausparsumme` zu, die Rate
      ist ein Sparbeitrag. Das Guthaben *erhöht* das Eigenkapital, und in der
      Ansparphase gibt es keine Zinslast: der Zinssatz ist ein Habenzins.

    `art` ist additiv und steht auf `Darlehen`, solange niemand etwas anderes
    wählt — jeder Bestand rechnet damit weiter wie bisher."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    bezeichnung: str
    art: str = DARLEHEN                    # 'Darlehen' | 'Bausparvertrag'
    bank: str = ""
    darlehensnummer: str = ""
    urspruenglich: Optional[float] = None
    restschuld: Optional[float] = None
    # --- nur beim Bausparvertrag -----------------------------------------
    # Die Bausparsumme ist das Ziel des Vertrags, `angespart` der Stand bei
    # Beginn. „Noch zu sparen" ist die Differenz und wird nicht gespeichert —
    # sie ergibt sich (siehe `vermoegen.kreditstand`).
    bausparsumme: Optional[float] = None
    angespart: Optional[float] = None
    # ---------------------------------------------------------------------
    zinssatz: Optional[float] = None       # Prozent p. a. (Bausparer: Habenzins)
    rate_monatlich: float = 0.0            # Rate je Turnus (Annuität / Sparrate)
    turnus: str = "monatlich"
    zinsbindung_bis: Optional[date] = None
    beginn: Optional[date] = None
    notiz: str = ""


class Kreditstand(SQLModel, table=True):
    """Der Jahresstand eines Vertrags zum 31.12. — wie ein Zählerstand.

    Beim **Darlehen** ist das die Restschuld: die Bank weist sie immer zum
    31.12. aus, nur dieser Wert lässt sich verlässlich eintragen. Zwischen
    zwei Ständen schreibt `vermoegen.stand_fortschreiben` monatlich fort
    (Rate minus Zinsanteil = Tilgung).

    Beim **Bausparvertrag** steht in derselben Spalte der Sparstand — dieselbe
    Mechanik mit umgekehrtem Vorzeichen: die Rate erhöht das Guthaben, der
    Zins schreibt es zusätzlich fort, und über die Bausparsumme hinaus wächst
    es nicht. Welche der beiden Lesarten gilt, sagt `Kredit.art`; die Spalte
    heisst weiter `restschuld`, weil jede bestehende Zeile eine ist.

    Der nächste eingetragene Stand ist die Wahrheit und setzt die Rechnung
    wieder auf den echten Wert.

    Ein Stand je Kredit und Jahr — ein zweiter ändert den vorhandenen."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kredit_id: int = Field(foreign_key="kredit.id", index=True)
    jahr: int = Field(index=True)          # der Stand gilt zum 31.12. dieses Jahres
    restschuld: float = 0.0                # Bausparer: Sparstand
    notiz: str = ""


class Bewohner(SQLModel, table=True):
    """Eine Person in einem Mietverhältnis, mit eigenem Kontakt.

    Am Mietverhältnis hängt weiterhin ein Hauptkontakt (`Miete.email`,
    `Miete.telefon`) — der bleibt unangetastet. Wohnen mehrere Personen in der
    Einheit, bekommt jede hier ihre eigene Mailadresse und Handynummer, damit
    die Abrechnung alle erreicht und nicht nur den, der den Vertrag
    unterschrieben hat."""
    id: Optional[int] = Field(default=None, primary_key=True)
    miete_id: int = Field(foreign_key="miete.id", index=True)
    name: str = ""
    email: str = ""
    telefon: str = ""
    rolle: str = ""                # 'Hauptmieter' | 'Mitbewohner' | frei
    # Wer die Abrechnung per Mail bekommen soll. Ein Kind im Haushalt steht in
    # der Liste, braucht aber keine Post.
    abrechnung: bool = True
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
    turnus: str = "jaehrlich"      # Steuervorauszahlungen laufen oft quartalsweise
    absetzbar: bool = True
    notiz: str = ""


class Versandprotokoll(SQLModel, table=True):
    """Wer hat seine Abrechnung schon bekommen.

    Ohne dieses Gedächtnis fängt ein zweiter Versandversuch — nach einem
    Fehler bei Partei drei — wieder bei Partei eins an, und die ersten beiden
    Mieter bekommen ihre Abrechnung ein zweites Mal."""
    id: Optional[int] = Field(default=None, primary_key=True)
    zeitraum_id: int = Field(foreign_key="zeitraum.id", index=True)
    partei: str
    empfaenger: str = ""
    versendet_am: Optional[date] = None
    fehler: str = ""


class Eigentuemer(SQLModel, table=True):
    """Person oder Gesellschaft, der Immobilien ganz oder teilweise gehören.
    Steht für sich — dieselbe Person kann an mehreren Objekten beteiligt sein."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # Historisch: die Rolle hing an der Person. Ob jemand Allein- oder
    # Miteigentuemer ist, entscheidet sich aber je Immobilie — die Rolle sitzt
    # deshalb an `Anteil`. Das Feld bleibt stehen (Spalten werden nie entfernt)
    # und wird nicht mehr ausgewertet.
    rolle: str = "Eigentümer"
    email: str = ""
    telefon: str = ""
    anschrift: str = ""
    steuernummer: str = ""
    notiz: str = ""


class Anteil(SQLModel, table=True):
    """Beteiligung an genau einem Objekt. 1000 ‰ = Alleineigentum."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    eigentuemer_id: int = Field(foreign_key="eigentuemer.id", index=True)
    # Ganzzahlig und deshalb zu grob: 1000/3 geht nie auf. Bleibt als gerundeter
    # Wert gepflegt, weil aeltere Leser (Vermoegensuebersicht, Objektseite)
    # darauf zugreifen — massgeblich ist `promille`.
    tausendstel: int = 1000
    # Bewusst ohne Vorgabe: eine gewachsene Datenbank bekommt die Spalte per
    # migrate.py als NULL und faellt beim Lesen auf `tausendstel` zurueck.
    # Mit einer Vorgabe von 1000.0 wuerde ein bestehender 600er-Anteil
    # stillschweigend zu Alleineigentum.
    promille: Optional[float] = None
    # Die Rolle gehoert ans Objekt, nicht an die Person: dieselbe Person kann
    # ein Haus allein und am naechsten mit 300 ‰ besitzen. Sie wird aus den
    # Promille abgeleitet statt von Hand gewaehlt — eine handverlesene Rolle
    # koennte den Anteilen widersprechen (600 ‰ und trotzdem
    # „Alleineigentuemer"), eine abgeleitete nie.
    rolle: str = "Eigentümer"
    # CLXI: Eigentum je Einheit. Ohne Angabe (leer) gilt die Beteiligung fürs
    # ganze Objekt — jeder Bestand bleibt damit unverändert. Ist eine Einheit
    # genannt, gehört dieser Anteil nur ihr: so lässt sich „mir gehört Wohnung 2"
    # ausdrücken, statt nur „mir gehören 200 ‰ des Hauses".
    einheit: str = ""
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
    # Ein Pfad, ein Eintrag. Ohne diese Eindeutigkeit legen Wachdienst und
    # „Ordner prüfen" dieselbe neue Datei zweimal an, wenn sie sich begegnen —
    # der zweite Eintrag zeigt nach dem Verschieben ins Leere und bleibt für
    # immer im Eingang.
    # `unique=True` wirkt nur, wenn `create_all` die Tabelle neu anlegt — eine
    # gewachsene Datenbank bekommt den Index beim Start durch
    # `migrate.eindeutigkeit_sichern`, nicht erst beim ersten Scanlauf.
    pfad: str = Field(index=True, unique=True)  # WebDAV-Pfad ab Benutzer-Root
    dateiname: str
    groesse: int = 0
    objekt_id: Optional[int] = Field(default=None, foreign_key="objekt.id", index=True)
    zeitraum_id: Optional[int] = Field(default=None, foreign_key="zeitraum.id")
    kategorie: str = ""                    # Dokumentart: Nebenkosten, Steuer, …
    # CLXXI/CXXVIII: die Art sagt nur den Ordner. Welche Zeile der Abrechnung
    # gemeint ist — Kaminkehrer, Wasser, Müllabfuhr —, steht hier. Der Wert ist
    # der Name einer `Kostenart` desselben Objekts; leer heisst „noch keine
    # Position gewählt". Bewusst ein Name und keine Fremdschlüssel-Id: der
    # Katalog wird umbenannt und ergänzt, und ein Beleg soll davon nicht
    # plötzlich auf nichts mehr zeigen.
    kostenart: str = ""
    # CLXXXIII: die Kostenposition, in die dieser Beleg eingerechnet ist.
    # Bewusst eine id und kein Name: sie ist der Rückweg von der Abrechnung zum
    # Beleg *und* die Sperre gegen doppeltes Zählen — ein zweites „Übernehmen"
    # findet dieselbe Position wieder, statt den Betrag noch einmal
    # draufzurechnen. Eine umbenannte Kostenart lässt sie unberührt (CLXXXIV).
    position_id: Optional[int] = Field(default=None,
                                       foreign_key="kostenposition.id",
                                       index=True)
    # CLXXXI: der Rechnungsbetrag am Beleg selbst. Er steht weiterhin auch im
    # Dateinamen (CXXIII) — dort sieht man ihn im Ordner. Als Grundlage einer
    # Kostenposition ist der Name aber zu wackelig: er wird bei jeder Korrektur
    # zerlegt und neu gesetzt, und aus „…-2.pdf" liest niemand mehr einen
    # Betrag heraus. Gerechnet wird deshalb mit diesem Feld.
    betrag: Optional[float] = None
    jahr: Optional[int] = None
    # CLXXII: das Rechnungsdatum, tagesgenau. `jahr` und der Monat im
    # Dateinamen benennen die Datei und bleiben, wie sie sind. Ob ein Beleg in
    # einen Abrechnungszeitraum fällt, entscheidet aber der Tag — die Zeiträume
    # laufen nicht immer von Januar bis Dezember, sondern z. B. 01.10.–30.09.
    belegdatum: Optional[date] = None
    status: str = "neu"                    # 'neu' | 'zugeordnet'
    erkannt_am: Optional[date] = None
