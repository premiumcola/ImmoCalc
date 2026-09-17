"""N483 — die Kostenart gehört nur dorthin, wo sie wirklich unterscheidet.

Gemeldet mit Screenshot aus der Cloud: im Ordner `30_Vermietung_Verpachtung`
hiessen die Mietverträge

    2014-09_Miete-Gebäudehaftpflicht-Jana.Meinecke.signed-bis.08.pdf
    2021-02_Miete-Gebäudehaftpflicht-Alicia_EG.pdf

Nutzer: „das ist ja ein Mietvertrag, das macht irgendwie keinen Sinn."

Die Ursache war nicht, dass irgendwo „die erste Kostenart" eingesetzt wurde —
das gibt es im Code nicht. Sie war banaler: `Dokument.kostenart` stand am
Beleg (ein Mietvertrag nennt fast immer eine Haftpflichtversicherung, und
`kostenarten.py::_KANON` bildet „Haftpflichtversicherung" auf
„Gebäudehaftpflicht" ab), wurde beim Umklassifizieren zu „Mietvertrag" nie
geleert, und der Namensbau hat sie bedingungslos eingesetzt.

Diese Datei hält beide Seiten fest: dass die Kostenart unter Nebenkosten
weiterhin im Namen steht (dort trägt sie die Unterscheidung), und dass sie in
allen übrigen Rubriken draussen bleibt — auch dann, wenn am Beleg noch eine
steht.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_name_kostenart.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from app.cloudkern import ARTKUERZEL  # noqa: E402
from app.dokumente.namen import KOSTENART_IM_NAMEN, dateiname  # noqa: E402


# ---- N483 — der gemeldete Fall ----------------------------------------

def test_der_mietvertrag_traegt_keine_gebaeudehaftpflicht_mehr():
    """Der Screenshot-Fall, Zeichen für Zeichen."""
    name = dateiname(2014, "Mietvertrag", "Jana.Meinecke.signed-bis.08",
                     ".pdf", monat=9, kostenart="Gebäudehaftpflicht")
    assert "Gebäudehaftpflicht" not in name
    assert name == "2014-09_Miete-Jana.Meinecke.signed-bis.08.pdf"


def test_auch_ohne_monat_und_ohne_bezeichnung_bleibt_die_kostenart_draussen():
    """Der magere Fall: nichts als Jahr und eine falsch stehengebliebene
    Kostenart. Früher wurde daraus „2021_Miete-Gebäudehaftpflicht" — der Name
    hätte dann ausschliesslich aus der falschen Angabe bestanden."""
    name = dateiname(2021, "Mietvertrag", "", ".pdf",
                     kostenart="Gebäudehaftpflicht")
    assert "Gebäudehaftpflicht" not in name
    assert name == "2021_Miete.pdf"


@pytest.mark.parametrize("kategorie", sorted(
    k for k in ARTKUERZEL if k not in KOSTENART_IM_NAMEN and k != "Lageplan"))
def test_keine_rubrik_ausser_nebenkosten_nimmt_die_kostenart_in_den_namen(kategorie):
    """Nicht nur der Mietvertrag: dasselbe galt für Versicherung, Kredit,
    Notarvertrag, Korrespondenz … überall dort ist die Kostenart eine Angabe,
    die den Beleg nicht beschreibt."""
    name = dateiname(2023, kategorie, "Musterfirma", ".pdf",
                     kostenart="Gebäudehaftpflicht")
    assert "Gebäudehaftpflicht" not in name, f"{kategorie}: {name}"
    assert "Musterfirma" in name


# ---- N483 — was ausdrücklich SO bleiben muss --------------------------

def test_unter_nebenkosten_steht_die_kostenart_weiterhin_im_namen():
    """Der Grund, warum es die Regel überhaupt gibt: unter Nebenkosten liegen
    dreissig Belege desselben Jahres, und erst die Kostenart sagt, welcher
    gemeint ist."""
    name = dateiname(2026, "Nebenkosten", "Rechnung", ".pdf", monat=2,
                     kostenart="Schornsteinfeger")
    # „Rechnung" sagt nichts und wird von der Kostenart ersetzt, nicht ergänzt.
    assert name == "2026-02_NK-Schornsteinfeger.pdf"


def test_nebenkosten_ohne_bezeichnung_nimmt_die_kostenart_als_sache():
    name = dateiname(2026, "Nebenkosten", "", ".pdf", monat=2,
                     kostenart="Wasser")
    assert name == "2026-02_NK-Wasser.pdf"


def test_der_name_bleibt_beim_zweiten_lauf_gleich():
    """Idempotenz — sonst wächst der Name bei jedem Korrekturlauf."""
    einmal = dateiname(2014, "Mietvertrag", "Jana.Meinecke.signed-bis.08",
                       ".pdf", monat=9, kostenart="Gebäudehaftpflicht")
    stamm = einmal[:-len(".pdf")]
    zweimal = dateiname(2014, "Mietvertrag", stamm, ".pdf", monat=9,
                        kostenart="Gebäudehaftpflicht")
    assert zweimal == einmal


def test_ein_alter_name_mit_der_kostenart_wird_beim_neubauen_bereinigt():
    """Der Weg, den der Korrekturlauf geht: der ALTE Dateiname ist die
    Bezeichnung, aus der neu gebaut wird. Die darin steckende Kostenart muss
    dabei verschwinden — sonst bliebe sie ewig stehen."""
    # So läuft es wirklich: `POST /{id}/umbenennen` übergibt den alten Namen
    # als Bezeichnung UND die am Beleg gespeicherte Kostenart.
    alt = "Miete-Gebäudehaftpflicht-Jana.Meinecke.signed-bis.08"
    neu = dateiname(2014, "Mietvertrag", alt, ".pdf", monat=9,
                    kostenart="Gebäudehaftpflicht")
    assert "Gebäudehaftpflicht" not in neu, neu
    assert "Jana.Meinecke.signed-bis.08" in neu
