"""N455 — die Zinslast muss den Anschlusszins kennen.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. `objekt_vermoegen`
rechnete die Jahreszinsen stur mit `kredit.zinssatz` — dem Zins der
Zinsbindung. Die Restschuld daneben wird längst mit `zinssatz_variabel`
fortgeschrieben (`_fortschreiben_darlehen`), und `verlauf` weist über
`_jahreszins_kalk` den richtigen Wert aus. Dieselbe Zahl stand in der App
also an zwei Stellen verschieden — und die falsche ist die, die in die
Anlage V wandert.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_zinslast_anschlusszins.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models import Kredit, Objekt  # noqa: E402
from app.vermoegen import _jahreszins_kalk, objekt_vermoegen  # noqa: E402


def _kredit(**abweichung):
    """Ein Darlehen mit ausgelaufener Zinsbindung: 1 % fest, 6 % danach."""
    daten = dict(id=1, objekt_id=1, art="darlehen", name="Hauskredit",
                 restschuld=200000.0, zinssatz=1.0, zinssatz_variabel=6.0,
                 zinsbindung_bis=date(2020, 12, 31),
                 rate_monatlich=1000.0, turnus="monatlich")
    daten.update(abweichung)
    return Kredit(**daten)


def _objekt():
    return Objekt(id=1, slug="zinsweg", name="Zinsweg 1",
                  verkehrswert=400000.0)


def test_zinslast_folgt_dem_anschlusszins():
    """Nach Ablauf der Zinsbindung gilt der variable Satz — nicht der alte.

    200.000 € zu 1 % fest / 6 % variabel, Bindung bis Ende 2020, Stichtag
    2026: mit dem festen Satz stünden 2.000 € in der Auswertung, tatsächlich
    fallen rund 12.000 € an. Faktor sechs auf einer Zahl, die in die
    Steuererklärung geht."""
    kredit = _kredit()
    stichtag = date(2026, 6, 30)
    ergebnis = objekt_vermoegen(_objekt(), [kredit], [], stichtag=stichtag)

    zinsen = ergebnis["zinslast_jahr"]
    mit_festem_satz = 200000.0 * 1.0 / 100
    assert abs(zinsen - mit_festem_satz) > 1000, (
        f"Zinslast {zinsen} entspricht noch dem festen Satz "
        f"({mit_festem_satz}) — der Anschlusszins fehlt")
    assert zinsen > 9000, f"erwartet ~12.000 €, bekam {zinsen}"


def test_zinslast_stimmt_mit_dem_verlauf_ueberein():
    """Dieselbe Zahl darf in der App nicht zweimal verschieden dastehen.

    `verlauf` rechnet über `_jahreszins_kalk`; die Kennzahl oben muss
    dasselbe Ergebnis liefern."""
    kredit = _kredit()
    stichtag = date(2026, 6, 30)
    ergebnis = objekt_vermoegen(_objekt(), [kredit], [], stichtag=stichtag)

    restschuld = ergebnis["restschuld"]
    erwartet = _jahreszins_kalk(kredit, stichtag.year - 1, restschuld,
                                1000.0)
    assert abs(ergebnis["zinslast_jahr"] - erwartet) < 1.0, (
        f"Kennzahl {ergebnis['zinslast_jahr']} weicht vom Verlauf "
        f"{erwartet} ab")


def test_ohne_anschlusszins_bleibt_es_beim_festen_satz():
    """Gegenprobe: ein Kredit ohne variablen Satz rechnet unverändert."""
    kredit = _kredit(zinssatz_variabel=None, zinsbindung_bis=None)
    ergebnis = objekt_vermoegen(_objekt(), [kredit], [],
                                stichtag=date(2026, 6, 30))
    erwartet = ergebnis["restschuld"] * 1.0 / 100
    assert abs(ergebnis["zinslast_jahr"] - erwartet) < 60, (
        f"{ergebnis['zinslast_jahr']} statt rund {erwartet}")
