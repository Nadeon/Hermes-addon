"""JPEG de prueba del banco (spec 024, T011), generado aquí byte a byte.

El banco necesita una imagen JPEG de verdad para la cámara `local_file`, la
subida de `image_upload` (que la abre con Pillow) y el fichero borrable de los
medios locales. No es una foto: es un cuadrado gris uniforme de `lado`×`lado`
píxeles, en escala de grises, codificado como JPEG baseline con tablas de
Huffman mínimas (un único símbolo en cada una). Así no hay ninguna imagen de
nadie en el repositorio, y `TestCoberturaDeLa024` comprueba que los ficheros
versionados son exactamente lo que genera esta función.

Por qué funciona: con todos los píxeles a 128, tras el desplazamiento de
nivel cada bloque de 8×8 tiene todos sus coeficientes a 0. Cada bloque se
codifica con la categoría 0 de DC (diferencia 0) y el EOB de AC, que con
estas tablas son un bit cada uno.
"""

from __future__ import annotations

import struct


def _segmento(marcador: int, datos: bytes) -> bytes:
    return bytes([0xFF, marcador]) + struct.pack(">H", len(datos) + 2) + datos


def jpeg_gris(lado: int = 16) -> bytes:
    """JPEG baseline gris de `lado`×`lado` (múltiplo de 8)."""
    if lado <= 0 or lado % 8:
        raise ValueError("lado must be a positive multiple of 8")
    app0 = _segmento(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    dqt = _segmento(0xDB, b"\x00" + b"\x01" * 64)
    sof0 = _segmento(0xC0, struct.pack(">BHHB", 8, lado, lado, 1) + b"\x01\x11\x00")
    # Una tabla DC (clase 0) y una AC (clase 1), cada una con un único código
    # de un bit: el símbolo 0x00 (categoría 0 en DC, EOB en AC).
    un_simbolo = b"\x01" + b"\x00" * 15 + b"\x00"
    dht = _segmento(0xC4, b"\x00" + un_simbolo + b"\x10" + un_simbolo)
    sos = _segmento(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    bloques = (lado // 8) ** 2
    # Dos bits «0» por bloque; el último byte se rellena con unos.
    bits = "00" * bloques
    bits += "1" * (-len(bits) % 8)
    datos = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
    return b"\xff\xd8" + app0 + dqt + sof0 + dht + sos + datos + b"\xff\xd9"
