"""N276 — die Arten der einmaligen Erwerbsnebenkosten.

Sie stehen hier und nicht im Prompt oder in der Oberfläche, weil sie an drei
Stellen gebraucht werden: die KI schlägt eine vor, der Server prüft sie, und
das Formular bietet sie zur Auswahl an. Gäbe es die Liste dreimal, liefe sie
auseinander — ein Wächter-Test hält die Fassung in `objekt-felder.js` dagegen.

Die Reihenfolge ist die des Erwerbsvorgangs: erst der Kaufvorgang, dann die
Ämter, dann das Umfeld. Danach sucht der Nutzer.

Die fachlich wichtige Trennung steckt in den Paaren:

    Notar (KV 21100/21101)           ↔ Notar – Grundschuldbestellung (KV 21200)
    Grundbuchamt – Umschreibung      ↔ Grundbuchamt – Grundpfandrecht (KV 14121)

Links steht der ERWERB — das wandert in die Anschaffungskosten und wird
abgeschrieben. Rechts steht die FINANZIERUNG — das sind sofort abzugsfähige
Werbungskosten. Beides in einen Topf zu werfen macht die AfA falsch, und genau
das tat die alte Sammelbezeichnung „Grundbuch / Grundschuld".

Additiv, nicht umbenannt: „Grundbuch / Grundschuld", „Makler" und „Gutachter"
waren die alten Sammelbezeichnungen vor dieser Aufteilung. Sie stehen weiter
am Ende der Liste, obwohl die KI sie nicht mehr vorschlägt (SYSTEM_PROMPT in
kiauslese.py kennt nur noch die feineren Arten) — ein Bestandsobjekt, das
schon damit getaggt ist, braucht weiterhin einen Treffer, sonst fällt die
Oberfläche (auswahl.js ohne Treffer auf den ersten Listeneintrag) auf „Notar"
zurück und zeigt eine falsche Art an.
"""
from __future__ import annotations

ERWERBSARTEN: list[str] = [
    "Notar",
    "Notar – Grundschuldbestellung",
    "Grunderwerbsteuer",
    "Grundbuchamt – Eigentumsumschreibung",
    "Grundbuchamt – Auflassungsvormerkung",
    "Grundbuchamt – Grundpfandrecht",
    "Katasterfortführung",
    "Vermessung / Gebäudeeinmessung",
    "Makler / Courtage",
    "Gutachter / Wertermittlung",
    "Bodengutachten / Baugrund",
    "Erschließungskosten",
    "Baugenehmigung / Behördengebühren",
    "Finanzierungsnebenkosten",
    # Bestandswerte vor N276 — additiv erhalten (siehe Docstring oben).
    "Grundbuch / Grundschuld",
    "Makler",
    "Gutachter",
    "Sonstiges",
]

# Vergleichsform: ohne Gross-/Kleinschreibung, ohne doppelte Leerzeichen, und
# mit dem Halbgeviertstrich auf den einfachen Bindestrich zurückgeführt — die
# beiden sehen gleich aus und werden vom Modell munter vertauscht.
def _schluessel(wert: str) -> str:
    return " ".join(str(wert or "").replace("–", "-").split()).casefold()


_NACHSCHLAG = {_schluessel(a): a for a in ERWERBSARTEN}


def erwerbsart(wert) -> str | None:
    """Eine vom Modell genannte Art auf die kanonische Schreibweise bringen.

    `None`, wenn sie nicht in der Liste steht. Bewusst kein Rückfall auf
    „Sonstiges": eine erfundene Art sähe im Formular aus wie eine erkannte,
    und der Nutzer übernähme sie ungeprüft.
    """
    if not wert:
        return None
    return _NACHSCHLAG.get(_schluessel(wert))
