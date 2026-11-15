# Research: host y red del host (032)

Fuentes: código del Supervisor 2026.11.0 (solo lectura), `inventario/supervisor-rutas.tsv`
de la 008, código de Hermes en `feat/cobertura-total` (`0b7d5e2`), ramas
`feat/019-montajes-y-ajustes-de-backup` y la spec de la 022 en curso.

## Rutas comprobadas

| Ruta | Handler (Supervisor 2026.11.0) | Cuerpo | Efecto | Inventario | Tabla hoy |
|---|---|---|---|---|---|
| `POST /host/shutdown` | `api/host.py::shutdown` | `{"force": bool}` opcional | `_check_ha_offline_migration(force)` y `host.control.shutdown()` (logind PowerOff) | A, CAP-086 | `deny` «spec 032» |
| `POST /host/options` | `api/host.py::options` | `{"hostname": str}` opcional | `set_static_hostname` por D-Bus; `HostInvalidHostnameError` si no vale | A, CAP-086 | `deny` «spec 032» |
| `POST /os/config/swap` | `api/os.py::config_swap_options` | `swap_size` (`^\d+([KMG](i?B)?|B)?$`), `swappiness` (0–200) | OS ≥ 15 o 404; si cambia algo, issue `reboot_required` con sugerencia `execute_reboot` | A, CAP-086 | `deny` «spec 032» |
| `POST /os/boot-slot` | `api/os.py::set_boot_slot` → `os/manager.py::set_boot_slot` | `{"boot_slot": "A"\|"B"}` | `rauc.mark(ACTIVE, slot)` y **`host.control.reboot()`** inmediato | A, CAP-086 | `deny` «spec 032» |
| `POST /network/reload` | `api/network.py::reload` → `host/network.py::update` | — | relee D-Bus de NetworkManager y fuerza la comprobación de conectividad; no cambia configuración | A, CAP-090 | `deny` «spec 032» |
| `POST /network/interface/{interface}/update` | `api/network.py::interface_update` | `SCHEMA_UPDATE`: `ipv4`, `ipv6`, `wifi`, `enabled`, `mdns`, `llmnr` | **reemplaza** cada bloque pasado y `apply_changes`; sin reversión automática | A, CAP-090 | `deny` «spec 032» |
| `POST /network/interface/{interface}/vlan/{vlan}` | `api/network.py::create_vlan` | `SCHEMA_UPDATE` (usa `ipv4`, `ipv6`, `mdns`, `llmnr`) | id 0–4094; madre `ethernet`; `HostNetworkError` si ya existe; crea la conexión y relee | A, CAP-090 | `deny` «spec 032» |

Lecturas que usan las vistas previas (ya existen, no se duplican): `GET
/host/info` (`sv_get_host_info`, hostname y `disk_free` en GiB), `GET /os/info`
(`sv_get_os_info`, `boot` y `boot_slots`), `GET /os/config/swap`
(`sv_get_swap`), `GET /network/info` y `GET /network/interface/{i}/info`
(`read` por `sv_read_api`, 013). `_get_interface("default")` del Supervisor
devuelve la interfaz `primary`.

## R-1 — Dos familias

`host_control` (`sv_shutdown_host`, `sv_set_hostname`, `sv_set_swap`,
`sv_set_boot_slot`) y `host_network` (`sv_reload_network`,
`sv_update_network_interface`, `sv_create_vlan`). El riesgo de la red es de
otro orden (research de la 008: CAP-090 «muy alto») y quien quiera que el
agente apague o cambie la swap no tiene por qué darle la red. No van en
`supervisor` (1.1.2: FR-010 de la 008 exige familias nuevas) ni en
`system_diagnostics` (013, solo lectura: su descripción dejaría de ser
verdad). La 022 usa `system_control` y `resolution_fixes`: sin choque.
Alternativa descartada: una sola familia `host` (más simple, pero obliga a
todo o nada con la red).

## R-2 — La interfaz por la que entra Hermes

Hermes corre en la red interna de Docker (`hassio`) y habla con el Supervisor
por ella: no ve por qué interfaz del host llega el cliente MCP. Lo que llega
de fuera (LAN, Funnel, un túnel) sale por la **ruta por defecto**, que
NetworkManager marca como `primary`. Por eso:

- **Rechazo fail-closed** (no solo aviso) al editar la principal: un error
  deja la casa sin Home Assistant y sin Hermes para deshacerlo, y el
  Supervisor no revierte (`apply_changes` sin temporizador, a diferencia de un
  commit-confirm). Nadie podría arreglarlo a distancia. Se rechaza también un
  cambio inocuo en la principal (`mdns`): una regla simple que no hay que
  razonar caso a caso; se hace desde la interfaz de HA, con acceso físico.
- **La única conectada** también se rechaza aunque no fuera `primary`
  (transitorios de NetworkManager): es igualmente el único camino.
- **Principal desconocida** (lectura fallida, ninguna `primary`, forma
  inesperada) → rechazo: si no se sabe, no se toca.
- `default` se rechaza como nombre: es la principal.
- La guarda se repite justo antes de enviar, y la huella del estado (R-6)
  incluye el papel de la interfaz: si pasa a principal en los 60 s, no se
  ejecuta.
- **VLAN sobre la madre principal**: se permite. Crear `eth0.20` no edita
  `eth0`; en equipos con una sola tarjeta es el único sitio donde crearla. El
  riesgo real es que la VLAN se quede con la ruta por defecto (gateway propio
  o DHCP con métrica menor): aviso fuerte en la vista previa.
- **Gateway en una interfaz secundaria**: aviso fuerte, no rechazo; es un uso
  legítimo (multi-WAN) y la vista previa lo dice.

Alternativas descartadas: solo aviso (el principio III pide fail-closed y la
008 dice «nunca»); detectar la interfaz del cliente por su IP (Hermes no la ve
detrás del proxy de ingress o del túnel, y adivinarla sería peor que la regla
simple).

## R-3 — `sv_reload_network` sin token

`host/network.py::update` solo llama a `sys_dbus.network.update()` y a
`check_connectivity(force=True)`: relee, no escribe. Con token, la tool
tendría que estar en `_DESTRUCTIVE_EXACT` (test
`test_every_tool_that_asks_for_a_token_says_it_is_destructive`) y la vista
previa tendría que anunciar un riesgo que no existe (principio V). Precedentes:
`sv_reload_supervisor` (022) y `sv_reload_mount` (019). FR-082 de la 008 dice
«con confirmación» para las tres; se interpreta como «todo **cambio** de red»,
que es lo que dice el criterio del supervisor del programa. Duda D-032-1 por si
el supervisor prefiere el texto literal.

## R-4 — Bloques completos

`interface_update` construye `IpSetting(method=config.get(METHOD, STATIC),
address=config.get(ADDRESS, []), …)`: un `ipv4={"nameservers": [...]}`
convierte la interfaz en estática **sin dirección**. `WifiConfig(auth=
config.get(AUTH, OPEN), ssid=… "")` convierte un Wi-Fi WPA en red abierta sin
nombre, y `psk=None` deja la conexión sin clave. Hermes no funde con lo actual
(no puede leer la PSK) y exige los campos que deciden el resultado (FR-008).
La vista previa enseña el bloque completo que se enviará, no un «diff» que
sugiera fusión.

## R-5 — Sin `force` al apagar

`force` salta la comprobación de migración de la base de datos de HA en
curso; apagar a mitad puede corromperla. `sv_reboot_host` (1.1.2) tampoco lo
expone. El error del Supervisor ya explica qué esperar.

## R-6 — Qué ata el token

Todos los argumentos tal como se envían (normalizados: `boot_slot` en
mayúsculas, bloques en orden canónico por `canonicalize_for_hash`) y, por
`estado=` (mecanismo de la 018, que usa la 019): `sv_set_hostname` → hostname
actual; `sv_set_swap` → swap actual (no `disk_free`, que cambia solo y
haría fallar casi cualquier token: `insufficient_disk` se repite al
confirmar); `sv_set_boot_slot` →
`boot` y `boot_slots`; `sv_update_network_interface` y `sv_create_vlan` → la
configuración de la interfaz (sin PSK y sin lo que fluctúa: `wifi.signal`,
`ready`), su `primary`/`connected` y el conjunto de interfaces
conectadas y la principal. `sv_shutdown_host` no tiene argumentos ni estado
que describa (como `sv_reboot_host`).

## R-7 — Validación de hostname, swap y VLAN

- Hostname: una etiqueta RFC 1123 en minúsculas (`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`).
  systemd admite más, pero un nombre con puntos o mayúsculas da sorpresas con
  mDNS; se pide lo seguro.
- Swap: la misma expresión que el Supervisor; tamaño en bytes con `K/M/G`
  binarios para comparar con `disk_free` (GiB). Si el tamaño no cabe en el
  disco libre, `insufficient_disk`: una swap que llena el disco de datos para
  Core.
- VLAN: 1–4094. El Supervisor admite 0 (etiquetado de prioridad, no una VLAN)
  y Hermes lo rechaza: nadie lo pide a propósito.

## R-8 — Fuera de alcance

- Borrar una VLAN: no hay ruta en la v1; la v2 es de la 027.
- Escanear Wi-Fi y leer la red: 013 (`read` por la tabla).
- `POST /host/reload`, `/host/reboot`: 022 y 1.1.2.
- Montajes y disco de datos: 019 y 013.

## R-9 — La PSK y el disco

`create_confirmation_token` guarda en disco el `action_hash`; hoy (base
`0b7d5e2`) es SHA-256 sin clave de los argumentos, que con una PSK débil
permitiría un ataque de diccionario sin conexión a quien lea
`/data/pending_confirmations`. La 019 lo cambia a **HMAC-SHA256 con clave en
memoria**: con eso, el hash no revela nada sin la clave. Por eso el tramo 2
necesita la 019 integrada (T014 lo comprueba y se detiene si no está). La PSK
no es omitible (no se guarda), se rechaza si es el marcador de redacción o
lleva caracteres de control, y sus centinelas se buscan en todo el directorio
de tokens.

## R-10 — Corte de conexión tras enviar

Apagar y la ranura de arranque tumban el host; un cambio de red puede cortar
la respuesta. Un `HAConnectionError` **después** de enviar no es un fallo
seguro: se responde `{"outcome": "unknown", "hint": …, "verify_with": …}`
(`sv_get_os_info` tras la ranura, `sv_read_api("/network/interface/<i>/info")`
tras la red) y el token se completa como fallido con ese motivo. Antes de
enviar (lecturas de la vista previa), un error es un error.

## R-11 — Log

Eventos `host_control` y `host_network` con `tool`, `outcome`, `changed`
(nombres de claves) e `interface` (nombre de dispositivo). Nada de hostname,
direcciones, DNS, SSID, MAC ni PSK: el log se pega en issues públicos
(principio VIII). Es menos de lo que ya registra Hermes para el Supervisor
(plantilla de ruta y resultado).

## R-12 — Tramos

Dos, como dice la 008: tramo 1 `host_control` (CAP-086, 4 tools), tramo 2
`host_network` (CAP-090, 3 tools). El 2 necesita el 1 (familias, tema de la
guía, fixtures) y la 019 (R-9).
