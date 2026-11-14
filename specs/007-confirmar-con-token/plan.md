# Plan de implementación: Hermes 1.1.2 — confirmar solo con el token

**Rama**: la de trabajo actual (no se crea ninguna) | **Fecha**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Resumen

En la vista previa, `security.py` guarda junto al token los argumentos que la
tool declara omitibles (el documento grande); en la confirmación, los omitidos
se toman de lo guardado y el `action_hash` se comprueba sobre los argumentos
resultantes. Cinco tools declaran su documento omitible y lo dicen en la
respuesta, en su descripción y en la guía. Lo guardado se borra al completar o
caducar, tiene un tope global y nunca llega al log. El principio IV se enmienda
de forma explícita. Versión 1.1.2.

Detalle y alternativas en [research.md](research.md); fichero de token en
[data-model.md](data-model.md); formas de respuesta en
[contracts/tools.md](contracts/tools.md); validación en
[quickstart.md](quickstart.md).

## Contexto técnico

**Lenguaje**: Python 3.13 · **Dependencias**: SDK `mcp` (MCPServer), aiohttp, structlog, pydantic 2 · **Almacenamiento**: ficheros JSON en `/data/pending_confirmations` · **Tests**: pytest, `unittest.IsolatedAsyncioTestCase`, `DummyMCP` y el cliente MCP en memoria · **Plataforma**: add-on de Home Assistant OS.

**Restricciones**: fail-closed (III); el token sigue atado a tool y argumentos (IV); ningún documento en el log ni en la respuesta (II); cambios mínimos: las demás tools con token no cambian (IX).

**Escala**: 5 tools, `security.py`, `tools/_common.py`, `tools/guide.py`, `__main__.py`; unos 9 ficheros de tests.

## Comprobación de la constitución

| Principio | Cumplimiento | Estado |
|---|---|---|
| I. Seguridad primero | Lista explícita de omitibles; solo se guarda el documento, no los demás argumentos (nada de opciones con contraseñas en disco). | OK |
| II. Secretos | El documento de `fs_write_file` puede contener datos sensibles: se borra al completar, al fallar y al caducar (≤ 60 s de limpieza); nunca en el log; los eventos nuevos llevan solo nombres de claves y bytes. | OK |
| III. Fail-closed | Omitir sin valor guardado se rechaza; tope lleno → comportamiento de 1.1.1, no uno más permisivo; fichero perdido → «expired or lost across restart». | OK |
| IV. Dos pasos, token atado | **Desviación del texto actual**: la constitución dice «la segunda, con los mismos argumentos y el token, ejecuta». Se justifica y se enmienda en este mismo cambio (T028): el token sigue atado a la tool y a sus argumentos, ahora guardados en el servidor; el hash se comprueba sobre los argumentos resultantes; la vista previa sigue describiendo exactamente lo que se ejecuta. | Enmienda |
| V. Nombre y descripción | Docstrings de las cinco tools y guía cambian en el mismo commit; anotaciones sin cambios. | OK |
| VI / VII | Test de regresión por requisito y control negativo anotado (T004, T016, T021, T023, T027). | OK |
| VIII. Privacidad | Datos de prueba ficticios (`panel-ficticio`, `automation.ficticia`, centinelas de texto); revisión del diff antes de commit. | OK |
| IX. Cambios mínimos | `validate_confirmation_token` conserva firma y comportamiento para las 46 llamadas restantes; fuera de alcance anotado en la spec. | OK |
| X. Comentarios en español | Cada guarda nueva explica el porqué (caducidad a 0,4 KB/s, secretos en disco, tope). | OK |
| XI. Versionado | 1.1.2 en los tres sitios y CHANGELOG `## [1.1.2] — 2026-11-14`. | OK |

Tras el diseño: sin cambios en la tabla. La desviación de IV queda resuelta
por la enmienda explícita de `docs/PRINCIPIOS.md` y de la constitución
(1.0.0 → 1.1.0), como pide Governance.

## Diseño

1. **`hermes/src/hermes/security.py`**
   - `CONFIRMATION_STORED_MAX_BYTES = 16 * 1024 * 1024`.
   - `_barrer_caducados() -> int` (síncrona): el cuerpo actual de
     `cleanup_expired_confirmations`, que pasa a llamarla.
   - `create_confirmation_token(tool_name, args, preview=None, *,
     omitibles: tuple[str, ...] = ())`: hash con TODOS los `args` (como hoy);
     `guardados = {k: args[k] for k in omitibles if args.get(k) is not None}`;
     si hay `guardados`, barre caducados y, en el mismo barrido, suma los bytes
     de los documentos guardados en los tokens vigentes (`stored_bytes`); si
     con los del nuevo no pasa de `CONFIRMATION_STORED_MAX_BYTES`, añade `stored_args` / `stored_bytes`; si no, registra
     `confirmation_args_not_stored`. Si `omitibles` no está vacío, añade a la
     respuesta `confirm_with`, `omit_on_confirm` (solo si se guardó) y
     `confirm_hint`.
   - `resolve_confirmation_token(token, tool_name, args, *, omitibles=()) ->
     tuple[bool, str, dict]`: formato, existencia, caducidad y estado como hoy;
     luego `faltan = [k for k in omitibles if args.get(k) is None and k not in
     stored_args]` → error «has no stored value for» sin tocar el estado;
     `resueltos = args sin los None de omitibles + stored_args de los omitidos`;
     hash sobre `resueltos`; `executing`; devuelve `resueltos`. Sin `await`
     entre la lectura y la escritura del estado.
   - `validate_confirmation_token(token, tool_name, args)`: envoltorio de
     `resolve_confirmation_token(..., omitibles=())` que devuelve `(ok, error)`.
   - `complete_confirmation_token`: `pop("stored_args")`, `pop("stored_bytes")`
     antes de reescribir.
2. **Tools** (`tools/lovelace.py`, `tools/filesystem_write.py`,
   `tools/automations.py`, `tools/scripts.py`, `tools/scenes.py`): constante
   `_OMITIBLES_*` con comentario; documento `| None = None` en la firma; sin
   token y sin documento → `invalid_argument`; validación/normalización del
   documento solo si viene; `args` sin la clave del documento si no viene;
   `create_confirmation_token(..., omitibles=…)`; en la confirmación,
   `resolve_confirmation_token(..., omitibles=…)` y el documento sale de los
   resueltos; docstring con la línea de la omisión. En `lovelace.py` el
   chequeo de modo YAML sigue antes de todo y `remove_top_level_keys` no es
   omitible.
3. **`tools/_common.py`**: en `_recortar_vista_previa`, `intocables` y el
   mínimo de último recurso incluyen `confirm_with`, `omit_on_confirm` y
   `confirm_hint`.
4. **`tools/guide.py`**: `INSTRUCTIONS` punto 1 y temas `security`, `files` y
   `workflows`.
5. **`__main__.py`**: `CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS = 60`, con el
   porqué (documentos pendientes en disco). `confirmations_cleaned` solo se
   registra si se ha limpiado algo (> 0): con una pasada por minuto, registrar
   también las vacías llenaría el log.
6. **Constitución y principios**: `docs/PRINCIPIOS.md` (IV) y
   `.specify/memory/constitution.md` (IV, versión 1.1.0, `Last Amended`).
7. **Versión y documentación**: ver FR-014.

## Riesgos

- **Cliente que ignora la pista**: sigue reenviando y sigue caducando con
  documentos grandes, pero no es peor que 1.1.1. La guía y la descripción de
  la tool lo dicen tres veces; SC-005 lo comprueba en vivo.
- **Disco**: acotado por el tope de 16 MiB y la limpieza cada 60 s.
- **Token de 1.1.1 tras actualizar**: no tiene `stored_args`; omitir da el
  error de FR-005 y reenviar todo funciona.

## Ficheros

- Código: `hermes/src/hermes/security.py`, `hermes/src/hermes/__main__.py`,
  `hermes/src/hermes/tools/{lovelace,filesystem_write,automations,scripts,scenes,_common,guide}.py`,
  `hermes/src/hermes/config.py`, `hermes/src/hermes/__init__.py`,
  `hermes/config.yaml`.
- Tests: `tests/test_security.py`, `tests/test_confirmations_periodic_cleanup.py`,
  `tests/test_tools_lovelace.py`, `tests/test_fs_write_security.py`,
  `tests/test_tools_automations.py`, `tests/test_tools_scripts.py`,
  `tests/test_tools_scenes.py`, `tests/test_response_limit.py`,
  `tests/test_tools_guide.py`, `tests/test_tools_registration.py`.
- Docs: `docs/PRINCIPIOS.md`, `.specify/memory/constitution.md`,
  `hermes/CHANGELOG.md`, `SECURITY.md`, `docs/HOJA-DE-RUTA.md`.
