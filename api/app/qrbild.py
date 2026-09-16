"""N477 — QR-Code für die Zwei-Faktor-Einrichtung, handgeschrieben.

Nutzer: „ich will den QR-Code auch scannen können wie üblich". Bis hierher
stand nur der Base32-Schlüssel zum Abtippen da — das kann jede
Authenticator-App, ist aber nicht das, was man gewohnt ist.

Wie PDF (`pdfkern.py`), WebDAV (`nextcloud.py`) und TOTP (`totp.py`) ohne
Fremdbibliothek — `CLAUDE.md` erlaubt ausser Google Fonts keine, und ein
QR-Encoder ist ein abgeschlossener, vollständig spezifizierter Algorithmus
(ISO/IEC 18004). Ausgabe als SVG: kein Pillow nötig, scharf in jeder Grösse,
kleiner als ein PNG und direkt in die Seite einsetzbar.

Umfang bewusst eng: Byte-Modus, Fehlerkorrektur **M** (15 %, der übliche
Wert für `otpauth`-Codes), Versionen 1–10. Eine `otpauth`-Zeile ist rund
110 Zeichen; Version 10 trägt 213 und lässt damit Luft für lange
Familiennamen. Wer mehr braucht, bekommt einen klaren Fehler statt eines
stillen Fehldrucks.

Geprüft wird das Ergebnis nicht am eigenen Code, sondern gegen einen echten
Decoder (OpenCV, `test_qrbild.py`) — ein QR-Code, den nur der eigene Encoder
für richtig hält, ist wertlos."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Tabellen aus ISO/IEC 18004 — Fehlerkorrekturstufe M.
# Je Version: (Fehlerkorrektur-Wörter je Block, [(Blöcke, Datenwörter je Block)])
# ---------------------------------------------------------------------------
_BLOECKE: dict[int, tuple[int, list[tuple[int, int]]]] = {
    1:  (10, [(1, 16)]),
    2:  (16, [(1, 28)]),
    3:  (26, [(1, 44)]),
    4:  (18, [(2, 32)]),
    5:  (24, [(2, 43)]),
    6:  (16, [(4, 27)]),
    7:  (18, [(4, 31)]),
    8:  (22, [(2, 38), (2, 39)]),
    9:  (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}

# Mittelpunkte der Ausrichtungsmuster je Version (Version 1 hat keine).
_AUSRICHTUNG: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# 18-Bit-Versionsinformation, erst ab Version 7 im Code enthalten.
_VERSIONSINFO: dict[int, int] = {
    7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3,
}

_FUELLER = (0xEC, 0x11)


class QRFehler(ValueError):
    """Der Text passt in keine unterstützte Version."""


# ---------------------------------------------------------------------------
# Galois-Feld GF(256) für die Reed-Solomon-Fehlerkorrektur
# ---------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _feld_aufbauen() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:                      # Primitivpolynom 0x11D
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_feld_aufbauen()


def _mal(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(grad: int) -> list[int]:
    """Das Generatorpolynom für `grad` Fehlerkorrekturwörter."""
    poly = [1]
    for i in range(grad):
        neu = [0] * (len(poly) + 1)
        for j, wert in enumerate(poly):
            neu[j] ^= wert
            neu[j + 1] ^= _mal(wert, _EXP[i])
        poly = neu
    return poly


def _fehlerkorrektur(daten: list[int], anzahl: int) -> list[int]:
    gen = _generator(anzahl)
    rest = list(daten) + [0] * anzahl
    for i in range(len(daten)):
        faktor = rest[i]
        if faktor == 0:
            continue
        for j, g in enumerate(gen):
            rest[i + j] ^= _mal(g, faktor)
    return rest[len(daten):]


# ---------------------------------------------------------------------------
# Daten kodieren
# ---------------------------------------------------------------------------

def _datenkapazitaet(version: int) -> int:
    ecc, gruppen = _BLOECKE[version]
    return sum(anzahl * groesse for anzahl, groesse in gruppen)


def _passende_version(laenge: int) -> int:
    for version in sorted(_BLOECKE):
        # 4 Bit Modus + 8 Bit Längenangabe (bis Version 9), sonst 16 Bit.
        kopf = 4 + (8 if version < 10 else 16)
        if _datenkapazitaet(version) * 8 >= kopf + laenge * 8:
            return version
    raise QRFehler(f"{laenge} Zeichen passen in keinen QR-Code bis Version 10.")


def _bitfolge(text: str, version: int) -> list[int]:
    roh = text.encode("utf-8")
    bits: list[int] = []

    def schreibe(wert: int, breite: int) -> None:
        bits.extend((wert >> (breite - 1 - i)) & 1 for i in range(breite))

    schreibe(0b0100, 4)                                  # Byte-Modus
    schreibe(len(roh), 8 if version < 10 else 16)
    for byte in roh:
        schreibe(byte, 8)

    kapazitaet = _datenkapazitaet(version) * 8
    bits.extend([0] * min(4, kapazitaet - len(bits)))    # Abschluss
    bits.extend([0] * (-len(bits) % 8))                  # auf volle Bytes
    for i in range((kapazitaet - len(bits)) // 8):       # Füllbytes
        schreibe(_FUELLER[i % 2], 8)
    return bits


def _codewoerter(text: str, version: int) -> list[int]:
    """Daten- und Fehlerkorrekturwörter, blockweise verschränkt."""
    bits = _bitfolge(text, version)
    roh = [int("".join(str(b) for b in bits[i:i + 8]), 2)
           for i in range(0, len(bits), 8)]

    ecc_anzahl, gruppen = _BLOECKE[version]
    datenbloecke: list[list[int]] = []
    eccbloecke: list[list[int]] = []
    stelle = 0
    for anzahl, groesse in gruppen:
        for _ in range(anzahl):
            block = roh[stelle:stelle + groesse]
            stelle += groesse
            datenbloecke.append(block)
            eccbloecke.append(_fehlerkorrektur(block, ecc_anzahl))

    folge: list[int] = []
    for i in range(max(len(b) for b in datenbloecke)):
        folge.extend(block[i] for block in datenbloecke if i < len(block))
    for i in range(ecc_anzahl):
        folge.extend(block[i] for block in eccbloecke)
    return folge


# ---------------------------------------------------------------------------
# Matrix aufbauen
# ---------------------------------------------------------------------------

def _leer(kante: int) -> list[list[int | None]]:
    return [[None] * kante for _ in range(kante)]


def _muster_setzen(m: list[list[int | None]], version: int) -> None:
    kante = len(m)

    def sucher(zeile: int, spalte: int) -> None:
        """Suchmuster 7×7 samt Trennlinie ringsum."""
        for dz in range(-1, 8):
            for ds in range(-1, 8):
                z, s = zeile + dz, spalte + ds
                if not (0 <= z < kante and 0 <= s < kante):
                    continue
                rand = dz in (-1, 7) or ds in (-1, 7)
                ring = dz in (0, 6) or ds in (0, 6)
                kern = 2 <= dz <= 4 and 2 <= ds <= 4
                m[z][s] = 0 if rand else (1 if (ring or kern) else 0)

    sucher(0, 0)
    sucher(0, kante - 7)
    sucher(kante - 7, 0)

    for i in range(8, kante - 8):                        # Taktmuster
        m[6][i] = m[i][6] = 1 - (i % 2)

    mitten = _AUSRICHTUNG[version]
    for z in mitten:
        for s in mitten:
            # Nicht über die drei Suchmuster legen.
            if (z < 8 and s < 8) or (z < 8 and s > kante - 9) \
                    or (z > kante - 9 and s < 8):
                continue
            for dz in range(-2, 3):
                for ds in range(-2, 3):
                    aussen = max(abs(dz), abs(ds))
                    m[z + dz][s + ds] = 1 if aussen != 1 else 0

    m[kante - 8][8] = 1                                  # immer dunkel


def _reserviert(version: int) -> set[tuple[int, int]]:
    """Alle Felder, die keine Daten tragen: Muster, Format, Version."""
    kante = version * 4 + 17
    felder: set[tuple[int, int]] = set()
    for i in range(9):                                   # Format links oben
        felder.add((8, i))
        felder.add((i, 8))
    for i in range(8):
        felder.add((8, kante - 1 - i))                   # Format rechts oben
        felder.add((kante - 1 - i, 8))                   # Format links unten
    if version >= 7:
        for i in range(6):
            for j in range(3):
                felder.add((kante - 11 + j, i))
                felder.add((i, kante - 11 + j))
    return felder


def _daten_platzieren(m: list[list[int | None]], folge: list[int]) -> None:
    """Zickzack von rechts unten nach links oben, Spalte 6 ausgelassen."""
    kante = len(m)
    bits = [(wort >> (7 - i)) & 1 for wort in folge for i in range(8)]
    stelle = 0
    spalte = kante - 1
    aufwaerts = True
    while spalte > 0:
        if spalte == 6:                                  # senkrechtes Taktmuster
            spalte -= 1
        zeilen = range(kante - 1, -1, -1) if aufwaerts else range(kante)
        for zeile in zeilen:
            for s in (spalte, spalte - 1):
                if m[zeile][s] is not None:
                    continue
                m[zeile][s] = bits[stelle] if stelle < len(bits) else 0
                stelle += 1
        spalte -= 2
        aufwaerts = not aufwaerts


_MASKEN = (
    lambda z, s: (z + s) % 2 == 0,
    lambda z, s: z % 2 == 0,
    lambda z, s: s % 3 == 0,
    lambda z, s: (z + s) % 3 == 0,
    lambda z, s: (z // 2 + s // 3) % 2 == 0,
    lambda z, s: (z * s) % 2 + (z * s) % 3 == 0,
    lambda z, s: ((z * s) % 2 + (z * s) % 3) % 2 == 0,
    lambda z, s: ((z + s) % 2 + (z * s) % 3) % 2 == 0,
)


def _strafe(m: list[list[int]]) -> int:
    """Die vier Bewertungsregeln — je niedriger, desto besser lesbar."""
    kante = len(m)
    punkte = 0

    for linien in (m, [list(spalte) for spalte in zip(*m)]):
        for linie in linien:
            lauf, vorher = 1, linie[0]
            for wert in linie[1:]:
                if wert == vorher:
                    lauf += 1
                else:
                    if lauf >= 5:
                        punkte += 3 + (lauf - 5)
                    lauf, vorher = 1, wert
            if lauf >= 5:
                punkte += 3 + (lauf - 5)
            # Regel 3: das Suchmuster-ähnliche Muster im Datenbereich
            text = "".join(str(w) for w in linie)
            punkte += 40 * (text.count("10111010000") + text.count("00001011101"))

    for z in range(kante - 1):                           # Regel 2: 2×2-Flächen
        for s in range(kante - 1):
            viert = (m[z][s], m[z][s + 1], m[z + 1][s], m[z + 1][s + 1])
            if len(set(viert)) == 1:
                punkte += 3

    dunkel = sum(sum(zeile) for zeile in m)
    anteil = dunkel * 100 // (kante * kante)
    punkte += 10 * (abs(anteil - 50) // 5)               # Regel 4
    return punkte


def _formatbits(maske: int) -> int:
    """15 Bit BCH für Stufe M (binär 00) und die Maskennummer."""
    wert = (0b00 << 3) | maske
    rest = wert << 10
    while rest.bit_length() > 10:
        rest ^= 0b10100110111 << (rest.bit_length() - 11)
    return ((wert << 10) | rest) ^ 0b101010000010010


def _format_platzieren(m: list[list[int]], maske: int) -> None:
    bits = _formatbits(maske)
    kante = len(m)
    for i in range(15):
        # MSB zuerst: auf der ersten Stelle des Wegs liegt Bit 14, nicht
        # Bit 0. Genau daran scheiterten mehrere Anläufe — die POSITIONEN
        # waren von Anfang an richtig, nur die Wertigkeit war gespiegelt.
        # Ein Selbsttest findet das nie: er liest mit derselben Spiegelung
        # zurück. Bewiesen wurde es erst, indem die Formatbits eines
        # fremden, nachweislich gültigen Codes so gelesen wurden, dass die
        # darin genannte Maske zu der passt, mit der sich seine Daten
        # tatsächlich entschlüsseln lassen (siehe test_qrbild.py).
        bit = (bits >> (14 - i)) & 1
        # Erste Kopie, um die Ecke links oben: Bit 0 liegt auf (8,0), läuft
        # in Zeile 8 nach rechts und ab Bit 8 in Spalte 8 nach oben. Die
        # Spalte 6 (senkrechtes Taktmuster) wird dabei übersprungen, deshalb
        # der Sprung von (8,5) auf (8,7) — und ebenso (6,8) auf dem Rückweg.
        if i < 6:
            m[8][i] = bit
        elif i == 6:
            m[8][7] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[7][8] = bit
        else:
            m[14 - i][8] = bit
        # Zweite Kopie: Bits 0-6 senkrecht in Spalte 8 von unten herauf
        # (SIEBEN, nicht acht — das achte Feld darunter ist das Dunkelmodul
        # und gehört nicht zum Format), Bits 7-14 waagerecht in Zeile 8 nach
        # rechts. Beide Fehler steckten im ersten Wurf: Zeile und Spalte
        # vertauscht, und eine Stelle zu weit gezählt, wodurch das
        # Dunkelmodul überschrieben wurde. Der Decoder fand dann gar nichts.
        if i < 7:
            m[kante - 1 - i][8] = bit
        else:
            m[8][kante - 15 + i] = bit


def _version_platzieren(m: list[list[int]], version: int) -> None:
    if version < 7:
        return
    bits = _VERSIONSINFO[version]
    kante = len(m)
    for i in range(18):
        bit = (bits >> i) & 1
        z, s = i // 3, i % 3
        m[kante - 11 + s][z] = bit
        m[z][kante - 11 + s] = bit


def matrix(text: str) -> list[list[int]]:
    """Die fertige QR-Matrix: 1 = dunkel, 0 = hell, ohne Rand."""
    if not text:
        raise QRFehler("Kein Inhalt für den QR-Code.")
    version = _passende_version(len(text.encode("utf-8")))
    kante = version * 4 + 17

    roh = _leer(kante)
    _muster_setzen(roh, version)
    for z, s in _reserviert(version):
        if roh[z][s] is None:
            roh[z][s] = 0
    fest = {(z, s) for z in range(kante) for s in range(kante)
            if roh[z][s] is not None}

    roh = _leer(kante)
    _muster_setzen(roh, version)
    for z, s in _reserviert(version):
        if roh[z][s] is None:
            roh[z][s] = 0
    _daten_platzieren(roh, _codewoerter(text, version))

    bester: list[list[int]] | None = None
    bestwert = None
    for nummer, maske in enumerate(_MASKEN):
        kandidat = [[roh[z][s] ^ (1 if (z, s) not in fest and maske(z, s) else 0)
                     for s in range(kante)] for z in range(kante)]
        _format_platzieren(kandidat, nummer)
        _version_platzieren(kandidat, version)
        wert = _strafe(kandidat)
        if bestwert is None or wert < bestwert:
            bester, bestwert = kandidat, wert
    return bester


def als_svg(text: str, rand: int = 4) -> str:
    """Der QR-Code als SVG-Zeichenkette, quadratisch und skalierbar.

    `rand` ist die vorgeschriebene helle Zone in Modulen — ohne sie finden
    manche Scanner den Code nicht. Die Module werden zeilenweise zu
    Rechtecken zusammengefasst, das spart gegenüber einem Rechteck je Modul
    rund zwei Drittel der Zeichen."""
    m = matrix(text)
    kante = len(m) + 2 * rand
    teile = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {kante} {kante}" '
             f'shape-rendering="crispEdges" role="img" '
             f'aria-label="QR-Code zur Einrichtung">'
             f'<rect width="{kante}" height="{kante}" fill="#fff"/>']
    for z, zeile in enumerate(m):
        s = 0
        while s < len(zeile):
            if not zeile[s]:
                s += 1
                continue
            start = s
            while s < len(zeile) and zeile[s]:
                s += 1
            teile.append(f'<rect x="{start + rand}" y="{z + rand}" '
                         f'width="{s - start}" height="1" fill="#16262C"/>')
    teile.append("</svg>")
    return "".join(teile)
