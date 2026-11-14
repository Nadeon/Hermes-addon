# Guía de validación: pruebas de las escrituras de Core en el banco (spec 028)

Cómo comprobar que la 028 funciona. El banco y su arranque son los de la 010:
[quickstart de la 010](../010-banco-de-pruebas-core/quickstart.md).

## 1. Suite normal (cualquier sistema, sin Docker)

Desde la raíz del repositorio (Git Bash en Windows):

```bash
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta temporal propia>)" <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider -rs
```

Esperado:

- `tests/test_banco_cobertura_escrituras.py` en verde: las 124 tools que
  modifican, clasificadas (contrato en
  [contracts/inventario-de-escrituras.md](contracts/inventario-de-escrituras.md)).
- Los tests de `tests/banco/` (también los `test_banco_escrituras_*.py`)
  saltados con el motivo de la 010 (falta `HERMES_BANCO_HA_URL`).
- En Windows, exactamente los 6 fallos conocidos.

## 2. Banco en el CI

Push de la rama y `gh run watch` del workflow `Tests`. En el job
`banco de Core`:

- `pytest -m banco tests/banco` ejecuta el humo, los helpers de la 010 y los
  `test_banco_escrituras_*.py`, con **0 saltados**.
- Cada tool de [data-model.md](data-model.md) pasa o figura como `XFAIL` con su
  motivo `HALLAZGO` (nunca `XPASS`).
- Duración del job por debajo de 10 minutos.

## 3. Banco en local con Docker (opcional)

Como en la 010: arrancar el contenedor con `tests/banco/ha_config` copiado a
una carpeta temporal y exportar `HERMES_BANCO_HA_URL`. La carpeta copiada lleva
ya `automations.yaml`, `scripts.yaml` y `scenes.yaml`, y la configuración carga
`frontend` y `kitchen_sink`.

```bash
pytest -m banco tests/banco/test_banco_escrituras_automatizacion.py -q -p no:cacheprovider
```

## 4. Comprobaciones rápidas de la configuración del banco

Con el banco arrancado, el lector (o `curl` con el token de larga duración)
debe ver:

- `config_entries/get` con una entrada de `kitchen_sink` en estado `loaded`
  (tramo B).
- `repairs/list_issues` con avisos de dominio `kitchen_sink` (tramo B).
- `lovelace/dashboards/list` sin error (tramo A).
- `GET /api/config/automation/config/<id-inexistente>` → 404, no 400 ni 500
  (tramo A: `automation:` cargado con su fichero).
