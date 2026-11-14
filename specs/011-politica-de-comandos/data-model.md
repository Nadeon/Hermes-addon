# Modelo de datos: política de comandos, genéricas y familias (011)

## Entrada de la tabla (`command_policy.Entrada`)

`dataclass(frozen=True, slots=True)`. Una por comando de Core o por método +
plantilla de ruta del Supervisor.

| Campo | Tipo | Regla |
|---|---|---|
| `category` | `Literal["dedicated", "read", "confirm", "deny"]` | Las cuatro de la 008; ninguna más |
| `reason` | `str` | No vacío. En `deny`, el motivo que verá el cliente (grupo B, motivo D, «pendiente de tool dedicada (spec NNN)», «pendiente de revisión (spec 025)», «uso interno de Hermes»). Nunca «sin revisar» al cerrar un tramo |
| `family` | `str` | Nombre de `tool_families.FAMILIAS`. En `dedicated`, la familia de `tool`; en el resto, `generic_commands` salvo que una sub-feature asigne otra |
| `tool` | `str \| None` | Obligatorio si y solo si `category == "dedicated"`; nombre de una tool registrada con todas las familias activas |
| `cap` | `str \| None` | `CAP-NNN` si la fila del inventario es de clase A o C (obligatorio entonces) |
| `one_shot` | `bool = False` | Solo con `category == "read"` y solo en Core: suscripción que se lee una vez y se cancela |
| `response` | `Literal["json", "text"] = "json"` | `text` solo en el Supervisor (logs) |
| `redact_extra` | `tuple[str, ...] = ()` | Nombres de clave que se tapan además de los marcadores de `redact_structure`, en la respuesta y en el resumen de la carga |
| `open_world` | `bool = False` | La ejecución sale a internet. Puede ir en `read` (T047): entonces la genérica de lectura de esa tabla se anuncia de mundo abierto, y un test lo ata |
| `example` | `dict \| None = None` | Ejemplo de carga revisado; la guía lo muestra; nunca datos reales (principio VIII) |

**Claves**:
- Core: `str`, el `type` del comando, con forma
  `^[a-z0-9_-]+(/[a-z0-9_-]+)*$`.
- Supervisor: `tuple[str, str]`, `(método en mayúsculas, plantilla)`; plantilla
  con `/` inicial, sin barra final, segmentos literales o `{nombre}`.

**Módulo `command_table.py`** (generado, revisado a mano):
`TABLE_HA_CORE: str`, `TABLE_SUPERVISOR: str`, `CORE_WS: dict[str, Entrada]`,
`SUPERVISOR: dict[tuple[str, str], Entrada]`. Una línea por entrada, en orden
alfabético de clave; comentarios con el porqué en las excepciones del test de
verbos y en las decisiones no evidentes.

## Decisión de las guardas (`command_policy.decidir`)

Función pura. Entrada: la tool genérica que llama (`"read"` o `"write"`), la
entrada encontrada (o `None`), las familias desactivadas y la familia de cada
tool dedicada. Salida: `Permitido(entrada)` o `Rechazo(codigo, campos)`.

| Situación | Código | Campos extra |
|---|---|---|
| Sin entrada | `command_not_classified` | `hint` (consultar `hermes_guide`) |
| `deny` | `command_denied` | `reason` |
| `dedicated` | `use_dedicated_tool` | `tool`, `family`, `family_disabled` (bool) |
| `read` pedido por la de escritura, o `confirm` por la de lectura | `wrong_generic_tool` | `use_tool` |
| `read`/`confirm` de familia desactivada | `family_disabled` | `family` |
| Ruta inválida, proxy de Core o dirigida a Hermes | `path_not_allowed` | `rule` (`shape`, `core_proxy`, `self_target`) |
| Argumentos con forma inválida | `invalid_argument` | `field` |

`invalid_argument` y `path_not_allowed` con reglas `shape` y `core_proxy` se
deciden antes de buscar en la tabla; `self_target` necesita saber qué segmento
es `{app}`, así que se decide justo después de casar la plantilla y antes de
mirar la categoría.

## Fila del resumen de la carga

| Campo | Tipo | Regla |
|---|---|---|
| `path` | `str` | `clave`, `a.b`, `a[0]`, `a.b[2].c`; la raíz no tiene fila |
| `type` | `str` | `string`, `integer`, `number`, `boolean`, `null`, `object`, `array` |
| `bytes` | `int` | Bytes de `json.dumps(valor, ensure_ascii=False)` en UTF-8 |
| `value` | escalar | Solo si: escalar; longitud ≤ 64 caracteres (cadena: el texto tal cual, sin comillas; número, booleano o `null`: su JSON); ninguna clave de la ruta sensible (`redact_structure` o `redact_extra`); `redact_secrets(str(valor)) == str(valor)` |
| `hidden` | `str` | Si no hay `value`: `container` (objeto o lista), `sensitive` o `too_long` (en ese orden de precedencia) |
| `head` | `str` | Solo con `too_long`: los 32 primeros caracteres del valor (cadena: el texto; número: su JSON), pasados por `redact_secrets` (T045) |
| `sha256` | `str` | Solo con `too_long`: los 12 primeros caracteres hex del SHA-256 del texto entero en UTF-8 (T045) |

Resumen: `{"bytes": <total>, "keys": <n filas>, "rows": [...]}`. Sin límite de
filas: si la vista previa completa no cabe en `response_max_bytes`,
`preview_too_large` y ningún token.

## Argumentos atados al token

| Tool | `args` del hash |
|---|---|
| `ha_call_ws_command` | `{"type": type, "payload": payload or {}}` |
| `sv_call_api` | `{"method": method.upper(), "path": path, "body": body}` |

Sin omitibles: nada de la carga se escribe en el fichero del token. Al
completar, `result={"executed": True}`.

## Familia (`tool_families.Familia`)

| Campo | Tipo | Regla |
|---|---|---|
| `nombre` | `str` | `^[a-z][a-z0-9_]*$`, único |
| `descripcion` | `str` | Inglés (la ve el usuario en DOCS) |
| `desde` | `str` | `"1.1.2"` o `"1.2.0"` |
| `desactivable` | `bool` | `False` solo en `base` |
| `modulos` | `tuple[str, ...]` | Nombres de módulos de `hermes/tools/`; cada módulo con `@mcp.tool()` en exactamente una familia |

`FAMILIAS: dict[str, Familia]`; `familia_de_modulo(nombre)`;
`validar_desactivadas(lista) -> frozenset[str]` (lanza `ValueError` con el
nombre inválido y los válidos).

## Opción

| Opción | Esquema | Por defecto | Entorno | `HermesConfig` |
|---|---|---|---|---|
| `tool_families_disabled` | `- "str?"` | `[]` | `HERMES_TOOL_FAMILIES_DISABLED` (JSON, como las demás listas) | `tool_families_disabled: list[str]`; `validate()` llama a `validar_desactivadas` |

## Inventarios

- `core-ws.tsv`: `comando`, `integracion`, `fichero`, `cobertura`, `clase`,
  `nota`, `cap`; 623 filas, una por comando (sin cambios).
- `supervisor-rutas.tsv`: `metodo`, `ruta`, `area`, `cobertura`, `clase`,
  `rol_admin`, `nota`, `cap`; **254 filas**, una por método + plantilla (se
  normaliza en esta sub-feature). `metodo` ∈ {`GET`, `POST`, `PUT`, `DELETE`,
  `PATCH`}.
- Fila nueva que añade el extractor: columnas manuales vacías y `clase`
  vacía; el generador la convierte en `deny` «sin revisar».
