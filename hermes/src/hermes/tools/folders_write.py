"""Hermes — Tools MCP que modifican /addons y /share (spec 034, 1.2.1).

Familia `addons_share`, junto a `tools/folders.py` (lectura). Este módulo es
el de las cuatro tools que modifican (escribir, crear carpeta, mover y
borrar, todas en dos pasos con huella), que llegan en el tramo 2 de la spec
034. Existe ya para que la familia nombre sus dos módulos desde el principio
(`tool_families.py`); hasta entonces no declara ni registra ninguna tool.
"""

from __future__ import annotations
