"""PlantUML text -> URL-safe encoding (standard algorithm).

Cross-language contract vector in server/tests/test_encoder.py and
web/test/encoder.test.ts.
"""

from __future__ import annotations

import zlib


def _decode6bit(cc: str) -> int | None:
    o = ord(cc)
    if 48 <= o <= 57:
        return o - 48
    if 65 <= o <= 90:
        return o - 65 + 10
    if 97 <= o <= 122:
        return o - 97 + 36
    if cc == "-":
        return 62
    if cc == "_":
        return 63
    return None


def _encode6bit(b: int) -> str:
    if b < 10:
        return chr(48 + b)
    b -= 10
    if b < 26:
        return chr(65 + b)
    b -= 26
    if b < 26:
        return chr(97 + b)
    b -= 26
    if b == 0:
        return "-"
    if b == 1:
        return "_"
    return "?"


def _append3bytes(b1: int, b2: int, b3: int) -> str:
    c1 = b1 >> 2
    c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
    c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
    c4 = b3 & 0x3F
    return _encode6bit(c1) + _encode6bit(c2) + _encode6bit(c3) + _encode6bit(c4)


def encode(text: str) -> str:
    data = zlib.compress(text.encode("utf-8"))[2:-4]  # raw deflate
    out: list[str] = []
    i = 0
    while i + 3 <= len(data):
        out.append(_append3bytes(data[i], data[i + 1], data[i + 2]))
        i += 3
    rem = len(data) - i
    if rem == 1:
        out.append(_append3bytes(data[i], 0, 0))
    elif rem == 2:
        out.append(_append3bytes(data[i], data[i + 1], 0))
    return "".join(out)


def decode(text: str) -> str:
    """Inverse of :func:`encode` (standard PlantUML decode -> raw deflate -> utf-8).

    Trailing padding bits (zeros) are discarded naturally by the bit buffer.
    """
    bits = 0
    nbits = 0
    out = bytearray()
    for ch in text:
        c = _decode6bit(ch)
        if c is None:
            raise ValueError(f"invalid plantuml encoded char: {ch!r}")
        bits = (bits << 6) | c
        nbits += 6
        if nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xFF)
    try:
        return zlib.decompress(bytes(out), -15).decode("utf-8")
    except zlib.error as e:
        raise ValueError(f"plantuml decode failed: {e}")
