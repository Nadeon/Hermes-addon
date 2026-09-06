"""Hermes — Detección de crash loop.

Si el add-on ha registrado >10 arranques previos en los últimos 5 minutos,
aborta inmediatamente para proteger el disco (especialmente SD cards).
El arranque actual NO se cuenta: se cumple >10 cuando hay 11+ entradas previas
en la ventana, lo que equivale al 12º arranque real como primer disparo real.
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

    Si detecta crash loop (>CRASH_THRESHOLD arranques en CRASH_WINDOW_SECONDS),
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
            # NO sobrescribir → preserva el fichero en disco para que el
            # próximo boot con lectura exitosa vea el histórico real.
            # Un único crash a media escritura no debe resetear el contador.
            file_was_corrupt = True
            logger.warning(
                "startup_log_corrupt",
                path=str(STARTUP_LOG_PATH),
                message=(
                    "startup_log.json is corrupt, likely due to a crash "
                    "during atomic write. Skipping write this boot to "
                    "preserve existing data."
                ),
            )

    # 2. Contar, SIN añadir el actual aún
    recent_count = sum(1 for ts in entries if (now - ts) < CRASH_WINDOW_SECONDS)

    # 3. Decidir
    if recent_count > CRASH_THRESHOLD:
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

    # 4. Registrar el arranque actual (solo si no es crash loop
    #    Y el fichero no estaba corrupto — en ese caso preservamos el original)
    if file_was_corrupt:
        return

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
