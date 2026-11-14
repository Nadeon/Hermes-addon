# Plan de implementación: 009 — correcciones pendientes y versión 1.2.0

**Rama**: `feat/009-correcciones-pendientes` (PR contra `feat/cobertura-total`; no se crea ninguna otra) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

Once arreglos pequeños y la subida de versión, sin tools nuevas. En
`security.py`, las tres expresiones cuadráticas de `redact_secrets` pasan a
lineales sin cambiar lo que redactan, y el barrido de tokens se hace como
mucho una vez por segundo. En `logging_setup.py`, la redacción de red tapa los
hosts de `external_url`/`internal_url` (que `HAClient` lee de `/api/config` al
conectar) y los nombres `ip-a-b-c-d`; la clasificación de automatizaciones deja
de escribir `entity_id`. En las tools, `sv_get_addon_logs` separa qué redactó,
`ha_get_history` añade `_response_limit`, `ha_marketplace_list_removed` gana
filtros y resumen, el Marketplace y `sv_get_resolution` escriben `*_ok`, y
`sv_update_addon` rechaza actualizar a Hermes antes de pedir nada. El apagado
deja de escribir la traza de la cancelación. La versión pasa a 1.2.0 y se abre
su entrada del CHANGELOG con las secciones del programa.

Detalle y alternativas en [research.md](research.md); estado nuevo en
[data-model.md](data-model.md); formas de respuesta y eventos en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` 2.x, aiohttp, structlog, uvicorn 0.54, pydantic 2 · **Almacenamiento**: `/data/pending_confirmations` (sin cambios de formato) · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP`, simuladores de HA y del Supervisor de cada fichero, `structlog.testing.capture_logs` y captura del `logging` estándar · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: lo que se redacta no puede ser menos que en la 1.1.2 (II); el tope de 16 MiB de la 007 no se puede pasar (III); argumentos nuevos opcionales con el comportamiento de la 1.1.2 por defecto (FR-020 de la 008); cambios mínimos (IX).

**Escala**: `security.py`, `logging_setup.py`, `ha.py`, `__main__.py`,
`tools/{ha,addons,history,marketplace,resolution,guide}.py`; unos 10 ficheros
de tests; 0 tools nuevas; versión y documentación.

**Línea base**: 1925 passed, 16 skipped, 6 failed (los 6 conocidos de
Windows) sobre `d75af3f`.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | La redacción lineal cierra un bloqueo del bucle de eventos provocable por un cliente autenticado; ninguna respuesta nueva sale sin pasar por el tope (`_response_limit` medido dentro de `response_max_bytes`) ni sin marcar el texto de terceros (`removal_type`). | OK |
| II. Secretos | Lo que se redacta no disminuye: test diferencial contra la 1.1.2 (FR-001) y S-01 (si difiere, solo redactando más). Ningún evento nuevo lleva valores: `*_ok` solo contadores; `ha_url_redaction_unavailable` sin URLs. | OK |
| III. Fail-closed | El total de documentos guardados solo puede sobrestimarse (R-6); `installed_only` con la lista ilegible devuelve error, no la lista sin filtrar; `sv_update_addon` sobre Hermes se niega antes de llamar. **Matiz**: si `/api/config` no se puede leer, la conexión con HA sigue sin tapar esos dos hosts: bloquear el servicio entero por la privacidad de dos nombres en el log sería desproporcionado, el resto de la redacción sigue activa y el fallo queda avisado (R-2). | OK, justificado |
| IV. Dos pasos, token atado | No cambia: el barrido es interno y no toca el hash ni el estado; `sv_update_addon` sobre Hermes ni emite ni gasta tokens. | OK |
| V. Nombre y descripción | Docstrings de `sv_get_addon_logs`, `sv_update_addon`, `ha_marketplace_list_removed` y `ha_get_history`, y el tema del Marketplace de la guía, cambian en el mismo commit que el comportamiento; anotaciones sin cambios (las comprueba `test_hints_did_not_change`). | OK |
| VI. Lo que no se puede probar | Cada FR con test; el traceback se reproduce con un uvicorn real en loopback antes de arreglarlo (R-7); el test de tiempo tiene la referencia en el CI de Linux. | OK |
| VII. Control negativo | Una tarea de control negativo por historia, con recuento anotado en el test o el commit. | OK |
| VIII. Privacidad | Centinelas genéricos (`casa.example.org`, `ha.lan.example`, `192.0.2.x`, `10.0.0.5`, `automation.ficticia`, `<slug>`); revisión del diff antes de cada commit de tramo. | OK |
| IX. Cambios mínimos | Solo lo que piden FR-025…FR-035 y FR-022 de la 008; fuera de alcance anotado en la spec (otras redacciones, otras formas de host, `_es_hermes`, CAP-023). | OK |
| X. Comentarios en español | Cada guarda nueva explica el porqué (forma adversaria medida, por qué sobrestimar, por qué no bloquear la conexión, por qué no tapar `homeassistant`). | OK |
| XI. Versionado | 1.2.0 en los tres sitios. **Desviación**: la cabecera lleva `<fecha de publicación>` y no `AAAA-MM-DD`, por decisión del mantenedor en la 008 (FR-022) mientras la versión se desarrolla en la rama del programa; la fecha la pone el cierre y nunca llega a `main` sin ella. Es la enmienda E-4 propuesta en la 008, que se decide en la 011. | Desviación justificada |
| Flujo, puertas 3–5 | Suite completa antes de cada commit de tramo, control negativo, revisión de privacidad; documentación en el mismo cambio (FR-013). Subir la versión es decisión del mantenedor, ya tomada en la 008. | OK |

Tras el diseño: sin cambios en la tabla.

## Diseño

1. **`security.py`** (FR-001, FR-009)
   - `_JWT_RE`, `_BASIC_AUTH_URL_RE`, `_JSON_SECRET_RE`: reescritura lineal
     equivalente (R-1). Las otras dos no se tocan.
   - `_en_uso_bytes: int`, `_ultimo_barrido: float | None`
     (`time.monotonic()`); `_BARRIDO_MIN_INTERVALO_S = 1.0`. `_barrer_caducados`
     fija ambos al terminar; `create_confirmation_token` barre solo si toca y
     suma lo guardado. Sin `await` entre leer y escribir el total.
2. **`logging_setup.py`** (FR-002, FR-004, FR-005)
   - `_net_state` pasa de 3 a 4 elementos: `(enabled, host_re, ha_hosts,
     salt)`, donde `ha_hosts` es una tupla de `(patrón, marcador)`
     ([data-model.md](data-model.md)).
     `configure_network_redaction` conserva su firma y deja `ha_hosts`
     vacío; `set_ha_url_hosts(external_host, internal_host)` lo rellena sin
     cambiar la sal ni lo demás.
   - `_IP_DASHED_RE` y su paso en `redact_network`, tras IPv4, reutilizando
     `_replace_ip`.
   - `network_redaction_enabled() -> bool`.
3. **`ha.py`** (FR-002): `_aprender_urls_de_ha()` en `_connect_and_watch`
   tras `_authenticate_ws()` y antes de `ha_ws_connected`; usa
   `_request_json("GET", "/config")`; extrae hosts con `urlsplit`; filtra IPs y
   los nombres por defecto; llama a `set_ha_url_hosts`; captura cualquier
   `Exception` (no `CancelledError`) → aviso sin valores: un fallo aquí no
   puede tumbar la conexión, y aiohttp lanza más tipos que `HAConnectionError`.
   El test de orden existente (`auth` → `suscribir` → `snapshot`, en
   `tests/test_security_regressions.py`) tiene que seguir pasando sin tocarlo.
4. **`tools/ha.py`** (FR-003): `auto_classify_restricted` → `count`,
   `new_count`; `auto_classify_on_save` → `restricted=True` y `count=1`, sin
   `entity_id`.
5. **`tools/addons.py`** (FR-005, FR-010)
   - `sv_get_addon_logs`: `secrets_redacted`, `network_redacted`; evento con
     los tres; docstring.
   - `sv_update_addon`: al principio, tras `_bad_slug`, si `_es_hermes(slug)`
     → `self_update_not_supported`; docstring.
6. **`tools/history.py`** (FR-006): `_envolver(working, truncated, total)`
   añade `_response_limit` cuando `truncated`; `_truncate_to_bytes` mide con
   el bloque; `total` = estados que HA devolvió antes de cualquier corte.
7. **`tools/marketplace.py`** (FR-007, FR-008)
   - `_list_flagged(..., installed_only=False, limit=None, resumen=False)`;
     `list_removed(ha_client, installed_only=False, limit=None, max_bytes=None)`;
     tool con los dos argumentos y validación.
   - `_trim` de `removal_type`; `_third_party(["reason", "removal_type"])` solo
     en `list_removed`.
   - `<tool>_ok` en cada `ha_marketplace_*` registrada, solo si la respuesta
     no trae `error`.
8. **`tools/resolution.py`** (FR-008): `sv_get_resolution_ok` con los cinco
   recuentos.
9. **`tools/guide.py`** (FR-013): línea de `ha_marketplace_list_removed` con
   `installed_only`, `limit` y `by_removal_type`.
10. **`__main__.py`** (FR-011): filtro `_CancelacionSinTraza` instalado en
    `uvicorn.error` al configurar el log; `except (KeyboardInterrupt,
    asyncio.CancelledError)` en `main()`; esperar `server_task` tras
    cancelarla.
11. **Versión y documentación** (FR-012, FR-013): `hermes/config.yaml`,
    `__init__.py`, `config.py`; `hermes/CHANGELOG.md`; README ×2, `DOCS.md`,
    `SECURITY.md`; `docs/HOJA-DE-RUTA.md`; matriz y T002 de la 008.

## Tramos de implementación

Dos tramos, como fija la 008 («(a) redacción y log; (b) tools y apagado»).
Cada uno lo hace un agente nuevo, deja la suite en verde (en Windows, solo los
6 conocidos) y se commitea por separado. El tramo B empieza sobre el commit del
A.

| Tramo | Tareas | Cubre | Ficheros de código |
|---|---|---|---|
| A — redacción, log, tokens y versión | T001–T020 | FR-001, FR-002, FR-003, FR-004, FR-009, FR-012; su parte de FR-013 y FR-014 | `security.py`, `logging_setup.py`, `ha.py`, `tools/ha.py`, `config.py`, `__init__.py`, `config.yaml` |
| B — tools, apagado y cierre | T021–T042 | FR-005, FR-006, FR-007, FR-008, FR-010, FR-011; su parte de FR-013 y FR-014 | `tools/addons.py`, `tools/history.py`, `tools/marketplace.py`, `tools/resolution.py`, `tools/guide.py`, `__main__.py` |

El tramo A va primero porque la versión y el esqueleto del CHANGELOG son de
los que dependen todas las sub-features, y porque `network_redaction_enabled()`
(T013, tramo A) la usa `sv_get_addon_logs` (tramo B).

## Riesgos

- **Equivalencia de la redacción**: un escáner lineal escrito a mano puede
  diferir en un borde. Mitigado con el test diferencial y la regla S-01 (si
  difiere, solo redactando más, y anotado).
- **Test de tiempo frágil**: umbral de 1 s para algo que debe tardar decenas
  de ms; si el runner es muy lento, se mide la razón entre 256 KiB y 1 MiB
  (≤ 8, lineal ≈ 4, cuadrático ≈ 16) en vez del tiempo absoluto, y se anota.
- **El traceback real es otro**: R-7 lo prevé; la prueba manual tras publicar
  lo confirma.
- **`/api/config` lento al conectar**: retrasa la conexión; se usa el mismo
  tiempo máximo que `/api/states` (30 s) y el fallo no bloquea.

## Ficheros

- Código: `hermes/src/hermes/{security,logging_setup,ha,__main__,config,__init__}.py`,
  `hermes/src/hermes/tools/{ha,addons,history,marketplace,resolution,guide}.py`,
  `hermes/config.yaml`.
- Tests: `tests/test_redact_secrets.py` (lineal y diferencial),
  `tests/test_log_redact_network.py` (hosts de HA, `ip-a-b-c-d`,
  `network_redaction_enabled`), `tests/test_ha_ws_reliability.py` (lectura de
  `/api/config` al conectar y al reconectar), `tests/test_call_service_security.py`
  (clasificación sin `entity_id`), `tests/test_security.py` (barrido),
  `tests/test_tools_supervisor.py` (`sv_get_addon_logs`, `sv_update_addon`),
  `tests/test_tools_history_logbook.py` y `tests/test_response_limit.py`
  (`_response_limit` de `ha_get_history`), `tests/test_tools_marketplace.py`,
  `tests/test_tools_resolution.py`, `tests/test_tools_registration.py`
  (esquema de `ha_marketplace_list_removed`), `tests/test_tools_guide.py`,
  `tests/test_boot_shutdown_diagnostics.py` (apagado),
  `tests/test_addon_manifest.py` (CHANGELOG).
- Docs: `hermes/CHANGELOG.md`, `README.md`, `README.es.md`, `hermes/DOCS.md`,
  `SECURITY.md`, `docs/HOJA-DE-RUTA.md`, `specs/008-cobertura-total/plan.md`,
  `specs/008-cobertura-total/tasks.md`.
