# Modelo de datos: Hermes 1.1.2 — confirmar solo con el token

## Fichero de token (`CONFIRMATIONS_DIR/<token>.json`)

Un fichero por token en `/data/pending_confirmations`, escrito de forma atómica
(`.tmp` + `os.replace`). Campos de 1.1.1 sin cambios; en negrita, los nuevos.

| Campo | Tipo | Notas |
|---|---|---|
| `token` | str (UUID4) | Formato comprobado antes de construir ninguna ruta. |
| `action_hash` | str (SHA-256) | De `{"tool", "args"}` con TODOS los argumentos de la vista previa. No cambia su cálculo. |
| `expires_at` | float | Creación + 60 s. Al completar, ahora + 60 s. |
| `state` | `pending` \| `executing` \| `completed` \| `failed` | |
| `tool_name` | str | |
| `created_at` | float | |
| `retries` | int | |
| **`stored_args`** | dict | Solo los omitibles de la tool presentes en la vista previa, con el valor que entró en el hash (normalizado en automatizaciones, scripts y escenas). Ausente si la tool no declara omitibles o si se superó el tope. |
| **`stored_bytes`** | int | Tamaño de `stored_args` serializado (UTF-8, `ensure_ascii=False`). Solo para el log y los tests. |
| `completed_at` | float | Al completar. |
| `cached_result` / `cached_error` | any / str | Al completar. Sin cambios. |

### Reglas

- `stored_args` solo contiene claves de la lista `omitibles` que la tool pasa
  a `create_confirmation_token`; nunca un destino.
- `stored_args` y `stored_bytes` desaparecen al completar (éxito o fallo); el
  fichero entero, al caducar (detectado en `resolve`/`validate`, en el barrido
  de cada vista previa nueva o en la limpieza periódica cada 60 s).
- Ninguno de los dos llega nunca al log ni a la respuesta.

### Transiciones

```text
(vista previa) ──► pending [+ stored_args]
pending ──resolve OK──► executing [stored_args intacto]
pending ──hash distinto / omitido sin guardar──► pending (no se gasta)
pending ──caducado──► (fichero borrado)
executing ──complete(success)──► completed [sin stored_args, + cached_result]
executing ──complete(fail)────► failed    [sin stored_args, + cached_error]
completed|failed ──60 s──► (fichero borrado por el barrido)
executing (caída a mitad) ──expires_at original──► (fichero borrado por el barrido)
```

## Omitibles por tool

Constante en el módulo de cada tool, con un comentario que explique por qué.

| Tool | Omitibles | Destino (siempre obligatorio) |
|---|---|---|
| `ha_save_lovelace_dashboard` | `config` | `url_path` (admite `null` = principal) |
| `fs_write_file` | `content` | `path` |
| `ha_create_or_update_automation` | `config` | `automation_id` |
| `ha_create_or_update_script` | `config` | `script_id` |
| `ha_create_or_update_scene` | `config` | `scene_id` |

## Constantes nuevas o cambiadas

| Constante | Dónde | Valor |
|---|---|---|
| `CONFIRMATION_STORED_MAX_BYTES` | `hermes/src/hermes/security.py` | `16 * 1024 * 1024` (nueva) |
| `CONFIRMATIONS_CLEANUP_INTERVAL_SECONDS` | `hermes/src/hermes/__main__.py` | 3600 → `60` |
| `CONFIRMATION_TTL_SECONDS` | `hermes/src/hermes/security.py` | 60 (sin cambios) |
