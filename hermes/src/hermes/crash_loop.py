"""Hermes — Detección de crash loop.

Si el add-on ha registrado 10 o más arranques previos en los últimos 5 minutos,
aborta inmediatamente para proteger el disco (especialmente SD cards).
El arranque actual NO se cuenta: con `>= CRASH_THRESHOLD` el disparo ocurre en
el 11º arranque real (10 entradas previas en la ventana).

El umbral era `> CRASH_THRESHOLD`, es decir 11 entradas previas y por tanto el
12º arranque. Ese disparo no llegaba nunca: el watchdog del Supervisor se rinde
alrededor del 10º-11º reinicio, así que la guarda quedaba siempre por detrás de
quien la iba a activar y el disco recibía la tanda entera de reinicios sin que
nadie la parase.

El orden es leer-contar-decidir antes de escribir.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

STARTUP_LOG_PATH = Path("/data/startup_log.json")
CRASH_WINDOW_SECONDS = 300  # 5 minutos
CRASH_THRESHOLD = 10
RING_BUFFER_SIZE = 20


def check_crash_loop() -> None:
    """Comprueba y registra el arranque actual.

    Si detecta crash loop (>=CRASH_THRESHOLD arranques en CRASH_WINDOW_SECONDS),
    sale con sys.exit(1) SIN escribir nada — protege el disco.
    """
    now = time.time()

    # 1. Leer (solo lectura)
    entries: list[float] = []
    file_was_corrupt = False

    if STARTUP_LOG_PATH.exists():
        try:
            raw = STARTUP_LOG_PATH.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                entries = [float(ts) for ts in parsed if isinstance(ts, (int, float))]
        except (json.JSONDecodeError, OSError, ValueError):
            # Fichero corrupto (crash previo durante escritura atómica).
            # Antes se preservaba el fichero sin tocarlo, pero un fichero
            # corrupto NUNCA se vuelve legible solo: la guarda se quedaba
            # desactivada para siempre, que es justo lo contrario de proteger
            # el disco. Se reescribe con el arranque actual, aceptando el coste
            # de perder el histórico de esta ventana (como mucho, un ciclo de
            # crash loop más antes de que la guarda vuelva a disparar).
            file_was_corrupt = True
            entries = []
            logger.warning(
                "startup_log_corrupt",
                path=str(STARTUP_LOG_PATH),
                message=(
                    "startup_log.json is corrupt, likely due to a crash "
                    "during atomic write. Resetting it to the current boot "
                    "so the crash-loop guard stays active."
                ),
            )

    # 2. Contar, SIN añadir el actual aún
    recent_count = sum(1 for ts in entries if (now - ts) < CRASH_WINDOW_SECONDS)

    # 3. Decidir
    if recent_count >= CRASH_THRESHOLD:
        logger.critical(
            "crash_loop_detected",
            starts_in_window=recent_count,
            window_seconds=CRASH_WINDOW_SECONDS,
            message=(
                f"Crash loop detectado ({recent_count} arranques en "
                f"{CRASH_WINDOW_SECONDS // 60} min). Abortando para proteger "
                f"el disco. Revisa los logs manualmente, para y arranca "
                f"el add-on a mano tras corregir el problema."
            ),
        )
        sys.exit(1)

    # 4. Registrar el arranque actual (solo si no es crash loop). Si el
    #    fichero estaba corrupto, `entries` viene vacío y esto lo deja en
    #    [now], que es exactamente la reescritura que lo devuelve a servicio.
    if file_was_corrupt:
        logger.info("startup_log_reset", path=str(STARTUP_LOG_PATH))

    entries.append(now)
    # Ring buffer: mantener solo las últimas N entries
    entries = entries[-RING_BUFFER_SIZE:]

    try:
        tmp_path = STARTUP_LOG_PATH.with_suffix(".tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(entries), encoding="utf-8"
        )
        os.replace(str(tmp_path), str(STARTUP_LOG_PATH))
    except OSError as exc:
        # Si no podemos escribir, continuar — no abortar por un log
        logger.warning(
            "startup_log_write_failed",
            error=str(exc),
        )
