"""Registro de los flujos de configuración que abre Hermes (spec 016, T048).

POR QUÉ existe (decisión del supervisor, cierre fail-closed de FR-010c): HA no
dice el origen de un flujo por su `flow_id`. El `GET` de un flujo no trae su
`context`, y `config_entries/flow/progress` lista los de descubrimiento y los
`reauth` pero excluye por igual los `user` y los `reconfigure`. Así que, para
`ha_continue_config_entry_flow`, un flujo que no está en `flow/progress` puede
ser un `user` que abrió Hermes o un `reconfigure` (abierto antes de reiniciar
Hermes o desde la interfaz de HA) que la vía general enviaría sin token.

La salida: Hermes apunta los `flow_id` que abre `ha_start_config_entry_flow`
(siempre de origen `user`). La vía general solo continúa un flujo que esté
aquí o en `flow/progress`; cualquier otro se rechaza sin tocar HA.

En memoria, con caducidad y con límite, para que no crezca sin fin. Olvidar
un flujo es fail-closed: deja de poder continuarse por la vía general y hay
que abrirlo de nuevo. Al reiniciar Hermes el registro empieza vacío, con el
mismo efecto.
"""

from __future__ import annotations

import time

# Una hora desde el último uso, como los reconfigure (`_reconfigure.py`): un
# flujo de configuración es interactivo, y uno olvidado no debe seguir
# aceptándose para siempre.
CADUCIDAD_S = 3600.0

# Flujos abiertos a la vez. Muy por encima de un uso normal (uno o dos a la
# vez); al pasarlo se olvidan primero los caducados y después los de uso más
# antiguo.
LIMITE = 100

# flow_id -> último uso (reloj monótono).
_REGISTRO: dict[str, float] = {}


def _ahora() -> float:
    # Reloj monótono: un cambio de hora del sistema no caduca nada. Los tests
    # lo sustituyen para adelantar el tiempo.
    return time.monotonic()


def _caducado(ultimo_uso: float) -> bool:
    return _ahora() - ultimo_uso > CADUCIDAD_S


def registrar(flow_id: str) -> None:
    _REGISTRO[flow_id] = _ahora()
    if len(_REGISTRO) <= LIMITE:
        return
    for fid, uso in list(_REGISTRO.items()):
        if _caducado(uso):
            del _REGISTRO[fid]
    while len(_REGISTRO) > LIMITE:
        mas_antiguo = min(_REGISTRO, key=_REGISTRO.__getitem__)
        del _REGISTRO[mas_antiguo]


def conocido(flow_id: str) -> bool:
    """`True` si Hermes abrió ese flujo y no ha caducado.

    Un caducado se olvida aquí mismo: a partir de ahora se trata como
    cualquier flujo desconocido.
    """
    uso = _REGISTRO.get(flow_id)
    if uso is None:
        return False
    if _caducado(uso):
        del _REGISTRO[flow_id]
        return False
    return True


def tocar(flow_id: str) -> None:
    if flow_id in _REGISTRO:
        _REGISTRO[flow_id] = _ahora()


def olvidar(flow_id: str) -> None:
    _REGISTRO.pop(flow_id, None)


def limpiar() -> None:
    """Vacía el registro (para los tests)."""
    _REGISTRO.clear()
