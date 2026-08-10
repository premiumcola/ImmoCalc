"""Datenmodell (SQLModel/SQLite) — abgeleitet aus dem ER-Diagramm."""
from __future__ import annotations
import json as _json
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
    # N322 — vom Nutzer gepflegtes Kurzzeichen für Filter-Chips im Eingang
    # (z. B. „TAU5"). Leer = weiterhin automatisch aus dem Namen abgeleitet
    # (`kurzObjekt` im Frontend); additiv, kein Zwang zu einem Format.
    kuerzel: str = ""
    ort: str = ""
    typ: str = "lg-mfhA"          # Logo-/Gebäudetyp
    # CCCXXXIV — freie Objektart für Anzeige/Übersicht (z. B. „Mehrfamilienhaus",
    # „Villa", „Grundstück"). Leer = aus `typ` abgeleitet.
    objektart: str = ""
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
    # CCCXXX — Baujahr/Baudatum, getrennt vom Kaufdatum (ein Objekt wird
    # später gekauft als gebaut). Additiv, Default None.
    baudatum: Optional[date] = None
    verkehrswert: Optional[float] = None
    # CCCXLII — ob der Verkehrswert je Einzeleinheit in der Einheitsansicht
    # geführt/angezeigt wird. Aus: die Zeile entfällt in allen Einheiten dieses
    # Objekts. Vorgabe True hält den Bestand unverändert (Anzeige wie bisher).
    einheit_verkehrswert: bool = True
    # CCCLVI — wie der Verkehrswert/Marktwert erfasst wird: für das ganze Objekt
    # (ein Wert in den Stammdaten) oder je Einheit einzeln (dann zeigt das Objekt
    # die Summe der Einheitenwerte). Additiv; Default hält den Bestand unverändert
    # (Objektwert wie bisher). Löst den Ja/Nein-Schalter aus CCCXLII ab.
    verkehrswert_modus: str = "Für das ganze Objekt"
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
    # CCXCVII — geschätzter Wert je m². Ist er gesetzt, errechnet sich der
    # Grundstückswert (`verkehrswert`) daraus × Fläche; sonst bleibt der von
    # Hand eingetragene Verkehrswert maßgeblich.
    grundstueck_m2_preis: Optional[float] = None   # € je m² (geschätzt)
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
    # ----------------------------------------------------------------------
    # CCIX — Rücklagenkonto je Objekt. Der Eigentümer legt Geld für die Immo
    # zurück (Instandhaltung, Sanierung). Beides optional: ein Bestandsobjekt
    # ohne Rücklage bleibt unverändert. `ruecklage_saldo` ist der aktuelle Stand
    # des zurückgelegten Geldes, `ruecklage_monatlich` die laufende Sparrate.
    # ----------------------------------------------------------------------
    ruecklage_saldo: Optional[float] = None        # Stand des Rücklagenkontos
    ruecklage_monatlich: Optional[float] = None    # monatliche Rücklage/Sparrate
    # ----------------------------------------------------------------------
    # CCVIII — WEG-Ebene. Ist das Objekt eine Eigentumswohnung in einer
    # Wohnungseigentümergemeinschaft, verteilt die Hausverwaltung/Abrechnungs-
    # firma die Nebenkosten; ImmoCalc verteilt dann nicht selbst, sondern die
    # abgetippten Endwerte je Mieter werden direkt eingetragen (Direkt-Modus
    # über `Kostenposition.nur_einheit`). Additiv: `weg` steht auf False, jeder
    # Bestand rechnet unverändert weiter. Ein Grundstück kann keine WEG sein.
    #
    # Die WEG-Ebene selbst ist Vermietersicht: das Hausgeld ist, was der
    # Eigentümer monatlich an die WEG zahlt (Eigentümerkosten, keine automatische
    # Mietersache), die Rücklagenzuführung der darin enthaltene Sparanteil, der
    # in die gemeinschaftliche Rücklage der WEG fliesst.
    # ----------------------------------------------------------------------
    weg: bool = False                              # Objekt ist Teil einer WEG
    hausgeld_monatlich: Optional[float] = None     # Hausgeld an die WEG, monatlich
    weg_ruecklage_zufuehrung: Optional[float] = None  # Sparanteil im Hausgeld, mtl.
    weg_verwalter: str = ""                        # Hausverwaltung/Abrechnungsfirma
    # ----------------------------------------------------------------------
    # N213 — Objektmodell. Legt fest, welche Nebenkosten-Maschinerie an einem
    # Objekt sichtbar ist. Bisher war die gesamte App auf die Laufer Str. 5
    # zugeschnitten (Stromkette, HKV, Wärmemengenverteilung, PV-/E-Tankstellen-
    # Kette). Für den übrigen Bestand ist das zu viel — dort genügen je
    # Einheit ein Stromzähler und einfache Heizkosten/Wärmemengen-Eingaben.
    #
    # Zwei Ausprägungen:
    #  * `standard` — die einfache Sicht (Bestand außer Laufer). Alle
    #    Laufer-spezifischen UI-Blöcke bleiben im Code, werden aber nicht
    #    gezeigt.
    #  * `laufer_spezial` — die vollständige, historisch gewachsene Sicht
    #    für die Laufer Str. 5.
    #
    # Additiv, Default = `standard`; die Migration zieht die Spalte am Bestand
    # nach. Ein separater One-Off-Setter (siehe `migrate.laufer_modell_setzen`)
    # setzt genau den einen Slug `eschenau-laufer-str-5` einmalig auf
    # `laufer_spezial`, sofern das Feld noch der Default ist. Damit bleibt
    # Laufer unverändert; alle anderen Objekte fallen sofort auf die einfache
    # Sicht. Ein anderer Slug wird nie automatisch umgestellt.
    # ----------------------------------------------------------------------
    modell: str = "standard"        # 'standard' | 'laufer_spezial' (N213)
    # ----------------------------------------------------------------------
    # CCXXXV — Erwerbsart. Nicht jedes Objekt wurde gekauft: geerbt, geschenkt
    # oder überlassen kommt vor. Das ändert die Abschreibung — die AfA wird vom
    # Rechtsvorgänger fortgeführt („Fußstapfenprinzip", `afa_basis_uebernommen`)
    # — und, bei vorbehaltenem Nießbrauch, wem die Mieteinnahmen steuerlich
    # zuzurechnen sind (dann nicht dem eingetragenen Eigentümer). Additiv:
    # `erwerbsart` steht auf „Kauf", jeder Bestand bleibt unverändert.
    # ----------------------------------------------------------------------
    erwerbsart: str = "Kauf"        # Kauf | Schenkung | Erbschaft | Überlassung
    afa_basis_uebernommen: Optional[float] = None   # vom Vorbesitzer fortgeführte AfA-Bemessung
    # CCCI — Nießbrauch ausdrücklich an/aus; ist er aus, bleiben Berechtigter und
    # Frist verborgen. Der Berechtigte ist einer der Eigentümer (Auswahl).
    niessbrauch_aktiv: bool = False
    niessbrauch_berechtigt: str = ""   # wer den Nießbrauch hält (leer = keiner)
    niessbrauch_bis: Optional[date] = None


class Einheit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None          # Wohn-/Nutzfläche in m²
    terrasse: Optional[float] = None         # Terrasse/Balkon in m²
    # N227 — additiv: wie viel Prozent der Terrasse/Balkon-Fläche zur Wohn-/
    # Nutzfläche zählt (Wohnflächenverordnung: üblicherweise 25–50 %). 50 als
    # Vorgabe, weil das schon der bisherige feste Wert in der Verteilung war
    # (`verteilung._gesamtflaeche`) — der Bestand rechnet dadurch unverändert
    # weiter, bis jemand die Einheit bewusst anders einstellt.
    terrasse_anteil_pct: float = 50.0
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
    # CCCXXVII: anteilig mitgenutzte Gemeinschaftsflächen als JSON-Liste
    # [{"bezeichnung": "Treppenhaus", "flaeche": 20, "personen": 4}, …].
    # Jede Fläche zählt geteilt durch die Zahl der Nutzer zur Einheitsfläche.
    # Leerer Bestand („[]") lässt jede bestehende Verteilung unverändert.
    gemeinflaechen: str = "[]"
    # CCCXXIX: zusätzliche Nutzflächen als JSON-Liste
    # [{"bezeichnung": "Bad", "flaeche": 8}, …]. Anders als die Gemeinschafts-
    # flächen zählen sie VOLL (ungeteilt) zur Einheitsfläche — benannte Teile
    # der Wohnfläche (z. B. ein separates Bad). Leerer Bestand („[]") lässt
    # jede bestehende Verteilung unverändert.
    nutzflaechen: str = "[]"
    # CCCXXXIII: €/m²-Ansätze je Flächenart. Aus ihnen leitet die Oberfläche
    # eine Kaltmiete her (Flächen × €/m²) und bietet sie im Miet-Formular als
    # überschreibbaren Vorschlag an. Der Mietpreis selbst gehört NICHT an die
    # Einheit — die tatsächliche Kaltmiete lebt am Mietverhältnis
    # (`Miete.kaltmiete`); hier steht nur der Ansatz je Quadratmeter. Alle
    # optional/None, additiv: ein Bestand ohne Ansatz bleibt unverändert.
    miete_qm_wohn: Optional[float] = None    # €/m² Wohn-/Nutzfläche (inkl. voller Zusatz-Nutzflächen)
    miete_qm_neben: Optional[float] = None   # €/m² Nebenfläche
    miete_qm_gemein: Optional[float] = None  # €/m² anteilige Gemeinschaftsfläche

    def gemein_flaeche(self) -> float:
        """Der anteilige Flächenbeitrag der Gemeinschaftsflächen: Summe über
        Fläche ÷ Nutzerzahl. Fehlt die Nutzerzahl (0), zählt der Posten nicht —
        eine Division durch null wäre sinnlos."""
        try:
            posten = _json.loads(self.gemeinflaechen or "[]")
        except (ValueError, TypeError):
            return 0.0
        if not isinstance(posten, list):
            return 0.0
        summe = 0.0
        for p in posten:
            try:
                flaeche = float(p.get("flaeche") or 0)
                personen = float(p.get("personen") or 0)
            except (ValueError, TypeError, AttributeError):
                continue
            if personen > 0:
                summe += flaeche / personen
        return round(summe, 2)

    def nutz_flaeche(self) -> float:
        """CCCXXIX: der volle Flächenbeitrag der zusätzlichen Nutzflächen —
        die Summe der `flaeche`-Werte, ungeteilt. Defensiv gegen kaputtes
        JSON: ein unlesbarer Wert ergibt 0, nie einen Fehler."""
        try:
            posten = _json.loads(self.nutzflaechen or "[]")
        except (ValueError, TypeError):
            return 0.0
        if not isinstance(posten, list):
            return 0.0
        summe = 0.0
        for p in posten:
            try:
                summe += float(p.get("flaeche") or 0)
            except (ValueError, TypeError, AttributeError):
                continue
        return round(summe, 2)


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
    # N189 — Pflicht/optional je Kostenart, objektweit über alle Zeiträume.
    # `optional=False` (Vorgabe) heißt Pflicht: eine sichtbare Position ohne
    # Betrag wird rot als fehlend markiert. `optional=True` nimmt diese Mahnung
    # zurück — für Positionen, die nicht jedes Jahr anfallen (z. B. Heizungs-
    # wartung), aber sichtbar bleiben sollen. Additiv, Default = bisheriges
    # Verhalten (alles Pflicht), damit der Bestand unverändert weiterrechnet.
    optional: bool = False
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
    # N116b — die vom Versorger ABGERECHNETE Wassermenge laut Bescheid. Der
    # eigene Zähler weist oft mehr aus (Zählerwechsel, Stichtagsversatz,
    # Leitungsverlust); verteilt wird dann auf die abgerechnete Menge, und die
    # Differenz bläht nicht den Anteil Haupthaus auf. Beide Werte bleiben
    # stehen: der Zählerstand am Zähler, die Rechnungsmenge hier — die
    # Abweichung wird ausgewiesen, nicht stillschweigend eingeebnet.
    # Additiv, Default 0 = keine Angabe, es gilt weiterhin der Zähler.
    wasser_rechnung_m3: float = 0.0
    # N192 — die geeichte Rechnungsmenge des Netzbezugs (kWh), wie sie auf der
    # Stromrechnung des Versorgers steht. SolarEdge misst am Wechselrichter, die
    # Rechnung am geeichten Zähler; für den E-Auto-Satz zählt diese Menge (N173).
    # Bisher ging sie nur über die `menge` einer externen Strom-Position; wo es
    # (noch) keine solche Position gibt, hält der Nutzer sie hier fest — direkt
    # aus dem Stromketten-Hinweis. Additiv, Default 0 = keine Angabe, dann fällt
    # der geeichte Satz auf den Verteilungssatz zurück.
    strom_rechnung_kwh: float = 0.0
    # N273 — WEG-Modus: die Einheit liegt in einer Wohnungseigentümergemeinschaft
    # und der Vermieter bekommt von der Messfirma eine FERTIGE Einzelabrechnung.
    # Dann gibt es keine eigenen Rechnungen, keine Zähler, keine Belegjagd — nur
    # noch die Übernahme der fremden Abrechnung. Additiv, Default False = alles
    # bleibt exakt wie bisher.
    weg_modus: bool = False
    # Der gelesene und vom Nutzer bestätigte Beleg, unverändert aufbewahrt.
    # Er trägt auch die NICHT umlagefähigen Positionen — die dürfen nie als
    # Kostenposition entstehen (sonst zahlt der Mieter die Instandhaltung der
    # Gemeinschaft mit), sollen aber sichtbar bleiben, damit der Nutzer die
    # Abrechnung gegen das Papier prüfen kann.
    weg_beleg: dict = Field(default_factory=dict, sa_column=Column(JSON))


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
    # N122 — die Menge hinter dem Betrag: „2.400 kWh für 862,51 €". Erlaubt es,
    # extern bezogenen von selbst erzeugtem Strom zu unterscheiden und daraus
    # die Eigenverbrauchsquote zu zeigen. Additiv, Default 0/"" — jede
    # bestehende Position rechnet unverändert weiter.
    menge: float = 0.0
    menge_einheit: str = ""       # 'kWh' | 'm³' | 'Liter' | ''
    # Woher der Strom kam: 'extern' (Netzbezug laut Rechnung) oder 'eigen'
    # (aus der eigenen PV-Anlage, gleich ob Direktverbrauch oder Akku).
    herkunft: str = ""
    # N124 — was auf der Versorgerrechnung steht, damit der Scan es ablegen und
    # der Betrag gegengeprueft werden kann. Der Durchschnittspreis wird NICHT
    # gespeichert: er ist `betrag / menge` und waere sonst eine zweite Wahrheit.
    arbeitspreis: float = 0.0      # ct/kWh laut Rechnung
    grundpreis_monat: float = 0.0  # Grundpreis in € je Monat
    s35: bool = False
    # CCCLIX — ein Teilbetrag kann vorab direkt auf EINE Einheit gehen (z.B.
    # 35 € einer 147-€-Rechnung), mit eigenem §35a-Status; der Rest (Betrag −
    # Vorab) läuft nach Schlüssel. Additiv, Default 0/""/False → kein Split, der
    # Bestand rechnet unverändert.
    vorab_betrag: float = 0.0
    vorab_einheit: str = ""
    vorab_s35: bool = False
    # CCCLX — der Nettobetrag, den der Nutzer eingegeben hat; `vorab_betrag` ist
    # der daraus gerechnete Brutto (× 1,19), mit dem die Engine verteilt. Nur zur
    # exakten Wiederanzeige. 0 = kein Netto/Brutto-Split (Betrag = Betrag).
    vorab_netto: float = 0.0
    # Partei -> Gewicht (Verbrauch/Fläche/Personen/Bewohnermonate/%/1)
    anteile: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # N5 — Herkunft der Gewichte. True = aus den Stammdaten abgeleitet (Fläche/
    # Personen/Bewohnermonate/„nur eine Einheit"): darf sich automatisch neu
    # ableiten, wenn sich ein Mietverhältnis oder eine Einheit ändert, damit ein
    # korrigierter Mietzeitraum nicht in einer alten Momentaufnahme weiterlebt.
    # False = von Hand gesetzt (Zählerwerte, Prozent, individuelle Überschreibung)
    # — bleibt unangetastet. Additiv, Default True: der Bestand gilt als abgeleitet
    # und heilt sich beim nächsten Stammdaten-Update selbst.
    abgeleitet: bool = True
    # CLXXXII: eine Position je Kostenart und Zeitraum bleibt die Regel — auf
    # dieselbe Zeile laufen aber vier Abschlagsrechnungen zu. `betrag` bleibt
    # die Wahrheit, mit der gerechnet wird; hier steht, welcher Teil davon aus
    # verknüpften Belegen stammt. Die Differenz ist das, was von Hand
    # eingetragen wurde — nur so lässt sich ein weiterer Beleg addieren, ohne
    # den Handeintrag zu überschreiben oder doppelt zu zählen.
    beleg_summe: float = 0.0
    # CCLXXVIII — Orange-Entwurf: ein aus einem Beleg vorläufig angelegter
    # Datensatz, den der Nutzer erst bestätigt (`vorlaeufig=False`) oder
    # verwirft. `quelle_dokument_id` zeigt auf den Beleg, aus dem er entstand.
    # Additiv, Default False/None: jeder Bestand ist damit schon „bestätigt".
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


class Vorauszahlung(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    zeitraum_id: int = Field(foreign_key="zeitraum.id", index=True)
    partei: str
    betrag: float


class WegVorauszahlung(SQLModel, table=True):
    """N273 — die Vorauszahlung des Mieters im WEG-Modus, in Abschnitten.

    Bewusst NICHT ein einzelner Jahresbetrag: der Nutzer sagt ausdrücklich, dass
    ein halbes Jahr höher oder niedriger gezahlt werden kann (Anpassung nach der
    letzten Abrechnung). Ein Abschnitt hält deshalb den MONATSBETRAG samt
    Geltungsspanne; gerechnet wird daraus monatsgenau (`weg.vorauszahlung`).

    `von`/`bis` dürfen leer bleiben — dann gilt der Abschnitt für den ganzen
    Abrechnungszeitraum. Ganz neue Tabelle: `create_all` legt sie an, kein
    bestehender Datensatz ändert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    zeitraum_id: int = Field(foreign_key="zeitraum.id", index=True)
    einheit: str = ""
    von: Optional[date] = None
    bis: Optional[date] = None
    betrag_monat: float = 0.0


class Zaehler(SQLModel, table=True):
    """Ein Zähler (oder berechneter Rest-Zähler) an einem Objekt. Die Ablese-
    stände werden linear auf den Abrechnungszeitraum interpoliert
    (`engine.interpoliere_verbrauch`) und fließen als Verbrauch in die NK-
    Kostenposition der `kostenart`. Additiv, hängt am Objekt (CCXCIII)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    name: str                         # 'Gesamt Wasser', 'Büro KW', …
    kostenart: str = ""               # NK-Kostenart, in die der Verbrauch zählt
    einheit_bezug: str = ""           # Partei/Einheit des Verbrauchs ('' = Haus/Gesamt)
    # CD — Mehrfachzuordnung: komma-separierte Liste von Einheit-`bezeichnung`en,
    # denen der Verbrauch dieses Zählers gemeinsam gehört (z. B. ein Boiler-Zulauf
    # für "EG,1.OG"). Der Verbrauch/die Kosten werden dann über diese Einheiten
    # nach Person·Mietdauer aufgeteilt. `einheit_bezug` (Einzelwert) bleibt als
    # Fallback bestehen: ist `einheiten` leer, gilt weiterhin `einheit_bezug`.
    # Additiv, Default leer — jeder Bestand rechnet unverändert weiter.
    einheiten: str = ""
    art: str = ""                     # N47: 'Kaltwasser'|'Warmwasser'|'Waschmaschine'|
                                      # 'Gartenwasser'|'Heizung' — Zeile in der Detailübersicht
    messeinheit: str = "m³"           # 'm³' | 'kWh' | 'Liter'
    typ: str = "gemessen"             # 'gemessen' | 'rest' (Gesamt minus Unterzähler)
    hauptzaehler_id: Optional[int] = Field(default=None, foreign_key="zaehler.id")
    reihenfolge: int = 0              # Reihenfolge in der Eingabemaske
    aktiv: bool = True
    notiz: str = ""


class Ablesung(SQLModel, table=True):
    """Ein Zählerstand zu einem Ablesedatum. Historie entsteht durch mehrere
    Einträge je Zähler; daraus interpoliert die Engine den Stand zum Soll-
    Stichtag des Abrechnungszeitraums. Additiv (CCXCIII)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    zaehler_id: int = Field(foreign_key="zaehler.id", index=True)
    datum: date                       # Ablesedatum (Ist)
    stand: float                      # abgelesener Zählerstand (kumuliert)
    zeitraum_id: Optional[int] = Field(default=None, foreign_key="zeitraum.id")
    notiz: str = ""


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
    # CCLXXVIII — Orange-Entwurf (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


class Notarvertrag(SQLModel, table=True):
    """Ein notariell beurkundeter Vertrag am Objekt — Kaufvertrag, Auflassung,
    Grundschuldbestellung, Teilungserklärung, Nießbrauch … Additiv, hängt am
    Objekt und gilt für jeden Objekttyp, auch für ein Grundstück (CCLXXXVII)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    art: str                       # 'Kaufvertrag' | 'Auflassung' | 'Grundschuld' …
    notar: str = ""                # Notar / Notariat
    urnr: str = ""                 # Urkundenrollen-Nummer (URNr)
    datum: Optional[date] = None   # Beurkundungsdatum
    betrag: float = 0.0            # beurkundeter Betrag / Kaufpreis
    beteiligte: str = ""           # Parteien der Urkunde
    notiz: str = ""
    # CCLXXVIII — Orange-Entwurf (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


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
    # N224 — additiv: die Kautionsunterlagen (Dokument-Checkliste) sagen nichts
    # darüber, ob das Geld auch wirklich auf dem Konto eingegangen ist. Leer =
    # noch nicht eingegangen.
    kaution_eingang: Optional[date] = None
    # N224 — additiv: statt eines eigenen Kautionskontos (Dokumentnachweis in
    # der Checkliste) überweist der Mieter manchmal einfach auf das normale
    # Objektkonto — dann gibt es kein Dokument, nur diesen Vermerk.
    kaution_objektkonto: bool = False
    notiz: str = ""
    # CCLXXVIII — Orange-Entwurf (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")
    # N228 — additiv: eine geplante Mieterhöhung legt einen neuen Mietstand
    # an, der den bisherigen ablöst. Der Vorgänger bleibt hier verknüpft,
    # damit seine Dokumente (Mietvertrag, Übergabeprotokolle, Kaution,
    # Selbstauskunft, Rauchwarnmelder …) auch am neuen Stand als hinterlegt
    # gelten — ohne Kopie, dieselbe Datei zählt für beide.
    vorgaenger_id: Optional[int] = Field(
        default=None, foreign_key="miete.id")


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
    # CCXXX — Anschlusszins nach der Zinsbindung. Läuft die Sollzinsbindung
    # (`zinsbindung_bis`) aus, gilt meist ein variabler Satz. Ist er hier
    # gepflegt, schreibt die Restschuld-Rechnung ab dem Bindungsende mit ihm
    # fort statt stur mit dem alten Satz. Leer = alles wie bisher.
    zinssatz_variabel: Optional[float] = None   # Prozent p. a., ab zinsbindung_bis
    # CCLXXVIII — Orange-Entwurf (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


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
    # CCXXXI — die echten Sollzinsen dieses Jahres laut Bank-Kontoauszug
    # (Finanzierungskostennachweis). Für die Anlage V zählt dieser Ist-Wert,
    # nicht die Kalkulation. Leer = es gilt weiter nur die berechnete Zinslast.
    zinsen_ist: Optional[float] = None
    notiz: str = ""


class Grundschuld(SQLModel, table=True):
    """CCXXIX — eine Grundschuld: das dingliche Pfandrecht, mit dem eine Bank
    ihren Kredit im Grundbuch absichert.

    Sie hängt am belasteten Objekt (`objekt_id`), sichert aber über die
    Verknüpfungstabelle `GrundschuldKredit` einen oder mehrere Kredite — auch
    Kredite an *anderen* Objekten. Genau dieser Fall kommt im Bestand vor: die
    Grundschuld auf Haus A besichert das Darlehen für Haus B. Additiv: ohne
    Grundschuld-Eintrag ändert sich an keinem Objekt etwas."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)  # das belastete Objekt
    betrag: Optional[float] = None
    rang: str = ""                # Rang im Grundbuch, z. B. „I", „II"
    grundbuch_blatt: str = ""     # Grundbuchbezirk/Blatt
    glaeubiger: str = ""          # begünstigte Bank
    brief: bool = False           # Brief- (True) oder Buchgrundschuld (False)
    notiz: str = ""
    # N331c — additiv: der Scan-Weg (wie bei Notarvertrag/Kredit/Zahlung) legt
    # den Beleg ab und muss ihn am Eintrag festhalten können.
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


class GrundschuldKredit(SQLModel, table=True):
    """Welche Kredite eine Grundschuld besichert (m:n). Eine Grundschuld kann
    mehrere Kredite decken, ein Kredit durch mehrere Grundschulden gesichert
    sein."""
    grundschuld_id: int = Field(foreign_key="grundschuld.id", primary_key=True)
    kredit_id: int = Field(foreign_key="kredit.id", primary_key=True)


class Erkennungsregel(SQLModel, table=True):
    """CCXLIX — vom Nutzer gepflegte Erkennungsregel für die Belegeingabe.

    Steht ein `muster` (ein Textstück, das auf dem Beleg steht — „N-ERGIE Netz",
    „WWK", „Schornsteinfeger") im OCR-Text, gilt die zugeordnete Richtung. So
    lernt die Erkennung die eigenen Belege statt zu raten:

      * `ist_kosten = False` — der Beleg ist gar keine Kostenrechnung
        (Ablesung, SEPA-Mandat, Anmeldung, Abrechnungs-Übersicht): er wird nach
        `kategorie` einsortiert, aber es entsteht keine Kostenposition.
      * `ist_kosten = True` — Kostenbeleg mit dieser `kategorie`/`kostenart`.

    Verglichen wird normalisiert (Kleinschreibung, ohne Leer-/Sonderzeichen),
    damit auch die zerrupften Scans („N - E R G I E") treffen. Die zuerst
    passende aktive Regel (nach `rang`, dann Länge des Musters) gewinnt."""
    id: Optional[int] = Field(default=None, primary_key=True)
    muster: str                          # Textstück, das auf dem Beleg steht
    kategorie: str = "Nebenkosten"       # Zielkategorie
    kostenart: str = ""                  # Ziel-Kostenart (leer = keine)
    ist_kosten: bool = True              # False = kein Kostenbeleg
    rang: int = 0                        # kleiner = wird zuerst geprüft
    aktiv: bool = True


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
    # Eigene Anschrift der Person — der Kontakt liegt seit CCLXVI bei den
    # Bewohnern, nicht mehr am Mietverhältnis. Additiv, Default leer:
    # migrate.py legt die Spalte für den Bestand an.
    anschrift: str = ""
    rolle: str = ""                # 'Hauptmieter' | 'Mitbewohner' | frei
    # Wer die Abrechnung per Mail bekommen soll. Ein Kind im Haushalt steht in
    # der Liste, braucht aber keine Post.
    abrechnung: bool = True
    notiz: str = ""
    # CCLXXVIII — Orange-Entwurf (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


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
    # CCXCIX — Orange-Entwurf aus einem Beleg (siehe Kostenposition).
    vorlaeufig: bool = False
    quelle_dokument_id: Optional[int] = Field(
        default=None, foreign_key="dokument.id")


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
    # N218 — Profilbild als Data-URI (z. B. "data:image/jpeg;base64,...").
    # Additiv, leer = kein Bild (Initialen-Icon bleibt der Normalfall).
    bild: str = ""


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
    # N290 — die zwei Kennzeichen, mit denen eine Datei wiedererkannt wird,
    # wenn der Nutzer sie im Windows-Explorer umbenennt UND verschiebt. Der
    # Pfad taugt dafür nicht: er ist genau das, was sich ändert.
    #
    # `nc_fileid` ist Nextclouds eigene Dateinummer — sie bleibt bei Umbenennen
    # und Verschieben dieselbe und liegt bei jedem PROPFIND kostenlos bei.
    # `sha1` ist die byte-exakte Prüfsumme; sie überlebt zusätzlich das
    # Neu-Hochladen derselben Datei (dann ändert sich die Nummer), fehlt aber
    # bei allem, was über die Weboberfläche kam. Zusammen decken sie beide
    # Fälle ab. Beide leer = alter Bestand; dann greift wie bisher die Suche
    # über Name und Größe.
    nc_fileid: str = Field(default="", index=True)
    sha1: str = Field(default="", index=True)
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
    # CCLXXIII: die KI-Einordnung — ein bis zwei kurze deutsche Sätze, was für
    # ein Beleg das ist (Absender, worum es geht, Datum, Betrag). Kommt aus der
    # KI-Auslese (`kiauslese.py`, CCLXVIII) und wird beim Erkennen eines
    # abgelegten Belegs gespeichert, damit die App sie zeigen kann, ohne den
    # Beleg jedes Mal neu zu lesen. Additiv, Default leer: migrate.py legt die
    # Spalte für den Bestand an, ein Beleg ohne Einordnung bleibt unverändert.
    ki_einordnung: str = ""
    # CCLXXIV: das Raster der KI-Auslese. `ki_felder` sind die typspezifischen
    # App-Eingabefelder, die die KI aus dem Beleg gezogen hat (Mieter,
    # Jahresbeitrag, Restschuld …) — als JSON, weil je Dokumenttyp andere Felder
    # anfallen. `ki_immobilie` ist die erkannte Liegenschaft/das Anwesen (NICHT
    # die Postanschrift), `ki_einheit` die erkannte Einheit. Alle additiv mit
    # Default: migrate.py legt die Spalten für den Bestand an.
    ki_felder: dict = Field(default_factory=dict, sa_column=Column(JSON))
    ki_immobilie: str = ""
    ki_einheit: str = ""
    # CCCX: der Info-Beleg. Nicht jeder Beleg begründet einen eigenen Datensatz
    # — die Bestätigung zum Kaufvertrag, das Anschreiben zur Police, der
    # Zahlungsnachweis zur Grundsteuer erläutern nur einen vorhandenen Eintrag.
    # `info_zu_typ` sagt woran ('notarvertrag' | 'zahlung' | 'kredit' |
    # 'versicherung' | 'miete' | 'kostenposition' | 'objekt'), `info_zu_id`
    # welcher Eintrag es ist (beim Objekt dessen Id). Bewusst getrennt von
    # `quelle_dokument_id` am Datensatz: der Beleg hat den Eintrag nicht
    # hervorgebracht, er hängt nur daran. Additiv mit Default: migrate.py legt
    # die Spalten für den Bestand an, ein Beleg ohne Info bleibt unverändert.
    info_zu_typ: str = ""
    info_zu_id: Optional[int] = None
    # N328(ii) — der volle erkannte Text eines Belegs (PDF-Textschicht oder
    # OCR), damit die Suche nicht nur den Dateinamen und die kurze KI-
    # Zusammenfassung findet, sondern JEDES Wort, das irgendwo im Beleg
    # steht — der eigentliche Vorteil digitaler Ablage. Wird beim Erkennen
    # eines Belegs (frischer Scan, `/erkennen`, `/neu-analysieren`) einmalig
    # aus derselben Texterkennung (`ocr.text_aus_beleg`) mitgeschrieben, die
    # ohnehin für Betrag/Datum/KI läuft — kein zweiter OCR-Lauf. Additiv mit
    # Default: migrate.py legt die Spalte für den Bestand an; die ~667
    # vorhandenen Belege bekommen ihren Text über
    # `POST /dokumente/{id}/text-nachtragen` nachgetragen.
    erkannter_text: str = ""


class Heizoellieferung(SQLModel, table=True):
    """N79 — eine Heizöl-Lieferung (oder der Anfangsbestand) an einem Objekt.

    Heizöl wird nicht abgelesen, sondern getankt: der Nutzer erfasst mehrere
    Lieferungen (Liter + Gesamtpreis + Datum) und einen Anfangsbestand (der
    Bestand zu Beginn, mit dem frühesten Datum). Der Verbrauch einer
    Abrechnungsperiode wird dann FIFO bewertet — das älteste Öl zuerst
    (`heizoel.verbrauch_bewerten`).

    `wert` ist der Gesamtpreis der Lieferung in €; der Preis je Liter ergibt
    sich als `wert / liter` und wird nicht gespeichert. `ist_anfangsbestand`
    markiert den Startbestand (üblicherweise das früheste Datum), damit die
    Oberfläche ihn getrennt führen kann; für die FIFO-Bewertung zählt allein
    das Datum. Additiv, hängt am Objekt — jeder Bestand bleibt unverändert."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    datum: date
    liter: float = 0.0
    wert: float = 0.0                 # Gesamtpreis der Lieferung in €
    ist_anfangsbestand: bool = False
    notiz: str = ""


class Heizverteiler(SQLModel, table=True):
    """N81 — ein Heizkostenverteiler (HKV) an einem Heizkörper des Objekts.

    Die Heizungswärme wird — wie beim Abrechnungsdienst — über die abgelesenen
    HKV-Einheiten je Einheit verteilt: pro Heizkörper `faktor × einheiten_stand`
    = gewichtete Einheiten, Summe je `einheit` → Kostenanteil
    (`waerme.verteile_heizung`).

    `faktor` ist der einmalige Bewertungsfaktor des Geräts (Größe/Leistung des
    Heizkörpers), `einheiten_stand` die jährliche Ablesung (abgelesene Einheiten
    der Periode). Der Einfachheit halber steht der Ablesewert direkt am Gerät —
    er wird je Abrechnungsperiode überschrieben; wer Historie braucht, hält sie
    in `notiz`. Additiv, ganz neue Tabelle (von `create_all` angelegt) — jeder
    Bestand bleibt unverändert."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    einheit: str = ""                 # Bezeichnung der Einheit (Zieleinheit)
    nummer: str = ""                  # HKV-Gerätenummer
    raum: str = ""                    # Raum/Heizkörper
    faktor: float = 1.0               # Bewertungsfaktor (einmalig)
    einheiten_stand: float = 0.0      # abgelesene Einheiten der Periode
    notiz: str = ""


class PVAnlage(SQLModel, table=True):
    """N139 — die Stammdaten der PV-Anlage, unabhängig vom Abrechnungsjahr.

    Anschaffung und bereits Abgetragenes hingen bisher am `Stromjahr` und
    änderten sich damit mit der Jahresauswahl — die Anlage wurde aber einmal
    gekauft, nicht jedes Jahr neu. Hier stehen die Angaben, die für alle Jahre
    gelten; `Stromjahr` behält nur, was wirklich jahresbezogen ist.

    Eine Anlage je Objekt. Additive neue Tabelle (von `create_all` angelegt);
    die alten Felder am `Stromjahr` bleiben stehen und werden ignoriert, damit
    kein Bestand bricht."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True, unique=True)
    anschaffung_eur: float = 0.0       # Investment der Anlage
    # Was die Anlage abgetragen hat, bevor die erste Abrechnung begann.
    # N153 — aufgeschluesselt wie die spaeteren Jahre, damit der Verlauf auch am
    # Anfang zeigt, WOHER der Vorsprung kam. Beim Nutzer betrifft das 2023/2024;
    # die Anlage lief lange nicht, praktisch also nur 2024, E-Tanken war 0.
    # `vorlauf_ertrag_eur` bleibt als Gesamtwert stehen (nie entfernen): ist die
    # Aufschluesselung gepflegt, gilt ihre Summe, sonst weiterhin dieses Feld.
    vorlauf_ertrag_eur: float = 0.0
    vorlauf_pv_strom_eur: float = 0.0     # den Mietern berechneter PV-Strom
    vorlauf_einspeisung_eur: float = 0.0  # Einspeiseverguetung
    vorlauf_tanken_eur: float = 0.0       # E-Tanken
    kwp: float = 0.0                   # installierte Leistung (Vergütungsstufe)
    inbetriebnahme: Optional[date] = None
    # Eigentümer-Anteile der Anlage als JSON {Name: Promille} — unabhängig von
    # den Objekt-Tausendsteln, die Anlage kann anderen gehören als das Haus.
    anteile: str = ""
    notiz: str = ""


class Stromjahr(SQLModel, table=True):
    """N83 — Strom/PV-Eingaben eines Objekts für ein Jahr.

    Strom ist zu vielschichtig für einen einzigen Betrag (siehe `app.strom`):
    aus drei Zählerständen entstehen zwei Verbrauchsgruppen (WG-Wohnungen und
    Büro/Studio = Rest), auf die die Bezugsquellen Netz/Solar/Akku verteilt
    werden, dazu die PV-Anlage mit Ertrag und Anschaffung. Hier stehen nur die
    Eingabewerte; gerechnet wird in der Engine.

    Ein Datensatz je Objekt und Jahr (`GET/PUT …/strom/{jahr}` legt bei Bedarf
    an). Alle Felder mit Default 0/„" — additiv, ganz neue Tabelle (von
    `create_all` angelegt), jeder Bestand bleibt unverändert."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    jahr: int = Field(index=True)
    # Zählerstände als Jahresverbrauch (kWh): Gesamt, WG/Haus (2 Wohnungen),
    # Garage — Büro/Studio ergibt sich als Rest (Gesamt − WG − Garage).
    gesamt_kwh: float = 0.0           # Stromzähler 666 GESAMT
    wg_kwh: float = 0.0               # Zwischenzähler WG/Haus (EG + 1.OG)
    garage_kwh: float = 0.0           # Garage (separat)
    # Aufteilung WG vs. Büro/Studio: fester Split in Prozent (0 = aus den kWh
    # ableiten), abzüglich des E-Auto-Ladestroms (aus dem Split herausgerechnet).
    wg_anteil_prozent: float = 0.0    # z. B. 60 (= WG 60 % / Büro 40 %)
    tanken_kwh: float = 0.0           # E-Auto-Ladung (nicht mit-geteilt)
    # Bezugsquellen: Menge (kWh) und Preis (€/kWh) je Netz/Solar/Akku.
    netz_kwh: float = 0.0
    netz_preis: float = 0.0
    solar_kwh: float = 0.0
    solar_preis: float = 0.0
    akku_kwh: float = 0.0
    akku_preis: float = 0.0
    # PV-Anlage.
    pv_produktion_kwh: float = 0.0
    einspeisung_kwh: float = 0.0
    pv_kwp: float = 0.0               # installierte Leistung (Vergütungssatz)
    verguetung_eur: float = 0.0       # 0 = aus Einspeisung × Satz(kwp) rechnen
    anschaffung_eur: float = 0.0      # Investment der PV-Anlage
    # N128 — was die Anlage VOR der ersten Nebenkostenabrechnung schon abgetragen
    # hat. Die erste Abrechnung beginnt am 01.10.2024, die Anlage lief davor
    # bereits. Ohne diesen einmaligen Vorbetrag stünde die Amortisation zu weit
    # zurück. Er wird dem ersten erfassten Jahr zugerechnet, nicht verteilt.
    # Additiv, Default 0 — jeder Bestand rechnet unverändert weiter.
    vorlauf_ertrag_eur: float = 0.0
    # N124 — die Aufteilung der E-Auto-Ladungen auf Netzbezug und eigenen Strom.
    # Von Hand gepflegt (eine Schnittstelle zur Wallbox kann spaeter dazukommen);
    # diese Mengen werden VOR der anteiligen Verteilung aus beiden Kostenbloecken
    # herausgenommen und exakt bepreist (`strombloecke.verteile`). Additiv,
    # Default 0/"" — ohne Angabe verteilt sich alles wie bisher.
    eauto_einheit: str = ""            # welche Einheit die Ladungen traegt
    eauto_extern_kwh: float = 0.0      # davon aus dem Netz
    eauto_eigen_kwh: float = 0.0       # davon aus der eigenen Anlage
    # N87 — die PV-Anlage ist ein eigenes Add-on-Investment je Immobilie:
    # eigene Eigentümer-Tausendstel (JSON {Name: ‰}, leer = Vorgabe 5/6 + 1/6),
    # unabhängig von den Objekt-Anteilen. Der Tank-Preis (€/kWh) ist der Satz,
    # den die ladende Person für den E-Auto-Strom an die PV-Anlage zahlt (N89).
    pv_anteile: str = ""
    tanken_preis: float = 0.0
    tanken_person: str = ""           # wem die Tankstelle berechnet wird
    # N89 - welche Immobilien-Einheiten zu welcher Verbrauchsgruppe gehoeren,
    # als JSON {Gruppe: "A,B"}. Erst damit wird aus zwei Gruppen ein Betrag je
    # Einheit, der in die Nebenkostenabrechnung zurueckfliesst.
    gruppen_einheiten: str = ""
    # N161 - der SolarEdge-Screenshot dieses Jahres als Beleg. Verweist auf ein
    # `Dokument` in der Nextcloud; leer = noch keiner abgelegt. Additiv.
    screenshot_dokument_id: Optional[int] = Field(default=None,
                                                  foreign_key="dokument.id")
    notiz: str = ""


class Kontakt(SQLModel, table=True):
    """N309 — eine Firma im Kontaktbuch: Handwerker, Versicherer, Versorger.

    Der Nutzer will „die Firmennamen aller Handwerker, Versicherer, unsere
    Kundennummern und Kontaktdaten immobilienzugehörig" an einer Stelle haben.
    Die Firma steht deshalb **einmal** hier — sie arbeitet oft für mehrere
    Immobilien —, und was je Immobilie verschieden ist (die Kundennummer),
    hängt in `Kundennummer` daran.

    `gewerk` ist der Schwerpunkt aus der Renovierungsliste (`renovierung.GEWERKE`)
    und darf leer sein: ein Versicherer hat keins. `quelle` sagt, woher der
    Eintrag kam ('beleg' | 'renovierung' | 'versicherung' | 'kredit' | 'hand') —
    wichtig, weil ein geernteter Eintrag beim nächsten Lauf ergänzt, ein von
    Hand gepflegter aber **nie überschrieben** werden darf.

    Ganz neue Tabelle, alle Felder mit Default: `create_all` legt sie an, kein
    bestehender Datensatz ändert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Kleingeschrieben und entrümpelt — daran wird wiedererkannt, damit
    # „Elektro Müller GmbH" und „Elektro Müller  gmbh" nicht zweimal entstehen.
    schluessel: str = Field(index=True, unique=True)
    firma: str = ""
    art: str = ""                      # Handwerker | Versicherung | Versorger …
    gewerk: str = ""                   # Schwerpunkt, siehe renovierung.GEWERKE
    telefon: str = ""
    email: str = ""
    web: str = ""
    adresse: str = ""
    notiz: str = ""
    quelle: str = ""                   # woher der Eintrag stammt
    # N309 — von Hand gepflegte Felder werden von der Ernte nie überschrieben.
    # Hier stehen ihre Namen, damit ein späterer Lauf sie in Ruhe lässt.
    handgepflegt: list = Field(default_factory=list, sa_column=Column(JSON))
    erfasst_am: Optional[date] = None


class Kundennummer(SQLModel, table=True):
    """N309 — die Nummer, unter der eine Immobilie bei einer Firma geführt wird.

    Bewusst eine eigene Tabelle: derselbe Versorger führt jede Immobilie unter
    einer anderen Kundennummer, und dieselbe Immobilie hat bei einer Firma
    manchmal mehrere (Kundennummer UND Vertragsnummer). Beides ginge in einem
    Feld am Kontakt verloren."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kontakt_id: Optional[int] = Field(default=None, foreign_key="kontakt.id",
                                      index=True)
    objekt_id: Optional[int] = Field(default=None, foreign_key="objekt.id",
                                     index=True)
    nummer: str = ""
    art: str = ""                      # Kundennummer | Vertragsnummer | Police …
    quelle: str = ""
    quelle_dokument_id: Optional[int] = Field(default=None,
                                              foreign_key="dokument.id")


class KiAuslese(SQLModel, table=True):
    """N296 — die KI-Auslese, am INHALT der Datei festgemacht statt am Eintrag.

    Ein KI-Aufruf kostet Budget des Nutzers. Gespeichert war die Auslese bisher
    nur am `Dokument` (N98) — also an der Eintragsnummer. Dieselbe Datei ein
    zweites Mal in der App (erneut gescannt, als Duplikat in einem zweiten
    Objektordner, oder nach einem Grabstein neu aufgenommen) bekam eine neue
    Nummer und wurde deshalb noch einmal bezahlt gelesen.

    Der Schlüssel ist hier der SHA1 des Dateiinhalts: byte-gleich heisst
    wortgleich, und die Auslese darf übernommen werden. `unique=True` — je
    Inhalt genau ein Eintrag.

    Bewusst NICHT dasselbe wie `Belegdaten`: dort steht die durchsuchbare
    Wissensdatenbank je BELEG (mit Objekt, Jahr, Betrag — fachlich gepflegt und
    vom Nutzer korrigierbar). Hier steht die rohe Antwort der KI zu einem
    Dateiinhalt, als reiner Zwischenspeicher. Wird sie gelöscht, geht keine
    Information verloren — nur Budget beim nächsten Lesen.

    Ganz neue Tabelle, alle Felder mit Default: `create_all` legt sie an, kein
    bestehender Datensatz ändert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sha1: str = Field(index=True, unique=True)
    # Die vollständige Auslese, so wie `ocr.erkenne` sie zurückgibt.
    ergebnis: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Womit gelesen wurde — eine spätere, bessere Fassung soll erkennbar sein.
    modell: str = ""
    erfasst_am: Optional[date] = None
    # Wie oft der Zwischenspeicher einen Aufruf erspart hat. Nur Auskunft.
    treffer: int = 0


class Belegdaten(SQLModel, table=True):
    """N84 — die interne Wissens-Datenbank der ausgelesenen Belegdaten.

    Bisher lagen die KI-Auslesen verstreut am Dokument (`ki_einordnung`,
    `ki_felder`, `ki_immobilie`, `ki_einheit`) und mussten bei jedem Ansehen
    neu zusammengesucht werden. Hier steht je Beleg ein Datensatz mit dem,
    was der Beleg aussagt — und mit `pfad` als **Link auf die Datei** in der
    Cloud statt einer lokalen Kopie. Über Jahre hinweg durchsuchbar
    (`app.kidb.suche`).

    Ein Eintrag je Beleg: `dokument_id` ist der Schlüssel, unter dem die
    Übernahme wiederfindet, was sie schon angelegt hat (idempotent). Bewusst
    ohne `unique=True` in der Tabelle — der Bestand soll auch dann laufen,
    wenn irgendwann zwei Einträge auf denselben Beleg zeigen; der Fachcode
    führt sie über `zusammenfuehren` additiv zusammen.

    Ganz neue Tabelle, alle Felder mit Default: `create_all` legt sie an,
    kein bestehender Datensatz ändert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    dokument_id: Optional[int] = Field(default=None,
                                       foreign_key="dokument.id", index=True)
    objekt_id: Optional[int] = Field(default=None,
                                     foreign_key="objekt.id", index=True)
    jahr: Optional[int] = Field(default=None, index=True)
    kategorie: str = ""               # Dokumentart, z. B. „Nebenkosten"
    kostenart: str = ""               # Zeile der Abrechnung, z. B. „Wasser"
    betrag: Optional[float] = None
    belegdatum: Optional[date] = None
    anbieter: str = ""                # Aussteller (KI: `anbieter`/`absender`)
    zusammenfassung: str = ""         # Freitext — die KI-Einordnung
    felder: dict = Field(default_factory=dict, sa_column=Column(JSON))
    pfad: str = ""                    # WebDAV-Pfad = der Link zur Datei
    dateiname: str = ""
    quelle: str = ""                  # 'ki' | 'regel' | 'hand'
    erfasst_am: Optional[date] = None


class Dokumentvorlage(SQLModel, table=True):
    """N240 — das Vorlagenarchiv: leere Formulare zum Ausfüllen, nicht die
    Belege des Nutzers. Liegt deshalb NICHT unter einem Objekt-Ordner, sondern
    unter einem eigenen Home-Unterordner (`/Vorlagen/<verwendungszweck>/`).

    `typ` ist bewusst dieselbe Zeichenkette wie der erste Eintrag eines
    `SCAN_TYPEN`-Paars im Frontend (`public/assets/objekt/state.js`), z. B.
    „Übergabeprotokoll Einzug" — so kann die Checkliste eine Vorlage rein per
    Textvergleich zu ihrem Checklisten-Punkt finden, ohne eine zweite
    Zuordnungstabelle zu brauchen.

    Ganz neue Tabelle, alle Felder mit Default: `create_all` legt sie an, kein
    bestehender Datensatz ändert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = ""                    # Anzeigename, z. B. "Übergabeprotokoll"
    verwendungszweck: str = "Vermietung"
    typ: str = ""                     # Deckt sich mit SCAN_TYPEN-Schlüsseln
    pfad: str = ""                    # WebDAV-Pfad = der Link zur Datei
    dateiname: str = ""
    quelle_url: str = ""              # Herkunft — fuer Nachvollziehbarkeit
    hinweis: str = ""                 # kurzer Nutzungshinweis, optional
    erstellt_am: Optional[date] = None


class Tanknutzer(SQLModel, table=True):
    """N164 — wer an der Ladestation lädt, mit den Stammdaten für den Versand.

    Lag bisher als JSON in einer Einstellung — das trug Name und E-Mail, mehr
    nicht. Für eine Quartalsabrechnung braucht es Anschrift und Bankverbindung,
    und die gehören in eine eigene Tabelle statt in einen JSON-Klumpen.

    Ein Nutzer muss **nicht** Eigentümer sein: an der Station lädt, wer darf.
    `person_id` verknüpft ihn mit einem Eigentümer, wenn es einer ist.

    Additiv, ganz neue Tabelle; jeder Bestand bleibt unverändert."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    name: str
    email: str = ""
    person_id: Optional[int] = Field(default=None, foreign_key="eigentuemer.id")
    # Anschrift für die Abrechnung
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    # Bankverbindung — wohin das Geld geht bzw. wovon abgebucht wird
    iban: str = ""
    bic: str = ""
    kontoinhaber: str = ""
    # N170 - das E-Auto des Nutzers, um aus geladenen kWh gefahrene km zu
    # schaetzen. `verbrauch_kwh_100km` wird einmalig ueber die KI zum Modell
    # ermittelt (defensive Fahrweise -> guenstiger Wert) und dann gespeichert;
    # von Hand ueberschreibbar. Additiv, Default leer/0.
    e_auto_modell: str = ""
    verbrauch_kwh_100km: float = 0.0
    aktiv: bool = True
    notiz: str = ""


class Tankladung(SQLModel, table=True):
    """N112 — eine Ladung an der E-Tankstelle der PV-Anlage.

    Der E-Auto-Strom gehoert der Anlage, nicht der Immobilie: er wird der
    ladenden Person berechnet und zahlt auf die Amortisation ein. Die Person
    ist ein `Eigentuemer`-Datensatz (dieselbe Personenliste wie sonst) oder,
    wenn sie dort nicht steht, ein freier Name mit E-Mail.

    Additiv, ganz neue Tabelle; jeder Bestand bleibt unveraendert."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    jahr: int = Field(index=True)
    person_id: Optional[int] = Field(default=None, foreign_key="eigentuemer.id")
    name: str = ""                 # falls die Person nicht in der Liste steht
    email: str = ""
    kwh: float = 0.0
    preis: float = 0.0             # EUR je kWh (0 = Satz des Strom-Jahres)
    datum: Optional[date] = None
    notiz: str = ""
    # N132b — die feste Zuordnung zum Nutzer der Ladestation. Bisher lief sie
    # ueber den Namen; wurde ein Nutzer umbenannt, verloren seine alten Ladungen
    # den Anschluss und standen als „nicht angelegt" da. Additiv, Default None —
    # ohne Angabe gilt weiterhin der Name.
    tanknutzer_id: Optional[int] = None


class Renovierung(SQLModel, table=True):
    """N270 — eine Renovierung/Sanierung an einem Objekt: Zeitraum, Budget mit
    laufendem Restbudget, und (in `Renovierungsposten`) die Rechnungen dazu.

    Ganz neue Tabelle, alle Felder ausser `objekt_id`/`name` mit Default:
    `create_all` legt sie an, kein bestehender Datensatz aendert sich."""
    id: Optional[int] = Field(default=None, primary_key=True)
    objekt_id: int = Field(foreign_key="objekt.id", index=True)
    name: str
    von: Optional[date] = None
    bis: Optional[date] = None
    budget: Optional[float] = None
    # Bezeichnungen der betroffenen Einheiten, mit "|" getrennt. Leer = ganzes
    # Objekt. "|" statt Komma, weil eine Einheitsbezeichnung ein Komma
    # enthalten darf ("EG, links"), ein "|" aber praktisch nie.
    einheiten: str = ""
    notiz: str = ""
    abgeschlossen: bool = False


class Renovierungsposten(SQLModel, table=True):
    """N270 — eine Rechnung/Position innerhalb einer Renovierung, einem Gewerk
    zugeordnet (fuer die spaetere Donut-Verteilung im Frontend)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    renovierung_id: int = Field(foreign_key="renovierung.id", index=True)
    datum: Optional[date] = None
    betrag: float = 0.0
    firma: str = ""
    gewerk: str = ""
    notiz: str = ""
    quelle_dokument_id: Optional[int] = Field(default=None, foreign_key="dokument.id")
