# Modelo de datos: 009 — correcciones pendientes

No hay datos persistentes nuevos: el fichero de token de la 007 no cambia.
Cambia estado en memoria de dos módulos.

## Estado de la redacción de red (`logging_setup.py`)

`_net_state`, que se sustituye entero de una vez (un hilo que redacta ve el
estado viejo o el nuevo, nunca una mezcla):

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `enabled` | `bool` | `log_redact_network` | Sin cambios |
| `host_re` | `re.Pattern \| None` | `public_hostname` | Sin cambios; se aplica primero |
| `ha_hosts` | `tuple[tuple[re.Pattern, str], ...]` | `external_url`, `internal_url` de `/api/config` | **Nuevo**. Hasta dos pares `(patrón, marcador)`: `<ha_external_host>`, `<ha_internal_host>`. Vacío al arrancar y si no se pudieron leer |
| `salt` | `bytes` | aleatoria en `configure_network_redaction` | Sin cambios; `set_ha_url_hosts` no la renueva, para que los seudónimos de IP sigan correlacionando |

Reglas de `ha_hosts`:

- Host = `urlsplit(url).hostname` (sin puerto ni credenciales), en minúsculas.
- Se descartan: `None`, vacío, literales IP (IPv4 o IPv6), `localhost`,
  `homeassistant`, `homeassistant.local`, y el que coincide con
  `public_hostname` (ya lo tapa `host_re`).
- Si `external` e `internal` dan el mismo host, un solo par con
  `<ha_external_host>`.
- Fronteras del patrón: las mismas que el de `public_hostname`.

## Total de documentos guardados (`security.py`)

| Campo | Tipo | Significado |
|---|---|---|
| `_en_uso_bytes` | `int` | Bytes de documentos de tokens vigentes según el último barrido, más los guardados después |
| `_ultimo_barrido` | `float \| None` | `time.monotonic()` del último barrido completo; `None` = ninguno |
| `_BARRIDO_MIN_INTERVALO_S` | `float` = 1.0 | Intervalo mínimo entre barridos desde `create_confirmation_token` |

Transiciones:

- `_barrer_caducados()` (desde `create_confirmation_token`,
  `cleanup_expired_confirmations`, arranque): recalcula y fija los dos.
- `create_confirmation_token` con documento: barre si `_ultimo_barrido` es
  `None`, si `monotonic() - _ultimo_barrido >= 1.0` o si es negativo; después,
  si `_en_uso_bytes + tam <= tope`, guarda y `_en_uso_bytes += tam`.
- `complete_confirmation_token` y la caducidad: **no** tocan `_en_uso_bytes`
  (sobrestimación conservadora hasta el siguiente barrido).

Invariante: `_en_uso_bytes >= bytes reales guardados en tokens vigentes`.
