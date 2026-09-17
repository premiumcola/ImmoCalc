"""N481 — Der TOTP-Kern gegen die VERÖFFENTLICHTEN Testvektoren der Standards.

Warum das eine eigene Datei ist und nicht in `test_zwei_faktor.py` steht:
dort erzeugt jeder Test den erwarteten Code mit `totp._code_fuer` — also mit
genau der Funktion, die geprüft werden soll. Solche Tests halten das Verhalten
stabil, können aber einen falsch herum gewählten Standard NIE entdecken. Sie
wären auch dann grün, wenn die App die Bytes in der falschen Reihenfolge
packte oder die falsche Stelle abschnitte — nur würde dann keine einzige
Authenticator-App dieselben Ziffern zeigen.

Genau dieser Fehler ist in diesem Projekt schon einmal passiert: der
handgeschriebene QR-Kodierer (N477) war gegen den eigenen Testdecoder grün und
ließ sich trotzdem von keinem Scanner lesen — die Formatbits lagen
spiegelverkehrt. Die Lehre daraus steht hier als Test.

Die Vektoren stammen aus:
  * RFC 4226, Anhang D — HOTP, Zähler 0…9
  * RFC 6238, Anhang B  — TOTP mit HMAC-SHA1, feste Zeitpunkte

Beide benutzen dasselbe Geheimnis: die 20 ASCII-Bytes „12345678901234567890".
Stimmen unsere Ziffern mit den dort abgedruckten überein, rechnet die App
nachweislich so wie jede Authenticator-App — und nicht nur so wie sie selbst.
"""
import base64
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_totp_rfc.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import totp  # noqa: E402

# Das Geheimnis der Standards, in der Base32-Form, die auch in der
# Authenticator-App landet (ohne Füllzeichen — manche Apps stolpern darüber).
RFC_GEHEIMNIS = base64.b32encode(b"12345678901234567890").decode().rstrip("=")

# ---- RFC 4226, Anhang D — HOTP je Zähler -------------------------------
# Zähler → sechsstelliger Code, wörtlich aus der Tabelle des Standards.
HOTP_VEKTOREN = {
    0: "755224", 1: "287082", 2: "359152", 3: "969429", 4: "338314",
    5: "254676", 6: "287922", 7: "162583", 8: "399871", 9: "520489",
}

# ---- RFC 6238, Anhang B — TOTP zu festen Zeitpunkten -------------------
# Der Standard druckt ACHT Ziffern; unsere App zeigt sechs. Beides ist
# derselbe Wert, nur anders abgeschnitten: TOTP = Rohwert mod 10^Ziffern.
# Die sechsstellige Form ist deshalb genau die achtstellige mod 1_000_000 —
# hier zur Kontrolle beides notiert, damit man beim Nachlesen im RFC nicht
# rechnen muss.
TOTP_VEKTOREN = [
    (59,          "94287082", "287082"),
    (1111111109,  "07081804", "081804"),
    (1111111111,  "14050471", "050471"),
    (1234567890,  "89005924", "005924"),
    (2000000000,  "69279037", "279037"),
    (20000000000, "65353130", "353130"),
]


# ---- N481 — der Rechenkern ---------------------------------------------

def test_hotp_trifft_alle_zehn_vektoren_aus_rfc_4226():
    """Zähler 0 bis 9 mit dem Geheimnis des Standards — zehn feste Zahlen,
    die jede korrekte HOTP-Umsetzung der Welt liefert."""
    for zaehler, erwartet in HOTP_VEKTOREN.items():
        assert totp._code_fuer(RFC_GEHEIMNIS, zaehler) == erwartet, (
            f"Zähler {zaehler}: erwartet {erwartet}, "
            f"bekommen {totp._code_fuer(RFC_GEHEIMNIS, zaehler)}")


def test_totp_trifft_die_vektoren_aus_rfc_6238():
    """Dieselbe Prüfung über die Zeitachse: aus dem Zeitpunkt muss das
    richtige 30-Sekunden-Fenster und daraus der richtige Code werden."""
    for zeitpunkt, acht, sechs in TOTP_VEKTOREN:
        assert sechs == acht[-6:], (
            f"Testdaten falsch notiert: {acht} endet nicht auf {sechs}")
        fenster = zeitpunkt // 30
        assert totp._code_fuer(RFC_GEHEIMNIS, fenster) == sechs, (
            f"Zeitpunkt {zeitpunkt} (Fenster {fenster}): erwartet {sechs}")


def test_code_pruefen_nimmt_den_vektor_zum_passenden_zeitpunkt_an():
    """Der Weg, den die Anmeldung wirklich geht: Zeitpunkt hinein, Code
    daneben, Ja oder Nein heraus."""
    for zeitpunkt, _acht, sechs in TOTP_VEKTOREN:
        assert totp.code_pruefen(RFC_GEHEIMNIS, sechs, zeitpunkt=zeitpunkt)


def test_code_pruefen_lehnt_den_vektor_eines_fremden_zeitpunkts_ab():
    """Gegenprobe — sonst wäre auch eine Funktion grün, die immer True sagt.
    Zwei Fenster Abstand liegen sicher ausserhalb der ±1-Toleranz."""
    for zeitpunkt, _acht, sechs in TOTP_VEKTOREN:
        assert not totp.code_pruefen(RFC_GEHEIMNIS, sechs,
                                     zeitpunkt=zeitpunkt + 5 * 30)


# ---- N481 — die Toleranz gegen Uhr-Drift -------------------------------

def test_ein_fenster_vor_und_zurueck_wird_akzeptiert():
    """±1 Schritt Toleranz: das Handy darf bis zu einer halben Minute
    vorgehen oder nachgehen, ohne dass die Anmeldung scheitert."""
    zeitpunkt = 1111111109
    code = totp._code_fuer(RFC_GEHEIMNIS, zeitpunkt // 30)
    assert totp.code_pruefen(RFC_GEHEIMNIS, code, zeitpunkt=zeitpunkt - 30)
    assert totp.code_pruefen(RFC_GEHEIMNIS, code, zeitpunkt=zeitpunkt + 30)


def test_zwei_fenster_daneben_wird_abgelehnt():
    """Die Toleranz ist ein Fenster, nicht beliebig viele — ein abgelaufener
    Code darf nicht ewig weitergelten."""
    zeitpunkt = 1111111109
    code = totp._code_fuer(RFC_GEHEIMNIS, zeitpunkt // 30)
    assert not totp.code_pruefen(RFC_GEHEIMNIS, code, zeitpunkt=zeitpunkt - 61)
    assert not totp.code_pruefen(RFC_GEHEIMNIS, code, zeitpunkt=zeitpunkt + 61)


# ---- N481 — was die App an die Authenticator-App übergibt ---------------

def test_das_erzeugte_geheimnis_ist_gueltiges_base32_ohne_fuellzeichen():
    """Manche Apps stolpern über die „="-Füllzeichen am Ende, andere über
    Kleinbuchstaben. Beides darf gar nicht erst entstehen."""
    for _ in range(50):
        g = totp.geheimnis_neu()
        assert "=" not in g
        assert g == g.upper()
        assert set(g) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        # 160 Bit sind 32 Base32-Zeichen — die Länge, die die Standards für
        # das gemeinsame Geheimnis empfehlen.
        assert len(g) == 32
        # Und es muss sich auch wieder dekodieren lassen, sonst nützt die
        # schönste Zeichenkette nichts.
        base64.b32decode(g + "=" * (-len(g) % 8))


def test_der_otpauth_link_traegt_alles_was_eine_app_braucht():
    """Aufbau nach der Key-Uri-Festlegung: Schema, Typ, Label mit Anbieter,
    Geheimnis, Aussteller, Ziffern, Periode."""
    url = totp.otpauth_url(RFC_GEHEIMNIS, "Heidenreich")
    assert url.startswith("otpauth://totp/")
    # Der Doppelpunkt zwischen Anbieter und Konto darf kodiert sein (%3A) —
    # die Festlegung erlaubt beides ausdrücklich.
    assert "ImmoCalc%3AHeidenreich" in url or "ImmoCalc:Heidenreich" in url
    assert f"secret={RFC_GEHEIMNIS}" in url
    assert "issuer=ImmoCalc" in url
    assert "digits=6" in url
    assert "period=30" in url
    # Kein Füllzeichen im Link — es müsste sonst prozentkodiert werden und
    # wird von etlichen Apps falsch gelesen.
    assert "=" not in url.split("secret=")[1].split("&")[0]


def test_ein_geheimnis_aus_der_app_rechnet_mit_dem_link_zusammen():
    """Die Rundreise, die der Nutzer geht: Geheimnis erzeugen → in den Link
    schreiben → aus dem Link auslesen → Code rechnen → Server fragt ab."""
    geheimnis = totp.geheimnis_neu()
    url = totp.otpauth_url(geheimnis, "Heidenreich")
    aus_dem_link = url.split("secret=")[1].split("&")[0]
    zeitpunkt = 1700000000
    code = totp._code_fuer(aus_dem_link, zeitpunkt // 30)
    assert totp.code_pruefen(geheimnis, code, zeitpunkt=zeitpunkt)


def test_zwei_geheimnisse_ergeben_nie_denselben_code():
    """Sonst öffnete das Handy der einen Familie die Anmeldung der anderen."""
    zeitpunkt = 1700000000
    codes = {totp._code_fuer(totp.geheimnis_neu(), zeitpunkt // 30)
             for _ in range(200)}
    # Bei 200 Ziehungen aus einer Million Möglichkeiten sind ein paar
    # Zusammenstösse rechnerisch normal; ein systematischer Fehler (immer
    # derselbe Code) fiele dagegen sofort auf.
    assert len(codes) > 190


# ---- N481 — die Wiederherstellungscodes --------------------------------

def test_wiederherstellungscodes_sind_einmalig_und_gleich_geformt():
    codes = totp.wiederherstellungscodes_neu(8)
    assert len(codes) == 8
    assert len(set(codes)) == 8
    for c in codes:
        vorn, _, hinten = c.partition("-")
        assert len(vorn) == 5 and len(hinten) == 5
        assert set(c) <= set("0123456789abcdef-")


def test_der_hash_eines_codes_ueberlebt_schreibweise_und_bindestriche():
    """Wer den Code aus dem Notizbuch abtippt, trifft Gross-/Kleinschreibung
    und Bindestrich nicht immer — daran darf die Anmeldung nicht scheitern."""
    code = totp.wiederherstellungscodes_neu(1)[0]
    erwartet = totp.code_hashen(code)
    assert totp.code_hashen(code.upper()) == erwartet
    assert totp.code_hashen(code.replace("-", "")) == erwartet
    assert totp.code_hashen(f"  {code.upper()}  ") == erwartet
    assert totp.code_hashen(code.replace("-", " ")) == erwartet


def test_der_hash_verraet_den_code_nicht():
    code = totp.wiederherstellungscodes_neu(1)[0]
    h = totp.code_hashen(code)
    assert h != code
    assert code.replace("-", "") not in h
    assert len(h) == 64
