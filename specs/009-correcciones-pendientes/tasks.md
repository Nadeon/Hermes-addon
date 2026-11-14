---

description: "Tareas de la sub-feature 009 (correcciones pendientes y versión 1.2.0)"
---

# Tareas: 009 — correcciones pendientes y versión 1.2.0

**Entrada**: `specs/009-correcciones-pendientes/` (spec.md, plan.md,
research.md, data-model.md, contracts/tools.md, quickstart.md).

**Tests**: obligatorios y **primero** (TDD): cada historia empieza por sus
tests, que se ejecutan y se ven en **rojo** sobre el código sin arreglar antes
de implementar; después, el arreglo; y al final, el **control negativo**
(principio VII): se deshace un momento la parte del código, se comprueba que
caen los tests nuevos, se restaura y se anota el recuento en el test o en el
mensaje del commit. Estilo de los existentes: `unittest.IsolatedAsyncioTestCase`,
`DummyMCP`, simuladores de HA y del Supervisor de cada fichero,
`structlog.testing.capture_logs` y captura del `logging` estándar.
`CONFIRMATIONS_DIR` en un `tempfile.TemporaryDirectory`. Solo marcadores
genéricos (principio VIII): `casa.example.org`, `ha.lan.example`,
`192.0.2.x`, `10.0.0.5`, `automation.ficticia`, `autor/ficticio`, `<slug>`.

**Suite**: desde la raíz del worktree,
`HERMES_CONFIG_BASE=<carpeta propia> <python del .venv> -m pytest -q -p no:cacheprovider`.
En Windows fallan exactamente 6 tests conocidos (finales de línea, byte nulo,
symlinks); nada más puede fallar. La referencia final es el CI de Linux.

## Formato: `[ID] [P?] [Historia] Descripción`

- **[P]**: se puede hacer en paralelo (ficheros distintos, sin dependencias).
- **[US1]…[US6]**: historias de [spec.md](spec.md).

## Tramos

La implementación se reparte en **dos tramos**; cada uno lo hace un agente
nuevo, deja la suite en verde y termina en su propio commit (solo las rutas que
toca, añadidas por nombre).

| Tramo | Tareas | Cubre |
|---|---|---|
| **A** — redacción, log, tokens y versión | **T001–T020** | US6 (versión 1.2.0 y esqueleto del CHANGELOG, FR-012), US1 (redacción lineal, FR-001), US2 (URLs de HA, `ip-a-b-c-d` y clasificación sin `entity_id`, FR-002…FR-004), barrido de tokens de US5 (FR-009) y su documentación |
| **B** — tools, apagado y cierre | **T021–T042** | US3 (`sv_get_addon_logs`, `ha_get_history`, `ha_marketplace_list_removed`, eventos `*_ok`, FR-005…FR-008), US4 (`sv_update_addon` sobre Hermes, FR-010), apagado de US5 (FR-011), compatibilidad (FR-014) y cierre documental (FR-013) |

El tramo B empieza sobre el commit del tramo A: usa
`network_redaction_enabled()` (T012) y añade sus líneas a la entrada
`## [1.2.0]` que abre T003.

---

# TRAMO A — redacción, log, tokens y versión (T001–T020)

## Fase 1: Preparación

- [ ] T001 Línea base del tramo A: ejecutar la suite completa sobre la punta de la rama y anotar el recuento (referencia en la punta `d75af3f`: 1925 passed, 16 skipped, 6 failed conocidos de Windows)

## Fase 2: Historia 6 — Versión 1.2.0 (P1, fundacional: el resto de sub-features escribe en esta entrada)

**Objetivo**: los tres sitios dicen 1.2.0 y existe la entrada única del CHANGELOG con las ocho secciones.
**Prueba independiente**: `tests/test_addon_manifest.py` pasa con el test nuevo.

- [ ] T002 [US6] Test en `tests/test_addon_manifest.py`, clase nueva `TestEntradaDelChangelog`: (a) la primera cabecera `## [` de `hermes/CHANGELOG.md` es la de `__version__` (sin fijar la fecha: admite `AAAA-MM-DD` o `<fecha de publicación>`); (b) esa entrada contiene, en este orden, las cabeceras `### Diagnóstico`, `### Integraciones`, `### Automatización`, `### Supervisor`, `### Sistema`, `### Política y genéricas`, `### Banco de pruebas` y `### Correcciones`; (c) hay una sola cabecera de esa versión. Ejecutar: (a) cae al subir la versión sin entrada; antes de T003 está en rojo por (b) (FR-012)
- [ ] T003 [US6] Versión `1.2.0` en `hermes/config.yaml` (`version:`), `hermes/src/hermes/__init__.py` (`__version__`) y `HA_CORE_LAST_TESTED_IN_HERMES` de `hermes/src/hermes/config.py`; en `hermes/CHANGELOG.md`, encima de la 1.1.2, `## [1.2.0] — <fecha de publicación>` con una introducción de dos o tres frases (programa de cobertura total de HA 2026.11, una sola versión, compatibilidad con la 1.1.2) y las ocho secciones de T002; todas salvo «Correcciones» con la línea en cursiva «Pendiente: la añade la sub-feature que lo implemente.» (research R-9) (FR-012)
- [ ] T004 [US6] Control negativo: sin la entrada nueva cae (a) de T002; quitando una sección cae (b); dejando `__version__` en 1.1.2 cae el test de coherencia existente. Anotar recuentos

## Fase 3: Historia 1 — Redacción lineal (P1)

**Objetivo**: `redact_secrets` lineal, con la misma salida que la 1.1.2.
**Prueba independiente**: 1 MiB de cada forma adversaria < 1 s; corpus diferencial idéntico.

- [ ] T005 [US1] Tests en `tests/test_redact_secrets.py`: (a) clase `TestRedaccionLineal`, un test por forma, cada una de 1 MiB sin espacios: `a` × n, `a.` × n, `a://b:c` × n, `eyJ` × n y `"` + `password` × n; `redact_secrets` completo < 1 s con `time.perf_counter` (comentario: medido en la 1.1.2, 30 KB tardaban 0,4–0,6 s); (b) clase `TestRedaccionDiferencial`: copia literal de `_JWT_RE`, `_BASIC_AUTH_URL_RE` y `_JSON_SECRET_RE` de la 1.1.2 y de la función `redact_secrets` de la 1.1.2 como referencia, corpus de ≥ 5 000 textos de 1–80 caracteres generados con `random.Random(2026)` a partir de fragmentos (`eyJ`, `.`, `://`, `:`, `@`, `"`, `password`, `token`, `api_key`, `=`, espacio, letras, dígitos, `-`, `_`), y `assertEqual` de la salida nueva con la de referencia en todos (subtests con el texto que falla); si la implementación redacta más en algún caso, se documenta como excepción en el test con su porqué (S-01) y nunca redacta menos. Ejecutar: (a) en rojo sobre el código actual (FR-001)
- [ ] T006 [US1] `hermes/src/hermes/security.py`: reescribir `_JWT_RE`, `_BASIC_AUTH_URL_RE` y `_JSON_SECRET_RE` (o su uso en `redact_secrets`) de forma lineal y equivalente según research R-1 (búsqueda anclada en `str.find` con ventana acotada o escáner lineal); `_SECRET_KEY_RE` y `_BARE_SECRET_RE` no se tocan; comentario en español con la forma adversaria medida y por qué no valen trocear, acotar cuantificadores ni lookbehind (FR-001)
- [ ] T007 [US1] Control negativo: con las tres expresiones de la 1.1.2 caen los tests de tiempo de T005 (a); con la variante lookbehind `(?<![A-Za-z0-9_-])eyJ…` cae el diferencial (`xeyJ…` deja de redactarse). Anotar recuentos

## Fase 4: Historia 2 — El log no identifica la instalación (P1)

**Objetivo**: hosts de las URLs de HA, `ip-a-b-c-d` y `entity_id` de la clasificación fuera del log.
**Prueba independiente**: centinelas ausentes del log capturado.

- [ ] T008 [P] [US2] Tests en `tests/test_log_redact_network.py`, clase `TestIpConGuiones`: `ip-10-0-0-5.ec2.internal` → `<ip:private:…>.ec2.internal` con el mismo seudónimo que `10.0.0.5` en la misma línea; `IP-192-0-2-7` (mayúsculas); `ip-010-000-000-005` igual que `10.0.0.5`; `ip-127-0-0-1` sin cambios; `ip-999-1-1-1`, `xip-10-0-0-5`, `ip-10-0-0-55555` sin cambios; idempotente (dos pasadas = una); con la redacción desactivada, sin cambios; también por el filtro del `logging` estándar (FR-004)
- [ ] T009 [P] [US2] Tests en `tests/test_call_service_security.py`, clase `TestClasificacionSinEntityId`: con `capture_logs`, `auto_classify_dangerous` sobre un `/config` temporal con una automatización ficticia que usa `shell_command.*` registra `auto_classify_restricted` con `count` y `new_count` y sin el `entity_id` centinela en ningún campo; `classify_saved_config("automation.ficticia", …)` registra `auto_classify_on_save` con `restricted` y `count` y sin el `entity_id`; la restricción en sí sigue funcionando (la entidad queda en la lista) (FR-003)
- [ ] T010 [P] [US2] Tests en `tests/test_log_redact_network.py`, clase `TestHostsDeLasUrlsDeHA`: tras `configure_network_redaction(True, "homeassistant.tailXXXX.ts.net")` y `set_ha_url_hosts("casa.example.org", "ha.lan.example")`, `redact_network` da `<ha_external_host>` y `<ha_internal_host>` en URLs, con puerto y en mayúsculas, y no toca `subcasa.example.org.evil` ni `casa.example.organic`; un IP literal, `localhost`, `homeassistant` y `homeassistant.local` no se añaden (`homeassistant.restart` sigue igual); host igual al público → sale `<public_hostname>`; la sal no cambia (el seudónimo de una IP es el mismo antes y después de `set_ha_url_hosts`); `set_ha_url_hosts(None, None)` vacía la lista; con la redacción desactivada no se tapa nada; `network_redaction_enabled()` refleja la opción; también por el filtro del `logging` estándar (FR-002)
- [ ] T011 [US2] Tests en `tests/test_ha_ws_reliability.py`, clase `TestUrlsDeHAAlConectar` (con los dobles de `_connect_and_watch` del estilo de `tests/test_security_regressions.py`): (a) `_connect_and_watch` lee `/config` por `_request_json` después de autenticar y antes de `_connected_event.set()` y del evento `ha_ws_connected`, y llama a `set_ha_url_hosts` con los hosts de `https://casa.example.org` y `http://ha.lan.example:8123`; (b) en una segunda conexión con otras URLs, se actualizan; (c) si `_request_json` lanza (`HAConnectionError`, `aiohttp.ClientError`, `TimeoutError`) o devuelve una forma inesperada, se registra `ha_url_redaction_unavailable` con `error_type` y sin ningún trozo de URL, y la conexión sigue hasta el bucle de lectura; (d) el test de orden existente de `tests/test_security_regressions.py` pasa sin tocarlo. Ejecutar: en rojo (FR-002)
- [ ] T012 [US2] `hermes/src/hermes/logging_setup.py`: `_net_state` con `ha_hosts` (data-model); `set_ha_url_hosts(external, internal)` que filtra y construye los patrones con las fronteras del hostname público y sustituye el estado entero sin renovar la sal; `network_redaction_enabled()`; `_IP_DASHED_RE` y su paso en `redact_network` tras IPv4 reutilizando `_replace_ip` sobre `a.b.c.d`; orden: público, hosts de HA, `*.ts.net`, IPv6, IPv4, `ip-a-b-c-d`. Comentarios con el porqué (por qué no `homeassistant`, por qué misma sal) (FR-002, FR-004)
- [ ] T013 [US2] `hermes/src/hermes/ha.py`: `_aprender_urls_de_ha()` llamada en `_connect_and_watch` tras `_authenticate_ws()` y antes de `ha_ws_connected`; `urlsplit(...).hostname`; captura `Exception` (no `CancelledError`) → `ha_url_redaction_unavailable` con `error_type=type(exc).__name__`; comentario con por qué REST y no WS (el bucle de lectura aún no corre) y por qué no bloquear la conexión (research R-2) (FR-002)
- [ ] T014 [US2] `hermes/src/hermes/tools/ha.py`: `auto_classify_restricted` con `count` y `new_count`; `auto_classify_on_save` con `restricted` y `count=1`, sin `entity_id`; comentario: el log se pega en issues públicos y los `entity_id` de automatizaciones nombran la casa (FR-003)
- [ ] T015 [US2] Control negativo: sin el paso `ip-a-b-c-d` caen los de T008; con `new=new_entities` de vuelta cae T009; sin `set_ha_url_hosts` en `redact_network` caen los de T010; llamando a `_aprender_urls_de_ha` después de `ha_ws_connected` cae T011 (a); dejando que la excepción se propague cae T011 (c). Anotar recuentos

## Fase 5: Historia 5 (parte) — Barrido de tokens acotado (P3)

**Objetivo**: una vista previa con documento no relee todos los tokens cada vez; el tope sigue intacto.
**Prueba independiente**: diez vistas previas en el mismo segundo = un barrido.

- [ ] T016 [US5] Tests en `tests/test_security.py`, clase `TestBarridoAcotado` (con `time.monotonic` parcheado y un contador sobre `_barrer_caducados`): (a) diez `create_confirmation_token(..., omitibles=("config",))` en el mismo segundo → un barrido; (b) a 1,1 s, la siguiente barre y borra un token caducado; (c) con `CONFIRMATION_STORED_MAX_BYTES` pequeño y sin barrido entre medias, el documento que haría pasar del tope no se guarda (`confirmation_args_not_stored`), contando lo guardado desde el último barrido; (d) tras `complete_confirmation_token`, el total en memoria no baja hasta el siguiente barrido (sobrestima, no subestima); (e) `cleanup_expired_confirmations` fija el total y la hora; (f) si el reloj monotónico retrocede, se barre; (g) las vistas previas sin documento no barren, como hoy. Ejecutar: (a) en rojo (FR-009)
- [ ] T017 [US5] `hermes/src/hermes/security.py`: `_en_uso_bytes`, `_ultimo_barrido`, `_BARRIDO_MIN_INTERVALO_S = 1.0` según data-model; `_barrer_caducados` los fija; `create_confirmation_token` barre solo si toca y suma lo guardado; sin `await` entre leer y escribir el total; comentario con por qué sobrestimar es fail-closed (research R-6) (FR-009)
- [ ] T018 [US5] Control negativo: barriendo siempre (código de la 1.1.2) cae (a); sin sumar lo guardado a la memoria cae (c); restando en `complete` cae (d). Anotar recuentos

## Fase 6: Cierre del tramo A

- [ ] T019 [P] Documentación del tramo A: en `hermes/CHANGELOG.md`, sección «Correcciones» de la 1.2.0, viñetas de FR-001 (redacción lineal, con la cifra de 30 KB → medio segundo), FR-002, FR-003, FR-004 y FR-009; la fila de `log_redact_network` de `README.md`, `README.es.md` y `hermes/DOCS.md` y la viñeta «Network redaction» de `SECURITY.md` añaden los hosts de `external_url`/`internal_url` y los nombres `ip-a-b-c-d` (los dos README sincronizados) (FR-013)
- [ ] T020 Suite completa (solo los 6 conocidos de Windows), revisión del diff buscando datos personales (principio VIII) y commit del tramo A con las rutas por nombre y los recuentos de los controles negativos de T004, T007, T015 y T018 en el mensaje

---

# TRAMO B — tools, apagado y cierre (T021–T042)

## Fase 7: Preparación

- [ ] T021 Línea base del tramo B sobre el commit del tramo A; anotar el recuento

## Fase 8: Historia 3 — Las respuestas dicen lo que han hecho (P2)

**Objetivo**: campos nuevos de `sv_get_addon_logs`, `ha_get_history` y `ha_marketplace_list_removed`, y eventos `*_ok`, según [contracts/tools.md](contracts/tools.md).
**Prueba independiente**: con simuladores, las respuestas cumplen el contrato y, sin argumentos nuevos, contienen las de la 1.1.2.

- [ ] T022 [P] [US3] Tests en `tests/test_tools_supervisor.py`, clase `TestQueRedactoElLog`: (a) log del propio Hermes con `<ip:private:…>` ya en el texto y sin secretos, redacción de red activa → `redacted: false`, `secrets_redacted: false`, `network_redacted: true`; (b) log de otro add-on con `password: centinela` → `true`, `true`, `false`; (c) Hermes con la redacción desactivada → `network_redacted: false`; (d) Hermes con una IP en claro → `redacted: true`, `network_redacted: true`, `secrets_redacted: false`; (e) el evento `sv_get_addon_logs` lleva los tres campos; (f) el recorte por tamaño conserva los campos nuevos; (g) tras `set_ha_url_hosts("casa.example.org", None)`, el log de Hermes que trae `casa.example.org` sale con `<ha_external_host>` (FR-002, FR-005)
- [ ] T023 [P] [US3] Tests en `tests/test_tools_history_logbook.py` y `tests/test_response_limit.py`: (a) recorte por bytes → `truncated: true`, `truncated_at` y `_response_limit` con `list: "history"`, `returned` = estados incluidos, `total` = estados de HA, `max_bytes` y `hint`, y la respuesta serializada cabe en `response_max_bytes`; (b) recorte por el tope de estados por entidad aunque quepa en bytes → igual, con `total` antes del corte; (c) sin recorte, ni `_response_limit` ni cambios respecto a la 1.1.2; (d) con un tope muy justo, sigue cabiendo con el bloque (FR-006)
- [ ] T024 [P] [US3] Tests en `tests/test_tools_marketplace.py`, clase `TestRetiradosConFiltros`, con el simulador del fichero: (a) sin argumentos, `repositories` igual a la de la 1.1.2 para el mismo simulador y además `by_removal_type`, `by_removal_type_other` y `_third_party_text.fields == ["reason", "removal_type"]`; (b) `installed_only=True` solo devuelve los instalados (coincidencia sin mayúsculas con `full_name`), con `total` y resumen sobre ellos; (c) `limit=2` con 5 → `count: 2`, `total: 5`, `truncated: true`, resumen sobre 5; (d) `limit` 0, 501, `True` y `"5"` → `invalid_argument`; (e) 25 tipos distintos → 20 en `by_removal_type` y el resto en `by_removal_type_other`, orden por `count` y luego por tipo; `null` cuenta como tipo; (f) `removal_type` de 5 000 caracteres sale con 300; (g) con `installed_only=True` y `repositories/list` fallando → error y no la lista sin filtrar; (h) fallback HACS; (i) `ha_marketplace_list_critical` responde igual que en la 1.1.2. Y en `tests/test_tools_registration.py`: en el esquema de entrada de `ha_marketplace_list_removed`, `installed_only` y `limit` existen y no están en `required` (FR-007, FR-014)
- [ ] T025 [P] [US3] Tests de eventos `*_ok` en `tests/test_tools_marketplace.py` y `tests/test_tools_resolution.py` con `capture_logs`: cada una de las siete `ha_marketplace_*` y `sv_get_resolution` registra su evento con los campos de [contracts/tools.md](contracts/tools.md) cuando termina bien; ninguno contiene el nombre de repositorio, `reason` ni `removal_type` centinela; con error (API desconocida, forma inesperada) no se registra `*_ok`; los alias `ha_hacs_*` no registran `ha_marketplace_*_ok` (FR-008)
- [ ] T026 [US3] `hermes/src/hermes/tools/addons.py`: `secrets_redacted` y `network_redacted` (con `network_redaction_enabled()` de `logging_setup`) en la respuesta y en el evento; `redacted` igual; docstring de `sv_get_addon_logs` según el contrato (FR-005)
- [ ] T027 [US3] `hermes/src/hermes/tools/history.py`: `_response_limit` cuando `truncated`, medido dentro del tope en `_truncate_to_bytes`; `total` de estados recibidos; `hint` en inglés; docstring de `ha_get_history` (FR-006)
- [ ] T028 [US3] `hermes/src/hermes/tools/marketplace.py`: `list_removed(ha_client, installed_only=False, limit=None, max_bytes=None)` y los argumentos opcionales en la tool con su validación; filtro por instalados con `repositories/list`; resumen top 20; `_trim` de `removal_type` y `_third_party(["reason", "removal_type"])` solo en retirados; `list_critical` sin cambios de respuesta; eventos `<tool>_ok` en las siete tools registradas, solo sin `error`; docstrings (FR-007, FR-008)
- [ ] T029 [US3] `hermes/src/hermes/tools/resolution.py`: `sv_get_resolution_ok` con los cinco recuentos, solo sin `error` (FR-008)
- [ ] T030 [US3] `hermes/src/hermes/tools/guide.py`: en el tema del Marketplace, la línea de `ha_marketplace_list_removed` con `installed_only`, `limit` y `by_removal_type`; test en `tests/test_tools_guide.py` de que el tema lo menciona (FR-013)
- [ ] T031 [US3] Control negativo: con `addons.py`, `history.py`, `marketplace.py` y `resolution.py` sin los cambios caen T022…T025 (salvo los de compatibilidad); con `installed_only=True` por defecto cae T024 (a); con el bloque fuera de la medición cae T023 (d); con `removal_type` sin `_trim` cae T024 (f). Anotar recuentos

## Fase 9: Historia 4 — `sv_update_addon` sobre Hermes (P2)

**Objetivo**: rechazo previo, sin token y sin llamar al Supervisor.
**Prueba independiente**: el Supervisor simulado no recibe ninguna petición.

- [ ] T032 [US4] Tests en `tests/test_tools_supervisor.py`, clase `TestNoSeActualizaASiMismo`: con `self`, `hermes`, `a1b2c3d4_hermes` y el slug derivado de `HOSTNAME` (parcheado): (a) sin token → `{"error": "self_update_not_supported", "detail": …}` que menciona la interfaz de Home Assistant, sin `confirmation_token`, y el simulador no registra ninguna petición (ni `/addons/<slug>/info` ni `/store/addons/<slug>/update`); (b) con un token emitido directamente con `create_confirmation_token("sv_update_addon", {"slug": <slug de Hermes>})` (lo que dejaba una vista previa de la 1.1.2) → mismo error, sin peticiones y el fichero del token sigue `pending`; (c) `core_mosquitto` se comporta como en la 1.1.2 (el test existente de vista previa sigue pasando) (FR-010)
- [ ] T033 [US4] `hermes/src/hermes/tools/addons.py`: en `sv_update_addon`, tras `_bad_slug`, `if _es_hermes(slug)` → `self_update_not_supported` con el `detail` del contrato; comentario: el Supervisor responde 403 («can't update itself»), así que la vista previa prometía algo imposible; docstring (FR-010)
- [ ] T034 [US4] Control negativo: sin la guarda caen (a) y (b) de T032. Anotar recuento

## Fase 10: Historia 5 (parte) — Apagado sin traza (P3)

**Objetivo**: el log de un apagado con peticiones en vuelo no tiene `Traceback`.
**Prueba independiente**: uvicorn real en loopback con una petición colgada.

- [ ] T035 [US5] Tests en `tests/test_boot_shutdown_diagnostics.py`, clase `TestApagadoSinTraza`: (a) uvicorn real en `127.0.0.1` y puerto libre, app ASGI mínima cuya petición duerme 5 s, `timeout_graceful_shutdown=0.2`, el filtro de Hermes instalado como en el arranque, una petición en vuelo, `should_exit = True`: en el `logging` capturado no hay `Traceback` ni `CancelledError` y sí `request_cancelled_on_shutdown`; ejecutarlo **antes** de T036 sin el filtro y anotar si reproduce `Exception in ASGI application` (si no lo reproduce, anotarlo en el test y en el commit: research R-7); (b) un registro de `uvicorn.error` con `exc_info` de un `RuntimeError` conserva su traza; (c) `main()` con `asyncio.run` parcheado para lanzar `asyncio.CancelledError` registra `interrupted` y no propaga la excepción; (d) la espera del servidor cancela y recoge la task colgada sin dejar una cancelación sin recoger (FR-011)
- [ ] T036 [US5] `hermes/src/hermes/__main__.py`: filtro `_CancelacionSinTraza` en el logger `uvicorn.error`, instalado en `_setup_logging_from_config`; `except (KeyboardInterrupt, asyncio.CancelledError)` en `main()`; tras `server_task.cancel()`, esperar la task suprimiendo `CancelledError`; comentarios con el porqué (problema 23, uvicorn 0.54 registra la cancelación como excepción) (FR-011)
- [ ] T037 [US5] Control negativo: sin el filtro cae (a) (si reprodujo); sin `CancelledError` en el `except` cae (c); filtrando cualquier excepción cae (b). Anotar recuentos

## Fase 11: Cierre del tramo B y de la sub-feature

- [ ] T038 Compatibilidad (FR-014): siguen pasando sin tocarlos `test_hints_did_not_change` y `test_every_declared_tool_is_registered` de `tests/test_tools_registration.py`; con el registro real (`_register_all()` de ese fichero) se comprueba una vez, y se anota en el commit, que hay 216 tools con los mismos nombres que en la punta `d75af3f` y que ningún argumento existente cambió de nombre ni pasó a obligatorio (no se deja como test permanente: las sub-features siguientes añaden tools); si algún test existente afirmaba un texto o campo que esta sub-feature cambia a propósito (eventos de clasificación, docstrings), actualizarlo explicando por qué en el propio test
- [ ] T039 [P] `hermes/CHANGELOG.md`, sección «Correcciones» de la 1.2.0: viñetas de FR-005, FR-006, FR-007 (con la cifra de ~500 entradas / ~97 KB), FR-008, FR-010 y FR-011 (problema 23) (FR-013)
- [ ] T040 [P] `docs/HOJA-DE-RUTA.md`: fila 009 del programa → «hecha»; problema 23 → «Resuelto en 1.2.0 (009)»; quitar de «lo que antes estaba pendiente» los menores de la 009 y `sv_update_addon` sobre Hermes (FR-013)
- [ ] T041 [P] `specs/008-cobertura-total/plan.md`: en la matriz, columna de test de CAP-010…CAP-018, CAP-021 y CAP-024 con el nombre de la clase de test de esta sub-feature; `specs/008-cobertura-total/tasks.md`: T002 → `[X]` (FR-013)
- [ ] T042 Suite completa (solo los 6 conocidos de Windows), revisión del diff buscando datos personales (principio VIII) y commit del tramo B con las rutas por nombre y los recuentos de T031, T034 y T037 en el mensaje. El CI de Linux en verde (puerta 4 de la constitución, SC-007) se comprueba cuando se suba la rama o el PR; si el encargo del tramo no incluye subirla, se deja anotado como pendiente en el informe

---

## Dependencias y orden

- **Tramo A antes que B.** Dentro de A: T001 → T002–T004 (versión) → US1
  (T005–T007) → US2 (T008–T015) → barrido (T016–T018) → T019 → T020. US1, US2 y
  el barrido son independientes entre sí; se ordenan así para que cada control
  negativo se haga con el código de su historia recién escrito.
- **Dentro de cada historia**: tests (en rojo) → implementación → control
  negativo. T011 depende de T012 solo para pasar a verde, no para escribirse.
- **Tramo B**: T021 → US3 (T022–T031) → US4 (T032–T034) → apagado
  (T035–T037) → T038–T042. US3, US4 y el apagado tocan ficheros distintos
  salvo `addons.py` (T026 y T033): no en paralelo.
- **[P]**: T008, T009, T010 entre sí; T022…T025 entre sí; T019, T039, T040 y
  T041 son de documentación en ficheros distintos.

## Trazabilidad

| FR (009) | FR / CAP (008) | Tareas |
|---|---|---|
| FR-001 | FR-025 / CAP-010 | T005–T007 |
| FR-002 | FR-026 / CAP-011 | T010–T013, T015 |
| FR-003 | FR-027 / CAP-012 | T009, T014, T015 |
| FR-004 | FR-028 / CAP-013 | T008, T012, T015 |
| FR-005 | FR-029 / CAP-014 | T022, T026, T031 |
| FR-006 | FR-030 / CAP-015 | T023, T027, T031 |
| FR-007 | FR-031 / CAP-016 | T024, T028, T031 |
| FR-008 | FR-032 / CAP-017 | T025, T028, T029, T031 |
| FR-009 | FR-033 / CAP-018 | T016–T018 |
| FR-010 | FR-034 / CAP-021 | T032–T034 |
| FR-011 | FR-035 / CAP-024 | T035–T037 |
| FR-012 | FR-022 | T002–T004 |
| FR-013 | FR-023, FR-024 | T019, T030, T039–T041 |
| FR-014 | FR-018, FR-020, FR-021 | T024, T038, T020, T042 |

## Notas

- Ningún test llama a la instalación real ni a las tools MCP de Hermes.
- Si un test de tiempo resulta frágil en el CI, se cambia por la razón entre
  256 KiB y 1 MiB (ver Riesgos del plan) y se anota; nunca se sube el umbral
  hasta que pase un algoritmo cuadrático.
