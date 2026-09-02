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
    # N439 — Schreibweisen aus einer echten WEG-Abrechnung (Immoware24), vom
    # Nutzer als Foto geschickt. Dort heissen die Konten ausgeschrieben, die
    # KI-Auslese liest sie genau so aus dem Beleg.
    "haus- und grundbesitzer-haftpflicht": "Gebäudehaftpflicht",
    "haus- und grundbesitzerhaftpflicht": "Gebäudehaftpflicht",
    "versicherung: haus- und grundbesitzer-haftpflicht": "Gebäudehaftpflicht",
    "grundbesitzerhaftpflicht": "Gebäudehaftpflicht",
    "versicherung: gebaeude": "Gebäudeversicherung",
    "hausmeisterkosten": "Hausmeister",
    "hausmeistergehalt": "Hausmeister",
    "muellentsorgung": "Müll",
    "strom allgemein": "Allgemeinstrom",
    "allgemeinstrom": "Allgemeinstrom",
    "wartung aufzug": "Aufzug",
    "aufzugwartung": "Aufzug",
    "wartung enthaertungsanlage": "Wartung Enthärtungsanlage",
    "enthaertungsanlage": "Wartung Enthärtungsanlage",
    "matten-service": "Mattenservice",
    "mattenservice": "Mattenservice",
    "zaehlermiete": "Zählermiete",
    "abrechnungskosten": "Abrechnungskosten",
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


def _ohne_kontonummer(text: str) -> str:
    """N439 — führende Kontonummer abtrennen: „040200 Hausmeistergehalt".

    Hausverwaltungs-Programme (hier: Immoware24) stellen jeder Kostenart ihre
    Kontonummer voran. Die KI-Auslese liest die Zeile so, wie sie im Beleg
    steht, und ohne dieses Abtrennen fiele jede solche Position durch die
    Zusammenfassung. Bewusst erst ab FÜNF Ziffern und nur, wenn danach noch
    Text kommt: Kontonummern haben dort sechs Stellen, eine Jahreszahl hat
    vier — „2026 Nachzahlung" und „1 Rate" bleiben so unangetastet."""
    teile = text.split(maxsplit=1)
    if len(teile) == 2 and teile[0].isdigit() and len(teile[0]) >= 5:
        return teile[1].strip()
    return text


def normalisieren(kostenart: str | None) -> str:
    """Kanonische Kostenart. Unbekannte Werte bleiben (getrimmt) erhalten."""
    roh = (kostenart or "").strip()
    if not roh:
        return ""
    if _fold(roh) in _KANON:
        return _KANON[_fold(roh)]
    ohne = _ohne_kontonummer(roh)
    return _KANON.get(_fold(ohne), ohne if ohne != roh else roh)
