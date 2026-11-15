"""Lectura de los jobs del Supervisor (`GET /jobs/{uuid}`) compartida.

Vive en un módulo propio, sin dependencias de las tools, porque la usan
`tools/backups.py`, `fs_write.py` y `safety_retention.py`, y `backups.py` ya
importa `safety_retention`: tenerla en `backups.py` creaba un import circular
(alertas de CodeQL de la revisión 1.1.0).
"""

from __future__ import annotations

from typing import Any

from hermes.security import redact_secrets, redact_structure

# Tope de cada mensaje de error de un job. El Supervisor puede devolver trazas
# largas; al cliente le basta el motivo.
JOB_ERROR_MAX_CHARS = 500

# Topes del recorrido de los sub-jobs (`child_jobs`). Un backup completo tiene
# un sub-job por app: 20 errores bastan para decidir, y 5 niveles cubren con
# holgura los anidamientos del Supervisor 2026.11.0 (backup → apps → app).
CHILD_ERRORS_MAX = 20
CHILD_JOBS_MAX_DEPTH = 5


def job_errors(data: Any) -> list[str]:
    """Mensajes de error de un job del Supervisor (`GET /jobs/{uuid}`), saneados.

    El job termina con `done: true` TAMBIÉN cuando falla, y los motivos van en
    `errors` (lista de `{type, message, stage}`). Solo se toma `message`: el
    resto no aporta al cliente. Se pasa por `redact_secrets` y luego se recorta
    porque el texto del Supervisor puede citar opciones o rutas con secretos.
    Un error sin `message` de texto cuenta igual como error: perderlo haría
    pasar un job fallido por correcto.
    """
    if not isinstance(data, dict):
        return []
    errores = data.get("errors")
    if not isinstance(errores, list):
        return []
    mensajes: list[str] = []
    for error in errores:
        mensaje = error.get("message") if isinstance(error, dict) else None
        if not isinstance(mensaje, str) or not mensaje:
            mensaje = "unknown error"
        mensajes.append(_redactar_y_recortar(mensaje))
    return mensajes


def _redactar_y_recortar(mensaje: str) -> str:
    """Redacta el mensaje ENTERO y solo después lo recorta.

    Al revés, un secreto que cruzaba el carácter 500 (un JWT, por ejemplo)
    llegaba cortado a `redact_secrets`, ya no encajaba en el patrón y salía a
    medias: cabecera y parte del payload (revisión de la 027, T028).
    """
    return redact_secrets(mensaje)[:JOB_ERROR_MAX_CHARS]


def _mensaje(error: Any) -> str:
    mensaje = error.get("message") if isinstance(error, dict) else None
    if not isinstance(mensaje, str) or not mensaje:
        mensaje = "unknown error"
    return _redactar_y_recortar(mensaje)


def child_job_errors(data: Any) -> tuple[list[dict[str, Any]], bool]:
    """Errores de los sub-jobs (`child_jobs`) de un job, en profundidad.

    El Supervisor 2026.11.0 guarda cada error en el job que lo captura y NO lo
    copia al padre (`jobs/__init__.py`, `capture_error`; `api/jobs.py`,
    `_list_jobs`): una app que no se pudo guardar en un backup completo deja
    el error en un sub-job y el job del backup termina con `errors: []`.
    Mirando solo `errors`, ese backup incompleto pasaba por correcto.

    Devuelve `([{job, message}], recortado)`. `job` es el `name` del sub-job
    si es texto (un identificador interno como `backup_store_apps`) o `None`;
    `message` se trata igual que en `job_errors`. `recortado` es `True` si se
    alcanzó el tope de entradas o si había sub-jobs por debajo del tope de
    niveles: quien decide si el job salió bien no puede darlo por bueno sin
    haberlo mirado todo (principio III).

    Recorrido iterativo con pila, en el orden de la respuesta, para no
    depender de la recursión con una respuesta rara. Las entradas que no
    tienen la forma esperada se ignoran: nunca se inventa un error.
    """
    if not isinstance(data, dict):
        return [], False
    salida: list[dict[str, Any]] = []
    recortado = False
    hijos = data.get("child_jobs")
    # Pila de (sub-job, nivel), con los hermanos en orden inverso para que el
    # primero de la respuesta salga el primero.
    pila: list[tuple[Any, int]] = (
        [(h, 1) for h in reversed(hijos)] if isinstance(hijos, list) else []
    )
    while pila:
        hijo, nivel = pila.pop()
        if not isinstance(hijo, dict):
            continue
        if nivel > CHILD_JOBS_MAX_DEPTH:
            recortado = True
            continue
        errores = hijo.get("errors")
        if isinstance(errores, list):
            nombre = hijo.get("name")
            for error in errores:
                if len(salida) >= CHILD_ERRORS_MAX:
                    return salida, True
                salida.append({
                    "job": nombre if isinstance(nombre, str) else None,
                    "message": _mensaje(error),
                })
        nietos = hijo.get("child_jobs")
        if isinstance(nietos, list):
            pila.extend((n, nivel + 1) for n in reversed(nietos))
    return salida, recortado


def child_errors_as_text(errores: list[dict[str, Any]], recortado: bool) -> list[str]:
    """Los errores de los sub-jobs como líneas `"<sub-job>: <mensaje>"`.

    Para los sitios que informan con una lista de textos (el sondeo del safety
    backup). Si el recorrido se recortó, lo dice en una línea más: callarlo
    daría por revisado lo que no se miró.
    """
    lineas = [f"{e['job'] or 'sub-job'}: {e['message']}" for e in errores]
    if recortado:
        lineas.append("more sub-jobs not checked (limit reached)")
    return lineas


def redact_child_jobs(child_jobs: Any) -> Any:
    """`child_jobs` de la respuesta del Supervisor, con los secretos tapados.

    `sv_get_job_status` devuelve `child_jobs` entero además de `child_errors`.
    Sin esto, un secreto en el error de un sub-job salía en claro por ahí
    aunque `child_errors` lo tapara (hallazgo de la revisión de la 027). Se
    aplican las dos redacciones: `redact_structure`, para los valores bajo
    claves sensibles (`password`, `token`…, p. ej. en `extra_fields`), y
    `redact_secrets` en cada texto, la misma que `child_errors`, porque el
    secreto suele ir DENTRO de `message`, una clave que no es sensible.
    """
    return _redactar_textos(redact_structure(child_jobs))


def _redactar_textos(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _redactar_textos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar_textos(v) for v in valor]
    if isinstance(valor, str):
        return redact_secrets(valor)
    return valor
