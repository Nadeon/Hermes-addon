# Validación: banco de pruebas de Core (spec 010)

Guía para comprobar que el banco funciona. El detalle de cada pieza está en
[contracts/job-banco.md](contracts/job-banco.md),
[contracts/supervisor-simulado.md](contracts/supervisor-simulado.md) y
[data-model.md](data-model.md).

## 1. En local, sin Docker (Windows o cualquier sistema)

Desde la raíz del worktree, en Git Bash:

```
export MSYS_NO_PATHCONV=1
HERMES_CONFIG_BASE="$(cygpath -w <carpeta-temporal-propia>)" \
  <venv>/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Esperado:

- Pasan los tests nuevos de la suite normal: `tests/test_banco_supervisor_simulado.py`,
  `tests/test_banco_onboarding.py`, `tests/test_banco_entorno.py`,
  `tests/test_banco_workflow.py` y (desde el tramo B) `tests/test_banco_cobertura.py`.
- Los de `tests/banco/` aparecen como saltados con el motivo «banco de Core no
  configurado: falta HERMES_BANCO_HA_URL…» (`pytest -rs` lo muestra).
- Fallan exactamente los 6 tests conocidos de Windows y nada más.

Solo el banco, para ver los motivos:

```
<venv>/Scripts/python.exe -m pytest -m banco tests/banco -rs -q -p no:cacheprovider
```

Con `HERMES_BANCO_OBLIGATORIO=1` delante, los mismos tests **fallan** en vez
de saltarse.

## 2. En local, con Docker (Linux, macOS o WSL)

Reproduce el job (ver los pasos exactos en el contrato del job):

```
docker pull "<HA_IMAGEN del workflow>"
cp -r tests/banco/ha_config /tmp/ha_config_banco
docker run -d --name ha-banco -p 127.0.0.1:8123:8123 \
  -v /tmp/ha_config_banco:/config -e TZ=Etc/UTC "<HA_IMAGEN>"
# esperar a que http://127.0.0.1:8123/api/onboarding responda 200
HERMES_BANCO_HA_URL=http://127.0.0.1:8123 HERMES_BANCO_OBLIGATORIO=1 \
  python -m pytest -m banco tests/banco -q -p no:cacheprovider
docker rm -f ha-banco && rm -rf /tmp/ha_config_banco
```

Cada ejecución necesita un contenedor y una copia de la configuración nuevos:
el onboarding solo se puede hacer una vez. En local no se corta la salida a
internet (es una regla de `iptables` del runner); el resultado de los tests no
depende de ello.

## 3. En el CI

```
git push origin feat/010-banco-de-pruebas-core
gh run watch            # elegir la ejecución del workflow Tests
gh run view --log-failed  # solo si falla
```

Esperado: los jobs `pytest (3.12)`, `pytest (3.13)` y `banco de Core` en
verde. En el log del banco: los tests del banco ejecutados (ninguno saltado),
la comprobación de red superada y ninguna credencial impresa.

## 4. Controles negativos del banco (una vez por tramo)

En una rama desechable (`prueba/010-control-a` o `-b`), con el cambio que debe
romper el banco (research R-9):

```
git switch -c prueba/010-control-a
# introducir el fallo, commit
git push origin prueba/010-control-a
gh run watch              # el job «banco de Core» tiene que acabar en rojo
git push origin --delete prueba/010-control-a
git switch feat/010-banco-de-pruebas-core && git branch -D prueba/010-control-a
```

Anotar en el commit del tramo qué se rompió y qué tests cayeron.

## 5. Después de fusionar (mantenedor)

- Añadir el check `banco de Core` a los checks obligatorios del ruleset del
  repositorio.
- La 011 aplica la enmienda E-3 (puerta 4 de la constitución).
