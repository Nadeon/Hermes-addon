# Modelo de datos: integraciones específicas por la tabla (025)

Sin entidades nuevas en el add-on. Tres estructuras de datos, dos de ellas ya
existentes.

## Entrada de la tabla (`Entrada`, `command_policy.py`; sin cambios de campos)

| Campo | Uso en la 025 |
|---|---|
| `category` | `read`, `confirm` o `deny` (nunca `dedicated`: no hay tools nuevas) |
| `reason` | texto exacto de research.md R-1; concreto, sin «pendiente» ni «sin revisar» |
| `family` | siempre `generic_commands` |
| `tool` | siempre `None` |
| `cap` | la del inventario (CAP-100…CAP-106); no cambia |
| `one_shot` | `True` en las cinco suscripciones de R-2 (solo `read`) |
| `response` | `json` (por defecto) |
| `redact_extra` | `("dsk",)`, `("network_key", "tc_link_key", "key_table", "stack_specific")` (tres de ZHA), `("active_dataset_tlvs",)` o `("code", "transmitted", "messages.payload")` (`mqtt/device/debug_info`; una clave con punto, `padre.hija`, tapa `hija` solo dentro de `padre`: convergencia, T049) |
| `open_world` | `True` en `zwave_js/check_for_config_updates` (`read`) y `zwave_js/install_config_update` (`confirm`) |
| `example` | las seis cargas de ejemplo de R-1 (datos ficticios, sin `id` ni `type`) |

**Cambio de semántica de `redact_extra`** (FR-008): la clave tapa su valor
ENTERO también cuando es un objeto o una lista. Antes, un objeto o una
lista se recorría y solo se tapaban sus escalares bajo claves sensibles. Los
escalares siguen como hoy: `None` y la cadena vacía se conservan (saber que
no hay valor no revela nada, como en `redact_structure`).

Validación al construir (`__post_init__`, sin cambios): `one_shot` solo con
`read`; `tool` solo con `dedicated`. Validación de los tests: verbos
(`TestVerbos` con tres excepciones nuevas), mundo abierto
(`_READ_QUE_SALEN` con una nueva), ejemplos (`test_ejemplos`), CAP
(`test_a_y_c_con_su_cap`).

### Comentarios encima de entradas en `command_table.py`

Llevan comentario con el porqué (la cabecera de la tabla lo exige para cada
excepción del test de verbos y cada decisión no evidente):

- las tres lecturas `zwave_js/*firmware_update*` (verbo `update`, solo leen);
- `zwave_js/network_neighbors` (`confirm` aunque solo lee: apaga la radio);
- las tres de ZHA con `redact_extra` (por qué el valor entero, H-1);
- `insteon/config/get` (la contraseña la tapa el marcador, sin `redact_extra`);
- `mqtt/device/debug_info` (por qué `code` y `transmitted` enteros);
- `insteon/config/get_modem_schema` (la contraseña viaja como `default`);
- `notify/html5/appkey` (clave pública, no secreta);
- las cinco `one_shot` y las suscripciones descartadas por R-2 (una línea
  por grupo).

## Mapa revisado de la clase C (`scripts/inventario/clase_c.py`, nuevo)

```python
CLASE_C: dict[str, dict[str, object]] = {
    "zwave_js/network_status": {"category": "read", "reason": "…"},
    "zwave_js/subscribe_node_statistics": {"category": "read", "reason": "…", "one_shot": True},
    "zha/network/settings": {"category": "read", "reason": "…",
                             "redact_extra": ("network_key", "tc_link_key", "key_table", "stack_specific")},
    …
}
```

- Claves: los comandos de clase C del inventario de Core. Una por línea (o
  por bloque si lleva `example`), en orden de clave.
- Valores: `category` y `reason` obligatorios; `one_shot`, `redact_extra`,
  `open_world` y `example` solo si difieren del valor por defecto (el mismo
  criterio que `_render` del generador).
- Solo lo importa `generar_tabla.py`. No lo importa nada de `hermes/src`.
- Invariante (test): para cada fila de clase C, generar desde cero da los
  mismos campos que la tabla real. Una clave del mapa que no está en el
  inventario no aparece en la tabla generada (la deriva la nombraría).

## Tema de la guía (`_GUIDE`, `tools/guide.py`)

Texto estático en Markdown, uno por grupo:

| Tema | CAP | Alias |
|---|---|---|
| `zwave` | CAP-100 | `zwave_js`, `z-wave`, `z_wave` |
| `zigbee` | CAP-101 | `zha` |
| `matter_thread` | CAP-102, CAP-103 | `matter`, `thread`, `otbr` |
| `other_integrations` | CAP-104…CAP-106 | `mqtt`, `usb`, `bluetooth`, `knx`, `insteon`, `lcn`, `esphome`, `dynalite`, `lorawan`, `modbus`, `wyoming` |

Secciones fijas en cada tema (las usa el test de cruce con la tabla):
`POR LA GENÉRICA` (lecturas y escrituras, con cargas), `RECHAZADO` (por
grupos de motivo) y `OTRA VÍA` (acciones de HA o la UI), más una línea final
con la búsqueda `search=`.
