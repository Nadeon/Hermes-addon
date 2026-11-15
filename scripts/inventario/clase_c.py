"""Clasificación revisada de la clase C para el generador de la tabla (spec
025, research R-4).

Comando de Core → `category`, `reason` y, solo si difieren del valor por
defecto, `one_shot`, `redact_extra`, `open_world` y `example`. Los textos son
los de `command_table.py` (research.md R-1 de la 025); la familia
(`generic_commands`) y la CAP las pone el generador desde el inventario.

POR QUÉ EXISTE: la regeneración EN SU SITIO ya conserva byte a byte cada
entrada revisada, pero la generación DESDE CERO (sin tabla previa) clasifica
con `_clasificar`, que daba a toda fila de clase C `deny` «pendiente de
revisión (spec 025)». Sin este mapa, generar desde cero desharía la revisión
comando a comando. `tests/test_generar_tabla.py` compara, fila a fila, la
generación desde cero con la tabla real: una entrada revisada en la tabla y no
aquí (o con otro texto) cae nombrándola.

Un módulo aparte y no `_DEDICADAS_INICIALES`: ese mapa solo admite tools o
`deny`, y 192 entradas con marcas enterrarían el resto del generador. Solo lo
importa `generar_tabla.py`; nada de `hermes/src` lo usa.

Se completa por tramos: el 1, `zwave_js/*`; el 2, ZHA, Matter, Thread y OTBR;
el 3, el resto.
"""

from __future__ import annotations

CLASE_C: dict[str, dict[str, object]] = {
    "zwave_js/abort_firmware_update": {"category": "deny", "reason": "firmware: abortar un flasheo a medias puede dejar el nodo inservible; se hace desde la UI"},
    "zwave_js/add_node": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/backup_nvm": {"category": "deny", "reason": "copia de la NVM del controlador por eventos de progreso (el resultado llega en un evento, no en la respuesta)"},
    "zwave_js/begin_rebuilding_routes": {"category": "confirm", "reason": "reconstruye las rutas de toda la red (largo, mucho tráfico de radio)"},
    "zwave_js/cancel_secure_bootstrap_s2": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/check_for_config_updates": {"category": "read", "reason": "pregunta por internet si hay base de datos de dispositivos nueva; solo lee", "open_world": True},
    "zwave_js/data_collection_status": {"category": "read", "reason": "si se envían estadísticas de uso a Z-Wave JS; solo lee"},
    "zwave_js/get_config_parameters": {"category": "read", "reason": "parámetros de configuración de un nodo con su valor y metadatos; solo lee"},
    "zwave_js/get_log_config": {"category": "read", "reason": "configuración del log del driver Z-Wave JS; solo lee"},
    "zwave_js/get_node_firmware_update_capabilities": {"category": "read", "reason": "qué admite un nodo para actualizar firmware; solo lee"},
    "zwave_js/get_provisioning_entries": {"category": "read", "reason": "nodos preaprovisionados por SmartStart; el `dsk` (incluye el PIN de S2) sale tapado", "redact_extra": ("dsk",)},
    "zwave_js/get_raw_config_parameter": {"category": "read", "reason": "pide al nodo el valor de un parámetro sin definición (tráfico de radio, no cambia nada)"},
    "zwave_js/grant_security_classes": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/hard_reset_controller": {"category": "deny", "reason": "reset de fábrica del controlador: borra la red entera"},
    "zwave_js/install_config_update": {"category": "confirm", "reason": "descarga e instala la base de datos de dispositivos nueva", "open_world": True},
    "zwave_js/invoke_cc_api": {"category": "deny", "reason": "llamada arbitraria a una clase de comando: puede escribir cualquier cosa (códigos de cerradura, seguridad) y no tiene vista previa útil"},
    "zwave_js/is_any_ota_firmware_update_in_progress": {"category": "read", "reason": "si algún nodo está actualizando firmware; solo lee"},
    "zwave_js/is_node_firmware_update_in_progress": {"category": "read", "reason": "si un nodo está actualizando firmware; solo lee"},
    "zwave_js/lookup_device": {"category": "read", "reason": "busca un modelo en la base de datos de dispositivos local de Z-Wave JS; solo lee"},
    "zwave_js/network_neighbors": {"category": "confirm", "reason": "lee la tabla de vecinos de todos los nodos APAGANDO la radio mientras dura (puede colgar controladores antiguos)"},
    "zwave_js/network_status": {"category": "read", "reason": "estado de la red Z-Wave: cliente, controlador y nodos (sin claves); solo lee"},
    "zwave_js/node_alerts": {"category": "read", "reason": "avisos de la base de datos de dispositivos para un nodo; solo lee"},
    "zwave_js/node_capabilities": {"category": "read", "reason": "clases de comando de cada endpoint de un nodo; solo lee"},
    "zwave_js/node_metadata": {"category": "read", "reason": "instrucciones de inclusión, exclusión y reset del fabricante y enlace a su base de datos; solo lee"},
    "zwave_js/node_status": {"category": "read", "reason": "estado de un nodo (vivo, dormido, listo, seguridad); solo lee"},
    "zwave_js/parse_qr_code_string": {"category": "deny", "reason": "devuelve el DSK del código QR (incluye el PIN de S2)"},
    "zwave_js/provision_smart_start_node": {"category": "deny", "reason": "SmartStart: lleva el DSK del código QR (incluye el PIN de S2); se hace desde la UI"},
    "zwave_js/rebuild_node_routes": {"category": "confirm", "reason": "reconstruye las rutas de un nodo", "example": {"device_id": "<device_id>"}},
    "zwave_js/refresh_node_cc_values": {"category": "confirm", "reason": "vuelve a pedir al nodo los valores de una clase de comando"},
    "zwave_js/refresh_node_info": {"category": "deny", "reason": "reentrevista el nodo y registra una suscripción de progreso en la conexión compartida que la genérica no cierra"},
    "zwave_js/refresh_node_values": {"category": "confirm", "reason": "vuelve a pedir al nodo todos sus valores (tráfico de radio)"},
    "zwave_js/remove_failed_node": {"category": "deny", "reason": "quita un nodo a la fuerza de la red, sin vuelta atrás"},
    "zwave_js/remove_node": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/replace_failed_node": {"category": "deny", "reason": "sustituye un nodo fallido: inclusión interactiva con eventos y sin vuelta atrás"},
    "zwave_js/restore_nvm": {"category": "deny", "reason": "sobrescribe la NVM del controlador: cambia la red entera"},
    "zwave_js/set_config_parameter": {"category": "confirm", "reason": "cambia un parámetro de configuración de un nodo", "example": {"device_id": "<device_id>", "property": 3, "value": 1}},
    "zwave_js/set_raw_config_parameter": {"category": "confirm", "reason": "escribe un parámetro sin definición en el nodo (lee antes el valor con get_raw_config_parameter)"},
    "zwave_js/stop_exclusion": {"category": "confirm", "reason": "detiene una exclusión en curso"},
    "zwave_js/stop_inclusion": {"category": "confirm", "reason": "detiene una inclusión en curso"},
    "zwave_js/stop_rebuilding_routes": {"category": "confirm", "reason": "detiene la reconstrucción de rutas de la red"},
    "zwave_js/subscribe_config_parameter_updates": {"category": "deny", "reason": "suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta"},
    "zwave_js/subscribe_controller_statistics": {"category": "read", "reason": "estadísticas del controlador: un solo mensaje y se cancela", "one_shot": True},
    "zwave_js/subscribe_firmware_update_status": {"category": "deny", "reason": "suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta"},
    "zwave_js/subscribe_log_updates": {"category": "deny", "reason": "suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta"},
    "zwave_js/subscribe_new_devices": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/subscribe_node_statistics": {"category": "read", "reason": "estadísticas de un nodo (RSSI, rutas, fallos): un solo mensaje y se cancela", "one_shot": True},
    "zwave_js/subscribe_node_status": {"category": "deny", "reason": "suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta"},
    "zwave_js/subscribe_rebuild_routes_progress": {"category": "deny", "reason": "suscripción/streaming sin primer mensaje con el estado: MCP es petición-respuesta"},
    "zwave_js/subscribe_s2_inclusion": {"category": "deny", "reason": "inclusión o exclusión interactiva: eventos, pulsar un botón del dispositivo y S2; se hace desde la UI"},
    "zwave_js/supports_feature": {"category": "read", "reason": "si el controlador admite una función (p. ej. SmartStart); solo lee"},
    "zwave_js/try_parse_dsk_from_qr_code_string": {"category": "deny", "reason": "devuelve el DSK del código QR (incluye el PIN de S2)"},
    "zwave_js/unprovision_smart_start_node": {"category": "deny", "reason": "SmartStart: lleva el DSK del código QR (incluye el PIN de S2); se hace desde la UI"},
    "zwave_js/update_data_collection_preference": {"category": "confirm", "reason": "activa o desactiva el envío de estadísticas de uso a Z-Wave JS"},
    "zwave_js/update_log_config": {"category": "confirm", "reason": "cambia el nivel o el destino del log del driver Z-Wave JS"},
    "zwave_js/validate_dsk_and_enter_pin": {"category": "deny", "reason": "introduce el PIN de S2 de una inclusión: secreto y acción física"},
}
