# Plan de implementación: pruebas de las escrituras de Core en el banco

**Rama**: `feat/028-pruebas-escrituras-core` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 028, ola 1

## Resumen

La 010 dejó un banco en el CI con HA Core 2026.11.1 real, un Supervisor
simulado y un lector independiente, y ejecutó en él las 47 tools de helpers.
La 028 ejecuta ahí las **53** tools `ha_*` que modifican y quedan:
automatizaciones, scripts, escenas, servicios, eventos, esperas y Lovelace
(tramo A, 26), y áreas, plantas, etiquetas, categorías, dispositivos,
entidades, reparaciones, config entries y flujos (tramo B, 27). Para tener
dispositivos, avisos de reparación y flujos sin hardware ni internet usa dos
integraciones de Core: `kitchen_sink` y `uptime`. Un invariante de la suite
normal garantiza que **las 124** tools que modifican están probadas en el banco
o fuera de él con un motivo (24: `fs_*` y `sv_*`). Un fallo contra HA real es
`xfail` estricto y hallazgo para el supervisor. Sin cambios en el código de
producto, salvo un arreglo trivial.

Decisiones en [research.md](research.md); listas y comprobaciones en
[data-model.md](data-model.md); contrato del inventario en
[contracts/inventario-de-escrituras.md](contracts/inventario-de-escrituras.md);
validación en [quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 (job del banco); suite normal en 3.12 y 3.13 · **Dependencias**: ninguna nueva (las del banco de la 010) · **Almacenamiento**: ninguno nuevo; lo que se crea en HA vive lo que dura el job · **Tests**: `unittest.IsolatedAsyncioTestCase` con la base de `tests/banco/base_helpers.py`, cliente MCP en memoria, lector independiente · **Plataforma**: job `banco de Core` (GitHub Actions, `ubuntu-latest`); en local, los tests del banco se saltan.

**Restricciones**: el código de producto no cambia salvo arreglo trivial (FR-006); no se tocan los ficheros de la 010 salvo `lector.py` (métodos nuevos) y la configuración de HA (dominios nuevos); ningún servicio que reinicie o pare HA (FR-008); el contenedor sigue sin internet (FR-005).

**Escala**: 6 ficheros de test del banco, 1 inventario, 1 test nuevo de la suite normal (y tests del lector añadidos a uno existente), 3 YAML nuevos de HA, 3 documentos.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | No añade ninguna vía a producción. El banco ejercita las guardas reales: la denylist de `ha_call_service` (vista previa sin efecto, `input_boolean.reload`), las confirmaciones de borrados y de recursos Lovelace. No se llama a nada que reinicie o pare HA. | OK |
| II. Secretos | Ninguna credencial nueva. Las de la 010 siguen solo en memoria; los tests nuevos no imprimen tokens ni respuestas con ellos. | OK |
| III. Fail-closed | Un salto en el job sigue siendo un fallo (010). Un fallo contra HA real no se salta: `xfail` **estricto**, que pone el CI en rojo si deja de fallar (FR-007). El invariante falla si una tool que modifica no está clasificada (FR-003). | OK |
| IV. Dos pasos, token atado | Las tools con token se ejecutan en sus dos pasos contra HA real y se comprueba que la vista previa no cambia nada (FR-001). La confirmación no cambia. | OK |
| V. Nombre y descripción | No cambia ninguna tool. El banco es la comprobación contra HA real de que las 53 hacen lo que dice su descripción; si no, queda a la vista como hallazgo. | OK |
| VI. Lo que no se puede probar | Es el objetivo: 100 de las 100 `ha_*` que modifican quedan ejecutadas contra la versión que se despliega (47 en la 010, 53 aquí); lo que no se puede ejecutar ahí tiene motivo escrito y vigilado por un test (FR-003, FR-004). | OK |
| VII. Control negativo | Locales para el invariante (FR-009: quitar una probada, meter una `ha_*` fuera del banco, vaciar un motivo) y para el lector; uno de CI por tramo (research R-12), anotados en el commit del tramo. Un arreglo trivial, con su control negativo local. | OK |
| VIII. Privacidad | Datos genéricos (`banco_<x>_<hex>`, `banco-<hex>`, rutas `/local/…`), integraciones de demostración de Core; diff revisado antes de cada commit (FR-011). | OK |
| IX. Cambios mínimos | Solo lo de la 028: no rehace nada de la 010 (inventario propio, lector solo ampliado), no arregla fallos no triviales (hallazgo), no reparte el job (FR-012). Lo de fuera de alcance se anota para el supervisor. | OK |
| X. Comentarios en español | Cada test, el inventario y la configuración de HA explican el porqué (por qué `kitchen_sink`, por qué ese servicio de la denylist, por qué esa comprobación). | OK |
| XI. Versionado | No sube versión (009). Completa la sección «Banco de pruebas» de `## [1.2.0] — <fecha de publicación>`. La cabecera provisional es la desviación transitoria ya justificada en la 010 (FR-022 de la 008, enmienda E-4 en la 011). | Justificada, depende de 011 (E-4) |
| VII y flujo, puerta 3 («la suite completa debe pasar antes de cada commit que se vaya a publicar») | **Desviación acotada**: el control negativo de CI (research R-12) exige empujar a propósito un commit que pone el banco en rojo, porque el banco solo corre en el CI. Se limita así: preferentemente en una **rama desechable** que nunca se fusiona y se borra al ver el rojo; solo si el encargo del tramo no permite empujar otras ramas, un commit de control en la rama de la sub-feature revertido en el commit siguiente (como la 010, T021). En ningún caso queda en la punta de la rama ni en un PR; su único cambio es el sabotaje anotado en el mensaje. | Justificada |
| Flujo, puerta 4 | El job `banco de Core` es de la 010 y su inclusión en la constitución es la enmienda E-3 (011); aquí solo se le añaden tests. Mientras tanto, falla en rojo y bloquea en la práctica. | Justificada, depende de 011 (E-3) |

Tras el diseño: sin cambios en la tabla.

## Diseño

### 1. Configuración de HA del banco

Según research R-3 y [data-model.md](data-model.md): tramo A añade
`automation:`, `script:`, `scene:` (con `!include` y sus tres YAML vacíos) y
`frontend:`; tramo B añade `kitchen_sink:`. Un comentario por bloque con el
porqué. Ninguno sale a internet; el paso de comprobación de red del job de la
010 sigue igual.

### 2. Lector — `tests/banco/lector.py`

Dos métodos públicos nuevos (research R-10): `comando(mensaje)` y
`rest(metodo, ruta, cuerpo=None)`. Tests en la suite normal, junto a los del
lector de la 010 en `tests/test_banco_entorno.py`, contra el doble de Core (`tests/banco/core_doble.py`): `comando` de un tipo cualquiera
hace ida y vuelta por el eco; `rest` con `GET`/`POST`/`DELETE` llega al eco con
el token de Core. Si el doble no tiene lo necesario, se le añade lo mínimo.

### 3. Inventario — `tests/banco/cobertura_escrituras.py` y su test

Según el [contrato](contracts/inventario-de-escrituras.md). El tramo A lo crea
con `PROBADAS_028` (26), `NO_EJECUTABLES_028` (vacío), `FUERA_DEL_BANCO` (24) y
`PENDIENTES_TRAMO_B` (27). El tramo B pasa las 27 a `PROBADAS_028` y borra
`PENDIENTES_TRAMO_B` del módulo y del test.

### 4. Tests del banco — `tests/banco/test_banco_escrituras_*.py`

Una sesión por test con la base de la 010 (`tests/banco/base_helpers.py`:
lector + Hermes conectado, limpieza al cerrar). Si la base no basta (por
ejemplo, para limpiar con REST), se añade un módulo propio
`tests/banco/base_escrituras.py` que la extiende sin modificarla.

| Fichero | Tramo | Tools | Contenido |
|---|---|---|---|
| `test_banco_escrituras_automatizacion.py` | A | 15 | clase por dominio (automation, script, scene): crear en dos pasos, editar (reemplazo), ejecutar o activar sobre un `input_boolean` del lector, recargar (servicio visto una vez), borrar |
| `test_banco_escrituras_servicios.py` | A | 4 | `ha_call_service` directo y en dos pasos, `ha_call_service_response`, `ha_fire_event`, `ha_cancel_wait` |
| `test_banco_escrituras_lovelace.py` | A | 7 | dashboard (crear, metadatos con token, guardar, borrar) y recurso (crear, editar, borrar) |
| `test_banco_escrituras_registros.py` | B | 12 | área, planta, etiqueta y categoría: crear, editar en dos pasos, borrar en dos pasos |
| `test_banco_escrituras_dispositivos.py` | B | 6 | dispositivo (editar y restaurar, dos borrados sobre dispositivos distintos de `kitchen_sink`), entidad (renombrar `entity_id`, quitar del registro) y reparación (ignorar y restaurar) |
| `test_banco_escrituras_integraciones.py` | B | 9 | ciclo de `uptime` (flujo abortado, flujo completado, recarga, deshabilitar, habilitar, borrar) y flujo de opciones de `kitchen_sink` |

Comprobación de cada tool: la columna «Efecto comprobado por el lector» de
[data-model.md](data-model.md).

### 5. Fallos contra HA real

Research R-6: `xfail` estricto con `raises` y `reason`, comentario
`HALLAZGO`, la tool sigue en `PROBADAS_028`, nota en «Notas del tramo» de
`tasks.md` y en el informe. Arreglo trivial: test unitario en `tests/` (debe
fallar sin el arreglo), arreglo, control negativo anotado, línea en
«Correcciones» del CHANGELOG, y el test del banco sin marca.

### 6. Documentación

- `hermes/CHANGELOG.md`: en la sección «Banco de pruebas» de `## [1.2.0]`, las
  escrituras de Core ejecutadas en el banco por grupos y los hallazgos (tramo A
  su parte; tramo B el resto).
- `docs/HOJA-DE-RUTA.md`: fila 028 → «en curso (tramo A)» y luego «hecha»; la
  lista de las 53 tools ejecutadas en el banco, la de fuera del banco con su
  motivo y los hallazgos; la frase de la cabecera sobre las 124 tools al día.
- `specs/008-cobertura-total/plan.md`: en la matriz, fila CAP-034, columna de
  test con `tests/banco/test_banco_escrituras_*.py` y
  `tests/test_banco_cobertura_escrituras.py` (tramo B).

## Código de producto

Ninguno previsto. Revisado contra el código (research R-9): las 53 tools
hablan con Core por la WebSocket y por REST `GET`/`POST`/`DELETE`, que el
simulado de la 010 ya reenvía. Si una falla contra HA real, se sigue §5: solo
un arreglo trivial entra aquí.

## Tratamiento de los fallos contra HA real

| Situación | Qué se hace |
|---|---|
| La tool falla y el arreglo es trivial | Se arregla con test unitario, control negativo y CHANGELOG; el test del banco pasa |
| La tool falla y el arreglo no es trivial | `xfail` estricto + `HALLAZGO` + nota en `tasks.md` + informe; no se toca el producto |
| Una integración de apoyo (`kitchen_sink`, `uptime`) no carga en el banco | Las tools que dependen de ella pasan a `NO_EJECUTABLES_028` con el motivo concreto (qué impide cargarla) y se avisa al supervisor para buscar otra integración (S-02) |
| La integración de apoyo carga pero la tool falla | Como cualquier tool: `xfail` estricto y hallazgo, o arreglo trivial |
| Falla la infraestructura de la 010 (simulado, lector) | Se corrige en `tests/banco/` con su test de contrato si es una ruta que falta (R-9); si es otra cosa, se para y se avisa |

## Tramos

Cada tramo lo hace un agente nuevo: deja la suite local con exactamente los 6
fallos conocidos de Windows, el CI de la rama en verde (`gh run watch`) y
termina en su propio commit con los recuentos de los controles negativos.

- **Tramo A — automatización, ejecución, eventos y Lovelace** (T001–T016):
  configuración de HA (`automation`, `script`, `scene`, `frontend`), lector
  ampliado, inventario e invariante (con `PENDIENTES_TRAMO_B`), 26 tools en el
  banco, control negativo de CI y documentación parcial.
- **Tramo B — registros, integraciones y reparaciones** (T017–T029):
  `kitchen_sink`, 27 tools en el banco, inventario cerrado (sin pendientes),
  control negativo de CI, documentación final y cierre.

## Dependencias con otras sub-features

- **010**: base. Su tramo B (helpers) va en otra rama: la 028 no toca
  `tests/banco/cobertura.py`, `test_banco_cobertura.py`, `base_helpers.py` ni
  los `test_banco_helpers_*.py`. Si al integrar el lector o la configuración
  de HA chocan, se fusionan las dos ampliaciones.
- **011**: añade genéricas que modifican (`ha_call_ws_command`,
  `sv_call_api`): al integrar, la segunda en llegar suma su lista al
  invariante (contrato, «Regla para las sub-features siguientes»).
- **014**: toma de aquí la lista de las tools ejecutadas en el banco y la de
  fuera del banco para su matriz tool → entorno.
- **009**: entrada `## [1.2.0]` del CHANGELOG; posible conflicto trivial.

## Riesgos

- **`kitchen_sink` no carga** sin internet o por una dependencia: T017 lo
  comprueba lo primero; plan B en la tabla de fallos.
- **Interferencias entre tests** por recursos compartidos: reglas de
  data-model («Recursos compartidos») y comprobaciones justo después de cada
  acción.
- **El job se alarga**: 53 tests más de pocos segundos cada uno; si pasa de 10
  minutos, se anota (FR-012).
- **Hallazgos en cadena** (varias tools fallan): cada una con su `xfail`; si
  son muchas o apuntan a algo de fondo, se avisa al supervisor antes de seguir.

## Ficheros

- Nuevos: `tests/banco/cobertura_escrituras.py`,
  `tests/test_banco_cobertura_escrituras.py`,
  `tests/banco/test_banco_escrituras_automatizacion.py`,
  `tests/banco/test_banco_escrituras_servicios.py`,
  `tests/banco/test_banco_escrituras_lovelace.py`,
  `tests/banco/test_banco_escrituras_registros.py`,
  `tests/banco/test_banco_escrituras_dispositivos.py`,
  `tests/banco/test_banco_escrituras_integraciones.py`,
  `tests/banco/ha_config/automations.yaml`, `tests/banco/ha_config/scripts.yaml`,
  `tests/banco/ha_config/scenes.yaml`; opcional `tests/banco/base_escrituras.py`.
- Modificados: `tests/banco/ha_config/configuration.yaml`,
  `tests/banco/lector.py`, `tests/test_banco_entorno.py` (tests del lector), `hermes/CHANGELOG.md`, `docs/HOJA-DE-RUTA.md`,
  `specs/008-cobertura-total/plan.md`; si hiciera falta,
  `tests/banco/core_doble.py`.
- Sin tocar: `hermes/src/` (salvo arreglo trivial), `.github/workflows/`,
  `README*.md`, `hermes/DOCS.md`, el inventario y los tests de helpers de la
  010.
