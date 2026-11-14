"""Hermes — Tools MCP para las trazas de automatizaciones y scripts.

Usa `trace/list` y `trace/get` (sin cambios de esquema desde 2024.10). Una
traza responde a «¿por qué no saltó / por qué falló?», pero en crudo pesa de
KB a cientos de KB y lleva estados con todos sus atributos (URLs de cámara
con `token=`, variables con credenciales…). Por eso:

- por defecto se devuelve un resumen (cabecera y, por paso, ruta, momento,
  resultado recortado y error), sin configuración ni variables;
- `detail="full"` añade variables y configuración, redactadas;
- ninguna respuesta supera `min(64 KiB, response_max_bytes)`: se recorta por
  partes enteras, nunca cortando el JSON a medias.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from hermes.ha import HAClient, HAConnectionError
from hermes.security import redact_secrets, redact_structure
from hermes.tools._common import requires_ready

logger = structlog.get_logger(__name__)

_DOMINIOS: tuple[str, ...] = ("automation", "script")
_DETALLES: tuple[str, ...] = ("summary", "full")
_LIMITE_MIN, _LIMITE_MAX = 1, 50

# Límite propio de las trazas, por debajo de lo que aguantan los clientes: una
# traza completa puede rondar el MB y casi nunca hace falta entera.
_TRACE_MAX_BYTES = 65536

_MAX_TEXTO_LISTA = 300   # `trigger` y `error` en cabeceras
_MAX_TEXTO_PASO = 500    # `result` y `error` de cada paso

# Tope por cadena dentro de variables y configuración, aplicado ANTES de
# redactar. Dos motivos: los patrones de `redact_secrets` tienen coste
# cuadrático con cadenas largas sin espacios (30 KB tardan ~0,4 s), y un
# atributo enorme (una imagen en base64, una lista de eventos) no ayuda a
# diagnosticar. 4096 caracteres se redactan en milisegundos.
_MAX_CADENA = 4096
_COLA_SIN_ESPACIOS = re.compile(r"\S*$")


def _invalid(field: str, detail: str) -> str:
    return json.dumps(
        {"error": "invalid_argument", "field": field, "detail": detail}
    )


def _acotar(texto: str, maximo: int) -> str:
    """Recorta `texto` a `maximo` caracteres sin dejar un secreto a medias.

    Se recorta antes de redactar (ver `_MAX_CADENA`), así que el corte podría
    caer dentro de un secreto (`https://user:pass…` sin la `@`) y dejar un
    trozo que ningún patrón reconoce. Por eso se descarta también la última
    palabra cortada: los secretos que buscan los patrones no llevan espacios.
    """
    if len(texto) <= maximo:
        return texto
    corte = _COLA_SIN_ESPACIOS.sub("", texto[:maximo])
    return f"{corte}…[{len(texto) - len(corte)} chars omitted]"


def _redactar(valor: Any) -> Any:
    """Redacta por clave y por patrón en cada texto de la estructura.

    Las dos capas hacen falta: la clave tapa `{"access_token": "…"}`, pero la
    URL de imagen de una cámara (`/api/camera_proxy/…?token=…`) va bajo una
    clave inocente (`entity_picture`) y solo la detecta el patrón.
    """
    valor = redact_structure(valor)
    if isinstance(valor, dict):
        return {k: _redactar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_redactar(v) for v in valor]
    if isinstance(valor, str):
        return redact_secrets(_acotar(valor, _MAX_CADENA))
    return valor


def _texto(valor: Any, maximo: int) -> str | None:
    """Texto redactado y recortado; lo que no es texto se serializa antes.

    Se redacta ANTES de recortar: recortar primero podría partir un secreto
    por la mitad y dejar un trozo que el patrón ya no reconoce.
    """
    if valor is None:
        return None
    if not isinstance(valor, str):
        valor = json.dumps(_redactar(valor), ensure_ascii=False, default=str)
    # Margen de sobra antes de redactar: la marca de redacción puede ser más
    # larga que el secreto que sustituye.
    return redact_secrets(_acotar(valor, maximo * 2))[:maximo]


def _cabecera(traza: dict[str, Any]) -> dict[str, Any]:
    ts = traza.get("timestamp")
    ts = ts if isinstance(ts, dict) else {}
    out: dict[str, Any] = {
        "run_id": traza.get("run_id"),
        "item_id": traza.get("item_id"),
        "state": traza.get("state"),
        "script_execution": traza.get("script_execution"),
        "start": ts.get("start"),
        "finish": ts.get("finish"),
        "last_step": traza.get("last_step"),
        "trigger": _texto(traza.get("trigger"), _MAX_TEXTO_LISTA),
        "error": _texto(traza.get("error"), _MAX_TEXTO_LISTA),
    }
    if "not_triggered" in traza:
        out["not_triggered"] = traza.get("not_triggered")
    return out


def _clave_inicio(traza: dict[str, Any]) -> str:
    ts = traza.get("timestamp")
    inicio = ts.get("start") if isinstance(ts, dict) else None
    return inicio if isinstance(inicio, str) else ""


def _child_id(valor: Any) -> dict[str, Any] | None:
    # En HA es {"domain", "item_id", "run_id"}; solo se copian esas claves.
    if not isinstance(valor, dict):
        return None
    return {k: valor.get(k) for k in ("domain", "item_id", "run_id") if k in valor}


def _pasos(traza: dict[str, Any], completo: bool) -> tuple[list[dict[str, Any]], int, bool]:
    """Aplana `trace` (ruta → lista de elementos) en pasos ordenados por tiempo.

    Devuelve (pasos, no_reconocidos, disponible). Lo que no tiene la forma
    esperada se cuenta y se omite: nunca se devuelve el objeto crudo, que
    podría arrastrar datos sin redactar.
    """
    arbol = traza.get("trace")
    if not isinstance(arbol, dict):
        return [], 0, False
    pasos: list[dict[str, Any]] = []
    raros = 0
    for ruta, elementos in arbol.items():
        if not isinstance(elementos, list):
            raros += 1
            continue
        for el in elementos:
            if not isinstance(el, dict):
                raros += 1
                continue
            path = el.get("path")
            ts = el.get("timestamp")
            resultado = el.get("result")
            paso: dict[str, Any] = {
                "path": path if isinstance(path, str) else str(ruta),
                "timestamp": ts if isinstance(ts, str) else None,
                "result": (
                    None if resultado is None
                    else _texto(resultado, _MAX_TEXTO_PASO)
                ),
                "error": _texto(el.get("error"), _MAX_TEXTO_PASO),
                "child_id": _child_id(el.get("child_id")),
            }
            if completo:
                paso["changed_variables"] = _redactar(el.get("changed_variables"))
            pasos.append(paso)
    # Un mismo `path` se repite en bucles: el orden real lo da el momento.
    # Los pasos sin momento van al final.
    pasos.sort(key=lambda p: (p["timestamp"] is None, p["timestamp"] or ""))
    return pasos, raros, True


def _resumen(traza: dict[str, Any], domain: str) -> dict[str, Any]:
    doc: dict[str, Any] = {"domain": domain, **_cabecera(traza)}
    pasos, raros, disponible = _pasos(traza, completo=False)
    doc["steps"] = pasos
    if not disponible:
        doc["steps_unavailable"] = True
    if raros:
        doc["unrecognized_steps"] = raros
    doc["truncated"] = False
    return doc


def _completo(traza: dict[str, Any], domain: str) -> dict[str, Any]:
    doc: dict[str, Any] = {"domain": domain, **_cabecera(traza)}
    pasos, raros, disponible = _pasos(traza, completo=True)
    doc["steps"] = pasos
    if not disponible:
        doc["steps_unavailable"] = True
    if raros:
        doc["unrecognized_steps"] = raros
    doc["config"] = _redactar(traza.get("config"))
    # `blueprint_inputs` y `context` no salen ni en `full`: no ayudan a
    # diagnosticar y el contexto lleva ids de usuario.
    doc["truncated"] = False
    return doc


def _tam(valor: Any) -> int:
    return len(json.dumps(valor, ensure_ascii=False).encode("utf-8"))


def _ajustar_a_limite(doc: dict[str, Any], limite: int) -> dict[str, Any]:
    """Recorta `doc` hasta que su JSON quepa en `limite` bytes.

    Orden de recorte (FR-018), de lo menos a lo más útil para diagnosticar:
    1. `changed_variables` desde el último paso hacia el primero: son lo más
       voluminoso y los primeros pasos (el disparo) son los que suelen
       explicar por qué se ejecutó o no;
    2. `config`: el usuario la puede leer con `ha_get_automation`/`ha_get_script`;
    3. pasos desde el final, conservando el disparo y las primeras acciones.

    El tamaño se lleva restando lo que aporta cada parte, en vez de
    reserializar el documento entero en cada paso (cuadrático con trazas de
    MB); al final se comprueba con el tamaño real.
    """
    if _tam(doc) <= limite:
        return doc

    omitted = {"changed_variables_steps": 0, "config": False, "steps": 0}
    doc["truncated"] = True
    doc["omitted"] = omitted
    pasos: list[dict[str, Any]] = doc.get("steps", [])
    total = _tam(doc)

    for paso in reversed(pasos):
        if total <= limite:
            break
        if "changed_variables" in paso:
            antes = _tam(paso)
            del paso["changed_variables"]
            paso["_sin_variables"] = True
            total -= antes - _tam(paso)
            omitted["changed_variables_steps"] += 1

    if total > limite and "config" in doc:
        total -= _tam(doc["config"]) + len(', "config": ')
        del doc["config"]
        omitted["config"] = True

    def _quitar_ultimo() -> int:
        paso = pasos.pop()
        omitted["steps"] += 1
        # `changed_variables_steps` cuenta pasos CONSERVADOS sin variables; si
        # el paso entero se va, deja de contar ahí y cuenta en `steps`.
        if paso.pop("_sin_variables", False):
            omitted["changed_variables_steps"] -= 1
        return _tam(paso) + 2

    while total > limite and pasos:
        total -= _quitar_ultimo()

    # La marca interna no sale; se quita antes de medir de verdad.
    for paso in pasos:
        paso.pop("_sin_variables", None)
    # Comprobación real: la estimación no cuenta separadores ni el crecimiento
    # de los dígitos de `omitted`.
    while _tam(doc) > limite and pasos:
        _quitar_ultimo()

    if _tam(doc) > limite:
        # Ni la cabecera cabe (límite absurdo): se devuelve lo mínimo antes
        # que romper la promesa de tamaño.
        return {
            "run_id": doc.get("run_id"),
            "domain": doc.get("domain"),
            "item_id": doc.get("item_id"),
            "error": "response_too_large",
            "truncated": True,
        }
    return doc


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int | None = 1_048_576,
) -> None:
    """Registra las tools de trazas."""

    ready = requires_ready(ha_client)
    limite = min(_TRACE_MAX_BYTES, response_max_bytes or _TRACE_MAX_BYTES)

    async def _resolver_item_id(
        domain: str, item_id: str | None, entity_id: str | None
    ) -> tuple[str | None, str | None]:
        """Devuelve (item_id, error_json).

        HA identifica la automatización por el `id` de su configuración y el
        script por su clave, no por el `entity_id`. Ambos coinciden con el
        `unique_id` del registro de entidades, así que se traduce por ahí en
        vez de pedir al usuario un id que no ve en la interfaz.
        """
        if item_id is not None and entity_id is not None:
            return None, _invalid(
                "entity_id", "item_id and entity_id are mutually exclusive"
            )
        if item_id is not None:
            if not isinstance(item_id, str) or not item_id.strip():
                return None, _invalid("item_id", "must be a non-empty string")
            return item_id, None
        if entity_id is None:
            return None, None
        if not isinstance(entity_id, str) or not entity_id.startswith(f"{domain}."):
            return None, _invalid("entity_id", f"must be a {domain}.* entity_id")
        try:
            entry: Any = await ha_client.ws_send(
                {"type": "config/entity_registry/get", "entity_id": entity_id}
            )
        except HAConnectionError as exc:
            # Se decide por el código, no por el texto, que HA puede cambiar.
            if exc.code == "not_found":
                return None, json.dumps(
                    {"error": "not_found", "entity_id": entity_id}
                )
            return None, json.dumps({"error": str(exc)})
        unique_id = entry.get("unique_id") if isinstance(entry, dict) else None
        if not isinstance(unique_id, str) or not unique_id:
            # Sin `unique_id` no hay a qué traducir; adivinar daría las trazas
            # de otro elemento.
            return None, json.dumps({"error": "not_found", "entity_id": entity_id})
        return unique_id, None

    # ── ha_list_traces ────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_list_traces(
        domain: str,
        item_id: str | None = None,
        entity_id: str | None = None,
        limit: int = 10,
    ) -> object:
        """List recent runs (traces) of automations or scripts, newest first.

        Use it to answer "why didn't my automation run / why did it fail?".
        Pass entity_id (e.g. automation.x) or item_id (the config id), not
        both; with neither, lists the newest runs of the whole domain.

        Args:
            domain: "automation" or "script".
            item_id: Config id of the automation, or script key.
            entity_id: Entity id, translated to item_id via the registry.
            limit: Number of runs to return, 1-50.

        Returns:
            JSON {"count", "total", "traces": [{run_id, item_id, state,
            script_execution, start, finish, last_step, trigger, error,
            not_triggered?}]}; trigger and error are redacted, <= 300 chars.
        """
        if domain not in _DOMINIOS:
            return _invalid("domain", "must be automation or script")
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not _LIMITE_MIN <= limit <= _LIMITE_MAX):
            return _invalid("limit", f"must be an integer between {_LIMITE_MIN} and {_LIMITE_MAX}")

        resuelto, error = await _resolver_item_id(domain, item_id, entity_id)
        if error is not None:
            return error

        payload: dict[str, Any] = {"type": "trace/list", "domain": domain}
        if resuelto is not None:
            payload["item_id"] = resuelto
        try:
            raw: Any = await ha_client.ws_send(payload)
        except HAConnectionError as exc:
            logger.error("ha_list_traces_ws_error", domain=domain, error=str(exc))
            return json.dumps({"error": str(exc)})
        if not isinstance(raw, list):
            return json.dumps({"error": "unexpected response from trace/list"})

        trazas = [t for t in raw if isinstance(t, dict)]
        trazas.sort(key=_clave_inicio, reverse=True)
        elegidas = [_cabecera(t) for t in trazas[:limit]]
        logger.info("ha_list_traces_ok", domain=domain, count=len(elegidas))
        return json.dumps(
            {"count": len(elegidas), "total": len(trazas), "traces": elegidas},
            ensure_ascii=False,
        )

    # ── ha_get_trace ──────────────────────────────────────────────────────

    @mcp.tool()
    @ready
    async def ha_get_trace(
        domain: str,
        run_id: str,
        item_id: str | None = None,
        entity_id: str | None = None,
        detail: str = "summary",
    ) -> object:
        """Get one run (trace) of an automation or script.

        detail="summary" (default): run header plus, per step, path,
        timestamp, result (<= 500 chars), error and child run id; no config
        and no variables. detail="full": also each step's changed_variables
        and the config, both redacted. Responses never exceed 64 KiB: when
        too large, variables of the last steps, then config, then the last
        steps are dropped, with "truncated": true and "omitted".

        Args:
            domain: "automation" or "script".
            run_id: Run id from ha_list_traces.
            item_id: Config id of the automation, or script key.
            entity_id: Entity id, alternative to item_id.
            detail: "summary" or "full".

        Returns:
            JSON with the run, or {"error": "not_found", "run_id": ...}.
        """
        if domain not in _DOMINIOS:
            return _invalid("domain", "must be automation or script")
        if detail not in _DETALLES:
            return _invalid("detail", "must be summary or full")
        if not isinstance(run_id, str) or not run_id.strip():
            return _invalid("run_id", "must be a non-empty string")
        if item_id is None and entity_id is None:
            return _invalid("item_id", "item_id or entity_id is required")

        resuelto, error = await _resolver_item_id(domain, item_id, entity_id)
        if error is not None:
            return error

        try:
            raw: Any = await ha_client.ws_send({
                "type": "trace/get",
                "domain": domain,
                "item_id": resuelto,
                "run_id": run_id,
            })
        except HAConnectionError as exc:
            if exc.code == "not_found":
                return json.dumps({"error": "not_found", "run_id": run_id})
            logger.error("ha_get_trace_ws_error", domain=domain, error=str(exc))
            return json.dumps({"error": str(exc)})
        if not isinstance(raw, dict):
            return json.dumps({"error": "unexpected response from trace/get"})

        doc = _completo(raw, domain) if detail == "full" else _resumen(raw, domain)
        doc = _ajustar_a_limite(doc, limite)
        logger.info(
            "ha_get_trace_ok", domain=domain, detail=detail,
            truncated=doc.get("truncated"),
        )
        return json.dumps(doc, ensure_ascii=False)
