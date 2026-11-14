"""Política de comandos de las tools genéricas (spec 011, FR-003, FR-004, FR-012).

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
Las cuatro tools genéricas (`ha_read_ws_command`, `ha_call_ws_command`,
`sv_read_api`, `sv_call_api`) pueden enviar a Core o al Supervisor casi
cualquier cosa. Lo único que las separa de un acceso sin control es la tabla
de clasificación (`command_table.py`) y las guardas de este módulo. Por eso la
decisión vive aquí, en funciones puras —sin red, sin HA, sin tools—, donde se
prueba con tablas inyectadas y con un control negativo por guarda; las tools
solo aplican lo que decide `decidir`.

Es neutral al estilo de `service_policy.py`: no importa tools. Solo importa
`_assert_safe_request_path` de `hermes.ha` para no duplicar la defensa
central contra rutas peligrosas (si se mejora allí, se mejora aquí). La tabla
real se importa de forma perezosa porque `command_table.py` importa `Entrada`
de este módulo.

Fail-closed (principio III): lo que no está en la tabla no se ejecuta; una
plantilla ambigua no casa; una ruta con forma dudosa no llega a buscarse.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from hermes.ha import HAConnectionError, _assert_safe_request_path
from hermes.security import es_clave_sensible, redact_secrets

Categoria = Literal["dedicated", "read", "confirm", "deny"]
_CATEGORIAS = frozenset({"dedicated", "read", "confirm", "deny"})

ClaveSupervisor = tuple[str, str]

# Tool genérica → (categoría que ejecuta, la otra genérica del mismo servidor).
# La de lectura solo ejecuta `read` y la de escritura solo `confirm`: así el
# `readOnlyHint` de la de lectura es verdad (principio V) y todo lo que escribe
# pasa por la vista previa con token (principio IV).
GENERICAS: dict[str, tuple[str, str]] = {
    "ha_read_ws_command": ("read", "ha_call_ws_command"),
    "ha_call_ws_command": ("confirm", "ha_read_ws_command"),
    "sv_read_api": ("read", "sv_call_api"),
    "sv_call_api": ("confirm", "sv_read_api"),
}

# Un `{parámetro}` de plantilla casa con un segmento de 1 a 64 caracteres de
# este alfabeto (slugs, ids, nombres de interfaz…). Sin `%`, `/`, `:` ni
# espacios: nada que yarl o el Supervisor puedan reinterpretar.
_SEGMENTO_PARAMETRO = re.compile(r"[A-Za-z0-9._-]{1,64}")

# Prefijos del proxy de Core en el Supervisor. Por ahí se llega a la API REST
# de Core saltándose la denylist de servicios y las guardas de las tools `ha_*`
# (dashboard principal, autoprotección…). Se rechazan siempre, digan lo que
# digan la tabla o el inventario.
_PREFIJOS_PROXY_CORE = ("/core/api", "/homeassistant/api")

_HINT_NO_CLASIFICADO = (
    "hermes_guide(topic='generic_commands', search=...) lists what is available."
)


@dataclass(frozen=True, slots=True)
class Entrada:
    """Una entrada de la tabla: un comando de Core o un método + plantilla del
    Supervisor. Se valida al construirse, así que un error en la tabla se ve
    al importarla (en el primer test), no en producción."""

    category: str
    reason: str
    family: str
    tool: str | None = None
    cap: str | None = None
    # Suscripción que se lee una vez y se cancela (solo `read` de Core).
    one_shot: bool = False
    # «text»: la respuesta son líneas de log (solo Supervisor).
    response: str = "json"
    # Claves que se tapan además de los marcadores de `redact_structure`.
    redact_extra: tuple[str, ...] = ()
    # La ejecución sale a internet. Puede ir en `read` (navegar fuentes de
    # medios remotas): entonces la genérica de lectura de esa tabla se anuncia
    # de mundo abierto, y tests/test_command_table.py lo comprueba (FR-018,
    # T047).
    open_world: bool = False
    # Ejemplo de carga revisado, con datos ficticios, para la guía.
    example: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIAS:
            raise ValueError(f"categoría inválida: {self.category!r}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("una entrada necesita un motivo")
        if not self.family:
            raise ValueError("una entrada necesita una familia")
        if (self.category == "dedicated") != bool(self.tool):
            raise ValueError("`tool` va si y solo si la categoría es `dedicated`")
        if self.one_shot and self.category != "read":
            raise ValueError("`one_shot` solo con la categoría `read`")
        if self.response not in ("json", "text"):
            raise ValueError(f"respuesta inválida: {self.response!r}")


@dataclass(frozen=True, slots=True)
class Permitido:
    """La genérica puede ejecutar la entrada (con dos pasos si es `confirm`)."""

    entrada: Entrada


@dataclass(frozen=True, slots=True)
class Rechazo:
    """La genérica rechaza sin llamar a HA ni al Supervisor.

    `codigo` es el `error` que verá el cliente; `campos`, los campos extra de
    la tabla de data-model. Nunca lleva valores de la carga ni la ruta o el
    comando si no tienen forma válida (principio II).
    """

    codigo: str
    campos: dict[str, Any] = field(default_factory=dict)


def _tabla_core() -> Mapping[str, Entrada]:
    from hermes import command_table
    return command_table.CORE_WS


def _tabla_supervisor() -> Mapping[ClaveSupervisor, Entrada]:
    from hermes import command_table
    return command_table.SUPERVISOR


def buscar_core(tipo: str, tabla: Mapping[str, Entrada] | None = None) -> Entrada | None:
    """Entrada exacta del comando de Core, o `None`.

    Exacta a propósito: nada de prefijos, comodines ni mayúsculas, que
    clasificarían comandos que nadie ha revisado.
    """
    tabla = _tabla_core() if tabla is None else tabla
    return tabla.get(tipo)


def _segmentos(ruta: str) -> list[str]:
    return ruta.split("/")[1:]


def _es_parametro(segmento: str) -> bool:
    return len(segmento) > 2 and segmento[0] == "{" and segmento[-1] == "}"


def _casa_segmento(plantilla: str, concreto: str) -> bool:
    if _es_parametro(plantilla):
        return (
            concreto not in (".", "..")
            and _SEGMENTO_PARAMETRO.fullmatch(concreto) is not None
        )
    return plantilla == concreto


def casar_ruta(
    method: str,
    path: str,
    tabla: Mapping[ClaveSupervisor, Entrada] | None = None,
) -> tuple[ClaveSupervisor, Entrada] | None:
    """Casa una ruta concreta con las plantillas de la tabla (research R-7).

    Segmento a segmento: un literal solo casa consigo mismo; un `{parámetro}`,
    con un segmento válido. Entre varias plantillas que casan gana la de más
    literales (`/addons/self/info` frente a `/addons/{app}/info`); si empatan,
    no casa ninguna: adivinar cuál quería el cliente podría elegir la menos
    restrictiva.
    """
    tabla = _tabla_supervisor() if tabla is None else tabla
    metodo = method.upper() if isinstance(method, str) else ""
    concretos = _segmentos(path)
    mejores: list[tuple[int, ClaveSupervisor]] = []
    for clave in tabla:
        m, plantilla = clave
        if m != metodo:
            continue
        segs = _segmentos(plantilla)
        if len(segs) != len(concretos):
            continue
        if all(_casa_segmento(s, c) for s, c in zip(segs, concretos)):
            literales = sum(1 for s in segs if not _es_parametro(s))
            mejores.append((literales, clave))
    if not mejores:
        return None
    mejores.sort(key=lambda x: x[0], reverse=True)
    if len(mejores) > 1 and mejores[0][0] == mejores[1][0]:
        return None
    clave = mejores[0][1]
    return clave, tabla[clave]


def parametros(plantilla: str, path: str) -> dict[str, str]:
    """Valores de los `{parámetros}` de una plantilla ya casada con `path`."""
    return {
        s[1:-1]: c
        for s, c in zip(_segmentos(plantilla), _segmentos(path))
        if _es_parametro(s)
    }


def validar_ruta(path: str) -> Rechazo | None:
    """Rechaza una ruta del Supervisor antes de buscarla en la tabla (FR-012).

    Regla `shape`: lo que `_assert_safe_request_path` ya prohíbe (sin `/`
    inicial, control, `%`, `?`, `#`, `..` también codificado) más `\\`, `//`
    o segmentos vacíos, barra final y segmentos `.`. Con eso no cabe un
    esquema ni un host (`http://x`, `//x`), ni una ruta que yarl normalizaría a
    otra distinta de la que se clasificó.

    Regla `core_proxy`: `/core/api*` y `/homeassistant/api*`, siempre.
    """
    if not isinstance(path, str):
        return Rechazo("path_not_allowed", {"rule": "shape"})
    try:
        _assert_safe_request_path(path)
    except HAConnectionError:
        return Rechazo("path_not_allowed", {"rule": "shape"})
    if "\\" in path or path.endswith("/") or "//" in path:
        return Rechazo("path_not_allowed", {"rule": "shape"})
    if any(s in ("", ".", "..") for s in _segmentos(path)):
        return Rechazo("path_not_allowed", {"rule": "shape"})
    if path.startswith(_PREFIJOS_PROXY_CORE):
        return Rechazo("path_not_allowed", {"rule": "core_proxy"})
    return None


def decidir(
    tool: str,
    entrada: Entrada | None,
    *,
    familias_desactivadas: frozenset[str] = frozenset(),
    familia_de_tool: Callable[[str], str] | None = None,
    parametros: Mapping[str, str] | None = None,
    es_hermes: Callable[[str], bool] | None = None,
) -> Permitido | Rechazo:
    """Decide si la genérica `tool` puede ejecutar `entrada` (tabla de
    data-model, en este orden):

    1. sin entrada → `command_not_classified` (fail-closed);
    2. `{app}` es el propio Hermes → `path_not_allowed` (`self_target`): la
       autoprotección de `tools/addons.py` no se salta por la genérica;
    3. `deny` → `command_denied` con su motivo;
    4. `dedicated` → `use_dedicated_tool` con la tool, su familia y si está
       desactivada: la genérica nunca es una vía alternativa a una tool que
       tiene vista previa semántica o protecciones propias, ni siquiera con
       su familia apagada;
    5. categoría de la otra genérica → `wrong_generic_tool`;
    6. familia de la entrada desactivada → `family_disabled` (apagar una
       familia apaga su capacidad por cualquier vía);
    7. si no, `Permitido`.
    """
    if tool not in GENERICAS:
        raise ValueError(f"tool genérica desconocida: {tool!r}")
    ejecuta, otra = GENERICAS[tool]

    if entrada is None:
        return Rechazo("command_not_classified", {"hint": _HINT_NO_CLASIFICADO})

    if es_hermes is not None and parametros and "app" in parametros:
        if es_hermes(parametros["app"]):
            return Rechazo("path_not_allowed", {"rule": "self_target"})

    if entrada.category == "deny":
        return Rechazo("command_denied", {"reason": entrada.reason})

    if entrada.category == "dedicated":
        familia = (
            familia_de_tool(entrada.tool) if familia_de_tool is not None
            else entrada.family
        )
        return Rechazo("use_dedicated_tool", {
            "tool": entrada.tool,
            "family": familia,
            "family_disabled": familia in familias_desactivadas,
        })

    if entrada.category != ejecuta:
        return Rechazo("wrong_generic_tool", {"use_tool": otra})

    if entrada.family in familias_desactivadas:
        return Rechazo("family_disabled", {"family": entrada.family})

    return Permitido(entrada)


# ── Resumen de la carga (FR-010) ─────────────────────────────────────────────

# Hasta aquí, un valor se enseña entero. Uno más largo se enseña por su INICIO
# (`_INICIO_VISIBLE` caracteres, pasados por `redact_secrets`), su tamaño y un
# hash corto (`_HASH_VISIBLE` hex de su SHA-256): quien confirma sabe qué
# aprueba (de qué texto se trata y cuánto mide; el hash le deja compararlo con
# el que quería enviar) sin que la vista previa crezca con la carga. No se
# enseña entero porque un texto largo es donde se esconde un secreto sin clave
# que lo delate (una clave privada, un token opaco) y porque la vista previa
# tiene tope (`preview_too_large`). Enmienda E-1 y T045 de la 011.
_MAX_VALOR_VISIBLE = 64
_INICIO_VISIBLE = 32
_HASH_VISIBLE = 12


def _tipo_json(valor: Any) -> str:
    # `bool` antes que `int`: en Python `True` es un `int`.
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "boolean"
    if isinstance(valor, int):
        return "integer"
    if isinstance(valor, float):
        return "number"
    if isinstance(valor, str):
        return "string"
    if isinstance(valor, Mapping):
        return "object"
    if isinstance(valor, (list, tuple)):
        return "array"
    return type(valor).__name__


def _bytes_json(valor: Any) -> int:
    return len(json.dumps(valor, ensure_ascii=False).encode("utf-8"))


def resumir_carga(
    valor: Mapping[str, Any] | None,
    redact_extra: Iterable[str] = (),
) -> dict[str, Any]:
    """Resumen de la carga para la vista previa de las genéricas de escritura
    (FR-010, data-model «Fila del resumen de la carga»).

    Una fila por clave, a cualquier profundidad (los elementos de una lista,
    por índice), con su ruta `a.b[0].c`, su tipo JSON y sus bytes. El valor
    solo si es un escalar, mide 64 caracteres o menos (el texto tal cual; un
    número, booleano o `null`, su JSON), ninguna clave de su ruta es sensible
    (`es_clave_sensible` o `redact_extra`) y `redact_secrets` no lo cambia. Si
    no, `hidden` dice por qué, con esta precedencia: `container`, `sensitive`,
    `too_long`. Una fila `too_long` lleva además `head` (los 32 primeros
    caracteres, pasados por `redact_secrets`) y `sha256` (12 hex del SHA-256
    del texto entero); una `sensitive`, solo tipo y tamaño.

    POR QUÉ ASÍ: la vista previa genérica no interpreta el comando; lo único
    que puede enseñar con verdad es lo que se va a enviar. Y lo enseña sin
    filtrar secretos: la sensibilidad se HEREDA (lo que cuelga de
    `credentials` es sensible aunque se llame `username`), porque una clave
    sensible con un objeto dentro es justo donde un secreto no lleva un nombre
    que lo delate.
    """
    extra = {k.lower() for k in redact_extra}
    carga: Any = {} if valor is None else valor
    filas: list[dict[str, Any]] = []

    def sensible(clave: str) -> bool:
        return es_clave_sensible(clave) or clave.lower() in extra

    def visitar(v: Any, ruta: str, heredada: bool) -> None:
        fila: dict[str, Any] = {"path": ruta, "type": _tipo_json(v), "bytes": _bytes_json(v)}
        filas.append(fila)
        if isinstance(v, (Mapping, list, tuple)):
            fila["hidden"] = "container"
            recorrer(v, ruta, heredada)
            return
        if heredada:
            fila["hidden"] = "sensitive"
            return
        texto = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        if redact_secrets(texto) != texto:
            fila["hidden"] = "sensitive"
        elif len(texto) > _MAX_VALOR_VISIBLE:
            fila["hidden"] = "too_long"
            # Ya se ha comprobado que `redact_secrets` no cambia el texto
            # entero; se vuelve a pasar el inicio por si el corte deja a la
            # vista un trozo que sí casa con un patrón.
            fila["head"] = redact_secrets(texto[:_INICIO_VISIBLE])
            fila["sha256"] = hashlib.sha256(
                texto.encode("utf-8")
            ).hexdigest()[:_HASH_VISIBLE]
        else:
            fila["value"] = v

    def recorrer(v: Any, ruta: str, heredada: bool) -> None:
        if isinstance(v, Mapping):
            for k, hijo in v.items():
                clave = str(k)
                visitar(hijo, f"{ruta}.{clave}" if ruta else clave,
                        heredada or sensible(clave))
        else:
            for i, hijo in enumerate(v):
                visitar(hijo, f"{ruta}[{i}]", heredada)

    if isinstance(carga, (Mapping, list, tuple)):
        recorrer(carga, "", False)
    return {"bytes": _bytes_json(carga), "keys": len(filas), "rows": filas}
