"""Hermes — Tools MCP para Add-ons del Supervisor.

Gestión de add-ons de HAOS vía Supervisor REST API.

Tools:
  sv_list_addons        — lista add-ons (instalados o todos del store)
  sv_get_addon          — info completa de un add-on
  sv_get_addon_options  — opciones actuales de configuración
  sv_set_addon_options  — cambia opciones conservando el resto (siempre requiere token)
  sv_start_addon        — arranca un add-on (siempre requiere token)
  sv_stop_addon         — para un add-on (siempre requiere token)
  sv_restart_addon      — reinicia un add-on (siempre requiere token)
  sv_install_addon      — instala desde el store (token + async job)
  sv_uninstall_addon    — desinstala (token + async job)
  sv_update_addon       — actualiza a la última versión (token + async job)
  sv_get_addon_logs     — logs recientes (REDACTADOS de secretos), también
                          de un arranque anterior (`boot`, `latest`)
  sv_get_addon_stats    — CPU / RAM / red del add-on

Auto-protección: si el slug del add-on objetivo es el propio Hermes
(local_hermes), las operaciones destructivas incluyen una advertencia
explícita en el preview.

Redacción de logs: todos los logs pasan por security.redact_secrets()
antes de ser devueltos al cliente MCP. Mosquitto, Zigbee2MQTT, MariaDB
y similares pueden incluir contraseñas y tokens en texto claro.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import structlog

from hermes.config import RESPONSE_MAX_BYTES_DEFAULT
from hermes.ha import HAClient, HAConnectionError
from hermes.logging_setup import network_redaction_enabled, redact_network
from hermes.security import (
    REDACTED_MARKER,
    redact_structure,
    complete_confirmation_token,
    create_confirmation_token,
    redact_secrets,
    validate_confirmation_token,
)
from hermes.tools._common import tam_json
from hermes.tools._logs import (
    ArgumentoInvalido,
    comprobar_latest,
    normalizar_boot,
    ruta_de_log,
)
from hermes.tools._store import (
    disponibilidad,
    es_integrado,
    ficha_de_tienda,
    mensaje_del_supervisor,
    texto_de_la_app,
    texto_de_terceros,
)
from hermes.tools._validation import InvalidIdentifier, validate_slug

logger = structlog.get_logger(__name__)

# Slug del propio add-on, para avisar antes de que Hermes se apague a sí mismo.
#
# No se puede fijar a una constante: el Supervisor le pone al slug un prefijo
# que depende de DÓNDE está instalado el add-on. En una carpeta local es
# `local_hermes`; instalado desde un repositorio es `<hash del repo>_hermes`,
# y ese hash es distinto en cada repositorio. Comparar contra `local_hermes` a
# secas hacía que el aviso no saltara nunca salvo en una instalación local.
#
# El Supervisor pone el hostname del contenedor igual que el slug pero con
# guiones, así que de ahí sale el valor real. Si no estuviera disponible, se
# cae a reconocer cualquier slug que termine en `hermes`.
_HERMES_SLUG = (os.environ.get("HOSTNAME") or "local-hermes").replace("-", "_").lower()

# Timeout largo para operaciones de instalación/actualización/desinstalación
_LONG_OP_TIMEOUT = 300.0  # 5 minutos

# Principio del changelog en la vista previa de `sv_update_addon` (spec 030,
# FR-010): lo bastante para ver qué cambia sin gastar el contexto de una
# vista previa; el entero, por trozos, con `sv_get_addon_changelog`.
_CHANGELOG_EXTRACTO = 4000


def _es_hermes(slug: str) -> bool:
    """True si el slug apunta al propio Hermes, esté instalado como esté."""
    s = slug.lower()
    # `self` es el alias del Supervisor para el add-on que llama: con él,
    # `/addons/self/logs` es el log de Hermes y se saltaba la redacción de red
    # (revisión 1.1.0, BAJO-1).
    return s in (_HERMES_SLUG, "hermes", "self") or s.endswith("_hermes")


def _self_warning(slug: str, action: str) -> str | None:
    """Devuelve un aviso de auto-daño si el slug es el propio Hermes."""
    if _es_hermes(slug):
        return (
            f"WARNING: {action} targets Hermes itself (slug={slug!r}). "
            "After this operation Hermes will be unavailable. "
            "Manual recovery via Supervisor UI will be required."
        )
    return None


def _addon_summary(addon: dict[str, Any]) -> dict[str, Any]:
    """Extrae campos relevantes de un objeto add-on del Supervisor."""
    return {
        "slug": addon.get("slug"),
        "name": addon.get("name"),
        "version": addon.get("version"),
        "version_latest": addon.get("version_latest"),
        "state": addon.get("state"),
        "update_available": addon.get("update_available"),
        "repository": addon.get("repository"),
        "description": addon.get("description"),
    }


def _store_addon_summary(addon: dict[str, Any]) -> dict[str, Any]:
    """Igual que `_addon_summary`, más los campos propios del store.

    `/store/addons` describe el catálogo, no lo instalado: `state` no existe
    ahí (solo lo tiene un add-on corriendo) y en cambio sí vienen `installed`
    y `available`, que son justo lo que distingue un add-on del store de uno
    ya puesto.
    """
    return {
        **_addon_summary(addon),
        "installed": addon.get("installed"),
        "available": addon.get("available"),
    }


# ── Opciones de add-on: mezcla de cambios ─────────────────────────────────────
#
# El Supervisor NO mezcla: `POST /addons/{slug}/options` valida el cuerpo con el
# schema del add-on y SUSTITUYE las opciones guardadas por él (supervisor/api/
# apps.py, `options`; setter `options` de supervisor/apps/app.py). Lo que no se
# envía se pierde y vuelve a su valor por defecto, si lo tiene. Por eso
# `sv_set_addon_options` envía siempre el conjunto completo: lo actual con los
# cambios del llamante encima.


def _mezclar_opciones(actuales: dict[str, Any], cambios: dict[str, Any]) -> dict[str, Any]:
    """Aplica `cambios` sobre `actuales` sin tocar lo que no se menciona.

    - Diccionario: se mezcla clave a clave, a cualquier profundidad. Cambiar
      `mqtt.user` conserva `mqtt.password`.
    - Lista o valor simple: se sustituye entero. Mezclar listas posición a
      posición no tiene un significado que el llamante pueda prever.
    - `None` (`null` en JSON): quita la clave. El Supervisor no acepta `null`
      como valor de una opción, así que no hay otro uso que darle.

    No modifica ninguno de los dos argumentos.
    """
    resultado = deepcopy(actuales)
    for clave, valor in cambios.items():
        if valor is None:
            resultado.pop(clave, None)
        elif isinstance(valor, dict):
            base = resultado.get(clave)
            resultado[clave] = _mezclar_opciones(base if isinstance(base, dict) else {}, valor)
        else:
            resultado[clave] = deepcopy(valor)
    return resultado


def _rutas_redactadas(valor: Any, ruta: str = "") -> list[str]:
    """Rutas (`mqtt.password`, `logins[0].password`) cuyo valor lleva el marcador.

    El llamante solo ve los secretos tapados con `REDACTED_MARKER`. Si copia ese
    texto en lo que envía, se guardaría literalmente y sustituiría al secreto
    real: hay que rechazarlo, a cualquier nivel de anidamiento.
    """
    if isinstance(valor, dict):
        rutas: list[str] = []
        for clave, sub in valor.items():
            rutas += _rutas_redactadas(sub, f"{ruta}.{clave}" if ruta else str(clave))
        return rutas
    if isinstance(valor, list):
        rutas = []
        for i, sub in enumerate(valor):
            rutas += _rutas_redactadas(sub, f"{ruta}[{i}]")
        return rutas
    if isinstance(valor, str) and REDACTED_MARKER in valor:
        return [ruta or "(raíz)"]
    return []


def _rutas_cambiadas(antes: Any, despues: Any, ruta: str = "") -> list[str]:
    """Rutas que difieren entre dos juegos de opciones (añadidas, quitadas o cambiadas).

    Solo nombres, nunca valores: es seguro devolverlo aunque toque secretos.
    """
    if isinstance(antes, dict) and isinstance(despues, dict):
        rutas: list[str] = []
        for clave in sorted(set(antes) | set(despues), key=str):
            sub = f"{ruta}.{clave}" if ruta else str(clave)
            if clave not in antes or clave not in despues:
                rutas.append(sub)
            else:
                rutas += _rutas_cambiadas(antes[clave], despues[clave], sub)
        return rutas
    # `type` además de `==`: en Python True == 1, y para el add-on no son lo mismo.
    if type(antes) is type(despues) and antes == despues:
        return []
    return [ruta or "(raíz)"]


def _valores_secretos(original: Any, redactado: Any) -> set[str]:
    """Los textos de `original` que `redact_structure` sustituyó en
    `redactado` (recorridos a la vez): los valores secretos de unas opciones."""
    if isinstance(original, dict) and isinstance(redactado, dict):
        out: set[str] = set()
        for clave, valor in original.items():
            out |= _valores_secretos(valor, redactado.get(clave))
        return out
    if isinstance(original, list) and isinstance(redactado, list):
        out = set()
        for valor, tapado in zip(original, redactado):
            out |= _valores_secretos(valor, tapado)
        return out
    if isinstance(original, str) and original and original != redactado:
        return {original}
    return set()


def _sin_valores_secretos(texto: str, opciones: dict[str, Any]) -> str:
    """Un mensaje del Supervisor sobre `opciones`, sin sus secretos.

    El mensaje de validación (`humanize_error`) repite el valor rechazado
    («… Got 'mi-clave'»), y un valor suelto no lleva la forma `clave: valor`
    que reconoce `redact_secrets`. Por eso, además de la redacción general,
    cada valor que `redact_structure` tapa en las opciones se sustituye
    LITERALMENTE por el marcador (spec 030, research R-7). Los más largos
    primero, para no dejar restos de uno que contiene a otro.
    """
    secretos = _valores_secretos(opciones, redact_structure(opciones))
    for valor in sorted(secretos, key=len, reverse=True):
        texto = texto.replace(valor, REDACTED_MARKER)
    return redact_secrets(texto)


def _tiene_obligatorias(schema_ui: Any) -> bool:
    """True si el schema de /info declara alguna opción obligatoria, a cualquier nivel.

    Es la `schema_ui` del Supervisor: una lista de nodos con `required: true`
    en las obligatorias y, en los objetos anidados, su propia lista bajo
    `schema`. Una obligatoria anidada también cuenta: el validador del
    Supervisor exige el objeto que la contiene.
    """
    if not isinstance(schema_ui, list):
        return False
    for nodo in schema_ui:
        if not isinstance(nodo, dict):
            continue
        if nodo.get("required") is True or _tiene_obligatorias(nodo.get("schema")):
            return True
    return False


def _ultimas_lineas_que_caben(
    respuesta: dict[str, Any], logs: str, max_bytes: int
) -> dict[str, Any]:
    """`respuesta` con `logs` entero si cabe; si no, sus últimas líneas.

    Un log es un texto, no una lista, así que el guardián central solo podía
    cambiarlo entero por `response_too_large`: un add-on que escribe mucho
    dejaba de tener log por Hermes (revisión de 1.1.1, M-2). En un log lo que
    importa es el final, así que se quitan líneas del PRINCIPIO y se dice.
    """
    completa = {**respuesta, "logs": logs}
    if tam_json(completa) <= max_bytes:
        return completa
    lineas = logs.splitlines(keepends=True)

    def armar(n: int) -> dict[str, Any]:
        return {
            **respuesta,
            "logs": "".join(lineas[len(lineas) - n:]) if n else "",
            "truncated": True,
            "lines_returned": n,
            "hint": (
                "Only the last lines that fit in response_max_bytes are shown. "
                "Ask for fewer lines instead of repeating the same call."
            ),
        }

    # Estimación con el tamaño escapado de cada línea desde el final y
    # verificación con el tamaño real.
    presupuesto = max_bytes - tam_json(armar(0)) - 8
    n = usado = 0
    for linea in reversed(lineas):
        coste = tam_json(linea) - 2
        if usado + coste > presupuesto:
            break
        usado += coste
        n += 1
    out = armar(n)
    while n > 0 and tam_json(out) > max_bytes:
        n -= 1
        out = armar(n)
    return out


def register(
    mcp: object,
    ha_client: HAClient,
    response_max_bytes: int = RESPONSE_MAX_BYTES_DEFAULT,
) -> None:
    """Registra las tools de add-ons en la instancia MCP."""

    def _bad_slug(slug: str) -> dict[str, Any] | None:
        """Valida el slug del add-on antes de interpolarlo en una URL REST."""
        try:
            validate_slug(slug, field="slug")
            return None
        except InvalidIdentifier as exc:
            return {"error": "invalid_identifier", "detail": str(exc)}

    # ── Vistas previas de la tienda (spec 030, tramo 2) ──
    #
    # Solo añaden campos a la vista previa o rechazan SIN token lo que el
    # Supervisor rechazaría. Ninguna cambia los argumentos ni lo que se hace
    # con un token válido (FR-009…FR-013 de la 030; SC-005).

    async def _vista_previa_de_instalar(
        slug: str, preview: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Completa `preview` o devuelve el rechazo (sin token)."""
        try:
            ficha = await ficha_de_tienda(ha_client, slug)
            if ficha is None:
                return {"error": "addon_not_found",
                        "detail": "No app with that slug in the store."}
            if ficha.get("installed") is True:
                return {"error": "already_installed",
                        "detail": ("The app is already installed. Use "
                                   "sv_update_addon to update it.")}
            disponible, motivo = await disponibilidad(ha_client, slug)
        except HAConnectionError as exc:
            if exc.status == 404:
                return {"error": "addon_not_found",
                        "detail": "No app with that slug in the store."}
            preview["store_check"] = {"checked": False,
                                      "reason": redact_secrets(str(exc))}
            return None
        if not disponible:
            return {"error": "addon_not_available", "reason": motivo,
                    "detail": "The app cannot be installed on this system."}
        repositorio = ficha.get("repository")
        preview.update({
            "name": redact_secrets(ficha["name"]) if isinstance(ficha.get("name"), str)
            else ficha.get("name"),
            "version_latest": ficha.get("version_latest"),
            "repository": repositorio,
            "build": ficha.get("build"),
            "store_check": {"checked": True, "available": True},
        })
        if not (isinstance(repositorio, str) and es_integrado(repositorio)):
            preview["third_party_repository"] = True
            preview["warning"] = (
                "This app comes from a third-party repository: it is not "
                "reviewed by Home Assistant nor by Hermes, and once installed "
                "it runs with the permissions it declares."
            )
        preview["_third_party_text"] = texto_de_terceros(["name"])
        return None

    async def _resumen_de_changelog(slug: str) -> dict[str, Any]:
        """Los campos de changelog de la vista previa de actualizar. Nunca
        impiden el token: sin changelog se dice por qué."""
        try:
            texto = await texto_de_la_app(ha_client, slug, "changelog")
        except HAConnectionError as exc:
            return {"changelog_excerpt": None,
                    "changelog_unavailable": redact_secrets(str(exc))}
        if texto is None:
            return {"changelog_excerpt": None,
                    "changelog_unavailable": "The app has no changelog."}
        # Se redacta el texto ENTERO antes de cortar (como en
        # `sv_get_addon_changelog`): un secreto no se parte en el corte.
        redactado = redact_secrets(texto)
        return {
            "changelog_excerpt": redactado[:_CHANGELOG_EXTRACTO],
            "changelog_truncated": len(redactado) > _CHANGELOG_EXTRACTO,
            "_third_party_text": texto_de_terceros(["changelog_excerpt"]),
        }

    async def _validar_opciones(
        slug: str,
        actuales: dict[str, Any],
        finales: dict[str, Any],
        preview: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Añade `validation` a `preview` o devuelve `invalid_options` (sin
        token). El cuerpo son las opciones finales SIN envolver
        (`api/apps.py`, `options_validate`)."""
        if not finales:
            # Con un cuerpo vacío el Supervisor valida las GUARDADAS, no las
            # enviadas: decir que se validó `{}` sería mentir.
            preview["validation"] = {"checked": False, "reason": "empty_options"}
            return None
        try:
            res = await ha_client.sv_request(
                "POST", f"/addons/{slug}/options/validate", json_body=finales)
        except HAConnectionError as exc:
            preview["validation"] = {
                "checked": False,
                "reason": _sin_valores_secretos(str(exc), finales),
            }
            return None
        if not isinstance(res, dict) or not isinstance(res.get("valid"), bool):
            preview["validation"] = {"checked": False, "reason": "unexpected_response"}
            return None
        if res["valid"] is False:
            mensaje = res.get("message")
            return {
                "error": "invalid_options",
                "message": _sin_valores_secretos(mensaje, finales)
                if isinstance(mensaje, str) else None,
                "changed_paths": _rutas_cambiadas(actuales, finales),
            }
        pwned = res.get("pwned")
        preview["validation"] = {"checked": True, "valid": True, "pwned": pwned}
        if pwned is True:
            preview["warning_pwned"] = (
                "The Supervisor reports that a secret in these options appears "
                "in known data breaches (Have I Been Pwned). Use another one."
            )
        elif pwned is None:
            preview["pwned_check"] = "failed"
        return None

    @mcp.tool()
    async def sv_list_addons(installed_only: bool = True) -> object:
        """Lista los add-ons de Home Assistant.

        Args:
            installed_only: Si True (default), solo devuelve los add-ons
                instalados (`GET /addons`). Si False, devuelve el catálogo
                completo del store (`GET /store/addons`), que puede ser una
                lista larga.

        Returns:
            {"addons": [...], "count": N, "source": "/addons"|"/store/addons"}
            installed_only=True  → slug, name, version, version_latest, state,
                update_available, repository, description.
            installed_only=False → los mismos campos más `installed` y
                `available`. Ahí `state` es siempre None: el store describe el
                catálogo, no procesos en marcha.
        """
        # `GET /addons` SOLO lista lo instalado y sus objetos no traen la clave
        # `installed`, así que el filtro anterior (`a.get("installed") is not
        # False`) no descartaba nada e `installed_only=False` no hacía nada: la
        # respuesta era idéntica en ambos casos. El catálogo vive en
        # `/store/addons`, que es otro endpoint y otra forma de respuesta.
        path = "/addons" if installed_only else "/store/addons"
        try:
            data = await ha_client.sv_request("GET", path)
            addons = data.get("addons", []) if isinstance(data, dict) else []
            summarize = _addon_summary if installed_only else _store_addon_summary
            summaries = [summarize(a) for a in addons]
            return {"addons": summaries, "count": len(summaries), "source": path}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon(slug: str, include_long_description: bool = False) -> object:
        """Devuelve información detallada de un add-on instalado.

        Args:
            slug: Identificador del add-on (ej. 'core_mosquitto',
                  'a0d7b954_tailscale', 'local_hermes').
            include_long_description: Incluir el README completo del add-on.
                  Por defecto NO: en add-ons con documentación larga son
                  decenas de miles de caracteres que rara vez se necesitan.

        Returns:
            Información completa: slug, name, version, version_latest,
            state, update_available, description, repository, boot,
            auto_update, protected, hostname, y otros campos del Supervisor.
            El README va aparte, bajo `long_description_omitted`, salvo que se
            pida expresamente.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/addons/{slug}/info")
            if isinstance(data, dict):
                # /addons/{slug}/info incluye el bloque `options` del add-on,
                # con sus secretos en claro. Nunca devolverlo sin redactar.
                data = redact_structure(data)
                if not include_long_description and isinstance(data, dict):
                    # `long_description` es el README entero del add-on:
                    # suele ser la mayor parte de la respuesta y casi nunca se
                    # necesita. Devolverlo se pagaría en cada llamada aunque
                    # nadie lo mirase, desplazando contexto útil.
                    readme = data.pop("long_description", None)
                    if readme is not None:
                        data["long_description_omitted"] = {
                            "bytes": len(readme) if isinstance(readme, str) else 0,
                            "hint": (
                                "README completo del add-on. Vuelve a llamar con "
                                "include_long_description=True si lo necesitas."
                            ),
                        }
                return data
            return {"error": "unexpected_response", "raw": str(data)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon_options(slug: str) -> object:
        """Devuelve las opciones actuales de configuración de un add-on.

        Devuelve las opciones tal como el usuario las tiene configuradas
        (el formulario del add-on en la UI de HAOS), y nada más.

        Es la versión enfocada de `sv_get_addon`: aquella trae el manifiesto
        entero —schema, traducciones, red, permisos—, que son varios kilobytes
        para leer cuatro valores.

        Args:
            slug: Identificador del add-on.

        Returns:
            {"slug": "...", "options": {...}} con los secretos redactados.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            # Las opciones se leen de /info y NO de /addons/{slug}/options/config:
            # ese endpoint el Supervisor lo reserva al add-on que se consulta a
            # sí mismo, y a cualquier otro le responde 403 "This can be only
            # read by the app itself!". Usándolo, esta tool no funcionaba nunca.
            data = await ha_client.sv_request("GET", f"/addons/{slug}/info")
            if not isinstance(data, dict):
                return {"error": "unexpected_response", "raw": str(data)}
            opciones = data.get("options")
            if opciones is None:
                return {"slug": slug, "options": {}, "detail": "el add-on no declara opciones"}
            # Las opciones llevan los secretos del add-on en claro: redactar
            # aquí es obligatorio, no opcional.
            return {"slug": slug, "options": redact_structure(opciones)}
        except HAConnectionError as exc:
            return {"error": str(exc)}

    async def _opciones_en_bruto(slug: str) -> dict[str, Any] | None:
        """Opciones guardadas del add-on, SIN redactar. Nunca devolverlas tal cual.

        Salen de `/addons/{slug}/info` (`app.options` en el Supervisor): las
        guardadas mezcladas con los valores por defecto del add-on, y con las
        referencias `!secret x` sin resolver. Es justo lo que hay que reenviar.

        `/addons/{slug}/options/config` no sirve: solo responde al add-on que se
        consulta a sí mismo (403 para cualquier otro), y además devuelve los
        `!secret` ya resueltos. Reenviarlos guardaría el secreto en claro en
        lugar de la referencia.

        Devuelve None —y entonces no se envía nada— si la respuesta no trae las
        opciones, o si trae `{}` y el schema tiene alguna obligatoria. Lo
        segundo es lo que el Supervisor manda cuando oculta las opciones a quien
        no tiene rol `manager` o `admin` (`info_data` en supervisor/api/
        apps.py): deja el schema entero pero cambia las opciones por `{}`.
        Mezclar sobre ese `{}` borraría todas las demás. Un add-on con alguna
        opción obligatoria no tiene `{}` legítimo: el Supervisor no lo valida.
        Hermes declara `hassio_role: admin`, así que no debería pasar; lo vigila
        también un test del manifiesto.
        """
        data = await ha_client.sv_request("GET", f"/addons/{slug}/info")
        if not isinstance(data, dict):
            return None
        opciones = data.get("options")
        if not isinstance(opciones, dict):
            return None
        if not opciones and _tiene_obligatorias(data.get("schema")):
            return None
        return opciones

    @mcp.tool()
    async def sv_set_addon_options(
        slug: str,
        options: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Cambia opciones de configuración de una app (add-on), conservando el resto.

        Pasa SOLO lo que quieres cambiar. El Supervisor sustituye las opciones
        guardadas por las que recibe, así que esta tool lee las actuales, pone
        tus cambios encima y envía el conjunto completo: lo que no mencionas,
        secretos incluidos, se queda como está.

        Cómo se aplican los cambios:
        - Objetos anidados (`mqtt`, `serial`…): clave a clave.
          `{"mqtt": {"user": "x"}}` conserva `mqtt.password` y el resto.
        - Listas y valores simples: se sustituyen enteros. Una lista con
          secretos (p. ej. `logins` de Mosquitto) hay que pasarla completa.
        - `null`: quita la opción. Si el add-on le da un valor por defecto,
          vuelve ese valor; si es obligatoria, el Supervisor rechaza el cambio.
        - Un valor con `***REDACTED***` se rechaza: es el marcador con que
          Hermes tapa los secretos, y guardarlo machacaría el real.

        Si no se pueden leer las opciones actuales, no se envía nada
        (`current_options_unavailable`): enviar solo los cambios borraría el
        resto.

        Siempre requiere confirmation_token: cambiar opciones puede dejar un
        add-on sin arrancar. Las opciones nuevas se aplican cuando el add-on
        se reinicia (`sv_restart_addon`).

        Primera llamada (sin token): preview con las opciones actuales, los
        cambios pedidos, las opciones finales que se enviarán y las rutas que
        cambian, todo con los secretos redactados, + confirmation_token. Antes
        de dar el token, el Supervisor valida las opciones finales: si no son
        válidas, responde `invalid_options` (mensaje redactado) SIN token; si
        no se pudo validar, `validation.checked` es false y el token sale igual
        (el guardado vuelve a validar). `warning_pwned` avisa de un secreto
        filtrado.
        Segunda llamada (con token): vuelve a leer las opciones actuales, mezcla
        de nuevo y envía. Si alguien las tocó entre medias, lo que tú no
        cambias conserva su valor más reciente.

        Args:
            slug: Identificador del add-on.
            options: JSON string con un objeto: solo las opciones a cambiar.
            confirmation_token: Token obtenido del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token válido: {"result": "ok", "slug": "..."}
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            opts_dict = json.loads(options) if isinstance(options, str) else options
        except json.JSONDecodeError as exc:
            return {"error": f"options must be valid JSON: {exc}"}
        if not isinstance(opts_dict, dict):
            return {
                "error": "invalid_options",
                "detail": "options debe ser un objeto JSON con las opciones a cambiar",
            }
        if (redactadas := _rutas_redactadas(opts_dict)):
            return {
                "error": "redacted_value",
                "detail": (
                    f"Estas opciones llevan el marcador {REDACTED_MARKER}, que es "
                    "como Hermes tapa los secretos: guardarlo sustituiría el valor "
                    "real. Quítalas para conservar el valor actual, o pasa el "
                    "valor nuevo en claro."
                ),
                "paths": redactadas,
            }

        tool_name = "sv_set_addon_options"
        args: dict[str, Any] = {"slug": slug, "options": options}
        sin_opciones = {
            "error": "current_options_unavailable",
            "detail": (
                "El Supervisor no ha devuelto las opciones actuales del add-on. "
                "Sin ellas no se puede enviar el conjunto completo, y enviar solo "
                "los cambios borraría el resto."
            ),
        }

        if not confirmation_token:
            # Las opciones actuales se leen de /info, igual que en
            # sv_get_addon_options (ver `_opciones_en_bruto`). Sin ellas no hay
            # preview: antes se seguía con `current_options: null` y se emitía
            # el token igualmente.
            try:
                actuales = await _opciones_en_bruto(slug)
            except HAConnectionError as exc:
                return {"error": str(exc)}
            if actuales is None:
                return sin_opciones
            finales = _mezclar_opciones(actuales, opts_dict)

            warning = _self_warning(slug, "changing options of")
            preview: dict[str, Any] = {
                "slug": slug,
                # Todo redactado. Las actuales y las finales traen los secretos
                # del add-on en claro: sin redactar, la tool de escritura sería
                # una puerta de atrás para leerlos. Los cambios pedidos también,
                # para que la vista previa no repita ningún secreto.
                "current_options": redact_structure(actuales),
                "requested_changes": redact_structure(opts_dict),
                "final_options": redact_structure(finales),
                "changed_paths": _rutas_cambiadas(actuales, finales),
            }
            if warning:
                preview["warning"] = warning
            # Spec 030 (FR-013, research R-7): el Supervisor valida las
            # opciones FINALES antes del token. Si dice que no valen, no hay
            # token (el guardado las rechazaría igual); si no se pudo validar,
            # se dice y el token sale como en la 1.1.2, porque el guardado
            # vuelve a validar.
            rechazo = await _validar_opciones(slug, actuales, finales, preview)
            if rechazo is not None:
                return rechazo
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(
            confirmation_token, tool_name, args
        )
        if not valid:
            return {"error": error}

        try:
            # Se vuelven a leer: las del preview pueden haber cambiado mientras
            # tanto, y reutilizarlas desharía cambios ajenos en lo que el
            # llamante no toca.
            actuales = await _opciones_en_bruto(slug)
            if actuales is None:
                await complete_confirmation_token(
                    confirmation_token, success=False, error=sin_opciones["error"]
                )
                return sin_opciones
            finales = _mezclar_opciones(actuales, opts_dict)
            await ha_client.sv_request(
                "POST", f"/addons/{slug}/options", json_body={"options": finales}
            )
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_set_addon_options_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(
                confirmation_token, success=False, error=str(exc)
            )
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_start_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Arranca un add-on detenido.

        Siempre requiere confirmation_token.
        Primera llamada: devuelve preview + token.
        Segunda llamada: arranca el add-on.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_start_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "start"}
            w = _self_warning(slug, "starting")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/start")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_start_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_stop_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Para un add-on en ejecución.

        Siempre requiere confirmation_token. Si el add-on objetivo es
        Hermes mismo, el preview incluye una advertencia crítica.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_stop_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "stop"}
            w = _self_warning(slug, "stopping")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/stop")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_stop_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_restart_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Reinicia un add-on.

        Siempre requiere confirmation_token. Si el add-on objetivo es
        Hermes mismo, el preview incluye una advertencia crítica.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"result": "ok"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_restart_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                state = info.get("state") if isinstance(info, dict) else None
            except HAConnectionError:
                state = None
            preview: dict[str, Any] = {"slug": slug, "current_state": state, "action": "restart"}
            w = _self_warning(slug, "restarting")
            if w:
                preview["warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            await ha_client.sv_request("POST", f"/addons/{slug}/restart")
            result: dict[str, Any] = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_restart_addon_ok", slug=slug)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_install_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Instala una app (add-on) de la tienda del Supervisor, en la versión
        que ofrece la tienda (`version_latest`): no se puede elegir otra.

        La vista previa comprueba antes la tienda: `addon_not_found`,
        `already_installed` y `addon_not_available` (con el motivo:
        arquitectura, máquina o versión de HA) se devuelven SIN token. Si la
        app viene de un repositorio de terceros, lo avisa.

        Operación larga — devuelve inmediatamente un job_id.
        Usa sv_get_job_status(job_id) para consultar el progreso.

        Args:
            slug: Identificador del add-on en el store.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_install_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            preview: dict[str, Any] = {
                "slug": slug,
                "action": "install",
                "note": "This operation may take several minutes.",
            }
            # Spec 030 (FR-009, research R-3): antes del token, la ficha de la
            # tienda y la disponibilidad. Lo que el Supervisor rechazaría (no
            # está, ya instalada, no disponible en este sistema) se dice sin
            # token. Si la tienda no se puede leer, se dice y el token sale
            # como en la 1.1.2: el Supervisor vuelve a comprobarlo al instalar.
            rechazo = await _vista_previa_de_instalar(slug, preview)
            if rechazo is not None:
                return rechazo
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/store/addons/{slug}/install",
                json_body={"background": True},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "install_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_install_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_uninstall_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Desinstala un add-on de HAOS.

        WARNING: la desinstalación elimina todos los datos del add-on
        en /data por defecto. Lee la documentación del add-on antes de
        confirmar si necesitas conservar los datos.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
        """
        if (err := _bad_slug(slug)):
            return err
        tool_name = "sv_uninstall_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                version = info.get("version") if isinstance(info, dict) else None
            except HAConnectionError:
                version = None
            preview: dict[str, Any] = {
                "slug": slug,
                "version": version,
                "action": "uninstall",
                "warning": (
                    "By default uninstall removes ALL add-on data in /data. "
                    "Read the add-on docs before confirming if you need to preserve data."
                ),
            }
            w = _self_warning(slug, "uninstalling")
            if w:
                preview["critical_warning"] = w
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/addons/{slug}/uninstall",
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "uninstall_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_uninstall_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_update_addon(
        slug: str,
        confirmation_token: str | None = None,
    ) -> object:
        """Actualiza una app (add-on) a la versión que ofrece la tienda
        (`version_latest`): no se puede elegir otra.

        La vista previa enseña la disponibilidad y el principio del changelog
        de esa versión (texto de terceros, redactado). Si la app ya está en la
        versión de la tienda, responde `already_up_to_date` con la versión
        instalada, SIN token: no hay nada que confirmar.

        Operación larga — devuelve job_id. Usa sv_get_job_status(job_id).

        Hermes no puede actualizarse a sí mismo: con su propio slug (o `self`)
        responde `self_update_not_supported`, sin token; se actualiza desde la
        interfaz de Home Assistant.

        Args:
            slug: Identificador del add-on.
            confirmation_token: Token del preview anterior.

        Returns:
            Sin token: {"confirmation_token": "...", "preview": {...}}
            Con token: {"job_id": "...", "status": "running",
                        "poll_with": "sv_get_job_status"}
            Sobre Hermes: {"error": "self_update_not_supported", "detail": "..."}
            Sin actualización: {"error": "already_up_to_date", "version": "..."}
        """
        if (err := _bad_slug(slug)):
            return err
        if _es_hermes(slug):
            # El Supervisor responde 403 («can't update itself») cuando un
            # add-on pide su propia actualización: la vista previa de la 1.1.2
            # daba un token para algo imposible. Se rechaza antes de cualquier
            # petición y sin tocar el token que se traiga (FR-010 de la 009).
            return {
                "error": "self_update_not_supported",
                "detail": (
                    "Hermes cannot update itself through the Supervisor API. "
                    "Update it from the Home Assistant UI: "
                    "Settings > Add-ons > Hermes > Update."
                ),
            }
        tool_name = "sv_update_addon"
        args: dict[str, Any] = {"slug": slug}

        if not confirmation_token:
            try:
                info = await ha_client.sv_request("GET", f"/addons/{slug}/info")
                if isinstance(info, dict):
                    current = info.get("version")
                    latest = info.get("version_latest")
                    avail = info.get("update_available", False)
                else:
                    current = latest = avail = None
            except HAConnectionError:
                current = latest = avail = None

            if avail is False and current is not None:
                # Spec 030, extra del supervisor del programa: una app
                # instalada sin actualización no tiene nada que confirmar (el
                # Supervisor respondería `AppNoUpdateAvailableError`), así que
                # no hay token. Solo con la lectura correcta y la app
                # instalada; si no se pudo leer, sigue como en la 1.1.2.
                return {
                    "error": "already_up_to_date",
                    "slug": slug,
                    "version": current,
                    "version_latest": latest,
                    "detail": ("The app is already at the version the store "
                               "offers; there is nothing to update."),
                }

            preview: dict[str, Any] = {
                "slug": slug,
                "current_version": current,
                "version_latest": latest,
                "update_available": avail,
            }
            if not avail and avail is not None:
                preview["note"] = "No update available at this time."
            # Spec 030 (FR-010): disponibilidad y principio del changelog de
            # la versión de la tienda. Ninguna de las dos impide el token.
            try:
                disponible, motivo = await disponibilidad(ha_client, slug)
                preview["available"] = disponible
                preview["reason"] = motivo
            except HAConnectionError as exc:
                preview["available"] = None
                preview["reason"] = redact_secrets(mensaje_del_supervisor(exc))
            preview.update(await _resumen_de_changelog(slug))
            return await create_confirmation_token(tool_name, args, preview=preview)

        valid, error = await validate_confirmation_token(confirmation_token, tool_name, args)
        if not valid:
            return {"error": error}

        try:
            data = await ha_client.sv_request(
                "POST",
                f"/store/addons/{slug}/update",
                json_body={"background": True},
                timeout_seconds=_LONG_OP_TIMEOUT,
            )
            job_id = data.get("job_id") if isinstance(data, dict) else None
            if job_id:
                await _track_job(job_id, {"op": "update_addon", "slug": slug})
                result: dict[str, Any] = {
                    "job_id": job_id,
                    "status": "running",
                    "poll_with": "sv_get_job_status",
                }
            else:
                result = {"result": "ok", "slug": slug}
            await complete_confirmation_token(confirmation_token, success=True, result=result)
            logger.info("sv_update_addon_started", slug=slug, job_id=job_id)
            return result
        except HAConnectionError as exc:
            await complete_confirmation_token(confirmation_token, success=False, error=str(exc))
            return {"error": str(exc)}

    @mcp.tool()
    async def sv_get_addon_logs(
        slug: str,
        lines: int = 100,
        boot: int | str | None = None,
        latest: bool = False,
    ) -> object:
        """Lee los logs recientes de un add-on.

        Los logs se REDACTAN automáticamente antes de ser devueltos:
        passwords, tokens, JWT, URLs con auth básica son sustituidos
        por ***REDACTED*** / ***JWT_REDACTED***.

        En el log del PROPIO Hermes, con `log_redact_network` activo (por
        defecto), también se redactan el hostname público (`<public_hostname>`),
        los nombres `*.ts.net` y las IPs que no son de loopback
        (`<ip:CLASE:HHHHHHHH>`, misma IP → mismo seudónimo), incluidas las
        líneas escritas antes de actualizar. Los logs de otros add-ons
        conservan sus IPs, que suelen ser justo lo que se quiere diagnosticar.

        Args:
            slug: Identificador del add-on.
            lines: Número de líneas a devolver (default 100, máx 1000).
            boot: Opcional (1.2.0): arranque a leer, como desplazamiento
                entero (0 = el actual, -1 = el anterior) o un id de
                `sv_list_boots`. Sin `boot` ni `latest`, la petición y la
                respuesta son las de siempre.
            latest: Opcional (1.2.0): solo las líneas desde el último arranque
                del contenedor del add-on. No se combina con `boot`.

        Returns:
            {"slug": "...", "lines_requested": N, "redacted": bool,
             "secrets_redacted": bool, "network_redacted": bool,
             "logs": "texto del log"}
            `redacted`: el texto devuelto difiere del leído.
            `secrets_redacted`: esta llamada sustituyó al menos un secreto.
            `network_redacted`: se aplicó la redacción de red (log de Hermes
            con `log_redact_network` activo), aunque el texto ya viniera
            redactado y no cambie; `false` para otros add-ons.
            `lines_requested` es el número pedido después de acotarlo a
            [1, 1000]; el log devuelto puede traer menos líneas si el add-on
            no tiene más. Si el log no cabe en `response_max_bytes`, se
            devuelven sus ÚLTIMAS líneas que caben, con `truncated: true`,
            `lines_returned` y una pista.
            Con `boot` o `latest`, la respuesta lleva además `route` (la
            plantilla de la ruta) y `boot` o `latest`. Un `boot` inválido, o
            `boot` con `latest`, devuelve {"error": "invalid_argument",
            "field", "detail"} sin llamar al Supervisor.
        """
        if (err := _bad_slug(slug)):
            return err
        # Spec 013 (FR-007): `boot` y `latest` son opcionales y, sin ellos, la
        # petición y la respuesta son las de la 1.1.2 (FR-020 de la 008). La
        # validación es la de las tools de logs del sistema (`tools/_logs.py`).
        try:
            boot_n = normalizar_boot(boot)
            comprobar_latest(boot_n, latest)
        except ArgumentoInvalido as exc:
            return exc.respuesta()
        ruta, plantilla = ruta_de_log(f"/addons/{slug}", "/addons/{app}", boot_n, latest)
        por_arranque = boot_n is not None or latest
        lines = min(max(1, lines), 1000)
        try:
            raw = await ha_client.sv_request_text(
                ruta,
                params={"lines": str(lines)},
            )
        except HAConnectionError as exc:
            # El mensaje del Supervisor puede repetir parte de la petición o
            # del log: se redacta como el log (FR-024 de la 013), y con la red
            # tapada si es el de Hermes. La forma `{"error": …}` es la de la
            # 1.1.2.
            mensaje = redact_secrets(str(exc))
            if _es_hermes(slug):
                mensaje = redact_network(mensaje)
            return {"error": mensaje}

        redacted = redact_secrets(raw)
        secrets_redacted = redacted != raw
        # `redacted` solo dice si el texto cambió. El log de Hermes ya se
        # escribe con la red tapada, así que lo normal es que no cambie aunque
        # la redacción de red se haya aplicado: sin este campo el agente leía
        # `redacted: false` y no podía saberlo (FR-005 de la 009).
        network_redacted = _es_hermes(slug) and network_redaction_enabled()
        if _es_hermes(slug):
            # El log de Hermes se pide para pegarlo en un issue, y las líneas
            # escritas por versiones anteriores (o con la opción recién
            # activada) traen hostname e IPs en claro. `redact_network` no
            # hace nada si la opción está desactivada.
            redacted = redact_network(redacted)
        was_redacted = redacted != raw
        # La plantilla de la ruta, nunca el id de arranque, y solo si se pidió
        # un arranque: sin `boot` ni `latest` el evento es el de antes.
        extra_log: dict[str, Any] = {"route": plantilla} if por_arranque else {}
        logger.info(
            "sv_get_addon_logs",
            slug=slug,
            lines=lines,
            bytes=len(raw),
            redacted=was_redacted,
            secrets_redacted=secrets_redacted,
            network_redacted=network_redacted,
            **extra_log,
        )
        respuesta: dict[str, Any] = {
            "slug": slug,
            "lines_requested": lines,
            "redacted": was_redacted,
            "secrets_redacted": secrets_redacted,
            "network_redacted": network_redacted,
        }
        if por_arranque:
            respuesta["route"] = plantilla
            if boot_n is not None:
                respuesta["boot"] = boot_n
            if latest:
                respuesta["latest"] = True
        return _ultimas_lineas_que_caben(respuesta, redacted, response_max_bytes)

    @mcp.tool()
    async def sv_get_addon_stats(slug: str) -> object:
        """Devuelve estadísticas de recursos de un add-on (CPU, RAM, red, disco).

        Args:
            slug: Identificador del add-on.

        Returns:
            La respuesta del Supervisor tal cual:
            {"cpu_percent": ..., "cpu_usage": ..., "cpu_system_usage": ...,
             "online_cpus": ..., "memory_usage": ..., "memory_limit": ...,
             "memory_percent": ..., "network_tx": ..., "network_rx": ...,
             "blk_read": ..., "blk_write": ...}
            Memoria, red y `blk_*` (lectura/escritura en disco) van en bytes.
        """
        if (err := _bad_slug(slug)):
            return err
        try:
            data = await ha_client.sv_request("GET", f"/addons/{slug}/stats")
            return data if isinstance(data, dict) else {"raw": data}
        except HAConnectionError as exc:
            return {"error": str(exc)}


# ── Job tracking helpers ──────────────────────────────────────────────────────
# Compartido entre addons.py y backups.py a través de importación directa.
# Fichero de estado: /data/pending_jobs.json

_PENDING_JOBS_PATH = Path("/data/pending_jobs.json")
_jobs_lock = asyncio.Lock()
_JOB_CLEANUP_AFTER_SECONDS = 3600  # 1 hora


def _load_jobs_sync() -> dict[str, Any]:
    try:
        jobs = json.loads(_PENDING_JOBS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(jobs, dict):
        # Un JSON válido pero que no es un objeto (`[]`, `null`, un número)
        # rompía a `_track_job` con TypeError DESPUÉS de haber lanzado ya el
        # POST de install/backup: la operación quedaba corriendo en el
        # Supervisor, su job_id perdido y el token de confirmación colgado sin
        # cerrar. Tratarlo como fichero corrupto y empezar de cero pierde como
        # mucho el seguimiento de jobs anteriores, nunca el actual.
        logger.warning(
            "pending_jobs_file_corrupt",
            path=str(_PENDING_JOBS_PATH),
            tipo=type(jobs).__name__,
        )
        return {}
    return jobs


def _write_jobs_sync(jobs: dict[str, Any]) -> None:
    tmp = _PENDING_JOBS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_PENDING_JOBS_PATH)


async def _track_job(job_id: str, meta: dict[str, Any]) -> None:
    """Persiste un job en vuelo en pending_jobs.json."""
    _PENDING_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _jobs_lock:
        jobs = _load_jobs_sync()
        jobs[job_id] = {
            **meta,
            "started_at": time.time(),
            "status": "running",
        }
        # Limpiar jobs viejos (>1h)
        cutoff = time.time() - _JOB_CLEANUP_AFTER_SECONDS
        jobs = {k: v for k, v in jobs.items() if v.get("started_at", 0) > cutoff}
        jobs[job_id] = {**meta, "started_at": time.time(), "status": "running"}
        _write_jobs_sync(jobs)
