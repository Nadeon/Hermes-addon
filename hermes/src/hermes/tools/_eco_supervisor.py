"""Hermes — mensajes del Supervisor sin el eco de lo que se le mandó.

El Supervisor valida los cuerpos con voluptuous (`api_validate` en
`supervisor/api/utils.py`) y, salvo con `redact_values`, responde con
`humanize_error(data, ex)`: «<error>. Got <repr() del valor>», cortado a 500
caracteres. Es decir: repite en su error lo que le mandó el usuario, con
contraseñas, PSK de wifi o credenciales de un montaje dentro, y entre
comillas simples de `repr()`, una forma que `redact_secrets` no reconoce.

La 030 lo cerró en `sv_set_addon_options`; el cierre de seguridad de la
1.2.0 lo sacó aquí para que TODAS las tools `sv_*` que mandan datos del
usuario (opciones, montajes, red, opciones de Core y del Supervisor,
repositorios, backups…) limpien sus errores en un único punto:
`sin_eco_del_supervisor`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from hermes.security import REDACTED_MARKER, redact_secrets, redact_structure


def sin_eco_del_supervisor(texto: str, *conjuntos: Any, que: str = "the request") -> str:
    """Un mensaje del Supervisor sin ningún valor de lo que se le mandó.

    `conjuntos` son los datos que pudo ver el Supervisor (el cuerpo enviado
    y, si aplica, lo que había antes): los valores de todos cuentan. `que`
    nombra lo rechazado en el mensaje genérico del paso 3 (`the options` en
    `sv_set_addon_options`). Ver `_sin_valores_secretos` para los pasos.
    """
    return _sin_valores_secretos(texto, *conjuntos, que=que)


def _valores_secretos(original: Any, redactado: Any) -> set[str]:
    """Los textos de `original` que `redact_structure` sustituyó en
    `redactado` (recorridos a la vez): los valores secretos de unas opciones."""
    if redactado == REDACTED_MARKER and original != REDACTED_MARKER and not isinstance(original, str):
        # Desde la 025 (`tapar_entero`) un objeto, una lista o un número bajo
        # una clave sensible se tapa ENTERO: el recorrido paralelo encontraba
        # dict frente a texto y no recogía nada, y un mensaje del Supervisor
        # que nombrara `credentials.password` salía tal cual (revisión de la
        # 025, MEDIO-1). Todos sus valores escalares cuentan como secretos.
        return {h for h in _hojas(original) if h}
    if isinstance(original, dict) and isinstance(redactado, dict):
        out: set[str] = set()
        for clave, valor in original.items():
            out |= _valores_secretos(valor, redactado.get(clave))
        return out
    if isinstance(original, list) and isinstance(redactado, list):
        out = set()
        for valor, tapado in zip(original, redactado):
            out |= _valores_secretos(valor, tapado)
        return out
    if isinstance(original, str) and original and original != redactado:
        return {original}
    return set()


def _sin_valores_secretos(texto: str, *conjuntos: Any, que: str = "the options") -> str:
    """Un mensaje del Supervisor sobre unas opciones, sin ningún valor suyo.

    Fail-closed, en cuatro pasos (convergencia de la 030, T029 y T030):

    1. Nada desde «Got» en adelante. El Supervisor valida con
       `vol.Schema(vol.All(dict, AppOptions))` y `AppOptions` lanza
       `vol.Invalid` en la RAÍZ, así que `humanize_error` añade «. Got
       <repr() de TODAS las opciones>», cortado a 497 caracteres + `...`.
       Un cliente podía alargar una opción para que el corte cayera dentro
       de un secreto y recibirlo entero menos su último carácter, y un
       secreto con barras invertidas, saltos de línea o comillas salía escapado y no se
       encontraba. Lo que queda antes de «Got» es el texto del error, que
       solo nombra la opción, la app y su slug.
    2. Cualquier otro eco de un valor (de TODAS las opciones, no solo de las
       secretas) se tapa: entero, escapado como lo escriben `repr()` y JSON,
       o cortado al final del texto.
    3. Si aun así queda un trozo de un valor secreto, no se arriesga nada: un
       mensaje genérico con solo las claves que fallan (`data['clave']`).
    4. La redacción general (`redact_secrets`) al final, como siempre.

    `conjuntos` son las opciones que pudo ver el Supervisor (las actuales,
    los cambios pedidos y las finales): los valores de todas cuentan.
    """
    m = _RE_GOT.search(texto)
    if m:
        texto = texto[:m.start()].rstrip()
    antes_de_got = texto

    formas: set[str] = set()
    for conjunto in conjuntos:
        for valor in _hojas(conjunto):
            formas |= {f for f in _formas(valor) if len(f) >= _LARGO_MIN_VALOR}
    # Los más largos primero, para no dejar restos de uno que contiene a otro.
    for forma in sorted(formas, key=len, reverse=True):
        texto = texto.replace(forma, REDACTED_MARKER)
    if m:
        texto += " (values not shown)"
    else:
        # Sin «Got» el texto no lo cortó voluptuous, pero pudo cortarlo
        # otro (el cuerpo de un error HTTP): un valor a medias al final.
        texto = _sin_cola_cortada(texto, formas)

    secretos: set[str] = set()
    for conjunto in conjuntos:
        secretos |= _valores_secretos(conjunto, redact_structure(conjunto))
    if _queda_rastro(texto, secretos):
        return _mensaje_generico(antes_de_got, conjuntos, que)
    return redact_secrets(texto)


# Desde aquí el Supervisor (`humanize_error`) repite los valores. `\b` a los
# dos lados: «Gotify» o un slug `abc_gotify` no cortan nada.
_RE_GOT = re.compile(r"\bGot\b", re.IGNORECASE)

# Por debajo de este largo un valor no se sustituye en el texto: un `1`, un
# `on` o un `u` aparecen en cualquier mensaje y lo dejarían ilegible. Tras
# cortar en «Got» el texto solo nombra opción, app y slug; un SECRETO corto
# que aparezca igualmente lleva al mensaje genérico (`_queda_rastro`).
_LARGO_MIN_VALOR = 4

# Largo del trozo de un secreto que, si aparece, delata que se ha colado algo.
_VENTANA_RASTRO = 6

# Las claves que nombra el error: «option 'clave'» (`apps/options.py`) y
# `data['clave']` (voluptuous).
_RE_CLAVE_EN_MENSAJE = re.compile(r"option '([^'\n]{1,200})'|data\['([^'\n]{1,200})'\]")


def _hojas(valor: Any) -> list[str]:
    """Los valores escalares de unas opciones, como texto. Sin booleanos ni
    `None`: `True`/`None` no identifican nada y están en cualquier mensaje."""
    if isinstance(valor, dict):
        return [h for v in valor.values() for h in _hojas(v)]
    if isinstance(valor, list):
        return [h for v in valor for h in _hojas(v)]
    if isinstance(valor, bool) or valor is None:
        return []
    if isinstance(valor, (str, int, float)):
        return [str(valor)]
    return []


def _claves(valor: Any) -> set[str]:
    """Todas las claves de unas opciones, a cualquier nivel."""
    if isinstance(valor, dict):
        out = {str(k) for k in valor}
        for v in valor.values():
            out |= _claves(v)
        return out
    if isinstance(valor, list):
        out = set()
        for v in valor:
            out |= _claves(v)
        return out
    return set()


def _formas(valor: str) -> set[str]:
    """Cómo puede aparecer `valor` en un mensaje: tal cual, escapado por
    `repr()` (con una u otra comilla), por JSON (con y sin `ensure_ascii`) y
    el `repr()` metido a su vez en un JSON (el cuerpo del error HTTP)."""
    escapado = repr(valor)[1:-1]
    return {
        valor,
        escapado,
        escapado.replace("\'", "'"),
        escapado.replace('"', '\\"'),
        json.dumps(valor, ensure_ascii=False)[1:-1],
        json.dumps(valor)[1:-1],
        json.dumps(escapado, ensure_ascii=False)[1:-1],
        json.dumps(escapado)[1:-1],
    } - {""}


def _sin_cola_cortada(texto: str, formas: set[str]) -> str:
    """Tapa el principio de un valor que se quedó al final del texto porque
    alguien lo cortó (voluptuous corta a 500 caracteres y añade `...`)."""
    cola = texto.rstrip(" .'\"}])")
    for forma in sorted(formas, key=len, reverse=True):
        for largo in range(len(forma) - 1, _LARGO_MIN_VALOR - 1, -1):
            if cola.endswith(forma[:largo]):
                return cola[: len(cola) - largo] + REDACTED_MARKER + "..."
    return texto


def _queda_rastro(texto: str, secretos: set[str]) -> bool:
    """True si en `texto` queda algún trozo de un secreto, en cualquiera de
    sus formas: el secreto entero si es corto, o cualquier trozo de
    `_VENTANA_RASTRO` caracteres si es largo (un corte en cualquier punto)."""
    comparar = texto.replace(REDACTED_MARKER, "\0")
    for secreto in secretos:
        for forma in _formas(secreto):
            ventana = min(len(forma), _VENTANA_RASTRO)
            for i in range(len(forma) - ventana + 1):
                if forma[i:i + ventana] in comparar:
                    return True
    return False


def _mensaje_generico(texto: str, conjuntos: tuple[Any, ...], que: str = "the options") -> str:
    """Solo las claves que fallan, nunca sus valores. Una clave entra solo si
    es de verdad una clave de las opciones: así no se cuela por aquí nada que
    no lo sea."""
    validas: set[str] = set()
    for conjunto in conjuntos:
        validas |= _claves(conjunto)
    claves: list[str] = []
    for m in _RE_CLAVE_EN_MENSAJE.finditer(texto):
        clave = m.group(1) or m.group(2)
        if clave in validas and clave not in claves:
            claves.append(clave)
    mensaje = (f"The Supervisor rejected {que}. Its message is not shown "
               "because it could reveal a secret value.")
    if claves:
        # «options» en `sv_set_addon_options`, como en la 030; «fields» en el resto.
        nombre = "options" if que == "the options" else "fields"
        mensaje += f" Failing {nombre}: " + ", ".join(f"data['{c}']" for c in claves)
    return mensaje
