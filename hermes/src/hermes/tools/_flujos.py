"""Hermes — tapado de secretos en los formularios de los flujos de HA
(spec 016).

Nació en `config_subentries.py` (tramo B, reconfigure y subentries) y se movió
aquí sin cambiarlo en el tramo C, que lo necesita también en los flujos de
reparación (`repair_flows.py`) y en los `reauth` que continúa
`ha_continue_config_entry_flow` (`config_entry_flows.py`, que no puede
importar `config_subentries` sin un ciclo).
"""

from __future__ import annotations

from typing import Any

from hermes.security import REDACTED_MARKER, es_clave_sensible
from hermes.tools._common import redactar_datos


def _campos_secretos(data_schema: Any) -> set[str]:
    """Nombres de los campos del formulario que son secretos.

    Por el selector de contraseña (`text` con `type: password`), que es como
    los marca la integración aunque el nombre sea inocente, o por el nombre
    con el mismo criterio que la redacción por clave.
    """
    secretos: set[str] = set()
    if not isinstance(data_schema, list):
        return secretos
    for campo in data_schema:
        if not isinstance(campo, dict) or not isinstance(campo.get("name"), str):
            continue
        nombre = campo["name"]
        selector = campo.get("selector")
        texto = selector.get("text") if isinstance(selector, dict) else None
        if (isinstance(texto, dict) and texto.get("type") == "password") or es_clave_sensible(nombre):
            secretos.add(nombre)
    return secretos


def _tapar_resultado(raw: dict[str, Any]) -> dict[str, Any]:
    """El resultado de un flujo con los secretos tapados.

    Un formulario de reconfigure suele traer los valores actuales como
    `default` o `description.suggested_value`, contraseña incluida: en un
    campo secreto se tapan. Después, todo el resultado pasa por la redacción
    por clave y por patrón (marcadores de la descripción, errores, títulos).
    """
    resultado = dict(raw)
    esquema = resultado.get("data_schema")
    if isinstance(esquema, list):
        resultado["data_schema"] = _tapar_esquema(esquema)
    return redactar_datos(resultado)


def _tapar_esquema(esquema: list[Any]) -> list[Any]:
    """Los campos secretos de un formulario con su valor sugerido tapado.

    Cierre de seguridad de la 1.2.0: también dentro de una SECCIÓN. HA
    serializa `data_entry_flow.section` como un campo `type: expandable` con
    su propia lista en `schema` (`cv.custom_serializer`), y
    `add_suggested_values_to_schema` rellena también los campos de dentro:
    el flujo de opciones de `scrape` lleva la contraseña en la sección
    `auth`. Solo se miraba el primer nivel.
    """
    secretos = _campos_secretos(esquema)
    nuevo = []
    for campo in esquema:
        if isinstance(campo, dict) and campo.get("type") == "expandable"                 and isinstance(campo.get("schema"), list):
            campo = {**campo, "schema": _tapar_esquema(campo["schema"])}
        elif isinstance(campo, dict) and campo.get("name") in secretos:
            campo = dict(campo)
            if campo.get("default") not in (None, ""):
                campo["default"] = REDACTED_MARKER
            desc = campo.get("description")
            if isinstance(desc, dict) and desc.get("suggested_value") not in (None, ""):
                campo["description"] = {**desc, "suggested_value": REDACTED_MARKER}
        nuevo.append(campo)
    return nuevo


def _lleva_marcador(valor: Any) -> bool:
    """True si `valor` contiene el marcador de redacción en algún sitio.

    Los formularios salen con los secretos sugeridos tapados: reenviar el
    marcador lo guardaría en HA como contraseña. Se rechaza antes de llamar.
    """
    if isinstance(valor, str):
        return REDACTED_MARKER in valor
    if isinstance(valor, dict):
        return any(_lleva_marcador(v) for v in valor.values())
    if isinstance(valor, list):
        return any(_lleva_marcador(v) for v in valor)
    return False


_ERROR_MARCADOR = (
    "contains the redaction marker; it would be saved as is. Send the real "
    "value or leave the field as the form allows.")


def _tapar_user_input(user_input: dict[str, Any], secretos: set[str]) -> dict[str, Any]:
    tapado: dict[str, Any] = {}
    for clave, valor in user_input.items():
        if (clave in secretos or es_clave_sensible(str(clave))) and valor not in (None, ""):
            # Un campo de contraseña se tapa sea cual sea su tipo: un PIN
            # numérico también es un secreto.
            tapado[clave] = REDACTED_MARKER
        else:
            tapado[clave] = redactar_datos(valor)
    return tapado
