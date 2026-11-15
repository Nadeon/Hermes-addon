# Quickstart: host y red del host (032)

Cómo comprobar la sub-feature al terminar cada tramo (sin tocar ninguna
instalación real).

## Suite

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <python del .venv> -m pytest -q -p no:cacheprovider
# Solo esta sub-feature:
... -m pytest -q -p no:cacheprovider tests/test_tools_host_control.py tests/test_tools_host_network.py
```

Deben fallar exactamente los 6 conocidos de Windows.

## Tabla

```bash
grep -c "spec 032" hermes/src/hermes/command_table.py   # 3 tras el tramo 1, 0 tras el 2
python scripts/inventario/generar_tabla.py               # y después:
git diff --exit-code hermes/src/hermes/command_table.py
```

## Flujo esperado (Supervisor simulado)

1. `sv_set_hostname("casa-ha")` → vista previa `homeassistant → casa-ha`,
   aviso mDNS, token.
2. La misma llamada con `confirmation_token` → `POST /host/options`.
3. `sv_update_network_interface("eth0", mdns="off")` con `eth0` principal →
   `primary_interface`, sin token.
4. `sv_update_network_interface("wlan0", wifi={…, "psk": "PSK-CENTINELA-032"},
   ipv4={"method": "auto"})` → vista previa con `"psk": "set"`; buscar el
   centinela en la respuesta, en `capture_logs` y en `CONFIRMATIONS_DIR`: cero
   apariciones.

## En la VM de la 014 (pendiente)

Ver «Pruebas en vivo» en [plan.md](plan.md) y las filas de la matriz.
