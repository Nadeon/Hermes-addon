# Contratos de las tools (032)

Descripciones al cliente en inglés; comentarios del código en español. Todas
las respuestas JSON pasan por `redact_structure` y caben de sobra en el tope
central (`tools/_common.py`): son objetos pequeños, sin listas que crezcan
(ninguna lista nueva: `sobre_de_lista` no aplica).

Flujo común de las seis con token:

1. Validar argumentos (sin llamar a nada). Error → `invalid_argument` con
   `field` y la regla, nunca el valor.
2. Leer el estado necesario (GET). Fallo o forma inesperada → `error` sin
   token.
3. Reglas de negocio (`no_change`, guarda de interfaz…) → error sin token.
4. Sin `confirmation_token`: `create_confirmation_token(tool, args,
   preview=…, estado=<huella>)` **sin** `omitibles`.
5. Con token: `resolve_confirmation_token`/`validate_confirmation_token` con
   los mismos `args` y la huella releída (pasos 2–3 otra vez); si no casa,
   no se ejecuta.
6. `POST` con la carga exacta. Corte de conexión tras enviar →
   `outcome: "unknown"` (research R-10). Error del Supervisor → redactado.
7. `complete_confirmation_token` con el resultado; log sin valores.

## Familia `host_control` (módulo `hermes/src/hermes/tools/host_control.py`)

### `sv_shutdown_host(confirmation_token: str | None = None)`

- Anotaciones: destructiva (`_DESTRUCTIVE_EXACT`), no de solo lectura,
  idempotente (lo que resuelva `classify`: apagar dos veces deja el mismo
  estado).
  Título «Shut down host (Supervisor)».
- Descripción: «Power off the whole Home Assistant OS machine. Nobody can
  power it back on remotely: someone needs physical access (or a smart plug /
  Wake-on-LAN that does not depend on this machine). Two-step. No `force`: an
  offline database migration in progress blocks it.»
- Vista previa: data-model. Carga confirmada: `POST /host/shutdown` con
  `json_body={}`.
- Respuesta: `{"result": "ok", "note": "Host shutdown initiated. …"}` o
  `outcome: "unknown"`.

### `sv_set_hostname(hostname: str, confirmation_token: str | None = None)`

- Valida RFC 1123 (research R-7). Lee `GET /host/info`. `no_change` si
  igual. Carga: `POST /host/options` `{"hostname": hostname}`.
- Respuesta: `{"result": "ok", "hostname": <releído de /host/info>}`.

### `sv_set_swap(swap_size: str | None = None, swappiness: int | None = None, confirmation_token: str | None = None)`

- Valida (FR-003). Lee `GET /os/config/swap` (404 → `not_supported` con la
  pista de la 013) y `GET /host/info` (`disk_free`). Carga: solo las claves
  pasadas. Respuesta: `{"result": "ok", "swap": <releído>,
  "reboot_required": bool, "hint": "sv_get_resolution / sv_reboot_host"}`.

### `sv_set_boot_slot(boot_slot: str, confirmation_token: str | None = None)`

- `boot_slot` en `{"A", "B"}` (se normaliza a mayúsculas antes del hash).
  Lee `GET /os/info` (404 → `not_supported`). Carga `POST /os/boot-slot`
  `{"boot_slot": "B"}`. Respuesta: `{"result": "ok", "note": "Rebooting into
  slot B …", "verify_with": "sv_get_os_info"}` u `outcome: "unknown"`.

## Familia `host_network` (módulo `hermes/src/hermes/tools/host_network.py`)

### `sv_reload_network()`

- Sin token. Anotaciones: ni de solo lectura ni destructiva, idempotente.
- Descripción: «Re-read the host network state from NetworkManager and
  re-check connectivity. Changes nothing.»
- `POST /network/reload`; respuesta `{"result": "ok", "host_internet": …}`
  releyendo `GET /network/info` (solo los dos booleanos de conectividad).

### `sv_update_network_interface(interface: str, ipv4: dict | None = None, ipv6: dict | None = None, wifi: dict | None = None, enabled: bool | None = None, mdns: str | None = None, llmnr: str | None = None, confirmation_token: str | None = None)`

- Título «Update host network interface (Supervisor)». Destructiva.
- Descripción: dice que **reemplaza** cada bloque que se pasa, que la
  interfaz principal (y la única conectada) se rechaza siempre, que el
  Supervisor no revierte y que la PSK no se devuelve.
- `interface`: `validate_path_segment` + `^[A-Za-z0-9_.-]{1,15}$`, distinto
  de `default`.
- Lee `GET /network/info` (guarda, FR-007) y `GET
  /network/interface/{interface}/info` (`before`). 404 → `interface_not_found`.
- Carga: `{bloque: valor normalizado}` solo de lo pasado.
- Respuesta: `{"result": "ok", "interface": <releída, sin mac ni PSK>}`;
  si la relectura falla, `"interface": null` y `verify_with`.

### `sv_create_vlan(interface: str, vlan_id: int, ipv4: dict | None = None, ipv6: dict | None = None, mdns: str | None = None, llmnr: str | None = None, confirmation_token: str | None = None)`

- Destructiva (token) y no idempotente (`sv_create_`).
- Lee `GET /network/info`: madre existe (`interface_not_found`), `type ==
  "ethernet"` (`not_ethernet`), `<madre>.<id>` no existe (`vlan_exists`).
- Carga: `POST /network/interface/{interface}/vlan/{vlan_id}` con los bloques
  pasados (vacío → el Supervisor usa `auto`).
- Respuesta: `{"result": "ok", "interface": <releída de
  /network/interface/<madre>.<id>/info, forma pública sin mac>}`.

## Inventario de la 033 (`tests/test_confirmation_args_inventory.py`)

| Tool | Argumentos | Clasificación |
|---|---|---|
| `sv_shutdown_host` | — | solo `confirmation_token` (exento, como en `sv_reboot_host`) |
| `sv_set_hostname` | `hostname` | atado |
| `sv_set_swap` | `swap_size`, `swappiness` | atado |
| `sv_set_boot_slot` | `boot_slot` | atado (normalizado) |
| `sv_update_network_interface` | `interface`, `ipv4`, `ipv6`, `wifi` (con `psk`), `enabled`, `mdns`, `llmnr` | atado |
| `sv_create_vlan` | `interface`, `vlan_id`, `ipv4`, `ipv6`, `mdns`, `llmnr` | atado |

Más la huella del estado en todas menos `sv_shutdown_host`.

## Matriz de la 014 (`docs/HOJA-DE-RUTA.md`)

| Tool | Entorno | Resultado | Nota |
|---|---|---|---|
| `sv_create_vlan` | VM | pendiente | VM con segunda interfaz; instantánea antes |
| `sv_reload_network` | VM | pendiente | |
| `sv_set_boot_slot` | VM | pendiente | instantánea antes; VM con HAOS y dos ranuras |
| `sv_set_hostname` | VM | pendiente | instantánea antes |
| `sv_set_swap` | VM | pendiente | HAOS ≥ 15; instantánea antes |
| `sv_shutdown_host` | VM | pendiente | instantánea antes; encender la VM a mano |
| `sv_update_network_interface` | VM | pendiente | VM con segunda interfaz; instantánea antes; comprobar el rechazo de la principal |
