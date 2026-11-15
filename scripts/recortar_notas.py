"""Recorta las notas de una release para que quepan en GitHub.

GitHub rechaza el cuerpo de una release de más de 125 000 caracteres (HTTP
422, «body is too long»). Pasó con la 1.2.0: `etiquetar.yml` creó la etiqueta,
pero no la release, y hubo que crearla a mano con un resumen.

Si las notas pasan del límite, se cortan en el último salto de línea que cabe,
se cierra un bloque de código que haya quedado abierto (si no, el resto de la
página se vería como código) y se añade un enlace al CHANGELOG completo de la
etiqueta, que siempre lo tiene entero. Las notas que caben no se tocan.

Se cuenta en caracteres, no en bytes, como GitHub. Por eso va en Python y no
con `wc`, cuyo recuento depende de la configuración regional del runner.

Uso: python3 scripts/recortar_notas.py <fichero> <versión> <url del repo>
"""

from __future__ import annotations

import sys
from pathlib import Path

# Margen bajo los 125 000 de GitHub, por si cuenta algún carácter distinto.
LIMITE = 120_000


def _aviso(version: str, url_repo: str) -> str:
    return (
        "\n\n---\n\n"
        "Notas recortadas: no caben enteras en una release de GitHub. "
        f"Están completas en el [CHANGELOG de la {version}]"
        f"({url_repo}/blob/v{version}/hermes/CHANGELOG.md).\n"
    )


def recortar(notas: str, version: str, url_repo: str, limite: int = LIMITE) -> str:
    """Devuelve `notas` tal cual si caben y, si no, recortadas con el aviso."""
    if len(notas) <= limite:
        return notas
    aviso = _aviso(version, url_repo)
    # Hueco para el aviso y para un cierre de bloque de código (4 caracteres).
    hueco = limite - len(aviso) - 4
    corte = notas.rfind("\n", 0, hueco)
    # Sin ningún salto de línea en el hueco (una línea enorme), se corta a
    # mitad de línea: mejor eso que dejar las notas vacías.
    recortadas = notas[: corte + 1] if corte >= 0 else notas[:hueco] + "\n"
    vallas = sum(
        1 for linea in recortadas.splitlines() if linea.lstrip().startswith("```")
    )
    if vallas % 2:
        recortadas += "```\n"
    return recortadas + aviso


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    ruta, version, url_repo = Path(argv[1]), argv[2], argv[3]
    notas = ruta.read_text(encoding="utf-8")
    nuevas = recortar(notas, version, url_repo)
    if nuevas != notas:
        ruta.write_text(nuevas, encoding="utf-8")
        print(f"Notas recortadas de {len(notas)} a {len(nuevas)} caracteres.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
