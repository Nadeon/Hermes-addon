"""Lectura de los jobs del Supervisor (`GET /jobs/{uuid}`) compartida.

Vive en un módulo propio, sin dependencias de las tools, porque la usan
`tools/backups.py`, `fs_write.py` y `safety_retention.py`, y `backups.py` ya
importa `safety_retention`: tenerla en `backups.py` creaba un import circular
(alertas de CodeQL de la revisión 1.1.0).
"""

from __future__ import annotations

from typing import Any

from hermes.security import redact_secrets

# Tope de cada mensaje de error de un job. El Supervisor puede devolver trazas
# largas; al cliente le basta el motivo.
JOB_ERROR_MAX_CHARS = 500


def job_errors(data: Any) -> list[str]:
    """Mensajes de error de un job del Supervisor (`GET /jobs/{uuid}`), saneados.

    El job termina con `done: true` TAMBIÉN cuando falla, y los motivos van en
    `errors` (lista de `{type, message, stage}`). Solo se toma `message`: el
    resto no aporta al cliente. Se recorta y se pasa por `redact_secrets`
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
        mensajes.append(redact_secrets(mensaje[:JOB_ERROR_MAX_CHARS]))
    return mensajes
