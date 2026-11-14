# Validación: Hermes 1.1.2 — confirmar solo con el token

## Requisitos

- Entorno de desarrollo de `CONTRIBUTING.es.md` (Python 3.13 en `.venv`).
- En Windows fallan 6 tests ajenos a este cambio; la referencia es el CI de
  Linux.

## Tests automáticos

```sh
.venv/bin/pytest tests/test_security.py tests/test_confirmations_periodic_cleanup.py
.venv/bin/pytest tests/test_tools_lovelace.py tests/test_fs_write_security.py \
  tests/test_tools_automations.py tests/test_tools_scripts.py tests/test_tools_scenes.py
.venv/bin/pytest tests/test_response_limit.py tests/test_tools_guide.py \
  tests/test_tools_registration.py
.venv/bin/pytest            # suite completa
```

Resultado esperado: todo verde. Lo que cubren está en tasks.md; las formas de
respuesta, en [contracts/tools.md](contracts/tools.md); el fichero de token, en
[data-model.md](data-model.md).

## Control negativo (principio VII)

1. Con el código de `security.py` de 1.1.1 (sin `resolve_confirmation_token`
   ni `stored_args`), los tests nuevos de confirmación sin documento y de
   borrado tienen que caer. Anotar el recuento.
2. Con las cinco tools de 1.1.1 (documento obligatorio), caen los de omisión
   por tool y el de esquema.
3. Sin los intocables nuevos del guardián, cae el de la vista previa
   recortada.
4. Con `CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS = 3600`, cae su test.

## Prueba en vivo (después de publicar; queda en la hoja de ruta)

En una instalación de prueba con HA 2026.11.x y Hermes 1.1.2, desde un
cliente MCP real:

1. Leer un dashboard de prueba de unos 40 KB con `ha_get_lovelace_dashboard`.
2. Guardarlo modificado con `ha_save_lovelace_dashboard`: la vista previa trae
   `omit_on_confirm: ["config"]`.
3. Confirmar con solo `url_path` y `confirmation_token`: `{"result": "ok"}` a
   la primera, sin `confirmation_token expired`.
4. Repetir con `fs_write_file` sobre un fichero de prueba grande.
5. Comprobar en el log del add-on que no aparece el contenido y que, pasados
   unos 2 minutos, el directorio de confirmaciones no conserva el documento.
