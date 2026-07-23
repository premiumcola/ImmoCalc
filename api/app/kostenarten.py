"""Kostenart-Normalisierung — Schreibweisen und Synonyme zusammenfassen (CCLXXX).

Der Massenlauf der KI-Auslese hat dieselbe Kostenart in vielen Schreibweisen
angelegt (`grundsteuer`/`Grundsteuer`, `muell`/`Müll`, `Zaehlerstand`/
`Zählerablesung`, `Heizung/Warmwasser`-Varianten …). `normalisieren` bildet
jede Variante auf eine kanonische Bezeichnung ab, damit Filter und Facette im
Dokumenteneingang nicht zerfasern. Unbekanntes bleibt unangetastet erhalten —
es wird nur zusammengefasst, nie verworfen.
"""


def _fold(text: str | None) -> str:
    """Vergleichsschlüssel: klein, ohne Umlaute/ß, ohne Randweißraum."""
    s = (text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


# Variante (nach `_fold`) -> kanonische Bezeichnung. Nur bewusste Zusammen-
# fassungen echter Dubletten; alles andere fällt auf sich selbst zurück.
_KANON: dict[str, str] = {
    "gebaeudehaftpflicht": "Gebäudehaftpflicht",
    "haftpflichtversicherung": "Gebäudehaftpflicht",
    "strom": "Strom",
    "grundsteuer": "Grundsteuer",
    "wasser": "Wasser",
    "wasser/abwasser": "Wasser",
    "schornsteinfeger": "Schornsteinfeger",
    "schornsteinfeger/abgas": "Schornsteinfeger",
    "heizung": "Heizung",
    "heizkosten": "Heizung",
    "heizung/warmwasser": "Heizung",
    "heizung/wasser/warmwasser": "Heizung",
    "heizung, warmwasser, betriebskosten": "Heizung",
    "waermewasser": "Heizung",
    "heizoel": "Heizöl",
    "heizung/oel": "Heizöl",
    "nebenkosten": "Nebenkosten",
    "nebenkosten gesamt": "Nebenkosten",
    "betriebskosten": "Nebenkosten",
    "versicherung": "Versicherung",
    "muell": "Müll",
    "zaehlerablesung": "Zählerablesung",
    "zaehlerstand": "Zählerablesung",
    "kaufpreisrate": "Kaufpreisrate",
    "handwerk": "Handwerk",
    "kaufpreis": "Kaufpreis",
    "material": "Material",
    "materialien": "Material",
    "gebaeudeversicherung": "Gebäudeversicherung",
    "wohngebaeude": "Gebäudeversicherung",
    "hausmeister": "Hausmeister",
    "darlehenszins": "Darlehenszins",
    "darlehenszinsen": "Darlehenszins",
    "hausverwaltung": "Hausverwaltung",
    "verbrauchserfassung": "Verbrauchserfassung",
    "heizmessung": "Verbrauchserfassung",
    "waermemessung": "Verbrauchserfassung",
    "elektro": "Elektro",
    "gehalt": "Gehalt",
    "grundstueck/gebaeude": "Grundstück/Gebäude",
    "messdienst": "Messdienst",
    "messdienste": "Messdienst",
    "messgebuehren": "Messdienst",
    "notargebuehren": "Notargebühren",
    "zusatzleistungen": "Zusatzleistungen",
    "bau": "Bau",
    "bausparbeitrag": "Bausparbeitrag",
    "bodensanierung": "Bodensanierung",
    "darlehen": "Darlehen",
    "gebaeude": "Gebäude",
    "gerichtsgebuehren": "Gerichtsgebühren",
    "hausgeld": "Hausgeld",
    "heizungswartung": "Heizungswartung",
    "instandhaltung": "Instandhaltung",
    "moebel": "Möbel",
    "reparatur": "Reparatur",
    "sepa-mandat": "SEPA-Mandat",
    "schloss": "Schloss",
    "sonstiges": "Sonstiges",
    "vorfinanzierungskredit": "Vorfinanzierungskredit",
    "wohnkredit": "Wohnkredit",
}


def normalisieren(kostenart: str | None) -> str:
    """Kanonische Kostenart. Unbekannte Werte bleiben (getrimmt) erhalten."""
    roh = (kostenart or "").strip()
    if not roh:
        return ""
    return _KANON.get(_fold(roh), roh)
