"""Privilegios en la vista previa de instalar y reconstruir (spec 034, tramo
3; T030–T033; FR-021, FR-022 y FR-023).

`sv_install_addon` y `sv_rebuild_addon` enseñan en su vista previa el bloque
`privileges` (data-model.md): los campos de privilegio de la ficha de la
tienda (`store`), los de la app instalada (`installed`, solo reconstruir), lo
que declara el `config.*` de una app local en `/addons`
(`declared_in_folder`, solo `local_*`) y `elevated`. El token se ata además a
ese bloque con `estado`: si cambia antes de confirmar, `preview_outdated` y
no se envía nada.

Las fichas tienen la forma REAL del Supervisor 2026.11.0, sacada de su
código: `GET /store/addons/{slug}` es `_generate_app_information(app,
extended=True)` (`supervisor/api/store.py`) y `GET /addons/{slug}/info` es
`info_data` (`supervisor/api/apps.py`). Ojo: en las dos, `apparmor` es TEXTO
(`"default"`, `"profile"` o `"disable"`, `apps/model.py`), no un booleano;
en el `config.yaml`, en cambio, es booleano (`apps/validate.py`). La raíz de
`/addons` es una carpeta temporal con ficheros REALES.

Controles negativos (T035, recuentos en `tasks.md`):
(a) sin `privileges` en el estado de instalar → caen los de privilegios
    cambiados de `TestEstadoDelToken`;
(b) lo mismo en reconstruir → caen los de `TestReconstruir` con un cambio;
(c) la ficha entera en `store` → cae `test_campos_exactos_de_la_tienda`;
(d) sin redactar los textos → cae `test_centinela_redactado`;
(e) mirar `local_*` también en `share` o sin el índice → caen los de
    `declared_in_folder`.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

from hermes import folders
from hermes.ha import HAConnectionError
from hermes.tools import addons as addons_mod
from hermes.tools import _store
from hermes.tools import store_apps as store_apps_mod
from hermes.tools._store import (
    CAMPOS_PRIVILEGIO_INSTALADA,
    CAMPOS_PRIVILEGIO_TIENDA,
    declarado_en_carpeta,
    estado_de_privilegios,
    privilegios_de,
)
from hermes.tools.addons import _LONG_OP_TIMEOUT
from tests.fixtures.supervisor_tienda import SupervisorSimulado, ficha

CENTINELA = "centinela-clave-1"
_LOCAL = "local_ejemplo"
_TERCEROS = "abcd1234_ejemplo"

# Los campos de privilegio, escritos aquí A MANO (y no importados) para que
# el test diga cuáles son: FR-021 (tienda) y FR-022 (instalada).
_TIENDA = {
    "apparmor", "auth_api", "docker_api", "full_access", "hassio_api",
    "hassio_role", "homeassistant_api", "host_network", "host_pid", "ingress",
    "rating", "signed",
}
_SOLO_INSTALADA = {
    "privileged", "devices", "host_ipc", "host_uts", "host_dbus",
    "kernel_modules", "udev", "usb", "uart", "gpio", "devicetree", "video",
    "audio",
}


def ficha_extendida(slug: str, **campos: Any) -> dict[str, Any]:
    """`GET /store/addons/{slug}` del Supervisor 2026.11.0: todos los campos
    de `_generate_app_information` con `extended=True`."""
    base = ficha(slug)
    base.update({
        # Los no extendidos que faltan en la ficha de la 030.
        "description": "Descripcion corta", "icon": False, "logo": False,
        "update_available": False, "url": "https://example.com/app",
        # Los extendidos.
        "apparmor": "default", "auth_api": False, "detached": False,
        "docker_api": False, "full_access": False, "hassio_api": True,
        "hassio_role": "default", "homeassistant_api": False,
        "host_network": False, "host_pid": False, "ingress": True,
        "long_description": "Texto largo de la app con password: centinela-larga",
        "rating": 6, "signed": False,
    })
    base.update(campos)
    return base


def info_instalada(slug: str, **campos: Any) -> dict[str, Any]:
    """`GET /addons/{slug}/info` del Supervisor 2026.11.0 (`info_data`)."""
    base: dict[str, Any] = {
        "name": "Ejemplo local", "slug": slug, "hostname": "local-ejemplo",
        "dns": [], "description": "Descripcion corta",
        "long_description": "Texto largo password: centinela-larga",
        "stage": "stable", "repository": "local", "version_latest": "1.0.0",
        "protected": True, "rating": 6, "boot_config": "auto", "boot": "auto",
        "options": {"password": "centinela-opcion"}, "schema": [],
        "arch": ["amd64"], "machine": [], "homeassistant": None, "url": None,
        "detached": False, "available": True, "build": True,
        "network": {"8080/tcp": 8080}, "network_description": None,
        "host_network": False, "host_pid": False, "host_ipc": False,
        "host_uts": False, "host_dbus": False, "privileged": [],
        "full_access": False, "apparmor": "default", "icon": False,
        "logo": False, "changelog": False, "documentation": False,
        "stdin": False, "hassio_api": False, "hassio_role": "default",
        "auth_api": False, "homeassistant_api": False, "gpio": False,
        "usb": False, "uart": False, "kernel_modules": False,
        "devicetree": False, "udev": False, "docker_api": False,
        "video": False, "audio": False, "startup": "application",
        "services": [], "discovery": [], "translations": {}, "ingress": False,
        "signed": False, "state": "started", "webui": None,
        "ingress_entry": None, "ingress_url": None, "ingress_port": 8099,
        "ingress_panel": False, "audio_input": None, "audio_output": None,
        "auto_update": False, "ip_address": "192.0.2.10", "version": "1.0.0",
        "update_available": False, "watchdog": False, "devices": [],
        "system_managed": False, "system_managed_config_entry": None,
        "log_format": "default",
    }
    base.update(campos)
    return base


_CONFIG_LOCAL = """\
name: Ejemplo local
version: "1.0.0"
slug: ejemplo
description: App de ejemplo
arch: [amd64]
map:
  - share:rw
  - ssl
privileged:
  - NET_ADMIN
devices:
  - /dev/ttyUSB0
ports:
  8080/tcp: 8080
options:
  password: centinela-opcion
"""


class _MCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class _ConRaices(unittest.IsolatedAsyncioTestCase):
    """Raíces temporales de `/addons` y `/share` con ficheros reales."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.addons = base / "addons"
        self.share = base / "share"
        self.addons.mkdir()
        self.share.mkdir()
        for nombre, valor in (("ADDONS_BASE", self.addons), ("SHARE_BASE", self.share)):
            p = unittest.mock.patch.object(folders, nombre, valor)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        # Convergencia T047: una recarga de la tienda «posterior» a todo lo
        # que escriban estos tests, para que la copia del Supervisor cuente
        # como al día. `TestCopiaDeTienda` lo cambia.
        _store._ULTIMA_RECARGA = time.time() + 60

    def app_local(self, texto: str = _CONFIG_LOCAL, carpeta: str = "ejemplo",
                  raiz: Path | None = None) -> Path:
        d = (raiz or self.addons) / carpeta
        d.mkdir(parents=True, exist_ok=True)
        p = d / "config.yaml"
        p.write_text(texto, encoding="utf-8")
        return p

    def assertSin(self, valor: Any, *trozos: str) -> None:  # noqa: N802
        texto = json.dumps(valor, ensure_ascii=False)
        for trozo in trozos:
            self.assertNotIn(trozo, texto)


# ── Función pura (T030) ───────────────────────────────────────────────────────


class TestBloque(_ConRaices):
    def test_las_listas_del_modulo_son_las_de_la_spec(self) -> None:
        self.assertEqual(set(CAMPOS_PRIVILEGIO_TIENDA), _TIENDA)
        self.assertEqual(set(CAMPOS_PRIVILEGIO_INSTALADA), _TIENDA | _SOLO_INSTALADA)

    def test_campos_exactos_de_la_tienda(self) -> None:
        b = privilegios_de(store=ficha_extendida(_TERCEROS))
        self.assertEqual(set(b["store"]), _TIENDA)
        self.assertEqual(b["store"]["apparmor"], "default")
        self.assertEqual(b["store"]["rating"], 6)
        self.assertNotIn("installed", b)
        self.assertNotIn("declared_in_folder", b)
        self.assertEqual(b["elevated"], [])
        self.assertSin(b, "centinela-larga", "Descripcion corta", "long_description")

    def test_instalada_anade_los_suyos(self) -> None:
        b = privilegios_de(store=ficha_extendida(_LOCAL),
                           installed=info_instalada(_LOCAL))
        self.assertEqual(set(b["installed"]), _TIENDA | _SOLO_INSTALADA)
        self.assertSin(b, "centinela-opcion", "centinela-larga", "192.0.2.10")
        for prohibido in ("options", "schema", "long_description", "network"):
            self.assertNotIn(prohibido, b["installed"])

    def test_elevated_por_regla(self) -> None:
        # Un caso por regla (research R-7), sobre la app instalada, que es la
        # que trae todos los campos.
        casos: list[tuple[dict[str, Any], str]] = [
            ({"full_access": True}, "full_access"),
            ({"docker_api": True}, "docker_api"),
            ({"host_network": True}, "host_network"),
            ({"host_pid": True}, "host_pid"),
            ({"host_ipc": True}, "host_ipc"),
            ({"host_uts": True}, "host_uts"),
            ({"host_dbus": True}, "host_dbus"),
            ({"kernel_modules": True}, "kernel_modules"),
            ({"udev": True}, "udev"),
            ({"privileged": ["SYS_ADMIN"]}, "privileged"),
            ({"devices": ["/dev/ttyUSB0"]}, "devices"),
            ({"hassio_role": "manager"}, "hassio_role:manager"),
            ({"hassio_role": "admin"}, "hassio_role:admin"),
            ({"apparmor": "disable"}, "apparmor:disabled"),
        ]
        for campos, esperado in casos:
            with self.subTest(campos=campos):
                b = privilegios_de(store=ficha_extendida(_LOCAL),
                                   installed=info_instalada(_LOCAL, **campos))
                self.assertEqual(b["elevated"], [esperado])
        # Los que no son elevados por la regla fija.
        for campos in ({"hassio_role": "homeassistant"}, {"hassio_role": "backup"},
                       {"apparmor": "profile"}, {"usb": True}, {"gpio": True},
                       {"hassio_api": True}, {"homeassistant_api": True}):
            with self.subTest(no_elevado=campos):
                b = privilegios_de(store=ficha_extendida(_LOCAL),
                                   installed=info_instalada(_LOCAL, **campos))
                self.assertEqual(b["elevated"], [])

    def test_elevated_desde_la_tienda_y_el_fichero(self) -> None:
        b = privilegios_de(store=ficha_extendida(_TERCEROS, full_access=True,
                                                 apparmor="disable"))
        self.assertEqual(b["elevated"], ["apparmor:disabled", "full_access"])
        b = privilegios_de(
            store=ficha_extendida(_LOCAL),
            declared={"config": "ejemplo/config.yaml", "apparmor": False,
                      "map": [{"type": "share", "read_only": False},
                              {"type": "ssl", "read_only": True}]})
        self.assertEqual(b["elevated"], ["apparmor:disabled", "map:share (read-write)"])

    def test_fichero_como_el_supervisor(self) -> None:
        # Convergencia T046: el `config.*` pasa por `vol.Boolean()` del
        # Supervisor (`apps/validate.py`): un texto por su lista (con
        # `lower()`, sin `strip()`) y cualquier otro valor con `bool(v)`.
        # Esos campos no salen en la ficha de la tienda: si `elevated` no
        # los ve en el fichero, nada los ve.
        # Control negativo comprobado: con la interpretación anterior (solo
        # `True` y textos) `elevated` salía vacío con los enteros y caía este
        # test.
        decl = {"config": "ejemplo/config.yaml", "host_dbus": 1, "kernel_modules": 1,
                "udev": 2, "host_ipc": 1.0, "host_uts": "ON", "full_access": "enable",
                "docker_api": "1", "host_network": [0], "host_pid": 0,
                "apparmor": 0}
        b = privilegios_de(store=ficha_extendida(_LOCAL), declared=decl)
        self.assertEqual(b["elevated"], [
            "apparmor:disabled", "docker_api", "full_access", "host_dbus",
            "host_ipc", "host_network", "host_uts", "kernel_modules", "udev"])
        # Lo que el Supervisor apaga no es elevado: 0, "off", None, [] y
        # `apparmor` encendido de cualquier forma.
        for valor in (0, "off", "No", "disable", None, [], False):
            with self.subTest(apagado=valor):
                b = privilegios_de(declared={"config": "x/config.yaml",
                                             "host_dbus": valor, "apparmor": 1})
                self.assertEqual(b["elevated"], [])
        # Lo que no sabría interpretar cuenta como elevado (fail-closed).
        b = privilegios_de(declared={
            "config": "x/config.yaml", "host_dbus": " true", "apparmor": "quizas",
            "hassio_role": "root",
            "map": [{"type": "share", "read_only": "false"},
                    {"type": "ssl", "read_only": 0},
                    {"type": "media", "read_only": True}]})
        self.assertEqual(b["elevated"], [
            "apparmor:unparsed", "hassio_role:unparsed", "host_dbus:unparsed",
            "map:share (unparsed)", "map:ssl (unparsed)"])
        # En la API los booleanos son JSON y `apparmor` es texto: `"default"`
        # o `"profile"` no son «sin interpretar».
        b = privilegios_de(store=ficha_extendida(_LOCAL, apparmor="profile"),
                           installed=info_instalada(_LOCAL, apparmor="default"))
        self.assertEqual(b["elevated"], [])

    def test_sin_nada_elevated_vacio(self) -> None:
        b = privilegios_de(store=ficha_extendida(_LOCAL), installed=info_instalada(_LOCAL),
                           declared={"config": "ejemplo/config.yaml", "map": []})
        self.assertEqual(b["elevated"], [])

    def test_centinela_redactado(self) -> None:
        role = f"manager password: {CENTINELA}"
        device = f"/dev/ttyUSB0?token={CENTINELA}"
        b = privilegios_de(
            store=ficha_extendida(_LOCAL, hassio_role=role),
            installed=info_instalada(_LOCAL, hassio_role=role, devices=[device]),
            declared={"config": "ejemplo/config.yaml", "devices": [device],
                      "map": [{"type": "share", "read_only": False,
                               "path": f"/datos password: {CENTINELA}"}]})
        self.assertSin(b, CENTINELA)
        self.assertSin(estado_de_privilegios(b), CENTINELA)
        self.assertIn("devices", b["elevated"])

    def test_ninguna_fuente(self) -> None:
        self.assertIsNone(privilegios_de(store=None, motivos={"store": "boom"}))
        b = privilegios_de(store=None, declared={"config": "ejemplo/config.yaml"},
                           motivos={"store": "boom"})
        self.assertIsNone(b["store"])
        self.assertEqual(b["unavailable"], {"store": "boom"})

    def test_estado_sin_notas_ni_motivos(self) -> None:
        b = privilegios_de(store=None, declared={"config": "ejemplo/config.yaml",
                                                 "note": "x"},
                           motivos={"store": "boom 1"})
        b2 = privilegios_de(store=None, declared={"config": "ejemplo/config.yaml",
                                                  "note": "y"},
                            motivos={"store": "boom 2"})
        self.assertEqual(estado_de_privilegios(b), estado_de_privilegios(b2))
        self.assertIsNone(estado_de_privilegios(None))

    # ── declared_in_folder ──

    def test_declarado_en_carpeta(self) -> None:
        self.app_local()
        d = declarado_en_carpeta(_LOCAL)
        self.assertEqual(d["config"], "ejemplo/config.yaml")
        self.assertEqual(d["map"], [{"type": "share", "read_only": False},
                                    {"type": "ssl", "read_only": True}])
        self.assertEqual(d["privileged"], ["NET_ADMIN"])
        self.assertEqual(d["devices"], ["/dev/ttyUSB0"])
        self.assertEqual(d["ports"], {"8080/tcp": 8080})
        self.assertIn("sv_reload_store", d["note"])
        for prohibido in ("options", "name", "description", "slug", "version"):
            self.assertNotIn(prohibido, d)
        self.assertSin(d, "centinela-opcion")
        b = privilegios_de(store=ficha_extendida(_LOCAL), declared=d)
        self.assertEqual(b["elevated"], ["devices", "map:share (read-write)", "privileged"])

    def test_declarado_con_map_de_diccionarios(self) -> None:
        self.app_local("slug: ejemplo\nmap:\n  - type: share\n    read_only: false\n"
                       "    path: /datos\n  - type: media\n")
        d = declarado_en_carpeta(_LOCAL)
        self.assertEqual(d["map"], [{"type": "share", "read_only": False, "path": "/datos"},
                                    {"type": "media", "read_only": True}])

    def test_declarado_solo_para_local(self) -> None:
        self.app_local()
        for slug in ("core_ejemplo", "abcd1234_ejemplo", "ejemplo"):
            with self.subTest(slug=slug):
                self.assertIsNone(declarado_en_carpeta(slug))

    def test_declarado_solo_desde_addons_y_por_el_indice(self) -> None:
        # Una app en /share con su `config.yaml` no es una app local: el
        # Supervisor solo mira /addons.
        self.app_local("slug: otra\nprivileged: [SYS_ADMIN]\n", carpeta="otra",
                       raiz=self.share)
        self.assertIsNone(declarado_en_carpeta("local_otra"))
        # El slug es el que DECLARA el fichero, no el nombre de la carpeta.
        self.app_local("slug: distinto\n", carpeta="ejemplo")
        self.assertIsNone(declarado_en_carpeta(_LOCAL))
        self.assertEqual(declarado_en_carpeta("local_distinto")["config"],
                         "ejemplo/config.yaml")
        # Lo que está bajo `rootfs` o una carpeta oculta, tampoco (R-4).
        self.app_local("slug: oculta\n", carpeta=".oculta")
        self.assertIsNone(declarado_en_carpeta("local_oculta"))


# ── Instalar (T031) ───────────────────────────────────────────────────────────


class _Instalar(_ConRaices):
    def setUp(self) -> None:
        super().setUp()
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        addons_mod.register(mcp, self.sv)
        self.t = mcp.tools

    def tienda(self, slug: str = _TERCEROS, **campos: Any) -> None:
        self.sv.respuesta("GET", f"/store/addons/{slug}", ficha_extendida(slug, **campos))
        self.sv.respuesta("GET", f"/store/addons/{slug}/availability", {})


class TestInstalar(_Instalar):
    async def test_vista_previa_con_la_tienda(self) -> None:
        self.tienda(full_access=True)
        r = await self.t["sv_install_addon"](_TERCEROS)
        priv = r["preview"]["privileges"]
        self.assertEqual(set(priv["store"]), _TIENDA)
        self.assertIs(priv["store"]["full_access"], True)
        self.assertEqual(priv["elevated"], ["full_access"])
        self.assertNotIn("declared_in_folder", priv)
        self.assertNotIn("installed", priv)
        self.assertIn("confirmation_token", r)
        # Sin llamadas nuevas al Supervisor: la ficha y la disponibilidad.
        self.assertEqual(self.sv.rutas(), [
            ("GET", f"/store/addons/{_TERCEROS}"),
            ("GET", f"/store/addons/{_TERCEROS}/availability"),
        ])
        self.assertSin(r, "centinela-larga")

    async def test_app_local_con_declared_in_folder(self) -> None:
        self.app_local()
        self.tienda(_LOCAL, repository="local")
        r = await self.t["sv_install_addon"](_LOCAL)
        priv = r["preview"]["privileges"]
        decl = priv["declared_in_folder"]
        self.assertEqual(decl["config"], "ejemplo/config.yaml")
        self.assertEqual(decl["map"][0], {"type": "share", "read_only": False})
        self.assertIn("sv_reload_store", decl["note"])
        self.assertEqual(priv["elevated"], ["devices", "map:share (read-write)", "privileged"])
        self.assertSin(r, "centinela-opcion")

    async def test_app_local_sin_carpeta_no_lo_inventa(self) -> None:
        # `local_ejemplo` sin `config.*` en /addons: no hay nada declarado, y
        # desde la convergencia T047 no se supone nada: sin token.
        self.tienda(_LOCAL, repository="local")
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale")
        self.assertNotIn("confirmation_token", r)

    async def test_app_local_con_addons_sin_montar(self) -> None:
        self.app_local()
        self.tienda(_LOCAL, repository="local")
        with unittest.mock.patch.object(folders, "ADDONS_BASE", self.addons / "sin_montar"):
            r = await self.t["sv_install_addon"](_LOCAL)
        # Convergencia T047: sin /addons no se sabe qué copia tiene el
        # Supervisor: sin token.
        self.assertEqual(r["error"], "store_copy_stale")
        self.assertIn("/addons", r["reason"])
        self.assertNotIn("confirmation_token", r)

    async def test_tienda_no_local_sin_declared(self) -> None:
        # Aunque haya una carpeta con el mismo slug en /addons.
        self.app_local("slug: ejemplo\n")
        self.tienda()
        r = await self.t["sv_install_addon"](_TERCEROS)
        self.assertNotIn("declared_in_folder", r["preview"]["privileges"])

    async def test_ficha_ilegible(self) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}", HAConnectionError(
            f"failed 500: boom password: {CENTINELA}", status=500))
        r = await self.t["sv_install_addon"](_TERCEROS)
        p = r["preview"]
        self.assertIsNone(p["privileges"])
        self.assertIn("boom", p["privileges_unavailable"])
        self.assertIn("confirmation_token", r)
        self.assertSin(r, CENTINELA)

    async def test_rechazos_de_la_030_sin_cambios(self) -> None:
        r = await self.t["sv_install_addon"](_TERCEROS)
        self.assertEqual(r["error"], "addon_not_found")
        self.tienda(installed=True, version="2.0.0")
        r = await self.t["sv_install_addon"](_TERCEROS)
        self.assertEqual(r["error"], "already_installed")
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}", ficha_extendida(_TERCEROS))
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}/availability", HAConnectionError(
            'failed 400: {"result": "error", "message": "not supported"}', status=400))
        r = await self.t["sv_install_addon"](_TERCEROS)
        self.assertEqual(r["error"], "addon_not_available")
        self.assertEqual(self.sv.escrituras(), [])


# ── Estado del token de instalar (T032) ───────────────────────────────────────


class TestEstadoDelToken(_Instalar):
    async def _confirmar(self, slug: str = _TERCEROS) -> dict[str, Any]:
        prev = await self.t["sv_install_addon"](slug)
        self.assertIn("confirmation_token", prev)
        return prev

    async def test_privilegios_cambiados_en_la_tienda(self) -> None:
        f1 = ficha_extendida(_TERCEROS)
        f2 = ficha_extendida(_TERCEROS, full_access=True)
        self.sv.secuencia("GET", f"/store/addons/{_TERCEROS}", [f1, f2])
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}/availability", {})
        self.sv.respuesta("POST", f"/store/addons/{_TERCEROS}/install", {"job_id": "x"})
        prev = await self._confirmar()
        r = await self.t["sv_install_addon"](
            _TERCEROS, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertIn("privileges", r["hint"])
        self.assertIn("version", r["hint"])
        self.assertEqual(self.sv.escrituras(), [])

    async def test_config_local_cambiado(self) -> None:
        # Con los campos obligatorios del esquema del Supervisor: sin ellos,
        # él descartaría el fichero (convergencia 2, T055).
        cabecera = "name: E\nversion: '1'\ndescription: d\narch: [amd64]\n"
        p = self.app_local(cabecera + "slug: ejemplo\nmap:\n  - ssl\n")
        self.tienda(_LOCAL, repository="local")
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "x"})
        prev = await self._confirmar(_LOCAL)
        p.write_text(cabecera + "slug: ejemplo\nmap:\n  - ssl\n  - share:rw\n",
                     encoding="utf-8")
        r = await self.t["sv_install_addon"](
            _LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_version_cambiada_como_en_la_030(self) -> None:
        self.sv.secuencia("GET", f"/store/addons/{_TERCEROS}", [
            ficha_extendida(_TERCEROS), ficha_extendida(_TERCEROS, version_latest="3.0.0")])
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}/availability", {})
        prev = await self._confirmar()
        r = await self.t["sv_install_addon"](
            _TERCEROS, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertEqual(r["version_latest"], "3.0.0")
        self.assertEqual(self.sv.escrituras(), [])

    async def test_sin_cambios_la_peticion_de_la_1_1_2(self) -> None:
        self.app_local()
        self.tienda(_LOCAL, repository="local")
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "abc"})
        prev = await self._confirmar(_LOCAL)
        n = len(self.sv.llamadas)
        r = await self.t["sv_install_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r["job_id"], "abc")
        # Convergencia 3 (T058): entre medias, la lectura de `/jobs/info`.
        [ficha_, jobs, post] = self.sv.llamadas[n:]
        self.assertEqual((jobs["metodo"], jobs["ruta"]), ("GET", "/jobs/info"))
        self.assertEqual((ficha_["metodo"], ficha_["ruta"]), ("GET", f"/store/addons/{_LOCAL}"))
        self.assertEqual((post["metodo"], post["ruta"], post["json"], post["timeout"]),
                         ("POST", f"/store/addons/{_LOCAL}/install", {"background": True},
                          _LONG_OP_TIMEOUT))

    async def test_ficha_ilegible_las_dos_veces_sigue_como_hoy(self) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}",
                          HAConnectionError("failed 500: boom", status=500))
        self.sv.respuesta("POST", f"/store/addons/{_TERCEROS}/install", {"job_id": "abc"})
        prev = await self._confirmar()
        r = await self.t["sv_install_addon"](
            _TERCEROS, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("job_id"), "abc", r)


# ── Reconstruir (T033) ────────────────────────────────────────────────────────


class TestReconstruir(_ConRaices):
    def setUp(self) -> None:
        super().setUp()
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        store_apps_mod.register(mcp, self.sv)
        self.t = mcp.tools
        self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", {})

    def fuentes(self, *, tienda: Any = None, info: Any = None) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}",
                          tienda or ficha_extendida(_LOCAL, repository="local",
                                                    installed=True, version="1.0.0",
                                                    version_latest="1.0.0", build=True))
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info or info_instalada(_LOCAL))

    async def test_vista_previa_con_las_tres_fuentes(self) -> None:
        self.app_local()
        self.fuentes(info=info_instalada(_LOCAL, host_network=True))
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        priv = r["preview"]["privileges"]
        self.assertEqual(set(priv["store"]), _TIENDA)
        self.assertEqual(set(priv["installed"]), _TIENDA | _SOLO_INSTALADA)
        self.assertEqual(priv["declared_in_folder"]["config"], "ejemplo/config.yaml")
        self.assertEqual(priv["elevated"], ["devices", "host_network",
                                            "map:share (read-write)", "privileged"])
        self.assertIn("confirmation_token", r)
        self.assertSin(r, "centinela-opcion", "centinela-larga")
        self.assertEqual(self.sv.escrituras(), [])

    async def test_sin_carpeta_ni_tienda(self) -> None:
        # La ficha de la tienda no está (404): `store` es null con su motivo
        # y el token sale igual.
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info_instalada(_LOCAL))
        self.app_local()
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        priv = r["preview"]["privileges"]
        self.assertIsNone(priv["store"])
        self.assertIn("store", priv["unavailable"])
        self.assertIn("declared_in_folder", priv)
        self.assertIn("confirmation_token", r)
        # Sin `config.*` local: desde la convergencia T047 no se supone qué
        # copia tiene el Supervisor, y no hay token.
        (self.addons / "ejemplo" / "config.yaml").unlink()
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale")
        self.assertNotIn("confirmation_token", r)

    async def _cambio(self, cambiar) -> dict[str, Any]:
        prev = await self.t["sv_rebuild_addon"](_LOCAL)
        self.assertIn("confirmation_token", prev)
        cambiar()
        r = await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertIs(r.get("preview_outdated"), True, r)
        self.assertIn("privileges", r["hint"])
        self.assertNotIn(("POST", f"/addons/{_LOCAL}/rebuild"), self.sv.rutas())
        return r

    async def test_cambia_la_tienda(self) -> None:
        self.app_local()
        self.fuentes()
        await self._cambio(lambda: self.fuentes(tienda=ficha_extendida(
            _LOCAL, repository="local", installed=True, version="1.0.0",
            version_latest="1.0.0", build=True, docker_api=True)))

    async def test_cambia_la_instalada(self) -> None:
        self.app_local()
        self.fuentes()
        await self._cambio(lambda: self.fuentes(
            info=info_instalada(_LOCAL, privileged=["SYS_ADMIN"])))

    async def test_cambia_el_fichero(self) -> None:
        p = self.app_local()
        self.fuentes()
        await self._cambio(lambda: p.write_text(
            _CONFIG_LOCAL.replace("  - ssl\n", "  - ssl:rw\n"), encoding="utf-8"))

    async def test_sin_cambios_la_peticion_de_la_030(self) -> None:
        self.app_local()
        self.fuentes()
        prev = await self.t["sv_rebuild_addon"](_LOCAL)
        r = await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "slug": _LOCAL, "force": False})
        [post] = self.sv.escrituras()
        self.assertEqual((post["ruta"], post["json"], post["timeout"]),
                         (f"/addons/{_LOCAL}/rebuild", {"force": False}, _LONG_OP_TIMEOUT))

    async def test_rechazos_de_la_030_sin_cambios(self) -> None:
        for campos, error in (({"version": None}, "addon_not_installed"),
                              ({"detached": True}, "addon_not_in_store"),
                              ({"version_latest": "1.1.0"}, "rebuild_version_changed"),
                              ({"build": False}, "rebuild_not_supported")):
            with self.subTest(error=error):
                self.fuentes(info=info_instalada(_LOCAL, **campos))
                r = await self.t["sv_rebuild_addon"](_LOCAL)
                self.assertEqual(r.get("error"), error, r)
                self.assertNotIn("confirmation_token", r)
                self.assertNotIn("privileges", r)
        self.assertEqual(self.sv.escrituras(), [])


# ── Copia de la tienda desfasada (convergencia T047) ──────────────────────────


class TestCopiaDeTienda(_ConRaices):
    """El Supervisor instala y reconstruye una app local con SU copia del
    `config.*`, la de la última recarga de la tienda (`store/data.py`;
    `rebuild` copia esa ficha, `apps/app.py`). Si el fichero o su camino
    cambiaron después de la última recarga que lanzó Hermes, o Hermes no ha
    lanzado ninguna, `store_copy_stale` sin token, en la vista previa y otra
    vez al confirmar, con la comprobación y la petición bajo el candado de
    /addons.

    Controles negativos comprobados: (a) sin la comprobación en la vista
    previa de instalar → cae `test_sin_recarga_instalar`; (b) sin ella al
    confirmar → cae `test_cambia_el_camino_entre_vista_previa_y_confirmacion`
    (instalar y reconstruir); (c) mirando solo la fecha del fichero → cae
    `test_mover_una_carpeta_del_camino_cuenta`; (d) sin el candado → cae
    `test_confirmar_espera_al_candado_de_addons`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.sv = SupervisorSimulado()
        mcp = _MCP()
        addons_mod.register(mcp, self.sv)
        store_apps_mod.register(mcp, self.sv)
        self.t = mcp.tools
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}",
                          ficha_extendida(_LOCAL, repository="local"))
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}/availability", {})
        self.sv.respuesta("POST", f"/store/addons/{_LOCAL}/install", {"job_id": "j1"})

    def reconstruible(self) -> None:
        self.sv.respuesta("GET", f"/store/addons/{_LOCAL}", ficha_extendida(
            _LOCAL, repository="local", installed=True, version="1.0.0",
            version_latest="1.0.0", build=True))
        self.sv.respuesta("GET", f"/addons/{_LOCAL}/info", info_instalada(_LOCAL))
        self.sv.respuesta("POST", f"/addons/{_LOCAL}/rebuild", {})

    def fechas(self, ruta: Path, segundos: float) -> None:
        os.utime(ruta, (segundos, segundos))

    def app_con_fechas(self, hace: float = 600) -> Path:
        """App local con el fichero y su camino fechados `hace` segundos."""
        p = self.app_local()
        antes = time.time() - hace
        for r in (p, p.parent, self.addons):
            self.fechas(r, antes)
        return p

    async def test_sin_recarga_instalar(self) -> None:
        self.app_con_fechas()
        _store._ULTIMA_RECARGA = None
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale", r)
        self.assertIn("not reloaded the store", r["reason"])
        self.assertIn("sv_reload_store", r["hint"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras(), [])

    async def test_sin_recarga_reconstruir(self) -> None:
        self.app_con_fechas()
        self.reconstruible()
        _store._ULTIMA_RECARGA = None
        r = await self.t["sv_rebuild_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale", r)
        self.assertNotIn("confirmation_token", r)

    async def test_fichero_posterior_a_la_recarga(self) -> None:
        p = self.app_con_fechas()
        _store._ULTIMA_RECARGA = time.time() - 300
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertIn("confirmation_token", r)
        # Se reescribe después de la recarga: la copia del Supervisor puede
        # ser otra (el ataque de escribir, recargar y volver a escribir).
        self.fechas(p, time.time() - 60)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale")
        self.assertIn("changed after the last store reload", r["reason"])

    async def test_margen_de_la_fecha(self) -> None:
        # Escrito un segundo antes de empezar la recarga: cuenta como
        # posterior (hay sistemas de ficheros con 2 s de resolución).
        p = self.app_con_fechas()
        _store._ULTIMA_RECARGA = time.time() - 100
        self.fechas(p, time.time() - 101)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale")

    async def test_mover_una_carpeta_del_camino_cuenta(self) -> None:
        # Mover una carpeta conserva la fecha de sus ficheros pero cambia la
        # de su carpeta padre: una app movida a su sitio después de recargar
        # (desde una carpeta oculta, que el Supervisor no lee) es posterior.
        self.app_con_fechas()
        _store._ULTIMA_RECARGA = time.time() - 300
        self.fechas(self.addons, time.time() - 60)
        r = await self.t["sv_install_addon"](_LOCAL)
        self.assertEqual(r["error"], "store_copy_stale")

    async def test_cambia_el_camino_entre_vista_previa_y_confirmacion(self) -> None:
        for tool in ("sv_install_addon", "sv_rebuild_addon"):
            with self.subTest(tool=tool):
                self.sv.llamadas.clear() if hasattr(self.sv, "llamadas") else None
                p = self.app_con_fechas()
                if tool == "sv_rebuild_addon":
                    self.reconstruible()
                _store._ULTIMA_RECARGA = time.time() - 300
                prev = await self.t[tool](_LOCAL)
                self.assertIn("confirmation_token", prev, prev)
                # Los privilegios no cambian (el token casa); cambia la
                # fecha de la carpeta de la app.
                self.fechas(p.parent, time.time() - 10)
                r = await self.t[tool](_LOCAL, confirmation_token=prev["confirmation_token"])
                self.assertEqual(r.get("error"), "store_copy_stale", r)
                self.assertNotIn(("POST", f"/store/addons/{_LOCAL}/install"), self.sv.rutas())
                self.assertNotIn(("POST", f"/addons/{_LOCAL}/rebuild"), self.sv.rutas())
                # El token se completó con error: no vuelve a valer.
                otra = await self.t[tool](_LOCAL, confirmation_token=prev["confirmation_token"])
                self.assertNotEqual(otra.get("error"), "store_copy_stale")
                self.assertIn("error", otra)

    async def test_al_dia_instala_y_reconstruye(self) -> None:
        self.app_con_fechas()
        _store._ULTIMA_RECARGA = time.time() - 300
        prev = await self.t["sv_install_addon"](_LOCAL)
        r = await self.t["sv_install_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r.get("job_id"), "j1", r)
        self.reconstruible()
        prev = await self.t["sv_rebuild_addon"](_LOCAL)
        r = await self.t["sv_rebuild_addon"](_LOCAL, confirmation_token=prev["confirmation_token"])
        self.assertEqual(r, {"result": "ok", "slug": _LOCAL, "force": False})

    async def test_no_se_supone_nada(self) -> None:
        _store._ULTIMA_RECARGA = time.time() + 60
        casos = {
            "sin /addons": lambda: unittest.mock.patch.object(
                folders, "ADDONS_BASE", self.addons / "sin_montar"),
            "no está en el índice": None,
            "dos config para el mismo slug": "dos",
            "un config ilegible": "ilegible",
        }
        for nombre, preparar in casos.items():
            with self.subTest(caso=nombre):
                for hijo in list(self.addons.iterdir()):
                    import shutil

                    shutil.rmtree(hijo)
                if nombre != "no está en el índice":
                    self.app_local()
                if preparar == "dos":
                    self.app_local(carpeta="copia")
                elif preparar == "ilegible":
                    # Uno que Hermes no lee (más de 1 MiB) y el Supervisor
                    # quizá sí. Uno que el Supervisor descartaría (UTF-8
                    # roto, sin slug) ya no bloquea: convergencia 2, T055.
                    (self.addons / "grande").mkdir()
                    (self.addons / "grande" / "config.yaml").write_bytes(
                        b"slug: grande\n" + b"#" * (folders.TAM_MAX_CONFIG + 1))
                if callable(preparar):
                    with preparar():
                        r = await self.t["sv_install_addon"](_LOCAL)
                else:
                    r = await self.t["sv_install_addon"](_LOCAL)
                self.assertEqual(r.get("error"), "store_copy_stale", r)
                self.assertNotIn("confirmation_token", r)

    async def test_otra_app_no_depende_de_la_recarga(self) -> None:
        _store._ULTIMA_RECARGA = None
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}", ficha_extendida(_TERCEROS))
        self.sv.respuesta("GET", f"/store/addons/{_TERCEROS}/availability", {})
        r = await self.t["sv_install_addon"](_TERCEROS)
        self.assertIn("confirmation_token", r)

    async def test_confirmar_espera_al_candado_de_addons(self) -> None:
        # Mientras otra operación de Hermes tiene el candado de /addons, la
        # confirmación de instalar una app local no comprueba ni envía nada.
        import asyncio

        self.app_con_fechas()
        _store._ULTIMA_RECARGA = time.time() - 300
        prev = await self.t["sv_install_addon"](_LOCAL)
        candado = folders.candado("addons")
        await candado.acquire()
        tarea = asyncio.ensure_future(self.t["sv_install_addon"](
            _LOCAL, confirmation_token=prev["confirmation_token"]))
        await asyncio.sleep(0.05)
        self.assertFalse(tarea.done())
        self.assertNotIn(("POST", f"/store/addons/{_LOCAL}/install"), self.sv.rutas())
        candado.release()
        r = await tarea
        self.assertEqual(r.get("job_id"), "j1", r)


class TestRecargasAnotadas(_ConRaices):
    """Las vías de Hermes que recargan la tienda anotan la hora de INICIO
    (antes de la petición) solo si el Supervisor respondió bien.
    Control negativo comprobado: sin `anotar_recarga_de_tienda` en
    `sv_reload_store` cae `test_reload_store`. Con /addons de verdad (una
    carpeta temporal): desde la convergencia 3 de la 034 (T057), sin poder
    marcar /addons no se anota nada."""

    def setUp(self) -> None:
        super().setUp()
        _store._ULTIMA_RECARGA = None

    async def test_reload_store(self) -> None:
        from hermes.tools import store_repositories

        sv = SupervisorSimulado()
        mcp = _MCP()
        store_repositories.register(mcp, sv)
        sv.respuesta("POST", "/store/reload", {})
        antes = time.time()
        r = await mcp.tools["sv_reload_store"]()
        self.assertEqual(r["result"], "ok")
        anotada = _store.ultima_recarga_de_tienda()
        self.assertIsNotNone(anotada)
        self.assertTrue(antes <= anotada <= time.time())
        _store._ULTIMA_RECARGA = None
        sv.respuesta("POST", "/store/reload", HAConnectionError("failed 500: boom", status=500))
        r = await mcp.tools["sv_reload_store"]()
        self.assertIn("error", r)
        self.assertIsNone(_store.ultima_recarga_de_tienda())

    async def test_check_for_updates(self) -> None:
        from hermes.tools import system_updates

        llamadas: list[tuple[str, str]] = []

        class Cliente:
            async def sv_request(self, metodo: str, ruta: str, **_: Any) -> Any:
                llamadas.append((metodo, ruta))
                if ruta == "/jobs/info":
                    return {"ignore_conditions": [], "jobs": []}
                return {}

        mcp = _MCP()
        system_updates.register(mcp, Cliente())
        antes = time.time()
        await mcp.tools["sv_check_for_updates"]()
        self.assertIn(("POST", "/refresh_updates"), llamadas)
        anotada = _store.ultima_recarga_de_tienda()
        self.assertIsNotNone(anotada)
        self.assertTrue(antes <= anotada <= time.time())

    def test_la_mas_reciente_gana(self) -> None:
        _store.anotar_recarga_de_tienda(100.0)
        _store.anotar_recarga_de_tienda(50.0)
        self.assertEqual(_store.ultima_recarga_de_tienda(), 100.0)


if __name__ == "__main__":
    unittest.main()
