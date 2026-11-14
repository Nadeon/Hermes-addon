# Validación rápida: banco de pruebas del Supervisor (spec 014)

## Requisitos

- El worktree de la rama, el `.venv` del checkout principal y una carpeta
  propia para `HERMES_CONFIG_BASE`. Nada más: ni Docker, ni HA, ni red.

## 1. Suite completa

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta propia>)" <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Esperado en Windows: exactamente los 6 fallos conocidos. En el CI de Linux,
todo en verde.

## 2. Solo lo de la 014

```bash
<venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider \
  tests/test_matriz_pruebas.py tests/test_rutas_supervisor_rol.py \
  tests/test_addon_manifest.py
```

Esperado: todo pasa.

## 3. Controles negativos (FR-010)

Cada uno se aplica, se ve caer y se restaura (`git checkout -- <fichero>`):

| Cambio | Cae |
|---|---|
| Borrar la fila de `sv_reboot_host` de la matriz | `test_una_fila_por_tool_que_modifica`, nombrándola |
| Poner `ok` sin nota a `sv_restart_core` | `test_notas_obligatorias` |
| Poner `banco de Core` a `fs_write_file` | `test_sv_y_fs_en_la_vm` (y la regla de `FUERA_DEL_BANCO`, si la 028 está) |
| Poner `pendiente` a una tool de `PROBADAS_EN_BANCO` | `test_coherente_con_los_inventarios` |
| Devolver el comentario viejo de `hassio_role` | `TestComentarioDelRol` |
| `hassio_role: manager` | `TestComentarioDelRol` (el rol no cambia en este programa) |
| Añadir `await ha_client.sv_request("GET", "/auth/list")` en una tool | `test_rutas_de_hermes_caben_en_manager`, nombrando la ruta |
| Quitar `(?!security)` del patrón copiado de `manager` | `test_patrones_copiados_rechazan_lo_de_admin` |

## 4. Lectura

- `docs/BANCO-SUPERVISOR.md` se entiende sin la spec, tiene las once secciones
  y ningún dato real.
- En la hoja de ruta, la matriz está tras el banco de Core, enlaza el
  procedimiento, y las casillas manuales dicen su entorno.
- `git diff --stat feat/cobertura-total -- hermes/` solo muestra
  `config.yaml` (comentario) y `CHANGELOG.md`.

## 5. Lo que NO se valida aquí

Montar la VM y ejecutar las tandas: es la prueba manual del final, siguiendo
`docs/BANCO-SUPERVISOR.md`, y su resultado se anota en la matriz.
