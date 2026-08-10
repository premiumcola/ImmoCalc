"""KI-gestützte Beleg-Auslese über ein günstiges Claude-Modell (CCLXVIII).

Die regelbasierte Heuristik in `ocr.py` verwechselt auf manchen Belegen die
Datumsangaben — sie nimmt ein Zahlungsziel oder eine Zeitraumgrenze statt des
Kopf-/Rechnungsdatums und schlägt dadurch den falschen NK-Zeitraum vor. Dieses
Modul lässt stattdessen ein sprachverstehendes Modell den (gekürzten) OCR-Text
lesen und das *richtige* Belegdatum sowie Betrag und eine Klassifizierungs-
Andeutung herausziehen.

Datenschutz — WICHTIG
---------------------
Der OCR-Text enthält echte Namen, IBANs und Beträge. Mit gesetztem
`ANTHROPIC_API_KEY` wird er an die Anthropic-API gesendet. Deshalb:

* **Opt-in.** Ohne vom Nutzer gesetzten Key ist das Feature stumm — genau wie
  die Bilderkennung ohne Tesseract. Standardmäßig ist es nie aktiv.
* **Kein Beleginhalt ins Log.** Bei Erfolg wird nur dezent geloggt, dass etwas
  gelesen wurde — nie der Text, nie die extrahierten Beträge oder Namen.

Bei JEDEM Fehler (kein Key, Netzwerk, Timeout, ungültige Antwort) gibt
`lies_beleg` `None` zurück und wirft nie eine Exception nach außen. Der Scan
funktioniert dann wie bisher, nur ohne KI-Vorschlag.
"""
from __future__ import annotations

import logging
import re
from datetime import date

try:                                                     # pragma: no cover
    import httpx
except ImportError:                                      # pragma: no cover
    httpx = None
    logging.getLogger("immocalc").info(
        "httpx fehlt — KI-Auslese bleibt stumm")

log = logging.getLogger("immocalc")

# N270 — die kanonische Gewerke-Liste (Elektro, Sanitär, Maler …) lebt in
# `renovierung.py`, damit es sie nur EIN Mal gibt (dort baut sie zusätzlich
# das Kreisdiagramm je Gewerk auf). Hier wird sie nur importiert und beim
# Auslesen gegen ein von der KI genanntes Gewerk geprüft. Der Fallback fängt
# ausschließlich den Übergang ab, in dem `renovierung.py` noch nicht existiert
# (parallele Arbeit an N270) — sobald die Datei da ist, greift der Import
# oben und dieses Modul (und alles, was es transitiv lädt) bricht nicht am
# fehlenden Import weg.
from . import erwerb, kiclient                           # noqa: E402
from .renovierung import GEWERKE                         # noqa: E402

# N288-B2 — Endpunkt, Kopfzeilen, Zeitlimit und Fehlerbehandlung stehen ein
# einziges Mal in `kiclient.py`. Hier bleiben nur die Namen, unter denen sie im
# Haus bekannt sind (`routers/ki.py` zeigt das Vorgabemodell in den
# Einstellungen an).
STANDARD_MODELL = kiclient.STANDARD_MODELL

# Mehr Text kostet mehr Tokens, ohne dass der Briefkopf (mit dem Datum) besser
# würde — er steht ohnehin oben. 6000 Zeichen decken die erste Seite ab.
MAX_ZEICHEN = 6000
# CCCLXVII: die Antwort trägt jetzt zusätzlich eine mehrsätzige Zusammenfassung
# und die inhaltliche Einschätzung (Kosten? NK? Zeitraum?) — dafür etwas mehr
# Raum, damit der Schluss-Satz nicht mitten im Wort abbricht.
MAX_TOKENS = 700
ZEITLIMIT = 15.0

# CCLXXIV: Das Modell zieht NUR die App-Eingabefelder je Dokumenttyp — das
# „Raster". Was auf dem Beleg fehlt, lässt es weg (kein erfundener Wert). Immer
# dabei: die IMMOBILIE (Liegenschaft/Anwesen, NICHT die Postanschrift), ggf. die
# Einheit, und die Einordnung. Knappe, deutsche Anweisung; das Modell soll NUR
# JSON liefern.
SYSTEM_PROMPT = (
    "Du liest einen deutschen Immobilien-Beleg (Rechnung/Bescheid/Vertrag). "
    "Gib NUR JSON zurück, kein weiterer Text:\n"
    '{"dokumenttyp":"…","kategorie":"…","absender":"…","immobilie":"…","einheit":"…",'
    '"datum":"YYYY-MM-DD|null","betrag":<Zahl|null>,'
    '"teilbetrag":<Zahl|null>,"teilzahlungen":<Zahl|null>,"ist_kosten":true|false,'
    '"kosten_relevant":true|false,"nebenkosten":true|false,'
    '"zeitraum_hinweis":"…","abrechnungsjahr":<Jahr|null>,'
    '"kostenart":"…","gewerk":"…","felder":{…},'
    # N309 — fürs Kontaktbuch: unter welcher Nummer WIR bei diesem Absender
    # geführt werden. Stand auf fast jedem Beleg und wurde nie gelesen.
    '"kundennummer":"…","vertragsnummer":"…","aktenzeichen":"…",'
    '"zusammenfassung":"…"}\n'
    "dokumenttyp = kurze Bezeichnung der Belegart (Mietvertrag, Versicherung, "
    "Kredit, Grundsteuerbescheid, Kaufvertrag, Grundbuch, WEG-Abrechnung, "
    "Nebenkosten-Rechnung, Zählerstand …). "
    "kategorie = bestimmt den Ablage-Ordner und MUSS EXAKT EINER dieser Werte "
    "sein: \"Nebenkosten\", \"Steuer\", \"Versicherung\", \"Kredit\", "
    "\"Mietvertrag\", \"Hausverwaltung\", \"Korrespondenz\", "
    "\"Erwerbsnebenkosten\", \"Sonstiges\". "
    # N283d — ohne diese Zeile ordnete die Auslese Notarrechnung und
    # Grunderwerbsteuer der laufenden „Steuer" zu; sie landeten damit beim
    # Finanzamt statt beim Erwerb, zu dem sie gehören.
    "\"Erwerbsnebenkosten\" sind die EINMALIGEN Kosten rund um den Kauf: "
    "Notarrechnung, Grunderwerbsteuer, Grundbuchamt, Maklercourtage, "
    "Gutachten, Grundschuldbestellung. Die laufende Grundsteuer und die "
    "Einkommensteuer gehören dagegen NICHT dazu. "
    "immobilie = Adresse der LIEGENSCHAFT/des Objekts, um die es geht "
    "(Straße + Nr, PLZ, Ort). Suche die Bezeichnungen \"Anwesen\", "
    "\"Liegenschaft\", \"Objekt\", \"Grundstück\", \"Verbrauchsstelle\", "
    "\"Lieferadresse\". Das ist NICHT die Empfänger-/Postanschrift. Beispiel: "
    "Ein Brief geht an \"Tauchersreuther Str. 7\", nennt aber \"Anwesen: Laufer "
    "Str. 5\" → immobilie = \"Laufer Str. 5\". Steht keine Liegenschaft dabei, "
    "immobilie weglassen. "
    "einheit = die betroffene Wohnung/Einheit, falls genannt (z. B. \"Whg 1. "
    "OG\", \"EG rechts\"), sonst weglassen. "
    "datum = Ausstellungs-/Rechnungsdatum aus dem Briefkopf, NICHT das "
    "Zahlungsziel, NICHT eine Zeitraumgrenze. "
    "absender = der/die Ausstellende des Belegs: Firma, Behörde, Zweckverband, "
    "Gemeinde/Stadt, Versorger oder Versicherer, als Name (z. B. \"Zweckverband "
    "Wasserversorgung\", \"WWK Versicherung AG\", \"Stadt Eckental\", \"E.ON\"). "
    "Das ist der Rechnungssteller/Absender im Briefkopf, NICHT der Empfänger. "
    "Steht keiner erkennbar dabei, absender weglassen. "
    # N309 — der Nutzer baut ein Kontaktbuch und will „unsere Kundennummern"
    # je Firma darin sehen. Sie stehen auf fast jedem Beleg, meist im Kopf
    # neben dem Absender, und wurden bisher gar nicht gelesen.
    "kundennummer = die Nummer, unter der WIR bei diesem Absender geführt "
    "werden — im Briefkopf oder Adressfeld, oft als \"Kundennummer\", "
    "\"Kunden-Nr.\", \"Vertragskonto\", \"Geschäftspartner\", \"Zählpunkt\", "
    "\"Mitgliedsnummer\". NICHT die Rechnungsnummer, NICHT die Belegnummer, "
    "NICHT das Datum. Steht keine dabei, kundennummer weglassen. "
    "vertragsnummer = eine davon getrennte Vertrags-, Policen- oder "
    "Darlehensnummer, falls der Beleg beide führt. "
    "aktenzeichen = bei Behördenschreiben das Aktenzeichen oder Kassenzeichen "
    "(Finanzamt, Gemeinde, Grundbuchamt). "
    "betrag = NUR der tatsächlich geforderte Gesamt-/Rechnungsbetrag in Euro als "
    "Zahl (Punkt als Dezimaltrenner, ohne Währungszeichen). Der Betrag ist IMMER "
    "POSITIV — die Höhe der Forderung, nie negativ; ein Minus/Klammern auf einer "
    "Saldo- oder Gutschriftzeile ändert daran nichts. Zahlen aus Geräte-"
    "Kennungen, Serien-/Zählernummern oder Datumsangaben (z. B. …,2003,03/2004 "
    "auf einer Typenplakette) sind KEIN Betrag — dann null. "
    # N162 — auf einer Energie-Jahresabrechnung stehen mehrere Beträge
    # nebeneinander. Abgerechnet wird die LIEFERUNG, nicht der Restsaldo.
    "Bei einer Jahres-/Verbrauchsabrechnung eines Energieversorgers (Strom, Gas, "
    "Fernwärme) ist der Betrag der BRUTTOBETRAG DER LIEFERUNG für den "
    "abgerechneten Zeitraum (\"Summe Bruttobetrag\", \"Rechnungsbetrag brutto\") "
    "— NICHT die Nachzahlung/Restforderung nach Abzug der geleisteten Abschläge "
    "und NICHT der monatliche Abschlag. Beispiel: \"Stromlieferung … 862,51 — "
    "abzüglich geleisteter Zahlungen -807,00 — Nachzahlung 55,51 — monatliche "
    "Abschlagszahlung 72,00\" → betrag = 862.51. "
    # N279 — der häufigste Lesefehler bei Handwerkerrechnungen: das Modell
    # nimmt den ERSTEN Betrag, den es findet. Bei einer mehrseitigen Rechnung
    # sind das die Positionszeilen der ersten Seite, nicht die Endsumme.
    "MEHRSEITIGE RECHNUNGEN: Die Seiten bauen in der übergebenen Reihenfolge "
    "aufeinander auf. Der zu zahlende Gesamtbetrag steht deshalb am ENDE des "
    "Textes — auf der letzten Seite, in einer Zeile wie \"Gesamtbetrag\", "
    "\"Rechnungsbetrag\", \"Endbetrag\", \"Summe brutto\", \"Bruttobetrag\", "
    "\"Zu zahlen\" oder \"Zahlbetrag\". Nimm NICHT den ersten Betrag, der im "
    "Text auftaucht: davor stehen Einzelpositionen, Mengen×Einheitspreise, "
    "Zwischensummen und Netto-Beträge. Gibt es mehrere Kandidaten, gilt der "
    "LETZTE Brutto-Gesamtbetrag im Dokument. "
    # N262 — eine Abbuchungsvorankündigung nennt Raten, keine Jahressumme. Der
    # Nutzer will den JAHRESWERT in der Nebenkostenabrechnung stehen haben; die
    # Herleitung wird zusätzlich ausgewiesen, damit sie prüfbar bleibt.
    "TEILBETRÄGE HOCHRECHNEN: Nennt der Beleg keine Gesamtsumme, sondern gleich "
    "hohe Teilbeträge zu mehreren Fälligkeitsterminen (Abbuchungs-/Lastschrift"
    "vorankündigung, Ratenplan, Quartals- oder Abschlagszahlung), dann setze "
    "teilbetrag = der einzelne Fälligkeitsbetrag, teilzahlungen = die Anzahl "
    "solcher Zahlungen im JAHR, und betrag = teilbetrag × teilzahlungen, also "
    "den Jahresbetrag. Grundsteuer und kommunale Grundabgaben werden in "
    "Deutschland zu den gesetzlichen Terminen 15.02., 15.05., 15.08. und 15.11. "
    "fällig — das sind VIER Quartalszahlungen im Jahr, auch wenn das Schreiben "
    "nur zwei davon aufführt. Beispiel: \"15.08.2026 … 87,00\" und \"15.11.2026 "
    "… 87,00\" → teilbetrag = 87, teilzahlungen = 4, betrag = 348. Halbjährliche "
    "Fälligkeit = 2, jährliche (01.07.) = 1, monatliche = 12. Steht dagegen eine "
    "echte Jahres-/Gesamtsumme auf dem Beleg, gilt DIESE als betrag und "
    "teilbetrag/teilzahlungen bleiben null. "
    "ist_kosten = false bei reinen Info-Belegen (SEPA-Mandat, Zählerstand, "
    "Ableseprotokoll), sonst true. "
    "kosten_relevant = true NUR, wenn auf dem Beleg echte, bezifferte Kosten "
    "gefordert werden (eine Rechnung/ein Bescheid mit Rechnungsbetrag). Eine "
    "bloße Bescheinigung, ein Mess-/Prüfprotokoll (z. B. Schornsteinfeger-"
    "Messbescheinigung), ein Zählerstand oder ein Informationsschreiben OHNE "
    "geforderten Betrag = false. Ist kosten_relevant=false, setze betrag=null. "
    # N262 — der Fehler, der das ausgelöst hat: eine Abbuchungsvorankündigung
    # mit zweimal 87,00 € wurde als „ohne Kostenangabe" abgetan.
    "ACHTUNG: Eine Abbuchungs-/Lastschriftvorankündigung MIT bezifferten "
    "Fälligkeitsbeträgen ist kosten_relevant = true — sie nennt die Kosten, auch "
    "wenn sie keine Rechnung ist. Nur ohne jeden Betrag (reines Mandat, blosse "
    "Terminankündigung) bleibt sie false. "
    "nebenkosten = true, wenn diese Kosten in die Nebenkosten-/Betriebskosten-"
    "abrechnung des Mieters gehören (umlagefähig: Wasser, Abwasser, Müll, "
    "Heizung, Schornsteinfeger, Grundsteuer, Gebäudeversicherung, Hausmeister, "
    "Winterdienst …); false bei nicht umlagefähigen Kosten (Instandhaltung, "
    "Verwaltervergütung, Kontoführung) oder wenn keine Kosten entstanden. "
    "zeitraum_hinweis = für welchen Abrechnungszeitraum/welches Jahr der Beleg "
    "zählt. Beachte: eine Rechnung trägt oft ein späteres Datum als der "
    "Zeitraum, den sie abrechnet (Rechnung im März 2025 für das Abrechnungsjahr "
    "2024) — nenne das Jahr des ABRECHNUNGSZEITRAUMS, nicht bloß das "
    "Rechnungsdatum. Leer, wenn es kein Abrechnungsbeleg ist. "
    "abrechnungsjahr = das JAHR des abgerechneten Zeitraums als Zahl. Trägt ein "
    "Beleg BEIDES — einen abgerechneten Zeitraum UND einen Abschlags-/Voraus-"
    "zahlungs-/Grundgebühr-Zeitraum für die Zukunft —, zählt der ABGERECHNETE "
    "Zeitraum, nicht der Abschlag. Beispiel: \"Abrechnung 2025, Grundgebühr "
    "2026\" → abrechnungsjahr = 2025 (NICHT 2026). Nimm auch NICHT das bloße "
    "Rechnungs-/"
    "Briefdatum, wenn der abgerechnete Zeitraum davorliegt (Bescheid vom Januar "
    "2026 rechnet 2025 ab → 2025). Kein Abrechnungsbeleg → null. "
    "kostenart = worum es GENAU geht, kurz (z. B. Heizöl, Grundsteuer, Wasser, "
    "Gebäudeversicherung, Schornsteinfeger, Müll, Darlehen). "
    # N270 — für die Renovierungsposten braucht die Kreisdiagramm-Auswertung
    # das Gewerk. Lieber gar keins als ein erfundenes: die Antwort wird
    # serverseitig gegen die feste Liste geprüft (siehe `_gewerk`).
    "gewerk = NUR bei einer Handwerker-/Bauleistung: das Gewerk, zu dem die "
    "Leistung gehört, EXAKT EINER dieser Werte: \"Rohbau\", \"Dach\", "
    "\"Fassade & Dämmung\", \"Fenster & Türen\", \"Elektro\", \"Sanitär\", "
    "\"Heizung\", \"Trockenbau\", \"Estrich & Böden\", \"Fliesen\", \"Maler\", "
    "\"Küche\", \"Außenanlagen\", \"Planung & Gebühren\", \"Sonstiges\". "
    "Zuordnungshilfen: Elektroinstallation/Zählerschrank/Steckdosen/"
    "Lichtschalter → Elektro; Bad/WC/Leitungen/Sanitärobjekte/Armaturen → "
    "Sanitär; Heizkörper/Wärmepumpe/Therme/Kessel → Heizung; Parkett/Laminat/"
    "Estrich/Bodenbelag → \"Estrich & Böden\"; Tapezieren/Streichen/Spachteln/"
    "Lackieren → Maler; Architekt/Statiker/Baugenehmigung/Bauantrag/"
    "Bauleitung → \"Planung & Gebühren\"; Gerüst/Dämmung/Putz/Wärmedämm-"
    "verbundsystem → \"Fassade & Dämmung\". Passt eine Handwerkerleistung zu "
    "keinem der übrigen Werte, gewerk = \"Sonstiges\". Ist es GAR KEINE Bau-/"
    "Handwerkerleistung (Versicherung, Kredit, Nebenkosten …), gewerk ganz "
    "WEGLASSEN — nicht \"Sonstiges\" raten. "
    "zusammenfassung = 2 bis 4 vollständige deutsche Sätze: was für ein Dokument "
    "das ist (Art, Absender), ob echte Kosten entstanden sind, ob es in die "
    "Nebenkostenabrechnung gehört, und für welchen Abrechnungszeitraum.\n"
    "felder = NUR die zum Typ passenden Angaben, die WIRKLICH auf dem Beleg "
    "stehen (Fehlendes weglassen). Raster je Typ:\n"
    # N280-D — `mietende` fehlte, obwohl die Maske ein Feld „Beendet am" hat und
    # die Zuordnung es längst erwartete: das Feld blieb strukturell immer leer.
    "MIETVERTRAG: mieter, kaltmiete, nebenkosten_vz, stellplatzmiete, "
    "sonstige_einnahmen, mietbeginn, mietende (nur bei befristetem oder "
    "gekündigtem Vertrag), kaution, personen, mieter_email, "
    "mieter_telefon.\n"
    "VERSICHERUNG: art, anbieter, police_nr, jahresbeitrag, turnus, "
    "versicherungssumme, beginn, ende, umlagefaehig.\n"
    "KREDIT/BAUSPAREN: bezeichnung, bank, darlehensnummer, darlehenssumme, "
    "bausparsumme, angespart, restschuld, zinssatz, rate_monatlich, "
    "zinsbindung_bis, beginn, schuldzinsen_jahr, jahr.\n"
    "GRUNDSTEUER: grundsteuerwert, grundsteuer_messbetrag, "
    "grundsteuer_hebesatz, jahresbetrag.\n"
    "KAUFVERTRAG: kaufpreis, kaufdatum.\n"
    # N263 — der Notarvertrag füllt eine eigene Eingabemaske (Art, Notar,
    # URNr, Beurkundungsdatum, Kaufpreis, Beteiligte). Ohne dieses Raster kam
    # von ihm nur ein Kaufpreis zurück und alles andere musste abgetippt werden.
    "NOTARVERTRAG/BEURKUNDUNG: art (Kaufvertrag, Auflassung, Grundschuld-"
    "bestellung, Übergabevertrag …), notar (Name des Notars oder des "
    "Notariats), urnr (Urkundenrollennummer, steht als \"URNr\", \"UR-Nr.\", "
    "\"Urkundenrolle Nr.\"), beurkundet_am (Datum der Beurkundung als "
    "YYYY-MM-DD), kaufpreis, beteiligte (Verkäufer und Käufer als ein Text, "
    "z. B. \"Meier → Schmidt\").\n"
    "GRUNDBUCH/GRUNDSCHULD: gemarkung, flurstueck, grundbuch_blatt, glaeubiger, "
    "grundschuld_betrag, rang.\n"
    # N276 — die Rechnungen rund um den Erwerb. Sie sehen sich sehr ähnlich
    # (alle amtlich, alle „Kostenrechnung"), meinen aber steuerlich
    # Gegensätzliches. Die KV-Nummer steht auf jeder GNotKG-Rechnung und ist
    # der eindeutigste Anhaltspunkt, den es hier gibt.
    "ERWERBSNEBENKOSTEN (einmalige Kosten rund um den Kauf): erwerbsart — "
    "EXAKT einer dieser Werte: \"Notar\", \"Notar – Grundschuldbestellung\", "
    "\"Grunderwerbsteuer\", \"Grundbuchamt – Eigentumsumschreibung\", "
    "\"Grundbuchamt – Auflassungsvormerkung\", \"Grundbuchamt – Grundpfandrecht\", "
    "\"Katasterfortführung\", \"Vermessung / Gebäudeeinmessung\", "
    "\"Makler / Courtage\", \"Gutachter / Wertermittlung\", "
    "\"Bodengutachten / Baugrund\", \"Erschließungskosten\", "
    "\"Baugenehmigung / Behördengebühren\", \"Finanzierungsnebenkosten\", "
    "\"Sonstiges\". "
    "ZUORDNUNG — die KV-Nummer der Kostenrechnung ist das sicherste Merkmal: "
    "KV 21100/21101 (Beurkundungsverfahren Kauf-/Bauträgervertrag, Auflassung) "
    "→ \"Notar\"; KV 21200 (Beurkundung Grundschuldbestellung) → "
    "\"Notar – Grundschuldbestellung\"; KV 14110 (Eigentumsumschreibung) → "
    "\"Grundbuchamt – Eigentumsumschreibung\"; KV 14150/14152 (Auflassungs"
    "vormerkung, deren Löschung) → \"Grundbuchamt – Auflassungsvormerkung\"; "
    "KV 14121 (Grundpfandrecht) → \"Grundbuchamt – Grundpfandrecht\". "
    "Hilfsweise der ABSENDER: Landesjustizkasse / Amtsgericht Grundbuchsache → "
    "Grundbuchamt; Finanzamt mit \"Bescheid über Grunderwerbsteuer\" → "
    "\"Grunderwerbsteuer\"; Amt für Digitalisierung, Breitband und Vermessung "
    "(Gebäudeeinmessung, VermKatG) → \"Vermessung / Gebäudeeinmessung\"; "
    "Katasterfortführungsgebühr (KatFortGebG) → \"Katasterfortführung\". "
    "Trägt eine Rechnung MEHRERE Positionen (eine Landesjustizkasse-Rechnung "
    "nennt oft Vormerkung UND Grundpfandrecht), nimm die Art der betragsmäßig "
    "größten Position. Ist es keine Erwerbsnebenkosten-Rechnung, lass "
    "erwerbsart weg — rate nicht \"Sonstiges\".\n"
    "WEG: verwalter, hausgeld_monatlich, ruecklage_zufuehrung.\n"
    # N280-D — die Renovierungsposten-Maske (N270) hatte kein eigenes Raster:
    # die ausführende Firma kam nur über den allgemeinen `absender` durch, und
    # der ist bei einer Rechnung über einen Zahlungsdienstleister der Falsche.
    # Das Gewerk steht bewusst nicht hier — es ist ein eigenes Antwortfeld und
    # wird gegen die feste Liste geprüft.
    "HANDWERKERRECHNUNG (Bau-/Renovierungsleistung): firma (der ausführende "
    "Handwerksbetrieb), leistung (was gemacht wurde, in wenigen Worten).\n"
    "NEBENKOSTEN-RECHNUNG: kostenart, betrag, zeitraum, s35a (true bei "
    "haushaltsnaher Dienstleistung: Schornsteinfeger, Wartung, Hausmeister, "
    "Winterdienst, Gartenpflege), verbrauch.\n"
    # N162 — der Strombeleg trägt zwei Zahlen, mit denen gerechnet wird: die
    # verbrauchte Menge und der Bruttobetrag der Lieferung. Beide gehören ins
    # Raster, damit sie nicht nur im Fließtext der Zusammenfassung stehen.
    "STROM-/ENERGIE-RECHNUNG (Stromversorger, Gas, Fernwärme): verbrauch_kwh "
    "(der Gesamtverbrauch des abgerechneten Zeitraums in kWh, kein Euro-Betrag "
    "und kein Zählerstand), bruttobetrag (Bruttobetrag der Lieferung, "
    "Grundpreis und MwSt. enthalten), nachzahlung (Restbetrag nach Abzug der "
    "Abschläge — NICHT bruttobetrag), abschlag_monat (monatliche "
    "Abschlagszahlung), zeitraum_von, zeitraum_bis (Anfang/Ende des "
    "abgerechneten Zeitraums als YYYY-MM-DD).\n"
    "INFO-BELEG (Zählerstand/Ableseprotokoll/SEPA-Mandat): keine felder, "
    "ist_kosten=false.\n"
    "Nimm KEINE Felder wie Zahlstatus/\"bezahlt\", KEINE fremde IBAN, KEINE "
    "Notar- oder Sachbearbeiternamen auf."
)


def verfuegbar(schluessel: str = "") -> bool:
    """Ist die KI-Auslese eingerichtet?

    Mit einem ausdrücklich übergebenen Schlüssel (aus den Einstellungen) ODER
    einem gesetzten `ANTHROPIC_API_KEY`. Ohne beides bleibt das Feature stumm,
    damit kein Beleginhalt ungewollt das Haus verlässt."""
    return bool(_schluessel(schluessel))


# Die Schlüsselwahl (übergebener vor Env) gehört zum Aufruf und lebt deshalb
# in `kiclient`; hier steht sie unter dem gewohnten Namen.
_schluessel = kiclient.api_schluessel


def _datum(wert) -> str | None:
    """Ein gültiges ISO-Datum oder None. Alles andere (Zeitraum, Unfug) fliegt
    raus — lieber kein Datum als ein falsches."""
    if not wert or not isinstance(wert, str):
        return None
    roh = wert.strip()[:10]
    try:
        return date.fromisoformat(roh).isoformat()
    except ValueError:
        return None


def _hochrechnung(betrag: float | None, teilbetrag: float | None,
                  anzahl) -> tuple[float | None, int | None, float | None]:
    """N262 — Teilbetrag × Anzahl = Jahresbetrag, hier nachgerechnet.

    Das Modell soll `betrag` bereits als Jahressumme liefern. Verlassen wird
    sich darauf nicht: Rechnen ist die schwächste Seite eines Sprachmodells,
    und ein falscher Jahreswert landete ungeprüft in der Abrechnung. Liegen
    Teilbetrag und Anzahl vor, gilt deshalb **das Produkt**, nicht die vom
    Modell genannte Summe.

    Unplausibles wird verworfen statt geraten: eine Anzahl ausserhalb von 1…12
    ist keine Zahlweise, die es gibt. Fehlt eines von beiden, bleibt alles wie
    es war — dann gab es schlicht keine Teilzahlung zu erkennen.
    """
    stueck = None
    try:
        stueck = int(anzahl)
    except (TypeError, ValueError):
        stueck = None
    if not teilbetrag or stueck is None or not 1 <= stueck <= 12:
        return None, None, betrag
    if stueck == 1:
        # Eine einzige Zahlung ist keine Hochrechnung — sie IST der Betrag.
        return None, None, betrag if betrag else teilbetrag
    return teilbetrag, stueck, round(teilbetrag * stueck, 2)


def _betrag(wert) -> float | None:
    """Ein Betrag als Zahl. Das Modell soll schon einen Punkt liefern; kommt
    doch ein deutsches Komma oder ein Währungszeichen, wird es aufgeräumt."""
    if isinstance(wert, bool):        # bool ist eine Zahl in Python — hier nicht
        return None
    # CCCXCIII — ein Betrag ist die Höhe der Forderung, immer positiv.
    if isinstance(wert, (int, float)):
        return round(abs(float(wert)), 2)
    if isinstance(wert, str):
        roh = re.sub(r"[^\d,.-]", "", wert).replace(",", ".")
        # Mehrere Punkte (Tausendertrenner) → nur der letzte zählt als Dezimal
        if roh.count(".") > 1:
            ganz, _, rest = roh.rpartition(".")
            roh = ganz.replace(".", "") + "." + rest
        try:
            return round(abs(float(roh)), 2)
        except ValueError:
            return None
    return None


# Die Mengeneinheit fliegt VOR dem Zahlenlesen raus: die „3" aus „m3" ist keine
# Ziffer der Menge (sonst wird aus „40 m3" 403 oder 43).
_EINHEIT = re.compile(r"(?i)m\s*(?:³|3|\^3)|cbm|kubikmeter")
# Eine Zahl samt Tausenderpunkt/Dezimalkomma.
_ZAHL = re.compile(r"\d[\d.,\s]*")


def _menge(wert) -> float | None:
    """Eine Verbrauchsmenge in m³ als Zahl — N102b.

    Wie `_betrag`, aber für Kubikmeter: die Einheit („m³", „m3", „cbm") wird
    abgeschnitten, das deutsche Komma zum Punkt („122,00 cbm" → 122.0). Liefert
    das Modell statt einer Summe die Teilmengen (Zählerwechsel) — als Liste
    oder als „102 m³ + 40 m³" —, werden sie addiert. Null oder negativ heißt
    „nicht gefunden" → None; eine Menge von 0 m³ ist keine belastbare Angabe.

    N287 — gelesen wird mit `_zahl_de`, NICHT mit `_betrag`. Der Unterschied
    entscheidet über den Faktor 1000: `_betrag` nimmt den letzten Punkt als
    Dezimaltrenner (bei Geld richtig), also würde aus „2.416 m³" ein Verbrauch
    von 2,416 m³. `gesamt_m3` geht als `rechnung_m3` in `wasser.verrechne` und
    bestimmt dort den Preis je m³ und die Verteilung auf alle Einheiten — der
    Fehler landete also unbemerkt in der Abrechnung. `_kwh` löst dasselbe
    Problem beim Strom seit N162 genau so."""
    if isinstance(wert, list):
        return _summe(_menge(teil) for teil in wert)
    if isinstance(wert, str):
        ohne_einheit = _EINHEIT.sub(" ", wert)
        teile = [_zahl_de(t) for t in _ZAHL.findall(ohne_einheit)]
        # Eine Menge ist ihr Betrag — ein Vorzeichen wäre ein Lesefehler.
        teile = [abs(t) if t is not None else None for t in teile]
        if "+" in wert:
            return _summe(teile)
        return next((t for t in teile if t), None)
    menge = _zahl_de(wert)
    return abs(menge) if menge else None


def _summe(mengen) -> float | None:
    """Die Summe vorhandener Teilmengen — None, wenn nichts Brauchbares übrig
    bleibt."""
    summe = sum(m for m in mengen if m)
    return round(summe, 2) if summe > 0 else None


# N162 — Strommengen. Die Einheit fliegt vor dem Zahlenlesen raus; „MWh" wird
# vorher gemerkt, weil daraus der Faktor 1000 folgt.
_STROM_EINHEIT = re.compile(r"(?i)\b(?:k|m)?\s*wh\b|kilowattstunden?|"
                            r"megawattstunden?")
_MEGA = re.compile(r"(?i)\bm\s*wh\b|megawattstunde")
# Eine deutsche Tausendergliederung: 2.416 · 1.234.567 — aber nicht 12.5.
_TAUSENDER = re.compile(r"\d{1,3}(?:\.\d{3})+")


def _zahl_de(wert) -> float | None:
    """Eine Zahl in deutscher Schreibweise — und nur in dieser.

    `_betrag` reicht dafür nicht: dort gilt der letzte Punkt als Dezimaltrenner,
    was bei einem Geldbetrag stimmt („1.234.56" → 1234.56), bei einer Menge ohne
    Nachkommastellen aber falsch ist — aus „2.416 kWh" würde 2,416 kWh, also ein
    Tausendstel des Verbrauchs. Hier entscheidet die Form:

    * Komma vorhanden → Komma ist der Dezimaltrenner, Punkte sind Tausender
      („2.416,0" → 2416.0)
    * nur Punkte, und sie gliedern in Dreiergruppen → Tausendertrenner
      („2.416" → 2416.0)
    * sonst ist der Punkt der Dezimaltrenner („12.5" → 12.5)
    """
    roh = re.sub(r"[^\d,.]", "", str(wert or ""))
    if not roh:
        return None
    if "," in roh:
        roh = roh.replace(".", "").replace(",", ".")
    elif _TAUSENDER.fullmatch(roh):
        roh = roh.replace(".", "")
    try:
        return float(roh)
    except ValueError:
        return None


def _kwh(wert) -> float | None:
    """Eine Strommenge in Kilowattstunden als Zahl — N162.

    Die Einheit („kWh", „MWh", „Kilowattstunden") wird abgeschnitten, MWh dabei
    auf kWh hochgerechnet. Führt die Rechnung wegen eines Preis- oder
    Zählerwechsels Teilmengen — als Liste oder als „1256 + 1160" —, werden sie
    addiert. Null, negativ oder unlesbar heißt „nicht gefunden" → None; eine
    Menge von 0 kWh ist keine belastbare Angabe."""
    if isinstance(wert, list):
        return _summe(_kwh(teil) for teil in wert)
    if isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return round(abs(float(wert)), 3) or None
    if not isinstance(wert, str):
        return None
    faktor = 1000.0 if _MEGA.search(wert) else 1.0
    teile = [_zahl_de(t) for t in _ZAHL.findall(_STROM_EINHEIT.sub(" ", wert))]
    teile = [abs(t) for t in teile if t]
    if not teile:
        return None
    menge = sum(teile) if "+" in wert else teile[0]
    return round(menge * faktor, 3) or None


def _jahr(wert) -> int | None:
    """Ein plausibles Abrechnungsjahr als int (1990..heute+1) — N14. Alles andere
    (Unfug, weit daneben) fliegt raus; lieber kein Jahr als ein falsches."""
    if isinstance(wert, bool):
        return None
    try:
        j = int(str(wert).strip()[:4])
    except (ValueError, TypeError):
        return None
    return j if 1990 <= j <= date.today().year + 1 else None


# N270 — tolerant vergleichen: Groß-/Kleinschreibung und Leerzeichen dürfen
# das Modell nicht daran hindern, ein an sich richtiges Gewerk zu treffen.
_GEWERKE_NORMALISIERT = {g.strip().casefold(): g for g in GEWERKE}


def _gewerk(wert) -> str | None:
    """Ein vom Modell genanntes Gewerk — nur, wenn es EXAKT einem der
    kanonischen Werte entspricht (tolerant bei Groß-/Kleinschreibung und
    Leerzeichen), sonst `None`.

    Ein erfundenes Gewerk ("Fensterputzen") würde im Kreisdiagramm eine
    eigene Tortenscheibe erzeugen, die es in der festen Liste nicht gibt und
    die der Nutzer nirgends nachträglich zuordnen könnte — deshalb wird hier
    verworfen statt geraten."""
    if not isinstance(wert, str):
        return None
    return _GEWERKE_NORMALISIERT.get(" ".join(wert.split()).casefold())


def _text(wert) -> str:
    """Ein Klartextfeld (kostenart/kategorie) — knapp und ohne Zeilenumbrüche."""
    if not isinstance(wert, str):
        return ""
    return wert.strip().replace("\n", " ")[:60]


def _adresse(wert) -> str:
    """Eine Adresse (Liegenschaft/Einheit) — etwas länger als ein Klartextfeld,
    weil „Laufer Str. 5, 91207 Lauf" hineinpassen muss, aber ohne Umbrüche."""
    if not isinstance(wert, str):
        return ""
    return " ".join(wert.strip().split())[:120]


def _langtext(wert) -> str:
    """Ein mehrsätziges Feld (Zusammenfassung, Zeitraum-Hinweis) — CCCLXVII.

    Länger als ein Klartextfeld, damit der Schluss-Satz nicht mitten im Wort
    abbricht (genau der Grund, warum die alte 60-Zeichen-Einordnung „zu kurz
    und abgeschnitten" wirkte), aber begrenzt, damit eine ausufernde Antwort
    das Dokument nicht flutet."""
    if not isinstance(wert, str):
        return ""
    return " ".join(wert.split())[:400]


def _wahrheit(wert):
    """Ein echtes bool oder None — CCCLXVII.

    Fehlt die Angabe (ältere Antwort ohne das Feld), bleibt sie offen (None),
    nicht stillschweigend false: nur ein ausdrückliches false darf später den
    vorgeschlagenen Betrag streichen."""
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, str):
        w = wert.strip().lower()
        if w in ("true", "ja", "yes", "1"):
            return True
        if w in ("false", "nein", "no", "0"):
            return False
    return None


# So viele Felder nimmt ein Raster höchstens auf — genug für den grössten Typ
# (Mietvertrag/Kredit), eng genug, dass eine ausufernde Modellantwort nicht
# beliebig viel Müll ins Dokument schreibt.
_MAX_FELDER = 30


def _felder(wert) -> dict:
    """Das Raster-Feld der KI säubern: nur ein flaches dict mit knappen, string-
    fähigen Schlüsseln und Werten. Verschachteltes, Listen und Unfug fliegen
    raus — lieber ein Feld weniger als ein kaputtes."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict = {}
    for schluessel, roh in wert.items():
        if len(sauber) >= _MAX_FELDER:
            break
        name = str(schluessel).strip().replace("\n", " ")[:40]
        if not name:
            continue
        if isinstance(roh, bool):
            sauber[name] = roh
        elif isinstance(roh, (int, float)):
            sauber[name] = roh
        elif isinstance(roh, str):
            gekuerzt = " ".join(roh.split())[:120]
            if gekuerzt:
                sauber[name] = gekuerzt
        # Listen/dicts/None werden bewusst übergangen.
    return sauber


def lies_beleg(text: str, dateiname: str = "", schluessel: str = "",
               modell: str = "") -> dict | None:
    """Liest einen Beleg mit dem günstigen Claude-Modell.

    Gibt bei Erfolg ein dict mit den Schlüsseln `datum` (ISO-String oder None),
    `betrag` (float oder None), `kostenart`, `kategorie` und `ist_kosten`
    zurück. Bei jedem Fehler — fehlender Key, kein httpx, Netzwerk, Timeout,
    ungültige Antwort — `None`, nie eine Exception.

    `schluessel`/`modell` (aus den Einstellungen) haben Vorrang vor der Env;
    ohne beides bleibt die Auslese stumm.

    `dateiname` ist optional und dient nur als zusätzlicher Kontext (ein Name
    wie „2025-10-oel-2729,91€.pdf" nennt Datum und Betrag mit)."""
    if httpx is None:
        return None
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return None
    inhalt = (text or "").strip()
    if not inhalt:
        return None

    gekuerzt = inhalt[:MAX_ZEICHEN]
    nutzer = gekuerzt if not dateiname else f"Dateiname: {dateiname}\n\n{gekuerzt}"
    antwort = kiclient.frage_modell(
        nutzer, schluessel=schluessel, modell=modell, system=SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS, zeitlimit=ZEITLIMIT, etikett="KI-Auslese",
        http=httpx)
    if not antwort.ok:
        return None
    block = antwort.block
    if block is None:
        log.info("KI-Auslese lieferte kein verwertbares JSON")
        return None

    # CCCLXVII: die mehrsätzige Zusammenfassung ist die neue, längere Fassung
    # der Einordnung. Ältere Antworten kennen nur „einordnung" — dann gilt die.
    zusammenfassung = _langtext(block.get("zusammenfassung")
                                or block.get("einordnung"))
    teilbetrag, teilzahlungen, betrag = _hochrechnung(
        _betrag(block.get("betrag")),
        _betrag(block.get("teilbetrag")),
        block.get("teilzahlungen"))
    ergebnis = {
        "datum": _datum(block.get("datum")),
        "betrag": betrag,
        # N262 — die Herleitung bleibt sichtbar: die Bestätigungsmaske zeigt
        # „87,00 € × 4 = 348,00 €", damit der Nutzer erkennt, dass der Wert
        # gerechnet und nicht abgelesen ist, und ihn ggf. überschreibt.
        "teilbetrag": teilbetrag,
        "teilzahlungen": teilzahlungen,
        "kostenart": _text(block.get("kostenart")),
        # N270 — nur ein Wert aus der festen Gewerke-Liste kommt durch; alles
        # andere (erfunden, uneindeutig, Tippfehler) wird zu None statt einer
        # neuen, nicht existierenden Tortenscheibe im Kreisdiagramm.
        "gewerk": _gewerk(block.get("gewerk")),
        "kategorie": _text(block.get("kategorie")),
        "ist_kosten": bool(block.get("ist_kosten", True)),
        # CCCLXVII: die inhaltliche Einschätzung — sind Kosten entstanden, NK?,
        # welcher Abrechnungszeitraum, und die längere Zusammenfassung. Die
        # Zusammenfassung dient zugleich als (nicht mehr abgeschnittene)
        # Einordnung für die Anzeige und das Festhalten am Beleg (CCLXXIII).
        "kosten_relevant": _wahrheit(block.get("kosten_relevant")),
        "nebenkosten": _wahrheit(block.get("nebenkosten")),
        "zeitraum_hinweis": _langtext(block.get("zeitraum_hinweis")),
        # N14 — das Jahr des abgerechneten Zeitraums (nicht des Abschlags/Briefes).
        "abrechnungsjahr": _jahr(block.get("abrechnungsjahr")),
        "zusammenfassung": zusammenfassung,
        "einordnung": zusammenfassung,
        # CD — der Aussteller/Absender (Firma, Zweckverband, Gemeinde,
        # Versicherer). Der Prompt fragt ihn längst ab, nur durchgereicht wurde
        # er nie: `_ki_ergaenzen` fand `absender` deshalb immer leer, das
        # Firma-Feld im Drop-Dialog blieb trotz klarer Erkennung unbefüllt.
        "absender": _text(block.get("absender")),
        # CCLXXIV: das Raster — Liegenschaft (nicht Postanschrift), Einheit und
        # die typspezifischen App-Eingabefelder.
        "dokumenttyp": _text(block.get("dokumenttyp")),
        "immobilie": _adresse(block.get("immobilie")),
        "einheit": _adresse(block.get("einheit")),
        "felder": _felder(block.get("felder")),
    }
    # N309 — die Nummern, unter denen WIR bei diesem Absender geführt werden.
    #
    # Sie stehen an ZWEI Stellen, und das ist Absicht: oben, weil die Vorlage
    # sie verspricht und ein versprochenes Feld auch ankommen muss (der Wächter
    # `test_die_antwortfelder_kommen_auch_wirklich_zurueck` besteht darauf,
    # nachdem CD genau diesen Fehler beim `absender` heilen musste) — und im
    # Raster, weil NUR das am Beleg gespeichert wird (`_ki_am_beleg_festhalten`
    # schreibt `felder` nach `ki_felder`). Ohne den zweiten Platz fände das
    # Kontaktbuch später nichts mehr.
    for feld in ("kundennummer", "vertragsnummer", "aktenzeichen"):
        wert = _text(block.get(feld))
        ergebnis[feld] = wert
        if wert:
            ergebnis["felder"].setdefault(feld, wert)
    # N276 — die Erwerbsart gegen die feste Liste halten. Eine erfundene Art
    # („Vermessungsgebühr") sähe im Formular aus wie eine erkannte und würde
    # ungeprüft übernommen; dann stünde ein Wert im Feld, den die Auswahl gar
    # nicht kennt. Passt sie nicht, fliegt sie raus — lieber ein leeres Feld,
    # das der Nutzer füllt, als ein falsch gefülltes.
    art = erwerb.erwerbsart(ergebnis["felder"].get("erwerbsart"))
    if art:
        ergebnis["felder"]["erwerbsart"] = art
    else:
        ergebnis["felder"].pop("erwerbsart", None)
    # Dezent loggen — OHNE Datum, Betrag oder Namen (Datenschutz). Nur, dass
    # eine Antwort kam und ob ein Datum darin stand.
    log.info("KI-Auslese gelesen (Datum %s)",
             "vorhanden" if ergebnis["datum"] else "keins")
    return ergebnis


# --------------------------------------------------------------------------
# N78 — der wasser-spezifische Auslese-Zweig.
#
# Ein Wasser-/Abwasserbescheid rechnet meist drei getrennte Bereiche ab:
# Frischwasser, Schmutzwasser (Abwasser) und Niederschlagswasser. Der generische
# Ein-Betrag-Prompt liefert dafür nur eine Summe. Wird der Beleg als Wasser
# gehintet (die Wasser-Sammelposition ist das Ziel), fragt dieser Prompt gezielt
# die drei Bereichs-Gebühren ab — die drei Kostenpositionen lassen sich dann in
# einem Schritt setzen. Reiner Zusatz: `lies_beleg` bleibt unberührt.
#
# N102b: dazu der Gesamtwasserverbrauch der Periode in m³ (`gesamt_m3`) — der
# Nutzer gleicht damit ab, ob der Bescheid zur Differenz seiner Zählerstände
# passt. Er steht im Schmutzwasser-Block als Bemessungsgrundlage „Wasserbezug";
# nach einem Zählerwechsel führt der Wasser-Block ihn in Teilmengen.
# --------------------------------------------------------------------------
WASSER_SYSTEM_PROMPT = (
    "Du liest einen deutschen Wasser-/Abwasser-Gebührenbescheid (von einem "
    "Zweckverband, Wasserversorger oder einer Gemeinde). Gib NUR JSON zurück, "
    "kein weiterer Text:\n"
    '{"wasser":<Zahl|null>,"schmutz":<Zahl|null>,"niederschlag":<Zahl|null>,'
    '"gesamt_m3":<Zahl|null>}\n'
    "Der Bescheid rechnet oft drei getrennte Abrechnungsbereiche ab. Gesucht ist "
    "je die GESAMT-GEBÜHR/SUMME des Bereichs (Grund-/Bereitstellungsgebühr plus "
    "Verbrauchs-/Mengengebühr des Bereichs zusammen) für den abgerechneten "
    "Zeitraum — NICHT die monatlichen Abschläge/Vorauszahlungen und NICHT die "
    "Nachzahlung/den Saldo/das Zahlungsziel.\n"
    "wasser = Bereich Frischwasser/Trinkwasser/Wasserversorgung "
    "(\"Abrechnungsbereich Wasser\", \"Frischwasser\", \"Trinkwasser\", "
    "\"Wasserverbrauch\"). "
    "schmutz = Bereich Schmutzwasser/Abwasser/Kanal "
    "(\"Schmutzwasser\", \"Abwasser\", \"Kanalbenutzungsgebühr\", "
    "\"Entwässerung\"). "
    "niederschlag = Bereich Niederschlagswasser/Regenwasser/versiegelte Fläche "
    "(\"Niederschlagswasser\", \"Regenwassergebühr\", \"Oberflächenwasser\").\n"
    "Beträge in Euro als Zahl (Punkt als Dezimaltrenner, ohne Währungszeichen), "
    "immer positiv. Fehlt ein Bereich auf dem Beleg, den Wert null setzen. Ist es "
    "überhaupt kein Wasser-/Abwasserbescheid, alle drei auf null.\n"
    "gesamt_m3 = der GESAMTE Wasserverbrauch der abgerechneten Periode in "
    "Kubikmetern als Zahl (kein Geldbetrag!). Die Einheit heißt \"m³\", \"m3\" "
    "oder \"cbm\". So findest du ihn:\n"
    "1. BEVORZUGT im Abrechnungsbereich SCHMUTZWASSER: dort ist die "
    "Bemessungsgrundlage der \"Wasserbezug\" (auch \"Frischwasserbezug\", "
    "\"bezogene Wassermenge\") — diese eine m³-Zahl ist der Gesamtverbrauch. "
    "Beispiel: \"Wasserbezug 30.09.24 … 122,00 cbm\" → gesamt_m3 = 122.\n"
    "2. SONST im Abrechnungsbereich WASSER: stehen dort wegen eines "
    "Zählerwechsels mehrere Teilmengen, ADDIERE sie zu einer Summe "
    "(z. B. 102 m³ + 40 m³ → gesamt_m3 = 142).\n"
    "Nimm NICHT die versiegelte Fläche des Niederschlagswassers (die ist in m²), "
    "nicht einen Zählerstand und keinen Euro-Betrag. Steht keine Verbrauchsmenge "
    "auf dem Beleg, gesamt_m3 = null."
)
WASSER_TOKENS = 200


def ist_wasser_kontext(hinweis: str) -> bool:
    """Deutet der Kontext (Kostenart/Kategorie) auf einen Wasser-Beleg?

    Genügt für den Auslese-Zweig: die Wasser-Sammelposition heißt „Wasser",
    ihre Bestandteile „Abwasser"/„Niederschlagswasser" — alle tragen das Wort.
    Absichtlich tolerant (Umlaute, Groß/Klein), damit der Hinweis vom Frontend
    zuverlässig greift; der Zweig kostet nur dann einen zusätzlichen KI-Aufruf."""
    n = (hinweis or "").lower()
    n = (n.replace("ä", "ae").replace("ö", "oe")
          .replace("ü", "ue").replace("ß", "ss"))
    return "wasser" in n or "niederschlag" in n or "entwaesser" in n


def lies_wasser(text: str, dateiname: str = "", schluessel: str = "",
                modell: str = "") -> dict | None:
    """Liest die drei Bereichs-Gebühren eines Wasserbescheids (N78) samt
    Gesamtverbrauch (N102b).

    Gibt bei Erfolg `{"wasser": float|None, "schmutz": float|None,
    "niederschlag": float|None, "gesamt_m3": float|None}` zurück (die ersten
    drei je die Gesamt-Gebühr des Bereichs in Euro, `gesamt_m3` der
    Gesamtwasserverbrauch der Periode in Kubikmetern) — None, wo der Beleg die
    Angabe nicht hergibt. Bei jedem Fehler —
    kein Key, kein httpx, Netzwerk, Timeout, ungültige Antwort, kein Wasser-
    beleg — `None`, nie eine Exception. Derselbe Key-/Modell-Vorrang wie
    `lies_beleg`."""
    if httpx is None:
        return None
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return None
    inhalt = (text or "").strip()
    if not inhalt:
        return None

    gekuerzt = inhalt[:MAX_ZEICHEN]
    nutzer = gekuerzt if not dateiname else f"Dateiname: {dateiname}\n\n{gekuerzt}"
    antwort = kiclient.frage_modell(
        nutzer, schluessel=schluessel, modell=modell,
        system=WASSER_SYSTEM_PROMPT, max_tokens=WASSER_TOKENS,
        zeitlimit=ZEITLIMIT, etikett="KI-Wasserauslese", http=httpx)
    if not antwort.ok:
        return None
    block = antwort.block
    if block is None:
        log.info("KI-Wasserauslese lieferte kein verwertbares JSON")
        return None

    ergebnis = {
        "wasser": _betrag(block.get("wasser")),
        "schmutz": _betrag(block.get("schmutz")),
        "niederschlag": _betrag(block.get("niederschlag")),
        # N102b — der Gesamtwasserverbrauch der Periode in m³, zum Abgleich mit
        # der Differenz der eigenen Zählerstände.
        "gesamt_m3": _menge(block.get("gesamt_m3")),
    }
    # Dezent loggen — OHNE Beträge/Mengen (Datenschutz): nur, wie viele Bereiche
    # kamen und ob eine Verbrauchsmenge dabei war.
    log.info("KI-Wasserauslese gelesen (%d Bereiche, Menge %s)",
             sum(1 for k, v in ergebnis.items()
                 if k != "gesamt_m3" and v is not None),
             "vorhanden" if ergebnis["gesamt_m3"] is not None else "keine")
    return ergebnis


# --------------------------------------------------------------------------
# N162 — der strom-spezifische Auslese-Zweig.
#
# Beim Strom ist der einzige Beleg in der Hochlage der externe Zukauf. Gebraucht
# werden daraus genau zwei Zahlen: die wirklich verbrauchten Kilowattstunden und
# der Bruttopreis dafür (der Grundpreis steckt darin und wird NICHT getrennt
# umgelegt). Betrag durch Menge ergibt den Netzpreis; die Stromkette leitet
# daraus PV und Akku mit 10 % Abschlag ab.
#
# Die Schwierigkeit ist nicht das Finden, sondern das Auseinanderhalten: eine
# Jahresabrechnung nennt nebeneinander den Bruttobetrag der Lieferung (862,51 €),
# die Nachzahlung nach Abzug der Abschläge (55,51 €) und den monatlichen
# Abschlag (72,00 €). Der generische Ein-Betrag-Prompt greift dabei leicht
# daneben — oder liefert gar nichts, weil ihm keiner der Beträge sicher genug
# ist. Hier werden alle drei getrennt abgefragt und getrennt zurückgegeben, mit
# einer klaren Empfehlung, welcher gemeint ist.
# --------------------------------------------------------------------------
STROM_SYSTEM_PROMPT = (
    "Du liest eine deutsche Strom-/Energierechnung (Jahres- oder "
    "Verbrauchsabrechnung eines Versorgers). Gib NUR JSON zurück, kein weiterer "
    "Text:\n"
    '{"menge_kwh":<Zahl|null>,"brutto":<Zahl|null>,"netto":<Zahl|null>,'
    '"nachzahlung":<Zahl|null>,"guthaben":<Zahl|null>,'
    '"abschlag_monat":<Zahl|null>,"von":"YYYY-MM-DD|null",'
    '"bis":"YYYY-MM-DD|null"}\n'
    "Auf so einer Rechnung stehen MEHRERE Euro-Beträge nebeneinander. Halte sie "
    "streng auseinander — sie zu verwechseln verfälscht die Abrechnung um ein "
    "Vielfaches:\n"
    "brutto = der BRUTTOBETRAG DER LIEFERUNG für den abgerechneten Zeitraum, "
    "inklusive Mehrwertsteuer UND inklusive Grundpreis (\"Summe Bruttobetrag\", "
    "\"Stromlieferung … Bruttobetrag\", \"Rechnungsbetrag brutto\"). Das ist der "
    "Betrag VOR Abzug der geleisteten Abschlagszahlungen.\n"
    "netto = derselbe Betrag ohne Mehrwertsteuer (\"Nettobetrag\").\n"
    "nachzahlung = was nach Abzug der geleisteten Abschläge noch offen ist "
    "(\"Nachzahlung\", \"Restbetrag\", \"noch zu zahlen\"). Das ist NIE brutto.\n"
    "guthaben = eine Erstattung, wenn die Abschläge höher waren als der "
    "Verbrauch.\n"
    "abschlag_monat = die monatliche Abschlags-/Vorauszahlung. Das ist NIE "
    "brutto.\n"
    "Beispiel: \"Stromlieferung 724,80 / 137,71 / 862,51 — abzüglich "
    "geleisteter Zahlungen -807,00 — Nachzahlung 55,51 — monatliche "
    "Abschlagszahlung 72,00 EUR\" → brutto = 862.51, netto = 724.80, "
    "nachzahlung = 55.51, abschlag_monat = 72.00.\n"
    "menge_kwh = der GESAMTE abgerechnete Verbrauch des Zeitraums in "
    "Kilowattstunden als Zahl (kein Geldbetrag!). Fundstellen: "
    "\"Gesamtverbrauch\", \"Jahresverbrauch\", Spalte \"Verbrauch kWh\", "
    "\"Ihr Stromverbrauch … beträgt\". Führt die Rechnung wegen eines Preis- "
    "oder Zählerwechsels mehrere Teilmengen, nimm die GESAMTSUMME (z. B. "
    "1256 + 1160 → 2416), nie eine einzelne Teilmenge. Nimm NICHT einen "
    "Zählerstand (Anfangs-/Endzählerstand) und keinen Euro-Betrag.\n"
    "von/bis = Anfang und Ende des ABGERECHNETEN Zeitraums als ISO-Datum "
    "(\"Abrechnung für den Zeitraum vom 15.06.2024 bis 14.06.2025\" → "
    "von = \"2024-06-15\", bis = \"2025-06-14\"). NICHT das Rechnungsdatum, "
    "NICHT den Zeitraum künftiger Abschläge.\n"
    "Beträge in Euro als Zahl (Punkt als Dezimaltrenner, ohne Währungszeichen), "
    "immer positiv. Was auf dem Beleg nicht steht, auf null setzen — nie raten. "
    "Ist es überhaupt keine Strom-/Energierechnung, alle Felder auf null."
)
STROM_TOKENS = 260

# Wie ein Betrag heißt, damit am Feld steht, WELCHER Betrag dort liegt. Der
# Nutzer soll nie raten müssen, ob er die Lieferung oder den Restsaldo sieht.
STROM_BETRAGSARTEN = {
    "lieferung": "Bruttobetrag der Lieferung (Grundpreis enthalten)",
    "nachzahlung": "Nachzahlung nach Abzug der Abschläge",
    "abschlag": "Monatlicher Abschlag",
}


def ist_strom_kontext(hinweis: str) -> bool:
    """Deutet der Kontext (Kostenart/Absender/Belegart) auf einen Strombeleg?

    Absichtlich tolerant (Umlaute, Groß/Klein, Wortteile), damit „Allgemein­
    strom", „Hausstrom", „Stromkosten" und ein Absender wie
    „Elektrizitätsversorgung" gleichermaßen greifen. Der Zweig kostet nur dann
    einen zusätzlichen KI-Aufruf."""
    n = (hinweis or "").lower()
    n = (n.replace("ä", "ae").replace("ö", "oe")
          .replace("ü", "ue").replace("ß", "ss"))
    return any(wort in n for wort in ("strom", "elektrizitaet", "elektrizitat",
                                      "kwh", "kilowattstunde"))


def _strom_kandidaten(block: dict) -> list[dict]:
    """Die belegten Beträge, benannt und geordnet — der beste zuerst.

    Nicht raten und nicht schweigen: sind mehrere Beträge plausibel, kommen alle
    mit, damit die Oberfläche sie zur Wahl stellen kann. Die Reihenfolge ist die
    fachliche Rangfolge — abgerechnet wird die Lieferung."""
    roh = [("lieferung", _betrag(block.get("brutto"))),
           ("nachzahlung", _betrag(block.get("nachzahlung"))),
           ("abschlag", _betrag(block.get("abschlag_monat")))]
    return [{"art": art, "label": STROM_BETRAGSARTEN[art], "betrag": wert}
            for art, wert in roh if wert]


def lies_strom(text: str, dateiname: str = "", schluessel: str = "",
               modell: str = "") -> dict | None:
    """Liest Menge und Bruttobetrag einer Stromrechnung (N162).

    Gibt bei Erfolg ein dict zurück:

    * `menge_kwh` — der abgerechnete Verbrauch in kWh (`einheit` sagt „kWh")
    * `betrag` / `betrag_art` / `betrag_label` — der Betrag, mit dem gerechnet
      wird, und WELCHER es ist. Erste Wahl ist der Bruttobetrag der Lieferung;
      steht nur eine Nachzahlung (oder nur ein Abschlag) auf dem Beleg, kommt
      der Betrag trotzdem — dann aber ausdrücklich als solcher benannt, statt
      das Feld leer zu lassen.
    * `kandidaten` — alle belegten Beträge samt Bezeichnung, zur Wahl
    * `brutto`, `netto`, `nachzahlung`, `guthaben`, `abschlag_monat` — einzeln
    * `von`, `bis` — der abgerechnete Zeitraum der RECHNUNG (er deckt sich nicht
      zwingend mit dem Nebenkostenzeitraum; das Umrechnen ist eine Entscheidung
      des Nutzers und passiert hier nicht)
    * `preis_kwh` — Betrag je Menge, nur zur Anzeige; gerechnet wird in der
      Stromkette

    `None`, wenn der Beleg nichts Brauchbares hergibt (weder Menge noch Betrag)
    oder bei jedem Fehler — kein Key, kein httpx, Netzwerk, Timeout, ungültige
    Antwort. Nie eine Exception. Derselbe Key-/Modell-Vorrang wie `lies_beleg`."""
    if httpx is None:
        return None
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return None
    inhalt = (text or "").strip()
    if not inhalt:
        return None

    gekuerzt = inhalt[:MAX_ZEICHEN]
    nutzer = gekuerzt if not dateiname else f"Dateiname: {dateiname}\n\n{gekuerzt}"
    antwort = kiclient.frage_modell(
        nutzer, schluessel=schluessel, modell=modell,
        system=STROM_SYSTEM_PROMPT, max_tokens=STROM_TOKENS,
        zeitlimit=ZEITLIMIT, etikett="KI-Stromauslese", http=httpx)
    if not antwort.ok:
        return None
    if antwort.block is None:
        log.info("KI-Stromauslese lieferte kein verwertbares JSON")
        return None
    return _strom_ergebnis(antwort.block)


def _strom_ergebnis(block: dict) -> dict | None:
    """Die Modellantwort zu einem geprüften Ergebnis — getrennt geführt, damit
    das Auseinanderhalten der Beträge für sich prüfbar bleibt."""
    menge = _kwh(block.get("menge_kwh"))
    kandidaten = _strom_kandidaten(block)
    if menge is None and not kandidaten:
        return None                       # kein Strombeleg — nichts erfinden
    beste = kandidaten[0] if kandidaten else None
    betrag = beste["betrag"] if beste else None
    ergebnis = {
        "menge_kwh": menge,
        "einheit": "kWh",
        "betrag": betrag,
        "betrag_art": beste["art"] if beste else "",
        "betrag_label": beste["label"] if beste else "",
        "kandidaten": kandidaten,
        "brutto": _betrag(block.get("brutto")),
        "netto": _betrag(block.get("netto")),
        "nachzahlung": _betrag(block.get("nachzahlung")),
        "guthaben": _betrag(block.get("guthaben")),
        "abschlag_monat": _betrag(block.get("abschlag_monat")),
        "von": _datum(block.get("von")),
        "bis": _datum(block.get("bis")),
        # Nur zur Anzeige („trifft das den erwarteten Preis?"). Die Stromkette
        # bildet den Netzpreis selbst aus Betrag und Menge der Kostenposition.
        "preis_kwh": (round(betrag / menge, 4)
                      if betrag and menge else None),
    }
    # Dezent loggen — OHNE Beträge und Mengen (Datenschutz): nur, ob Menge und
    # Betrag gefunden wurden und welcher Betrag es geworden ist.
    log.info("KI-Stromauslese gelesen (Menge %s, Betrag %s)",
             "vorhanden" if menge else "keine",
             ergebnis["betrag_art"] or "keiner")
    return ergebnis


# --------------------------------------------------------------------------
# N273 — die fertige WEG-Einzelabrechnung der Messfirma lesen.
#
# Anders als bei Wasser oder Strom geht es hier nicht um zwei Zahlen, sondern um
# eine ganze Tabelle. Jede Zeile hat die Form
#
#     Gesamtkosten EUR : Gesamteinheit = Preis je Einheit × Ihre Einheiten
#                                        = Ihre Kosten EUR
#     Wasserkosten  788,80 : 381,151 Wasser gesamt = 2,069521 × 49,884 cbm
#                                        = 103,24
#
# Die naheliegendste Verwechslung ist zugleich die teuerste: `ihre_kosten` ist
# die Spalte GANZ RECHTS. Wer stattdessen die Gesamtkosten der Liegenschaft
# nimmt, rechnet dem Mieter das Vielfache seines Anteils auf — bei fünf
# Wohneinheiten das Fünffache. Der Prompt sagt das deshalb ausdrücklich und
# mehrfach.
#
# Der zweite Fallstrick ist fachlich: unter der Überschrift „Nicht umlagefähig"
# stehen Anschaffungen, Reparaturen und Schädlingsbekämpfung. Die trägt die
# Eigentümergemeinschaft, nie der Mieter. Sie werden gelesen und markiert
# (`umlagefaehig: false`), damit `weg.py` sie sichtbar machen, aber niemals
# anlegen kann.
#
# Heiz- und Warmwasserkosten stehen auf einem eigenen Blatt und sind eigene
# Positionen — sie gehören nicht in die Betriebskostentabelle.
# --------------------------------------------------------------------------
WEG_SYSTEM_PROMPT = (
    "Du liest eine deutsche Betriebskosten-Einzelabrechnung, wie sie ein "
    "Messdienst für EINE Wohnung einer Wohnungseigentümergemeinschaft "
    "erstellt. Gib NUR JSON zurück, kein weiterer Text:\n"
    '{"firma":"…","liegenschaft":"…","nutzer_nr":"…",'
    '"von":"YYYY-MM-DD|null","bis":"YYYY-MM-DD|null","datum":"YYYY-MM-DD|null",'
    '"positionen":[{"bezeichnung":"…","gesamtkosten":<Zahl|null>,'
    '"ihre_kosten":<Zahl|null>,"schluessel":"…","umlagefaehig":true}],'
    '"heizkosten":<Zahl|null>,"warmwasserkosten":<Zahl|null>,'
    '"betriebskosten":<Zahl|null>,"rechnungsbetrag":<Zahl|null>,'
    '"vorauszahlung":<Zahl|null>,"nachzahlung":<Zahl|null>}\n'
    "Jede Zeile der Betriebskostentabelle hat die Form: Gesamtkosten EUR : "
    "Gesamteinheit = Preis je Einheit × Ihre Einheiten = Ihre Kosten EUR. "
    "Beispiel: \"Wasserkosten 788,80 : 381,151 Wasser gesamt = 2,069521 × "
    "49,884 cbm = 103,24\".\n"
    "ihre_kosten = die Spalte GANZ RECHTS (\"Ihre Kosten\"), also im Beispiel "
    "103,24 — NICHT die 788,80. Das ist der häufigste Lesefehler und macht die "
    "Abrechnung um den Faktor der Einheitenzahl falsch. Wenn du unsicher bist, "
    "nimm IMMER den kleineren der beiden Beträge einer Zeile.\n"
    "Liegt dir zu jeder Seite auch ein Bild vor: verlass dich bei dieser "
    "Tabelle auf das Bild, nicht auf den mitgeschickten Text — der aus dem "
    "PDF gewonnene Text verliert bei manchen Belegen genau in dieser Tabelle "
    "das Gleichheitszeichen, reisst eine Zeile mitten durch oder vertauscht "
    "Ziffern (z. B. wird aus \"99,000\" ein sinnloses \"00066\"). Das Bild "
    "zeigt die echten Zeichen, der Text ist nur eine Krücke für Kopfdaten wie "
    "Firma, Nutzer-Nr. oder Zeitraum, die zuverlässig extrahiert werden.\n"
    "gesamtkosten = die Spalte GANZ LINKS (Kosten der ganzen Liegenschaft), im "
    "Beispiel 788,80.\n"
    "schluessel = der Verteilungsmaßstab hinter dem Doppelpunkt (\"Wasser "
    "gesamt\", \"Personen\", \"m2 Betriebsk.\", \"Anzahl WE\", \"Anzahl "
    "RWM\").\n"
    "umlagefaehig = true für alle normalen Betriebskosten. Steht eine Position "
    "unterhalb der Überschrift \"Nicht umlagefähig\" (Anschaffungen, "
    "Reparatur, Schädlingsbekämpfung, Instandhaltung), dann umlagefaehig = "
    "false. Lass solche Positionen NICHT weg — gib sie mit false zurück.\n"
    "heizkosten und warmwasserkosten stehen auf dem Deckblatt bzw. auf der "
    "Heiz- und Warmwasserkostenabrechnung. Sie sind EIGENE Positionen und "
    "gehören NICHT in die Liste \"positionen\".\n"
    "betriebskosten = die Summe \"Ihre Kosten\" der Betriebskostenabrechnung "
    "laut Deckblatt.\n"
    "rechnungsbetrag = Heizkosten + Warmwasserkosten + Betriebskosten laut "
    "Deckblatt. vorauszahlung = die geleistete Vorauszahlung. nachzahlung = "
    "was der Nutzer nachzahlen muss (bei einem Guthaben null).\n"
    "von/bis = der Abrechnungszeitraum, datum = das Abrechnungsdatum.\n"
    "Beträge in Euro als Zahl, immer positiv, Punkt als Dezimaltrenner. Was "
    "nicht auf dem Beleg steht, auf null setzen — nie raten. Ist es überhaupt "
    "keine solche Abrechnung, gib {\"positionen\":[]} zurück."
)
# Eine Abrechnung mit fünfzehn Zeilen — reichlich Luft, damit das JSON nicht
# mitten in der Tabelle abbricht.
WEG_TOKENS = 3000
# Der Beleg hat drei Seiten; 6000 Zeichen schneiden das Heizkostenblatt ab.
WEG_MAX_ZEICHEN = 20000
# Ab wie viel Abweichung zwischen der Summe der Einzelpositionen und der auf dem
# Deckblatt genannten Betriebskostensumme gewarnt wird. Ein Cent Rundung ist
# normal, ein Prozent ist eine verlesene Zeile.
WEG_TOLERANZ = 0.01


def _weg_betrag(wert) -> float | None:
    """Ein Betrag aus der Abrechnung, in deutscher Schreibweise gelesen.

    `_betrag` allein reicht nicht: „2.008" ist auf diesem Beleg
    zweitausendacht, nicht zwei Komma null null acht — dort ist der letzte
    Punkt aber Dezimaltrenner. Für Zeichenketten entscheidet deshalb `_zahl_de`
    über die Form (Komma → dezimal, Dreiergliederung → Tausender); Zahlen
    kommen unverändert über `_betrag`."""
    if isinstance(wert, str):
        zahl = _zahl_de(wert)
        return round(abs(zahl), 2) if zahl is not None else None
    return _betrag(wert)


def _weg_positionen(wert) -> list[dict]:
    """Die Tabellenzeilen, normalisiert. Zeilen ohne Bezeichnung fliegen raus —
    eine Kostenposition ohne Namen ist nicht zuzuordnen."""
    if not isinstance(wert, list):
        return []
    zeilen: list[dict] = []
    for roh in wert[:60]:                       # Deckel gegen ein Ausufern
        if not isinstance(roh, dict):
            continue
        name = _text(roh.get("bezeichnung"))
        if not name:
            continue
        zeilen.append({
            "bezeichnung": name,
            "gesamtkosten": _weg_betrag(roh.get("gesamtkosten")),
            "ihre_kosten": _weg_betrag(roh.get("ihre_kosten")),
            "schluessel": _text(roh.get("schluessel")),
            # Im Zweifel umlagefähig? Nein — im Zweifel gilt, was dasteht.
            # Fehlt die Angabe, ist es eine normale Betriebskostenzeile.
            "umlagefaehig": roh.get("umlagefaehig") is not False,
        })
    return zeilen


def _weg_pruefung(ergebnis: dict) -> str:
    """Stimmt die Summe der Einzelpositionen mit dem Deckblatt überein?

    Serverseitig gerechnet, nicht vom Modell erfragt: Addieren ist die
    schwächste Seite eines Sprachmodells. Die Abweichung wird **vermerkt, nicht
    verworfen** — der Nutzer hat das Papier vor sich und entscheidet."""
    soll = ergebnis.get("betriebskosten")
    ist = sum(p["ihre_kosten"] or 0.0 for p in ergebnis["positionen"]
              if p["umlagefaehig"])
    if not soll or not ist:
        return ""
    if abs(ist - soll) <= abs(soll) * WEG_TOLERANZ:
        return ""
    return (f"Die Summe der gelesenen Positionen ({ist:.2f} €) weicht von der "
            f"Betriebskostensumme des Deckblatts ({soll:.2f} €) ab — bitte die "
            f"Zeilen gegen den Beleg prüfen.")


def lies_weg_abrechnung(text: str, dateiname: str = "", schluessel: str = "",
                        modell: str = "",
                        bilder: list[bytes] | None = None) -> dict | None:
    """Liest eine fertige WEG-Einzelabrechnung (N273).

    `bilder` sind die Seiten des Belegs als PNG (`pdftext.seiten_als_png`,
    vom Router gerastert) — N330: der aus dem PDF gewonnene Text verliert bei
    manchen Belegen ausgerechnet in der dichten Betriebskostentabelle
    Trennzeichen und einzelne Ziffern; mit dem Bild daneben liest das Modell
    die echten Zeichen, statt sich auf eine beschädigte Textschicht zu
    verlassen. Ohne Bilder (Rasterung nicht möglich/kein `pypdfium2`) läuft
    die Erkennung wie zuvor rein textbasiert weiter.

    Gibt bei Erfolg Kopfdaten, die Positionstabelle (jede Zeile mit
    `umlagefaehig`) und die Beträge des Deckblatts zurück; passt die Summe der
    Positionen nicht zum Deckblatt, steht das in `warnung` — das Ergebnis wird
    deswegen nicht verworfen.

    Bei jedem Fehler — kein Key, kein httpx, Netzwerk, Timeout, ungültige
    Antwort, keine Abrechnung — `None`, nie eine Exception. Derselbe Key-/
    Modell-Vorrang wie `lies_beleg`."""
    if httpx is None:
        return None
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return None
    inhalt = (text or "").strip()
    if not inhalt:
        return None

    gekuerzt = inhalt[:WEG_MAX_ZEICHEN]
    nutzer = gekuerzt if not dateiname else f"Dateiname: {dateiname}\n\n{gekuerzt}"
    # Drei Seiten Abrechnung und 3000 Tokens Antwort brauchen mehr Luft als ein
    # einzelner Beleg — deshalb das vierfache Zeitlimit.
    antwort = kiclient.frage_modell(
        nutzer, schluessel=schluessel, modell=modell,
        system=WEG_SYSTEM_PROMPT, max_tokens=WEG_TOKENS, bild=bilder or None,
        zeitlimit=ZEITLIMIT * 4, etikett="KI-WEG-Auslese", http=httpx)
    if not antwort.ok:
        return None
    if antwort.block is None:
        log.info("KI-WEG-Auslese lieferte kein verwertbares JSON")
        return None
    return weg_ergebnis(antwort.block)


def weg_ergebnis(block: dict) -> dict | None:
    """Die Modellantwort zu einem geprüften Ergebnis — getrennt geführt, damit
    das Normalisieren und die Plausibilitätsprüfung für sich prüfbar bleiben."""
    positionen = _weg_positionen(block.get("positionen"))
    heiz = _weg_betrag(block.get("heizkosten"))
    warm = _weg_betrag(block.get("warmwasserkosten"))
    if not positionen and not heiz and not warm:
        return None                       # keine Abrechnung — nichts erfinden
    ergebnis = {
        "firma": _text(block.get("firma")),
        "liegenschaft": _adresse(block.get("liegenschaft")),
        "nutzer_nr": _text(block.get("nutzer_nr")),
        "von": _datum(block.get("von")),
        "bis": _datum(block.get("bis")),
        "datum": _datum(block.get("datum")),
        "positionen": positionen,
        "heizkosten": heiz,
        "warmwasserkosten": warm,
        "betriebskosten": _weg_betrag(block.get("betriebskosten")),
        "rechnungsbetrag": _weg_betrag(block.get("rechnungsbetrag")),
        "vorauszahlung": _weg_betrag(block.get("vorauszahlung")),
        "nachzahlung": _weg_betrag(block.get("nachzahlung")),
    }
    ergebnis["warnung"] = _weg_pruefung(ergebnis)
    # Dezent loggen — OHNE Beträge (Datenschutz): nur Anzahl und ob gewarnt wird.
    log.info("KI-WEG-Auslese gelesen (%d Positionen, davon %d nicht "
             "umlagefähig, Warnung: %s)", len(positionen),
             sum(1 for p in positionen if not p["umlagefaehig"]),
             "ja" if ergebnis["warnung"] else "nein")
    return ergebnis


# --------------------------------------------------------------------------
# Orientierung eines gescannten Blattes über das Vision-Modell.
#
# Tesseract-OSD verfehlt bei zerknitterten Foto-Scans die Drehrichtung (ein
# Mietvertrag wurde kopfüber gedreht). Ein Vision-Modell erkennt die
# Orientierung dagegen zuverlässig — es „sieht" das Blatt statt Zeichenkanten
# zu zählen. Gesendet wird nur das gerenderte Seitenbild, kein OCR-Text; die
# Antwort ist eine einzige Zahl.
# --------------------------------------------------------------------------
ORIENT_PROMPT = (
    "Um wie viel Grad im Uhrzeigersinn muss dieses gescannte Dokument gedreht "
    "werden, damit der Text normal aufrecht (nicht kopfüber, nicht seitlich) "
    "steht? Antworte NUR mit einer Zahl: 0, 90, 180 oder 270."
)
ORIENT_TOKENS = 10
ORIENT_ZEITLIMIT = 20.0
_ORIENT_ZAHL = re.compile(r"\d+")


def _winkel(text: str) -> int:
    """Die erste Zahl der Modellantwort, auf 0/90/180/270 gerundet.

    Alles andere (kein Treffer, krummer Winkel) wird zu 0 — lieber nicht drehen
    als falsch drehen."""
    treffer = _ORIENT_ZAHL.search(text or "")
    if not treffer:
        return 0
    grad = int(treffer.group()) % 360
    # Auf das nächste rechte-Winkel-Vielfache runden (91 → 90, 179 → 180).
    gerundet = (round(grad / 90) * 90) % 360
    return gerundet if gerundet in (90, 180, 270) else 0


def orientierung(png_bytes: bytes, schluessel: str = "") -> int:
    """Um wie viel Grad IM UHRZEIGERSINN ein Seitenbild gedreht werden muss,
    damit der Text aufrecht steht — erkannt vom Vision-Modell.

    Gibt 0/90/180/270 zurück. Bei JEDEM Fehler (kein httpx, kein Key, Netzwerk,
    Timeout, ungültige Antwort, kein Vielfaches von 90°) `0`, nie eine
    Exception — dann bleibt die Seite ungedreht (der Aufrufer weicht auf OSD
    aus). Denselben Key-Vorrang wie `lies_beleg`: übergebener Schlüssel vor Env.
    """
    if httpx is None or not png_bytes:
        return 0
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return 0

    antwort = kiclient.frage_modell(
        ORIENT_PROMPT, schluessel=schluessel, bild=png_bytes,
        media_type="image/png", max_tokens=ORIENT_TOKENS,
        zeitlimit=ORIENT_ZEITLIMIT, etikett="KI-Orientierung", http=httpx)
    if not antwort.ok:
        return 0
    # Die Antwort ist eine blosse Zahl, kein JSON — hier zählt der Text.
    return _winkel(antwort.text)


# --------------------------------------------------------------------------
# N126 — der SolarEdge-Screenshot.
#
# Der Nutzer liest seine Stromdaten in der SolarEdge-Oberfläche ab. Statt die
# vier Zahlen abzutippen, lädt er das Bild hoch: zwei waagerechte Balken mit je
# einer Gesamtmenge und drei Prozentangaben. Das Vision-Modell liest sie ab —
# derselbe Weg wie bei `orientierung`, nur mit strukturierter Antwort.
#
# Die Zahlen stehen als Text im Bild; zu lesen ist also nichts Verstecktes.
# Trotzdem gilt hier wie überall: schlägt irgendetwas fehl, kommt ein LEERES
# Ergebnis zurück — der Nutzer trägt die vier Werte dann von Hand ein. Das ist
# der ausdrücklich gewünschte Rückfallweg, keine Notlösung.
#
# Umgerechnet und geprüft wird nichts hier, sondern in `solaredge.py`.
# --------------------------------------------------------------------------
SOLAREDGE_PROMPT = (
    "Das Bild ist ein Screenshot aus der SolarEdge-Oberfläche mit zwei "
    "waagerechten Balken: „Produktion\" und „Verbrauch\". Jeder Balken trägt "
    "links seine Gesamtmenge (z. B. „12.5 MWh\") und im Balken drei "
    "Prozentangaben.\n"
    "Gib NUR JSON zurück, kein weiterer Text:\n"
    '{"produktion_wert":<Zahl|null>,"produktion_einheit":"MWh|kWh|null",'
    '"produktion_netz_prozent":<Zahl|null>,'
    '"produktion_gebaeude_prozent":<Zahl|null>,'
    '"produktion_speicher_prozent":<Zahl|null>,'
    '"verbrauch_wert":<Zahl|null>,"verbrauch_einheit":"MWh|kWh|null",'
    '"verbrauch_netz_prozent":<Zahl|null>,'
    '"verbrauch_pv_prozent":<Zahl|null>,'
    '"verbrauch_speicher_prozent":<Zahl|null>}\n'
    "Die drei Prozentzahlen im Produktionsbalken stehen in dieser Reihenfolge: "
    "„Ins Netz\", „Ins Gebäude\", „Zum Speicher\". Die drei im Verbrauchsbalken: "
    "„Vom Netz\", „Aus PV-Energie\", „Vom Speicher\". Die Legende rechts nennt "
    "dieselbe Reihenfolge — richte dich nach der Beschriftung, nicht nach der "
    "Farbe.\n"
    "wert = die Gesamtmenge des Balkens als Zahl, OHNE Einheit (Punkt als "
    "Dezimaltrenner). einheit = die Einheit, die daneben steht, genau so wie "
    "sie dort steht („MWh\" oder „kWh\") — rechne NICHT um und rate sie NICHT. "
    "Die Prozentangaben als Zahl ohne Prozentzeichen (33, nicht \"33 %\").\n"
    "Steht ein Wert nicht auf dem Bild oder ist er unleserlich, setze ihn auf "
    "null. Rate nichts und fülle nichts mit 0 auf. Ist das überhaupt kein "
    "SolarEdge-Screenshot, setze alle Felder auf null."
)
SOLAREDGE_TOKENS = 300
SOLAREDGE_ZEITLIMIT = 30.0
# Was die Bilderkennung annimmt. Ein anderer Typ kommt gar nicht erst weg.
SOLAREDGE_TYPEN = ("image/png", "image/jpeg", "image/gif", "image/webp")


def lies_solaredge(bild: bytes, media_type: str = "image/png",
                   schluessel: str = "", modell: str = "") -> dict:
    """Liest die Zahlen eines SolarEdge-Screenshots (N126).

    Gibt bei Erfolg das rohe Feld-dict des Modells zurück (Mengen samt
    Einheit, Prozentangaben) — die Prüfung und die Umrechnung auf kWh macht
    `solaredge.aufbereiten`.

    Bei JEDEM Fehler — kein httpx, kein Schlüssel, kein Bild, unbekanntes
    Bildformat, Netzwerk, Timeout, unbrauchbare Antwort — ein **leeres dict**,
    nie eine Exception: der Nutzer trägt die vier Werte dann von Hand ein.
    Derselbe Schlüssel-Vorrang wie `lies_beleg` (übergebener Schlüssel vor
    Env)."""
    if httpx is None or not bild:
        return {}
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return {}
    if media_type not in SOLAREDGE_TYPEN:
        log.info("KI-SolarEdge: Bildformat wird nicht gelesen")
        return {}

    antwort = kiclient.frage_modell(
        SOLAREDGE_PROMPT, schluessel=schluessel, modell=modell, bild=bild,
        media_type=media_type, max_tokens=SOLAREDGE_TOKENS,
        zeitlimit=SOLAREDGE_ZEITLIMIT, etikett="KI-SolarEdge", http=httpx)
    if not antwort.ok:
        return {}

    block = antwort.block
    if block is None:
        log.info("KI-SolarEdge lieferte kein verwertbares JSON")
        return {}
    # Dezent loggen — ohne die abgelesenen Zahlen: nur, wie viele Felder kamen.
    log.info("KI-SolarEdge gelesen (%d Felder)",
             sum(1 for wert in block.values() if wert is not None))
    return block


# Ein winziger, günstiger Ping: ein Zeichen Prompt, eine Antwort-Token, kurzer
# Timeout. Genug, um zu wissen, ob Schlüssel und Netz stehen — ohne echte Kosten.
PRUEF_TOKENS = 1
PRUEF_ZEITLIMIT = 10.0


def pruefe(schluessel: str = "", modell: str = "") -> dict:
    """Prüft, ob die KI erreichbar ist — ein minimaler echter Call.

    Gibt `{"erreichbar": bool, "fehler": str}` zurück. Jeder Fehler — kein Key,
    kein httpx, Netzwerk, Timeout, HTTP-Status — wird zu `erreichbar: false`
    mit knappem Grund; nie fliegt eine Exception nach außen. `schluessel`/
    `modell` (aus den Einstellungen) haben Vorrang vor der Env.

    Der Beleginhalt spielt hier keine Rolle: gesendet wird nur „ping", damit
    keine echten Daten für den bloßen Erreichbarkeitstest das Haus verlassen."""
    antwort = kiclient.frage_modell(
        "ping", schluessel=schluessel, modell=modell, max_tokens=PRUEF_TOKENS,
        zeitlimit=PRUEF_ZEITLIMIT, etikett="KI-Prüfung", http=httpx)
    # Erreichbar heißt: die Gegenseite hat mit 200 geantwortet. Ob der Body
    # lesbar war, ist für den Ping gleichgültig — gefragt war nur der Weg.
    if antwort.status == 200:
        return {"erreichbar": True, "fehler": ""}
    if antwort.status == 401:
        return {"erreichbar": False, "fehler": "Schlüssel abgelehnt (401)"}
    if antwort.status:
        # Anthropics eigene Meldung durchreichen — „HTTP 400" allein sagt
        # nichts; „model: … not found" schon. Enthält nie den Beleginhalt.
        return {"erreichbar": False,
                "fehler": f"HTTP {antwort.status}: {antwort.grund}"
                          if antwort.grund else f"HTTP {antwort.status}"}
    # Gar nicht bis zu einer Antwort gekommen: kein httpx, kein Key, Netz.
    return {"erreichbar": False, "fehler": antwort.fehler}
