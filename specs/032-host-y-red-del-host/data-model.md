# Modelo de datos: host y red del host (032)

Formas del Supervisor 2026.11.0 (API v1) y de las vistas previas. Valores de
ejemplo genéricos (principio VIII).

## Entradas de la tabla que pasan a `dedicated`

| Clave | Tool | Familia | CAP | Tramo |
|---|---|---|---|---|
| `("POST", "/host/shutdown")` | `sv_shutdown_host` | `host_control` | CAP-086 | 1 |
| `("POST", "/host/options")` | `sv_set_hostname` | `host_control` | CAP-086 | 1 |
| `("POST", "/os/config/swap")` | `sv_set_swap` | `host_control` | CAP-086 | 1 |
| `("POST", "/os/boot-slot")` | `sv_set_boot_slot` | `host_control` | CAP-086 | 1 |
| `("POST", "/network/reload")` | `sv_reload_network` | `host_network` | CAP-090 | 2 |
| `("POST", "/network/interface/{interface}/update")` | `sv_update_network_interface` | `host_network` | CAP-090 | 2 |
| `("POST", "/network/interface/{interface}/vlan/{vlan}")` | `sv_create_vlan` | `host_network` | CAP-090 | 2 |

Las lecturas (`GET /network/*`, `/host/info`, `/os/info`, `/os/config/swap`)
no cambian.

## Lecturas que usan las vistas previas

- `GET /host/info` → `{"hostname": "homeassistant", "disk_free": 20.5, …}`
  (`disk_*` en GiB).
- `GET /os/config/swap` → `{"swap_size": "1G", "swappiness": 1}`; 404 sin
  HAOS ≥ 15.
- `GET /os/info` → `{"version": "17.0", "boot": "A", "boot_slots": {"A":
  {"state": "booted", "status": "good", "version": "17.0"}, "B": {"state":
  "inactive", "status": "bad", "version": "17.1"}}, …}`.
- `GET /network/info` → `{"interfaces": [<Interfaz>…], "docker": {…},
  "host_internet": bool, "supervisor_internet": bool}`.
- `GET /network/interface/{i}/info` → `<Interfaz>`.

### Interfaz (forma v1)

```json
{
  "interface": "wlan0", "type": "wireless", "enabled": true,
  "connected": false, "primary": false, "mac": "aa:bb:cc:dd:ee:ff",
  "ipv4": {"method": "auto", "address": ["192.0.2.20/24"],
           "nameservers": ["192.0.2.1"], "gateway": "192.0.2.1",
           "route_metric": null, "ready": true},
  "ipv6": {"method": "auto", "addr_gen_mode": "default",
           "ip6_privacy": "default", "address": [], "nameservers": [],
           "gateway": null, "route_metric": null, "ready": false},
  "wifi": {"mode": "infrastructure", "auth": "wpa-psk", "ssid": "mi-red",
           "signal": 60},
  "vlan": null, "mdns": "default", "llmnr": "default"
}
```

`type`: `ethernet`, `wireless`, `vlan`. El Supervisor nunca devuelve la PSK.

## Argumentos de red (FR-008)

| Bloque | Campo | Regla |
|---|---|---|
| `ipv4` / `ipv6` | `method` | obligatorio: `auto`, `static`, `disabled` |
| | `address` | lista de `IP/prefijo` de la familia; obligatoria (≥ 1) con `static`; prohibida con `auto`/`disabled` |
| | `gateway` | IP de la familia; solo con `static` |
| | `nameservers` | lista de IP de la familia (≤ 8) |
| | `route_metric` | entero ≥ 0 (no `bool`) |
| `ipv6` | `addr_gen_mode` | `eui64`, `stable-privacy`, `default-or-eui64`, `default` |
| | `ip6_privacy` | `disabled`, `enabled-prefer-public`, `enabled`, `default` |
| `wifi` | `mode` | obligatorio: `infrastructure`, `mesh`, `adhoc`, `ap` |
| | `auth` | obligatorio: `open`, `wep`, `wpa-psk` |
| | `ssid` | obligatorio, 1–32 bytes UTF-8, sin caracteres de control |
| | `psk` | obligatoria con `wep`/`wpa-psk`, prohibida con `open`; sin caracteres de control, distinta del marcador de redacción; `wpa-psk` 8–63 caracteres o 64 hexadecimales |
| — | `enabled` | booleano |
| — | `mdns`, `llmnr` | `default`, `off`, `resolve`, `announce` |

Claves desconocidas en cualquier bloque → `invalid_argument`. Los vocabularios
salen de `supervisor/host/const.py`.

## Vistas previas

### `sv_shutdown_host`

```json
{"action": "shutdown_host",
 "stops": ["host", "home_assistant_core", "all_apps", "hermes"],
 "warning": "Nobody can power this machine on remotely …",
 "connection": "This connection to Hermes will be lost."}
```

### `sv_set_hostname`

`{"action": "set_hostname", "from": "homeassistant", "to": "casa-ha",
"warning": "<mDNS: homeassistant.local → casa-ha.local …>"}`

### `sv_set_swap`

`{"action": "set_swap", "changes": {"swap_size": {"from": "1G", "to": "2G"}},
"disk_free_gib": 20.5, "reboot_required": true, "warning"?: "…disables swap"}`

### `sv_set_boot_slot`

`{"action": "set_boot_slot", "current": {"slot": "A", "version": "17.0"},
"target": {"slot": "B", "version": "17.1", "state": "inactive", "status":
"bad"}, "reboots_now": true, "warning": "…", "slot_warning"?: "…bad…",
"rollback": "sv_set_boot_slot(\"A\")"}`

### `sv_update_network_interface`

```json
{"action": "update_network_interface", "interface": "wlan0",
 "role": {"primary": false, "connected": false, "other_connected": ["eth0"]},
 "before": {<Interfaz sin mac>},
 "after": {"ipv4": {"method": "auto"},
           "wifi": {"mode": "infrastructure", "auth": "wpa-psk",
                    "ssid": "mi-red", "psk": "set"}},
 "replaces_blocks": ["ipv4", "wifi"],
 "warning": "The Supervisor does NOT roll back …",
 "route_warning"?: "A gateway here may take the default route …"}
```

### `sv_create_vlan`

`{"action": "create_vlan", "parent": "eth0", "new_interface": "eth0.20",
"vlan_id": 20, "config": {"ipv4": {"method": "auto"}}, "warning": "…",
"route_warning": "…"}`

## Huellas del estado (`estado=`)

| Tool | Huella |
|---|---|
| `sv_set_hostname` | `{"hostname"}` |
| `sv_set_swap` | `{"swap_size", "swappiness"}` (el disco libre cambia solo: no entra; `insufficient_disk` se repite al confirmar) |
| `sv_set_boot_slot` | `{"boot", "boot_slots"}` |
| `sv_update_network_interface` | `{"interface": <Interfaz sin `wifi.signal` ni `ready`>, "primary": <nombre>, "connected": [<nombres>]}` |
| `sv_create_vlan` | `{"parent": <Interfaz sin `wifi.signal` ni `ready`>, "existing": [<nombres>], "primary", "connected"}` |

## Errores

`invalid_argument` (con `field` y regla), `no_change`, `not_supported`,
`insufficient_disk`, `already_booted`, `slot_unusable`, `primary_interface`,
`only_connected_interface`, `primary_unknown`, `interface_not_found`,
`not_ethernet`, `vlan_exists`, `state_changed` (huella), errores del
Supervisor redactados y `outcome: "unknown"` (R-10).

## Eventos de log

`host_control` / `host_network`: `tool`, `outcome`
(`preview`/`ok`/`error`/`invalid_argument`/`rejected`/`unknown`), `changed`
(claves), `interface`, `field`, `reason`. Nunca valores.
