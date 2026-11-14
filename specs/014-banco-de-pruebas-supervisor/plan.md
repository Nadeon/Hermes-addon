# Plan de implementación: banco de pruebas del Supervisor (procedimiento, matriz y `hassio_role`)

**Rama**: `feat/014-banco-de-pruebas-supervisor` (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md) | **Programa**: [008](../008-cobertura-total/plan.md), sub-feature 014, ola 2, S, 1 tramo

## Resumen

Tres entregas, sin tocar el código de producto: (1) el **procedimiento**
documentado del banco del Supervisor, `docs/BANCO-SUPERVISOR.md`: VM con HAOS,
Core 2026.11.1 fijado y la versión del Supervisor anotada, instantáneas, Hermes como
add-on local, cliente MCP con TLS, tandas de pruebas y prueba de
`hassio_role: manager`; nadie lo ejecuta en este programa. (2) La **matriz
tool → entorno → resultado** en `docs/HOJA-DE-RUTA.md`, con una fila por cada
tool que modifica, atada por un test de la suite normal al registro de
producción y a los inventarios del banco; y las **casillas** de las pruebas
manuales con su entorno. (3) El **comentario de `hassio_role`** en
`hermes/config.yaml` corregido según el Supervisor 2026.11.0, con un test que
fija el rol y el texto y otro que comprueba que las rutas del Supervisor que
usa Hermes caben en `manager`.

Decisiones y alternativas en [research.md](research.md); entidades en
[data-model.md](data-model.md); contratos de la matriz y del procedimiento en
[contracts/](contracts/); validación en [quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 (tests); Markdown (documentos) · **Dependencias**:
ninguna nueva (`ast`, `re`, `importlib`, `pkgutil` de la biblioteca estándar;
PyYAML ya está en la suite) · **Almacenamiento**: ninguno · **Tests**:
`unittest.TestCase` en la suite normal, sin HA, Docker ni red · **Plataforma**:
cualquier sistema operativo.

**Restricciones**: en `hermes/` solo cambian el comentario de `hassio_role` y
`CHANGELOG.md` (FR-011); nada se ejecuta contra una VM ni contra una HA real;
sin datos personales en documentos ni tests (VIII).

**Escala**: un documento nuevo (~250 líneas), unas 140 líneas nuevas en la hoja
de ruta (la matriz), dos ficheros de test nuevos y un test más en
`tests/test_addon_manifest.py`, un comentario, una viñeta del CHANGELOG.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | No cambia ningún permiso: `hassio_role` sigue en `admin` (D-02). El procedimiento manda probar lo destructivo solo en una VM con instantánea, nunca en la instalación real, y con un add-on de prueba como objetivo. | OK |
| II. Secretos | El procedimiento manda generar una contraseña de prueba para la VM y guardarla fuera del repositorio; las notas de la matriz no admiten datos de la VM. Los tests no usan credenciales. | OK |
| III. Fail-closed | El test de la matriz cae con una tool sin fila, una fila de más, una contradicción con un inventario o una convención de inventario ambigua; el de rutas cae con una ruta fuera de `manager` no declarada o con una llamada cuya ruta no se puede leer. | OK |
| IV. Dos pasos, token atado | No cambia. El procedimiento exige comprobar en la VM que cada vista previa no cambia nada y describe el efecto exacto. | OK |
| V. Nombre y descripción | Es el motivo de FR-007: el comentario de `hassio_role` afirmaba un 403 y una dependencia de `bashio::config` que no son ciertos en 2026.11.0. La matriz no cambia ninguna tool. | OK |
| VI. Lo que no se puede probar | Los dos invariantes (matriz completa y coherente; rutas dentro de `manager`) se comprueban solos. Lo que solo se puede probar en una VM queda como casilla manual, no como afirmación. | OK |
| VII. Control negativo | Cinco controles locales (FR-010), anotados en el commit. | OK |
| VIII. Privacidad | Marcadores genéricos en el procedimiento (`haos-prueba.tailXXXX.ts.net`, `<ip-de-la-vm>`, `192.0.2.x`); diff revisado antes del commit. | OK |
| IX. Cambios mínimos | Ni tools, ni opciones, ni tabla de clasificación, ni familias, ni scripts. El docstring de `config.py` con el mismo error se anota y no se toca (código de producto, fuera de FR-017). | OK |
| X. Comentarios en español | El comentario nuevo explica por qué se mantiene `admin` y cita el fichero del Supervisor; los tests explican el porqué de cada regla. | OK |
| XI. Versionado | No sube versión (lo hizo la 009). Viñeta en «Banco de pruebas» de `## [1.2.0] — <fecha de publicación>`; esa cabecera provisional es la de FR-022 de la 008 (enmienda E-4, en la 011). | Justificada, como en la 010 |
| Flujo, puerta 5 | README y DOCS no cambian: ni opciones ni comportamiento nuevos para el usuario (FR-009). | OK |

Tras el diseño: sin cambios en la tabla.

## Diseño

### 1. Procedimiento — `docs/BANCO-SUPERVISOR.md`

Según [contracts/procedimiento.md](contracts/procedimiento.md): once secciones
`##` con nombre fijo. Comandos en bloques, con marcadores genéricos. La
sección «Tandas de pruebas» nombra cada una de las 24 `sv_*`/`fs_*` que
modifican (las de `FUERA_DEL_BANCO`) y dice qué comprobar; el test de la
matriz comprueba que toda tool con entorno «VM» aparece nombrada en el
procedimiento.

### 2. Matriz — `docs/HOJA-DE-RUTA.md`

Subsección `#### Matriz de pruebas: tool → entorno → resultado (014)`, tras
«Banco de Core: helpers (010)» (o tras la sección de la 028, si ya está),
según [contracts/matriz.md](contracts/matriz.md). Las filas se generan una vez
desde el registro y los inventarios con un fragmento de Python que no se
versiona (el test es lo que queda); luego se mantienen a mano.

### 3. Casillas manuales — misma hoja de ruta

En «Pruebas manuales pendientes en una instalación real» (el título pasa a
«Pruebas manuales pendientes»: no todas son en la instalación real): cada
casilla lleva su entorno entre paréntesis al principio (research R-5); casillas
nuevas «Matriz del Supervisor en la VM» y «Pruebas en vivo de las tools nuevas
de la 1.2.0, tras publicar»; la de `hassio_role: manager` reescrita sin
`bashio::config` y con lo que hay que comprobar; la de «las 13 tools de
escritura de la 1.1.x» remite a la matriz.

### 4. Comentario de `hassio_role` — `hermes/config.yaml`

Texto (líneas de comentario junto a `hassio_role: admin`, estilo del fichero):

```yaml
hassio_role: admin         # Se mantiene 'admin' hasta probar 'manager' en vivo
                           # (docs/HOJA-DE-RUTA.md, pruebas manuales; procedimiento
                           # en docs/BANCO-SUPERVISOR.md). En el Supervisor 2026.11.0
                           # /addons/self/options/config está en api_bypass y pasa con
                           # cualquier rol (supervisor/api/middleware/security.py), y
                           # Hermes no usa bashio::config: run.sh lee /data/options.json.
                           # Con el código del Supervisor 2026.11.0, todas las rutas que
                           # usa Hermes están permitidas para 'manager'
                           # (tests/test_rutas_supervisor_rol.py); el rol no se ha bajado
                           # porque falta probarlo en una instalación real.
```

(Convergencia, T021: la primera versión decía que el 403 «era de una versión
anterior del Supervisor», algo que no se puede comprobar con el código de
2026.11.0; el comentario dice solo lo comprobado.)

El valor no cambia. La redacción exacta puede ajustarse mientras cumpla el
test (FR-007).

### 5. Tests

- `tests/test_matriz_pruebas.py`: los de [contracts/matriz.md](contracts/matriz.md).
  Lectura de la matriz con una expresión regular por fila entre los
  marcadores; registro como en `tests/test_banco_cobertura.py` (010);
  descubrimiento de inventarios con `pkgutil.iter_modules` sobre
  `tests/banco` y `importlib.import_module` de los que empiezan por
  `cobertura`.
- `tests/test_rutas_supervisor_rol.py`: patrones copiados (data-model) con la
  cita de fichero y versión; extracción con `ast` (research R-4);
  `LLAMADAS_DECLARADAS` y `EXCEPCIONES_ADMIN`; comprobación de la tabla de la
  011 con `importlib.util.find_spec("hermes.command_table")`. Un test propio
  comprueba que los patrones copiados rechazan `/auth/list`,
  `/addons/x/security` y `/os/datadisk/wipe` (si alguien los afloja, cae).
- `tests/test_addon_manifest.py`, clase nueva `TestComentarioDelRol`: lee el
  texto de `hermes/config.yaml`, aísla el bloque de comentario de
  `hassio_role` (de esa línea hasta la siguiente clave) y comprueba FR-007.

### 6. Documentación

CHANGELOG (viñeta en «Banco de pruebas»), tabla del programa (014 →
«hecha»), «Verificado contra» (las 24 del Supervisor se prueban con
simuladores; en real, según la matriz), párrafo «Probar `hassio_role:
manager`» (el comentario ya está corregido; queda la prueba), y la matriz de
trazabilidad de la 008 (filas CAP-006, CAP-022, CAP-034, CAP-035 con los
tests nuevos).

## Dependencias con otras sub-features

- **010** (integrada): `tests/banco/cobertura.py` es el primer inventario.
- **028** (en su rama): si se integra antes, sus 53 entran como «ok» y sus
  24 de `FUERA_DEL_BANCO` como «VM»; si se integra después, el test de la
  matriz cae en la integración hasta poner sus filas al día (research R-2).
- **011** (en su rama): si está integrada, sus genéricas que modifican
  (`ha_call_ws_command`, `sv_call_api`) tienen fila (la de `sv_call_api`, en
  «VM»), y el test de rutas comprueba las entradas del Supervisor `read` y
  `confirm` de su tabla. La 014 no añade entradas a la tabla ni pasa nada a
  `dedicated`.
- **015, 019, 022, 030, 031, 032** y cualquier otra con `sv_*` nuevas: añaden
  su fila (contrato de la matriz) y su línea en «Tandas de pruebas».
- **009**: creó la entrada `## [1.2.0]` del CHANGELOG.

## Riesgos

- **Conflictos en la hoja de ruta** al integrar sub-features en paralelo: la
  matriz va en orden alfabético y entre marcadores, para que los conflictos
  sean de una línea.
- **La convención de inventarios cambia** en otra sub-feature: el test cae
  con un mensaje que nombra el módulo y la constante (fail-closed).
- **El extractor de rutas no ve una llamada nueva** escrita de otra forma
  (otro nombre de método): el test cuenta además las apariciones de
  `sv_request` en el código y cae si alguna no es una llamada que reconoce.

## Ficheros

- Nuevos: `docs/BANCO-SUPERVISOR.md`, `tests/test_matriz_pruebas.py`,
  `tests/test_rutas_supervisor_rol.py`.
- Modificados: `docs/HOJA-DE-RUTA.md`, `hermes/config.yaml` (solo el
  comentario), `hermes/CHANGELOG.md`, `tests/test_addon_manifest.py`,
  `specs/008-cobertura-total/plan.md` (matriz de trazabilidad).
