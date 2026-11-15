# Modelo de datos: banco de pruebas del Supervisor (spec 014)

No hay datos persistentes nuevos en Hermes. Las «entidades» son documentos y
constantes de test.

## Matriz de pruebas (`docs/HOJA-DE-RUTA.md`)

Formato exacto en [contracts/matriz.md](contracts/matriz.md).

| Campo | Valores | Regla |
|---|---|---|
| Tool | nombre registrado, entre comillas invertidas | una fila por tool que modifica; sin repetir |
| Entorno | `banco de Core`, `VM`, `instalación real` | dónde se prueba contra el software real |
| Resultado | `ok`, `falla`, `pendiente`, `no ejecutable` | el último resultado en ese entorno; `no ejecutable` (desde la 033) solo con `banco de Core` y para una tool de un `NO_EJECUTABLES*` |
| Nota | texto libre, puede ir vacía | obligatoria con `falla` (causa o hallazgo), con `no ejecutable` (motivo) y con `ok` fuera del banco (versión de Hermes y fecha) |

Reglas de coherencia (FR-003), con `I` = inventarios del banco descubiertos:

| Si la tool… | Entorno | Resultado |
|---|---|---|
| está en algún `PROBADAS*` de `I` | `banco de Core` | `ok` |
| está en algún `FALLAN*` de `I` | `banco de Core` | `falla` (nota obligatoria) |
| está en algún `NO_EJECUTABLES*` de `I` | `banco de Core`, u otro si se prueba fuera | `no ejecutable` en el banco (motivo en la nota); fuera, cualquiera |
| está en `FUERA_DEL_BANCO` de `I` | `VM` | cualquiera |
| es `sv_*` o `fs_*` | `VM` | cualquiera |
| no está en ningún inventario y es `ha_*` | `banco de Core` | `pendiente` |
| tiene `ok` con `banco de Core` | — | tiene que estar en algún `PROBADAS*` |

Estado inicial esperado (con la 028 integrada): 46 `ok` y 1 `falla`
(`ha_reload_counters`) de la 010; 53 `ok` (o lo que diga su inventario) de la
028; 24 `VM`/`pendiente`. Sin la 028: esas 53, `banco de Core`/`pendiente`.

## Inventarios del banco (solo lectura)

| Módulo | Constantes que cuentan | Sub-feature |
|---|---|---|
| `tests/banco/cobertura.py` | `PROBADAS_EN_BANCO`, `NO_EJECUTABLES`, `FALLAN_EN_BANCO` | 010 |
| `tests/banco/cobertura_escrituras.py` | `PROBADAS_028`, `NO_EJECUTABLES_028`, `FUERA_DEL_BANCO` | 028 (si está integrada) |
| `tests/banco/cobertura_<NNN>.py` | `PROBADAS_<NNN>`, `NO_EJECUTABLES_<NNN>`, `FALLAN_<NNN>` | siguientes |

Se ignoran por nombre: `DOMINIOS_*`, `MODULOS_*`, `XFAIL_*`, `PENDIENTES_*`.
Un nombre en mayúsculas que empiece por `PROBADAS`, `FALLAN`,
`NO_EJECUTABLES` o sea `FUERA_DEL_BANCO` y no sea `frozenset`/`set` (probadas)
o `dict` (el resto) hace caer el test: la convención no admite ambigüedad.

## Patrones de acceso del Supervisor 2026.11.0 (constantes del test)

Copiados de `supervisor/api/middleware/security.py` (`_V1_PATTERNS`), con
`RE_SLUG = r"[-_.A-Za-z0-9]+"` de `supervisor/apps/const.py`:

- `API_BYPASS`: `/addons/self/(?!security|update)[^/]+`,
  `/addons/self/options/config`, `/info`, `/services.*`, `/discovery.*`,
  `/auth`.
- `ROL_MANAGER`: el patrón completo del rol `manager`, copiado tal cual.
- `NO_SECURITY_CHECK`: `/homeassistant/api/.*`, `/homeassistant/websocket`,
  `/core/api/.*`, `/core/websocket`, `/supervisor/ping` y los demás de la
  lista (el proxy de Core).

Una ruta se acepta si casa con `NO_SECURITY_CHECK`, `API_BYPASS` o
`ROL_MANAGER` (el mismo orden que `SecurityMiddleware`).

## Rutas del Supervisor que usa Hermes

| Origen | Cómo se obtienen |
|---|---|
| `sv_request(método, ruta)` y `sv_request_text(ruta)` | `ast` sobre `hermes/src/hermes`; `JoinedStr` con huecos → `x` |
| Proxy de Core en `HAClient` | constantes del test: `/core/api/states` (muestra del REST) y `/core/api/websocket` |
| Tabla de la 011, si existe | claves de `SUPERVISOR` con categoría `read` o `confirm`; huecos `{…}` → `x` |
| Llamadas con ruta no literal | `LLAMADAS_DECLARADAS: dict[tuple[str, str], tuple[str, ...] \| str]`: (módulo, función) → las rutas posibles, o `"tabla de la 011"` para las genéricas. Hoy, una: `("hermes.tools.addons", "sv_list_addons") → ("/addons", "/store/addons")`; las rutas declaradas se comprueban como las demás. Los métodos `sv_request` y `sv_request_text` de `hermes/src/hermes/ha.py` son las definiciones, no llamadas |

`EXCEPCIONES_ADMIN: dict[str, str]` (ruta → motivo): rutas que solo pasan con
`admin`. Hoy vacía. Si se llena, el comentario de `hassio_role` y la casilla
manual las nombran.

## Procedimiento (`docs/BANCO-SUPERVISOR.md`)

Secciones obligatorias en [contracts/procedimiento.md](contracts/procedimiento.md).
