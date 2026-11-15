# Plan de implementación: host y red del host (032)

**Rama**: `feat/032-host-y-red-del-host` (sale de `feat/cobertura-total`, `0b7d5e2`) | **Fecha**: 2026-11-15 | **Spec**: [spec.md](spec.md)

**Entrada**: [spec.md](spec.md), la paraguas
[`specs/008-cobertura-total`](../008-cobertura-total/plan.md) (CAP-086,
CAP-090, FR-081, FR-082) y el código del Supervisor 2026.11.0.

## Resumen

Siete tools dedicadas en dos familias nuevas. `host_control`: apagar el host,
cambiar el hostname, la swap y la ranura de arranque, todas en dos pasos con
el antes y el después y avisos explícitos (nadie enciende el host a
distancia; la ranura reinicia ya en otro OS). `host_network`: recargar la red
(sin token: solo relee), editar una interfaz y crear una VLAN, en dos pasos,
con el antes y el después, un aviso fuerte de pérdida de acceso, la PSK que
entra y nunca sale, y el **rechazo fail-closed** de la interfaz principal o la
única conectada. Las siete rutas pasan de `deny` «spec 032» a `dedicated`.
Todo se prueba con el Supervisor simulado y queda en la matriz de la 014 como
VM / pendiente. Dos tramos.

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp,
structlog (ninguna nueva; `ipaddress` de la biblioteca estándar para validar
direcciones) · **Almacenamiento**: ninguno nuevo; el fichero del token de
siempre, solo con el `action_hash` (HMAC de la 019) y la huella del estado ·
**Tests**: pytest con `unittest.IsolatedAsyncioTestCase`, `DummyMCP`,
`MockHAClient` como Supervisor simulado (método, ruta y `json_body` por
llamada; respuestas por método y ruta; `HAConnectionError` con `status`),
`structlog.testing.capture_logs`, `CONFIRMATIONS_DIR` temporal de
`tests/conftest.py` · **Plataforma**: add-on de Home Assistant OS · **Tipo**:
servidor MCP · **Rendimiento**: una a tres lecturas del Supervisor por vista
previa · **Restricciones**: fail-closed, dos pasos con token atado a
argumentos y estado, anotaciones verdaderas, PSK fuera de todo retorno, log y
disco, repositorio público · **Escala**: 7 tools nuevas (la 008 estimaba ~7),
7 entradas de la tabla, 2 familias, 1 tema de guía.

Sin incógnitas abiertas: decisiones en [research.md](research.md) (R-1…R-12).

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Guarda de la interfaz de acceso antes de la vista previa y antes de enviar (FR-007); bloques validados enteros porque el Supervisor los reemplaza (FR-008); `force` no expuesto (R-5); las genéricas rechazan las 7 rutas hacia su tool (FR-014). | OK |
| II. Secretos | PSK nunca en vista previa, respuesta, error, log ni fichero del token (sin `omitibles`); el hash es HMAC con clave en memoria (019, requisito del tramo 2, R-9); marcador de redacción y caracteres de control rechazados; centinelas en todos los caminos (FR-010, SC-003). | OK |
| III. Fail-closed | Principal desconocida o lectura fallida → rechazo (FR-007); forma inesperada → `error`, nunca vista previa inventada; `no_change`, `slot_unusable`, `insufficient_disk`, `vlan_exists` sin token; corte tras enviar → `outcome: "unknown"`, no «ok» (FR-013). | OK |
| IV. Dos pasos, token atado | Seis tools con token que ata todos los argumentos y la huella del estado de la vista previa (FR-011, `estado=` de la 018); inventario de la 033. Vistas previas con antes → después y avisos que no mienten. `sv_reload_network` sin token porque no cambia nada (R-3). | OK (desviación razonada, D-032-1) |
| V. Nombre y descripción | Seis destructivas ⇔ seis con token; `sv_reload_network` no destructiva e idempotente; descripciones que dicen que se reemplazan los bloques, que la principal se rechaza, que no hay `force` y que nadie enciende el host a distancia (FR-016). | OK |
| VI. Lo que no se puede probar | Unitarios contra el Supervisor simulado con formas sacadas del código de 2026.11.0; el banco de Core no aplica. Las 7 en la matriz como **VM / pendiente** con su línea en el procedimiento (FR-018). | OK con pendiente declarado |
| VII. Control negativo | T012 y T026 con recuentos: guarda de la principal, de la única conectada y de la desconocida, PSK en el hash guardado, huella, validación de bloques, `outcome: unknown`, `dedicated`, log sin valores. | OK |
| VIII. Privacidad | Fixtures con `192.0.2.x`, `2001:db8::`, `aa:bb:cc:dd:ee:ff`, «mi-red», `casa-ha` y centinelas; el log no lleva hostname, IP, SSID, MAC ni PSK (FR-012); revisión del diff en cada tramo. | OK |
| IX. Cambios mínimos | Dos módulos nuevos; `sv_reboot_host`, `sv_get_host_info` y las lecturas de la 013 no se tocan; nada de la v2 de red (027); borrar VLAN fuera (R-8). | OK |
| X. Comentarios en español | Comentarios con el porqué; descripciones, errores y eventos en inglés. | OK |
| XI. Versionado | Sin subida de versión; sección propia en `## [1.2.0]`. | OK |
| Flujo, puerta 4 (CI) | Cada tramo deja la suite en verde en el CI de Linux (6 fallos conocidos en local). | OK |

**Tras el diseño**: sin cambios.

## Diseño

### Tramo 1 — `host_control` (CAP-086)

- **Familia** `host_control` en `tool_families.py` («desde» 1.2.0,
  desactivable, módulo `host_control`); registro en `tools/__init__.py` bajo
  `_activa("host_control")`.
- **Módulo** `hermes/src/hermes/tools/host_control.py`:
  - `_leer(tool, ruta)`: GET con error redactado y pista de OS en 404 (mismo
    patrón que `host_system._leer`).
  - Validadores (`_validar_hostname`, `_validar_swap`, `_validar_ranura`) con
    `ArgumentoInvalido` de `tools/_logs.py`.
  - `_bytes_de_swap(texto)` para comparar con `disk_free` (GiB).
  - `_enviar(tool, ruta, carga, token, verify_with)`: `POST`, distingue el
    corte tras enviar (R-10) y completa el token.
  - Las cuatro tools con el flujo de [contracts/tools.md](contracts/tools.md).
- **Anotaciones**: las cuatro en `_DESTRUCTIVE_EXACT` con un comentario.
- **Tabla**: 4 entradas en `_DEDICADAS_INICIALES` de
  `scripts/inventario/generar_tabla.py` y en `command_table.py`; regenerar y
  comprobar que no cambia.
- **Inventario de la 033**: 4 entradas; `test_recuento` + 4.
- **Matriz de la 014**: 4 filas y sus líneas en el procedimiento.
- **Guía**: tema `host_control` (parte de host) con sus alias; índice.
- **Documentación** (parte): CHANGELOG, DOCS, README, hoja de ruta (en curso).

### Tramo 2 — `host_network` (CAP-090)

- **Requisito**: el HMAC de la 019 en `security.py` (R-9). T014 lo comprueba.
- **Familia** `host_network` (módulo `host_network`).
- **Módulo** `hermes/src/hermes/tools/host_network.py`:
  - `_leer_red()`: `GET /network/info` → `(interfaces por nombre, principal,
    conectadas)`; forma inesperada o sin principal → `primary_unknown`.
  - `_guarda(nombre, red)`: FR-007.
  - `_validar_bloque_ip(familia, valor)`, `_validar_wifi(valor)`,
    `_validar_modo_dns(valor)`: FR-008, mensajes sin valores.
  - `_interfaz_publica(i)`: forma v1 sin `mac` en la vista previa (el antes no
    la necesita) y nunca `psk`.
  - `_limpiar_error(texto, secretos)`: sustituye la PSK literal y pasa por
    `redact_secrets` (patrón de la 019).
  - Tres tools según los contratos; `create_confirmation_token` sin
    `omitibles`.
- **Anotaciones**: `sv_update_network_interface` y `sv_create_vlan` en
  `_DESTRUCTIVE_EXACT`; `sv_reload_network` sin entrada (no destructiva, no de
  solo lectura, idempotente).
- **Tabla**: 3 entradas; `grep -c "spec 032"` = 0.
- **Inventario de la 033**: 2 entradas; `test_recuento` + 2.
- **Matriz**: 3 filas.
- **Guía** completa (red) y **documentación** completa: CHANGELOG, DOCS,
  README, hoja de ruta («hecha»), filas CAP-086 y CAP-090 de la matriz de la
  008.

## Estructura de ficheros

```text
specs/032-host-y-red-del-host/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md · tasks.md
├── contracts/tools.md
└── checklists/requirements.md

hermes/src/hermes/
├── tool_families.py              # `host_control` (T002), `host_network` (T015)
├── command_table.py              # 7 entradas a `dedicated` (T008, T022)
└── tools/
    ├── __init__.py               # registro (T007, T021)
    ├── _annotations.py           # 6 en _DESTRUCTIVE_EXACT (T007, T021)
    ├── host_control.py           # NUEVO, tramo 1 (T006)
    ├── host_network.py           # NUEVO, tramo 2 (T020)
    └── guide.py                  # tema `host_control` (T011, T025)

scripts/inventario/generar_tabla.py   # _DEDICADAS_INICIALES (T008, T022)

tests/
├── fixtures/supervisor_host.py          # NUEVO (T003, T016)
├── test_tools_host_control.py           # NUEVO (T004–T005)
├── test_tools_host_network.py           # NUEVO (T017–T019)
├── test_tool_families.py · test_config_validation.py   (T002, T015)
├── test_tools_registration.py           (T007, T021)
├── test_command_table.py · test_tools_generic_commands.py · test_generar_tabla.py   (T008, T022)
├── test_confirmation_args_inventory.py  (T009, T023)
├── test_matriz_pruebas.py               # sin cambios (T010, T024)
└── test_tools_guide.py                  (T011, T025)

docs/HOJA-DE-RUTA.md · docs/BANCO-SUPERVISOR.md · hermes/CHANGELOG.md ·
hermes/DOCS.md · README.md · README.es.md · specs/008-cobertura-total/plan.md
```

## Trazabilidad (FR de la 032 → FR/CAP de la 008 → tarea → test)

| FR 032 | FR 008 | CAP | Tareas | Test |
|---|---|---|---|---|
| FR-001 | FR-081 | 086 | T004, T006 | `test_tools_host_control.py` (`TestApagar`) |
| FR-002 | FR-081 | 086 | T004, T006 | ídem (`TestHostname`) |
| FR-003 | FR-081 | 086 | T004, T006 | ídem (`TestSwap`) |
| FR-004 | FR-081 | 086 | T004, T006 | ídem (`TestRanura`) |
| FR-005 | FR-082 | 090 | T017, T020 | `test_tools_host_network.py` (`TestRecargar`) |
| FR-006 | FR-082 | 090 | T017, T020 | ídem (`TestEditarInterfaz`) |
| FR-007 | FR-082 | 090 | T018, T020 | ídem (`TestGuardaDeAcceso`) |
| FR-008 | FR-082 | 090 | T018, T020 | ídem (`TestValidacionDeBloques`) |
| FR-009 | FR-082 | 090 | T017, T020 | ídem (`TestCrearVlan`) |
| FR-010 | FR-019, FR-082 | 090 | T019, T020 | ídem (`TestPsk`) |
| FR-011 | FR-018 | 086, 090 | T005, T009, T019, T023 | `TestTokenAtado` (los dos ficheros), `test_confirmation_args_inventory.py` |
| FR-012 | FR-019 | 086, 090 | T005, T019 | `TestLog` (los dos ficheros) |
| FR-013 | FR-020 | 086, 090 | T005, T019 | `TestCorteTrasEnviar` (los dos ficheros) |
| FR-014 | FR-012 | 001, 086, 090 | T008, T022 | `test_command_table.py`, `test_tools_generic_commands.py`, `test_generar_tabla.py` |
| FR-015 | FR-010 | 004 | T002, T015 | `test_tool_families.py`, `test_config_validation.py`, `test_tools_registration.py` |
| FR-016 | FR-018 | 004 | T007, T021 | `test_tools_registration.py` |
| FR-017 | FR-011 | 008 | T011, T025 | `test_tools_guide.py` |
| FR-018 | FR-016 | 006 | T010, T024 | `test_matriz_pruebas.py` |
| FR-019 | FR-019, FR-021 | — | T003, T016 | revisión del diff y fixtures |
| FR-020 | FR-023, FR-024 | — | T013, T027 | documental |

## Tramos

Cada tramo lo hace un agente nuevo, deja la suite en verde y se commitea por
separado; el 2 necesita el 1 integrado y la 019 en la rama.

| Tramo | Contenido | Tareas |
|---|---|---|
| 1 | Línea base, familia `host_control`, fixtures de host y OS, 4 tools con token atado al estado, anotaciones, 4 `dedicated`, inventario de la 033, matriz y procedimiento (4), guía (host), documentación (parte), control negativo | T001–T013 |
| 2 | Requisito HMAC, familia `host_network`, fixtures de red, 3 tools con la guarda de acceso y la PSK, anotaciones, 3 `dedicated`, inventario, matriz (3), guía completa, documentación completa y filas de la 008, control negativo | T014–T027 |

## Pruebas en vivo (pendiente declarado)

En la VM de la 014 con instantánea antes de cada una: hostname (y volver),
swap (HAOS ≥ 15), ranura de arranque (y volver), apagar (encender a mano). Red:
VM con una segunda interfaz (otra tarjeta virtual) para editarla y crear una
VLAN; comprobar que la principal se rechaza y que la PSK no aparece en
`ha network info` ni en el log de Hermes.

## Dependencias

- 011, 013, 014 y 033: integradas en la base.
- 019: HMAC del `action_hash`, requisito del tramo 2 (R-9).
- 022: no se pisa (control de Core y Supervisor; `sv_reboot_host` no cambia).
- 027: la API v2 de red no entra.

## Riesgos

- **Recuentos** (tabla, inventario de la 033, familias en DOCS y README):
  otras sub-features los suben a la vez; se resuelven al integrar.
- **Forma real del Supervisor**: las respuestas simuladas salen del código; la
  VM puede enseñar matices (por ejemplo, `primary` en transitorios).
- **Ruta por defecto en secundarias**: solo se avisa (R-2); un usuario puede
  confirmar un gateway que le quite el acceso. Lo dice la vista previa.
