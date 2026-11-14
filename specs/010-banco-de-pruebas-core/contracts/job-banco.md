# Contrato: job `banco-core` de `.github/workflows/tests.yml`

Lo que el job garantiza a quien mira el CI y a las sub-features que añadan
tests al banco.

## Identidad

- Clave del job: `banco-core`. Nombre del check: `banco de Core`. Ninguno de los
  dos lleva la versión de HA, para que el check obligatorio no cambie de nombre
  al subir de versión.
- Disparadores: los del workflow (`push`, `pull_request`, `schedule` semanal).
- Sin `continue-on-error`. `timeout-minutes: 20`. `runs-on: ubuntu-latest`.

## Entorno

```yaml
env:
  HA_IMAGEN: ghcr.io/home-assistant/home-assistant:2026.11.1@sha256:6785d1eca68747a524c156faae1b139ed415c07357386ae6fe17291986e59e82
```

`HA_IMAGEN` se declara una sola vez, a nivel del job, con esa forma exacta
(`<repo>:<etiqueta>@sha256:<64 hex>`): es lo que lee el test de FR-001.

## Pasos (en este orden)

1. Checkout (`actions/checkout@v5`).
2. Python 3.13 (`actions/setup-python@v5`, caché de pip).
3. Dependencias: las del job `pytest` más `pytest-timeout`.
4. Descargar la imagen: `docker pull "$HA_IMAGEN"`, hasta 3 intentos con
   esperas de 10 y 30 s.
5. Preparar la configuración: copiar `tests/banco/ha_config/` a
   `$RUNNER_TEMP/ha_config`.
6. Red sin salida: `docker network create hermes-banco`; leer su subred con
   `docker network inspect`; `sudo iptables -I DOCKER-USER -s <subred> ! -d <subred> -j REJECT`.
7. Arrancar HA: `docker run -d --name ha-banco --network hermes-banco -p 127.0.0.1:8123:8123 -v "$RUNNER_TEMP/ha_config:/config" -e TZ=Etc/UTC "$HA_IMAGEN"`.
8. Esperar al HTTP: sondear `http://127.0.0.1:8123/api/onboarding` cada 2 s,
   como mucho 300 s; si no llega, fallar con «HA no respondió en 300 s».
9. Comprobar la red: desde dentro del contenedor, con el `python3` de la
   propia imagen, `tests/banco/sin_salida.py` abre TCP a IP literales
   (`1.1.1.1:443` y `8.8.8.8:443`, 5 s de tope, sin DNS ni HTTP). Solo si todas
   fallan a nivel de red el paso pasa; si alguna se establece, o el script no
   se puede ejecutar, falla con «el contenedor de HA tiene salida a internet».
   (T040: la versión con `urllib` daba por buena una respuesta 429 o 5xx.)
10. Preparar `/data` como el job `pytest` (`sudo mkdir -p /data && sudo chmod 777 /data`).
11. Ejecutar: `pytest -m banco tests/banco -q -p no:cacheprovider --timeout=120`
    con `HERMES_BANCO_HA_URL=http://127.0.0.1:8123`,
    `HERMES_BANCO_OBLIGATORIO=1` y `HERMES_CONFIG_BASE=${{ runner.temp }}/hermes_config`.
12. «La suite no debe escribir fuera del árbol»: la misma comprobación de
    `/data` que el job `pytest`.
13. `if: failure()`: `docker logs --tail 200 ha-banco`.
14. `if: always()`: `docker rm -f ha-banco` y borrar la red.

## Garantías

- El job falla si: la imagen no se descarga; HA no arranca; el contenedor sale
  a internet; el onboarding falla; algún test del banco falla o se salta
  (la obligatoriedad convierte los saltos en fallos); pytest no recoge ningún
  test (código de salida 5); la suite escribe en `/data`.
- Ninguna credencial aparece en el log del job: se generan dentro de pytest y
  no se imprimen (FR-012).
- Duración esperada: menos de 10 minutos; tope 20.

## Para las sub-features que añaden tests al banco

- Ficheros `tests/banco/test_banco_*.py` con `pytestmark = pytest.mark.banco`.
- El entorno se pide a `tests/banco/entorno.py`; el efecto se comprueba con
  `tests/banco/lector.py`, nunca con el propio Hermes.
- Si necesitan un dominio más en HA, lo añaden a
  `tests/banco/ha_config/configuration.yaml` en su propio cambio.
- Si necesitan una ruta más del Supervisor, la añaden al simulado y a
  [supervisor-simulado.md](supervisor-simulado.md) con su test de contrato.
