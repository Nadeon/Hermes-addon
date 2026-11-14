"""Montajes del Supervisor (spec 019, tramo 1; CAP-083, FR-066 de la 008).

`sv_list_mounts`, `sv_create_mount`, `sv_update_mount`, `sv_delete_mount`,
`sv_reload_mount` y `sv_set_default_backup_mount` contra el Supervisor
simulado de `tests/fixtures/supervisor_montajes.py` (forma y comportamiento
del Supervisor 2026.11.0, datos ficticios y centinelas de credenciales).

Lo que se vigila, además de cada petición exacta:

- las credenciales CIFS entran y nunca salen: ni en respuestas, vistas
  previas, errores, eventos de log ni en el directorio de tokens (FR-008,
  FR-019);
- el token ata todos los argumentos (también la contraseña) y la huella del
  estado que describe la vista previa (FR-009);
- todo argumento inválido se rechaza sin ninguna llamada y sin copiar el
  valor (FR-007, SC-003);
- el log no lleva servidor, recurso, ruta ni dispositivo (FR-020).

Controles negativos del tramo 1 (T016), con recuentos, en el mensaje del
commit que añade este fichero.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from structlog.testing import capture_logs

from hermes import security
from hermes.ha import HAConnectionError
from hermes.tools.mounts import register
from tests.fixtures.supervisor_montajes import (
    CLAVE,
    RECURSO_CIFS,
    RUTA_NFS,
    SERVIDOR_CIFS,
    SERVIDOR_NFS,
    UUID_DISCO,
    USUARIO,
    SupervisorDeMontajes,
    backup,
    error_al_montar,
)

_PERMITIDAS = {"name", "type", "usage", "read_only", "server", "port", "share",
               "path", "version", "uuid", "filesystem", "state", "user_path"}


class DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _texto(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def _ficheros_de_tokens() -> str:
    """Todo el contenido del directorio de tokens, junto."""
    d = security.CONFIRMATIONS_DIR
    if not d.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(d.iterdir()) if p.is_file())


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sv = SupervisorDeMontajes()
        self.mcp = DummyMCP()
        register(self.mcp, self.sv)
        self.t = self.mcp.tools

    def _cifs(self, **cambios: Any) -> dict[str, Any]:
        base = {"name": "nas2", "type": "cifs", "usage": "backup",
                "server": "nas2.local", "share": "recurso2"}
        base.update(cambios)
        return base

    async def _confirmar(self, tool: str, **kw: Any) -> tuple[dict, dict]:
        vista = await self.t[tool](**kw)
        self.assertIn("confirmation_token", vista, vista)
        hecho = await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
        return vista, hecho

    def _sin_centinelas(self, *valores: Any) -> None:
        for v in valores:
            texto = _texto(v)
            self.assertNotIn(USUARIO, texto)
            self.assertNotIn(CLAVE, texto)


# ── T004: listar (FR-001, FR-010) ─────────────────────────────────────────────


class TestListar(_Base):
    async def test_sobre_y_claves_permitidas(self) -> None:
        r = await self.t["sv_list_mounts"]()
        self.assertEqual(list(r), ["default_backup_mount", "count", "items", "truncated"])
        self.assertEqual(r["default_backup_mount"], "nas_backups")
        self.assertEqual((r["count"], r["truncated"]), (3, False))
        por_nombre = {m["name"]: m for m in r["items"]}
        for m in r["items"]:
            self.assertLessEqual(set(m), _PERMITIDAS)
        self.assertEqual(set(por_nombre["nas_backups"]), {
            "name", "type", "usage", "read_only", "server", "share", "version",
            "state", "user_path"})
        self.assertEqual(por_nombre["nas_media"]["path"], RUTA_NFS)
        self.assertEqual(por_nombre["usb_share"]["uuid"], UUID_DISCO)
        self.assertEqual(por_nombre["usb_share"]["filesystem"], "exfat")
        self.assertEqual(por_nombre["nas_backups"]["user_path"], "/backup/nas_backups")
        self.assertEqual([(c["metodo"], c["ruta"]) for c in self.sv.llamadas],
                         [("GET", "/mounts")])

    async def test_un_supervisor_que_filtrara_credenciales(self) -> None:
        self.sv.filtra = True
        with capture_logs() as eventos:
            r = await self.t["sv_list_mounts"]()
        cifs = next(m for m in r["items"] if m["name"] == "nas_backups")
        self.assertNotIn("username", cifs)
        self.assertNotIn("password", cifs)
        self._sin_centinelas(r, eventos)

    async def test_claves_desconocidas_se_descartan(self) -> None:
        crudo = await self.sv.sv_request("GET", "/mounts")
        crudo["mounts"][0]["clave_nueva"] = "valor-ficticio"
        crudo["mounts"][2]["device"] = "/dev/sdz9"
        self.sv.formas[("GET", "/mounts")] = crudo
        r = await self.t["sv_list_mounts"]()
        self.assertNotIn("valor-ficticio", _texto(r))
        self.assertNotIn("/dev/sdz9", _texto(r))

    async def test_uuid_y_filesystem_solo_en_disk(self) -> None:
        crudo = await self.sv.sv_request("GET", "/mounts")
        crudo["mounts"][0]["uuid"] = "no-deberia"
        self.sv.formas[("GET", "/mounts")] = crudo
        r = await self.t["sv_list_mounts"]()
        self.assertNotIn("uuid", r["items"][0])

    async def test_formas_inesperadas_dan_error(self) -> None:
        for forma in ([], {"default_backup_mount": None},
                      {"default_backup_mount": None, "mounts": "x"}, "texto",
                      {"default_backup_mount": None, "mounts": ["x"]}):
            with self.subTest(forma=forma):
                self.sv.formas[("GET", "/mounts")] = forma
                r = await self.t["sv_list_mounts"]()
                self.assertIn("error", r)
                self.assertNotIn("items", r)

    async def test_supervisor_caido(self) -> None:
        self.sv.errores[("GET", "/mounts")] = HAConnectionError("conexión rechazada")
        r = await self.t["sv_list_mounts"]()
        self.assertIn("conexión rechazada", r["error"])


# ── T005: crear y validar (FR-002, FR-007, FR-010) ────────────────────────────


# (kwargs que se cambian sobre un CIFS válido, código de error esperado,
#  valor que no puede aparecer en el mensaje o None)
_INVALIDOS: list[tuple[dict[str, Any], str, str | None]] = [
    ({"name": "mal-nombre"}, "invalid_argument", "mal-nombre"),
    ({"name": ""}, "invalid_argument", None),
    ({"name": "n" * 65}, "invalid_argument", "n" * 65),
    ({"type": "bind"}, "unsupported_mount_type", None),
    ({"usage": "otro_uso"}, "invalid_argument", "otro_uso"),
    ({"server": "nas/x"}, "invalid_argument", "nas/x"),
    ({"server": "nas x"}, "invalid_argument", "nas x"),
    ({"server": "nas\nx"}, "invalid_argument", "nas\nx"),
    ({"server": "a" * 254}, "invalid_argument", "a" * 254),
    ({"server": None}, "invalid_argument", None),
    ({"share": "a/b"}, "invalid_argument", "a/b"),
    ({"share": "rec\x01"}, "invalid_argument", "rec\x01"),
    ({"share": None}, "invalid_argument", None),
    ({"port": 0}, "invalid_argument", None),
    ({"port": 70000}, "invalid_argument", "70000"),
    ({"port": True}, "invalid_argument", None),
    ({"version": "3.0"}, "invalid_argument", "3.0"),
    ({"read_only": True}, "invalid_argument", None),
    ({"read_only": "si"}, "invalid_argument", None),
    ({"username": USUARIO}, "invalid_argument", USUARIO),
    ({"password": CLAVE}, "invalid_argument", CLAVE),
    ({"username": "usu\nrio", "password": CLAVE}, "invalid_argument", "usu\nrio"),
    ({"username": USUARIO, "password": "cla\x00ve"}, "invalid_argument", "cla\x00ve"),
    ({"username": USUARIO, "password": "***REDACTED***"}, "invalid_argument", None),
    ({"username": "***REDACTED***", "password": CLAVE}, "invalid_argument", None),
    ({"path": "/export/x"}, "invalid_argument", "/export/x"),
    ({"device": "/dev/sdb1"}, "invalid_argument", "/dev/sdb1"),
    ({"uuid": "ABCD-1234"}, "invalid_argument", "ABCD-1234"),
    # NFS
    ({"type": "nfs", "share": None, "path": "export/relativa"}, "invalid_argument",
     "export/relativa"),
    ({"type": "nfs", "share": None, "path": None}, "invalid_argument", None),
    ({"type": "nfs", "path": "/export/x"}, "invalid_argument", None),  # share en NFS
    ({"type": "nfs", "share": None, "path": "/e", "version": "2.0"},
     "invalid_argument", None),
    ({"type": "nfs", "share": None, "path": "/e", "username": USUARIO,
      "password": CLAVE}, "invalid_argument", CLAVE),
    ({"type": "nfs", "share": None, "path": "/e", "uuid": "AB-12"},
     "invalid_argument", None),
    # disk (decisión del supervisor del programa)
    ({"type": "disk", "server": None, "share": None}, "invalid_argument", None),
    ({"type": "disk", "share": None, "device": "/dev/sdb1"}, "invalid_argument", None),
    ({"type": "disk", "server": None, "share": None, "device": "/dev/sdb1",
      "username": USUARIO, "password": CLAVE}, "invalid_argument", CLAVE),
    ({"type": "disk", "server": None, "share": None, "device": "/tmp/disco"},
     "invalid_argument", "/tmp/disco"),
    ({"type": "disk", "server": None, "share": None, "device": "/dev/../etc/x"},
     "invalid_argument", "/dev/../etc/x"),
    ({"type": "disk", "server": None, "share": None, "device": "/dev/sd b"},
     "invalid_argument", "/dev/sd b"),
    ({"type": "disk", "server": None, "share": None, "uuid": "uuid con espacios"},
     "invalid_argument", "uuid con espacios"),
    ({"type": "disk", "server": None, "share": None, "uuid": "AB-12", "port": 445},
     "invalid_argument", None),
]


class TestValidacion(_Base):
    async def test_cada_regla_sin_llamadas_ni_valor(self) -> None:
        for cambios, codigo, valor in _INVALIDOS:
            with self.subTest(cambios=cambios):
                self.sv.llamadas.clear()
                kw = {k: v for k, v in self._cifs(**cambios).items() if v is not None}
                r = await self.t["sv_create_mount"](**kw)
                self.assertEqual(r.get("error"), codigo, r)
                self.assertNotIn("confirmation_token", r)
                self.assertEqual(self.sv.llamadas, [])
                self.assertTrue(r.get("detail"), r)
                if valor is not None:
                    self.assertNotIn(valor, _texto(r))
                self._sin_centinelas(r)


class TestCrear(_Base):
    async def test_vista_previa_cifs_con_credenciales(self) -> None:
        r = await self.t["sv_create_mount"](**self._cifs(username=USUARIO, password=CLAVE))
        p = r["preview"]
        self.assertEqual(p["action"], "create_mount")
        self.assertEqual(p["mount"], {
            "name": "nas2", "type": "cifs", "usage": "backup", "read_only": False,
            "server": "nas2.local", "share": "recurso2", "version": None})
        self.assertEqual(p["credentials"], "set")
        self.assertIs(p["becomes_default_backup_mount"], False)
        self.assertIs(p["reloads_backups"], True)
        self.assertIn("nothing is created", p["note"])
        self.assertEqual(self.sv.escrituras, [])
        self._sin_centinelas(r)

    async def test_pasa_a_ser_el_por_defecto_si_no_hay(self) -> None:
        self.sv.por_defecto = None
        r = await self.t["sv_create_mount"](**self._cifs())
        self.assertIs(r["preview"]["becomes_default_backup_mount"], True)
        self.assertEqual(r["preview"]["credentials"], "none")
        r = await self.t["sv_create_mount"](**self._cifs(usage="media"))
        self.assertIs(r["preview"]["becomes_default_backup_mount"], False)
        self.assertIs(r["preview"]["reloads_backups"], False)

    async def test_nfs_sin_credentials(self) -> None:
        r = await self.t["sv_create_mount"](
            name="nfs2", type="nfs", usage="media", server=SERVIDOR_NFS,
            path="/export/fotos", read_only=True)
        self.assertNotIn("credentials", r["preview"])
        self.assertEqual(r["preview"]["mount"]["path"], "/export/fotos")

    async def test_nombre_que_ya_existe(self) -> None:
        r = await self.t["sv_create_mount"](**self._cifs(name="nas_backups"))
        self.assertEqual(r["error"], "mount_exists")
        self.assertIn("sv_update_mount", r["hint"])
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_confirmacion_carga_exacta_y_lectura_de_vuelta(self) -> None:
        _, r = await self._confirmar(
            "sv_create_mount", **self._cifs(username=USUARIO, password=CLAVE, port=4445,
                                            version="2.0"))
        self.assertEqual(self.sv.escrituras, [{
            "metodo": "POST", "ruta": "/mounts", "json": {
                "name": "nas2", "type": "cifs", "usage": "backup", "read_only": False,
                "server": "nas2.local", "share": "recurso2", "version": "2.0", "port": 4445,
                "username": USUARIO, "password": CLAVE}}])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["mount"]["name"], "nas2")
        self.assertEqual(r["mount"]["state"], "active")
        self.assertEqual(r["default_backup_mount"], "nas_backups")
        self._sin_centinelas(r)

    async def test_version_auto_es_null(self) -> None:
        await self._confirmar("sv_create_mount", **self._cifs(version="auto"))
        self.assertIsNone(self.sv.escrituras[0]["json"]["version"])
        self.assertNotIn("username", self.sv.escrituras[0]["json"])

    async def test_error_al_montar_redactado_con_pista(self) -> None:
        self.sv.errores[("POST", "/mounts")] = error_al_montar()
        vista, r = await self._confirmar(
            "sv_create_mount", **self._cifs(username=USUARIO, password=CLAVE))
        self.assertIn("error", r)
        self.assertIn("Permission denied", r["error"])
        self.assertIn("sv_get_resolution", r["hint"])
        self._sin_centinelas(r)
        datos = json.loads((security.CONFIRMATIONS_DIR
                            / f"{vista['confirmation_token']}.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["state"], "failed")
        self._sin_centinelas(datos)

    async def test_forma_inesperada_en_la_vista_previa(self) -> None:
        self.sv.formas[("GET", "/mounts")] = {"sin_mounts": True}
        r = await self.t["sv_create_mount"](**self._cifs())
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)

    async def test_disco_local(self) -> None:
        """Decisión del supervisor del programa: `disk` también se crea."""
        kw = {"name": "usb_backup", "type": "disk", "usage": "backup",
              "device": "/dev/sdb1"}
        vista, r = await self._confirmar("sv_create_mount", **kw)
        p = vista["preview"]
        self.assertEqual(p["mount"], {"name": "usb_backup", "type": "disk",
                                      "usage": "backup", "read_only": False,
                                      "device": "/dev/sdb1"})
        self.assertNotIn("credentials", p)
        self.assertIn("Home Assistant OS", p["note"])
        self.assertEqual(self.sv.escrituras, [{
            "metodo": "POST", "ruta": "/mounts", "json": {
                "name": "usb_backup", "type": "disk", "usage": "backup",
                "read_only": False, "device": "/dev/sdb1"}}])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["mount"]["type"], "disk")
        self.assertIn("uuid", r["mount"])

    async def test_disco_por_uuid(self) -> None:
        await self._confirmar("sv_create_mount", name="usb2", type="disk",
                              usage="media", uuid="ABCD-0001", read_only=True)
        self.assertEqual(self.sv.escrituras[0]["json"], {
            "name": "usb2", "type": "disk", "usage": "media", "read_only": True,
            "uuid": "ABCD-0001"})


# ── T006: editar (FR-003, FR-007) ─────────────────────────────────────────────


class TestEditar(_Base):
    async def test_funde_con_lo_actual(self) -> None:
        vista, r = await self._confirmar("sv_update_mount", name="nas_media",
                                         server="192.0.2.20")
        p = vista["preview"]
        self.assertEqual(p["changes"], {"server": {"from": SERVIDOR_NFS, "to": "192.0.2.20"}})
        self.assertIs(p["remount"], True)
        self.assertNotIn("credentials", p)
        self.assertEqual(self.sv.escrituras, [{
            "metodo": "PUT", "ruta": "/mounts/nas_media", "json": {
                "name": "nas_media", "type": "nfs", "usage": "media", "read_only": True,
                "server": "192.0.2.20", "path": RUTA_NFS}}])
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["mount"]["server"], "192.0.2.20")

    async def test_cifs_sin_credenciales_avisa_y_las_quita(self) -> None:
        vista, _ = await self._confirmar("sv_update_mount", name="nas_backups",
                                         version="2.0")
        p = vista["preview"]
        self.assertEqual(p["credentials"], "removed_if_present")
        self.assertIn("removed", p["credentials_warning"])
        self.assertEqual(p["changes"], {"version": {"from": None, "to": "2.0"}})
        cuerpo = self.sv.escrituras[0]["json"]
        self.assertNotIn("username", cuerpo)
        self.assertNotIn("password", cuerpo)
        self.assertEqual((cuerpo["server"], cuerpo["share"], cuerpo["version"]),
                         (SERVIDOR_CIFS, RECURSO_CIFS, "2.0"))

    async def test_cifs_con_credenciales_las_reemplaza(self) -> None:
        vista, r = await self._confirmar("sv_update_mount", name="nas_backups",
                                         username=USUARIO, password=CLAVE)
        self.assertEqual(vista["preview"]["credentials"], "replaced")
        self.assertNotIn("credentials_warning", vista["preview"])
        self._sin_centinelas(vista, r)
        cuerpo = self.sv.escrituras[0]["json"]
        self.assertEqual((cuerpo["username"], cuerpo["password"]), (USUARIO, CLAVE))

    async def test_cambio_de_tipo(self) -> None:
        r = await self.t["sv_update_mount"](name="nas_media", type="cifs")
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.escrituras, [])
        # Sin `server` tampoco: cambiar de tipo parte de cero.
        r = await self.t["sv_update_mount"](name="nas_media", type="cifs", share="media")
        self.assertEqual(r["error"], "invalid_argument")
        _, r = await self._confirmar("sv_update_mount", name="nas_media", type="cifs",
                                     server=SERVIDOR_CIFS, share="media")
        self.assertEqual(self.sv.escrituras[-1]["json"], {
            "name": "nas_media", "type": "cifs", "usage": "media", "read_only": True,
            "server": SERVIDOR_CIFS, "share": "media", "version": None})

    async def test_version_auto_vuelve_a_null(self) -> None:
        self.sv.montaje("nas_backups")["version"] = "1.0"
        vista, _ = await self._confirmar("sv_update_mount", name="nas_backups",
                                         version="auto")
        self.assertEqual(vista["preview"]["changes"],
                         {"version": {"from": "1.0", "to": None}})
        self.assertIsNone(self.sv.escrituras[0]["json"]["version"])

    async def test_solo_lectura_en_backup_se_valida_fundido(self) -> None:
        r = await self.t["sv_update_mount"](name="nas_backups", read_only=True)
        self.assertEqual(r["error"], "invalid_argument")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_deja_de_ser_el_por_defecto_y_backups_afectados(self) -> None:
        r = await self.t["sv_update_mount"](name="nas_backups", usage="media")
        p = r["preview"]
        self.assertIs(p["stops_being_default_backup_mount"], True)
        af = p["affected_backups"]
        self.assertEqual((af["count"], af["only_here"], len(af["items"]), af["truncated"]),
                         (27, 25, 20, True))
        self.assertEqual(af["items"][0]["slug"], "ambos002")
        self.assertEqual(set(af["items"][0]), {"slug", "name", "date"})

    async def test_destino_cambiado_y_no_cambiado(self) -> None:
        r = await self.t["sv_update_mount"](name="nas_backups", server="nas3.local")
        self.assertIn("affected_backups", r["preview"])
        self.assertIs(r["preview"]["stops_being_default_backup_mount"], False)
        r = await self.t["sv_update_mount"](name="nas_backups", version="2.0")
        self.assertNotIn("affected_backups", r["preview"])

    async def test_inexistente(self) -> None:
        r = await self.t["sv_update_mount"](name="no_existe", server="x.local")
        self.assertEqual(r["error"], "mount_not_found")
        self.assertNotIn("confirmation_token", r)
        self.assertEqual(self.sv.escrituras, [])

    async def test_disco_editable(self) -> None:
        _, r = await self._confirmar("sv_update_mount", name="usb_share", usage="media")
        self.assertEqual(self.sv.escrituras[0]["json"], {
            "name": "usb_share", "type": "disk", "usage": "media", "read_only": False,
            "uuid": UUID_DISCO})
        self.assertEqual(r["result"], "ok")

    async def test_disco_con_otro_device_no_arrastra_el_uuid(self) -> None:
        vista, _ = await self._confirmar("sv_update_mount", name="usb_share",
                                         device="/dev/sdc1")
        self.assertEqual(self.sv.escrituras[0]["json"], {
            "name": "usb_share", "type": "disk", "usage": "share", "read_only": False,
            "device": "/dev/sdc1"})
        self.assertIn("device", vista["preview"]["changes"])

    async def test_argumentos_de_otro_tipo(self) -> None:
        for kw in ({"name": "nas_media", "share": "x"},
                   {"name": "nas_backups", "path": "/x"},
                   {"name": "usb_share", "server": "x.local"},
                   {"name": "nas_media", "username": USUARIO, "password": CLAVE}):
            with self.subTest(kw=kw):
                self.sv.llamadas.clear()
                r = await self.t["sv_update_mount"](**kw)
                self.assertEqual(r["error"], "invalid_argument", r)
                self.assertEqual(self.sv.escrituras, [])
                self._sin_centinelas(r)


# ── T007: borrar (FR-004) ─────────────────────────────────────────────────────


class TestBorrar(_Base):
    async def test_vista_previa_de_backup_por_defecto(self) -> None:
        vista, r = await self._confirmar("sv_delete_mount", name="nas_backups")
        p = vista["preview"]
        self.assertEqual(p["action"], "delete_mount")
        self.assertEqual(p["mount"]["name"], "nas_backups")
        self.assertNotIn("username", p["mount"])
        self.assertIs(p["is_default_backup_mount"], True)
        self.assertIsNone(p["default_after"])
        af = p["affected_backups"]
        self.assertEqual((af["count"], af["only_here"], len(af["items"]), af["truncated"]),
                         (27, 25, 20, True))
        fechas = [b["date"] for b in af["items"]]
        self.assertEqual(fechas, sorted(fechas, reverse=True))
        for frase in ("25 backups", "local storage", "safety backups", "stay on the server"):
            self.assertIn(frase, p["warning"])
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "DELETE", "ruta": "/mounts/nas_backups", "json": None}])
        self.assertEqual(r, {"result": "ok", "deleted": "nas_backups",
                             "default_backup_mount": None})

    async def test_media_avisa_de_su_ruta(self) -> None:
        r = await self.t["sv_delete_mount"](name="nas_media")
        p = r["preview"]
        self.assertIn("/media/nas_media", p["warning"])
        self.assertNotIn("affected_backups", p)
        self.assertIs(p["is_default_backup_mount"], False)
        self.assertEqual(p["default_after"], "nas_backups")

    async def test_disco_se_puede_borrar(self) -> None:
        _, r = await self._confirmar("sv_delete_mount", name="usb_share")
        self.assertEqual(r["result"], "ok")
        self.assertIsNone(self.sv.montaje("usb_share"))

    async def test_inexistente(self) -> None:
        r = await self.t["sv_delete_mount"](name="no_existe")
        self.assertEqual(r["error"], "mount_not_found")
        self.assertNotIn("confirmation_token", r)

    async def test_backups_ilegibles_sin_token(self) -> None:
        self.sv.formas[("GET", "/backups")] = {"otra": []}
        r = await self.t["sv_delete_mount"](name="nas_backups")
        self.assertIn("error", r)
        self.assertNotIn("confirmation_token", r)


# ── T008: recargar y montaje por defecto (FR-005, FR-006) ─────────────────────


class TestRecargar(_Base):
    async def test_recarga_sin_token(self) -> None:
        self.sv.estados["nas_media"] = "failed"
        r = await self.t["sv_reload_mount"](name="nas_media")
        self.assertEqual(r["result"], "ok")
        self.assertEqual(r["mount"]["state"], "active")
        self.assertEqual(self.sv.escrituras, [
            {"metodo": "POST", "ruta": "/mounts/nas_media/reload", "json": None}])

    async def test_error_redactado_con_pista(self) -> None:
        self.sv.errores[("POST", "/mounts/nas_backups/reload")] = error_al_montar()
        r = await self.t["sv_reload_mount"](name="nas_backups")
        self.assertIn("sv_get_resolution", r["hint"])
        # Al recargar, Hermes no conoce las credenciales (no las recibe):
        # solo puede tapar lo que `redact_secrets` reconoce, como el valor
        # tras «password».
        self.assertNotIn(CLAVE, r["error"])
        self.assertIn("Permission denied", r["error"])

    async def test_nombre_invalido_o_inexistente(self) -> None:
        r = await self.t["sv_reload_mount"](name="../x")
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.llamadas, [])
        r = await self.t["sv_reload_mount"](name="no_existe")
        self.assertEqual(r["error"], "mount_not_found")
        self.assertEqual(self.sv.escrituras, [])


class TestPorDefecto(_Base):
    async def test_volver_al_disco_local(self) -> None:
        vista, r = await self._confirmar("sv_set_default_backup_mount", name=None)
        p = vista["preview"]
        self.assertEqual((p["from"], p["to"]), ("nas_backups", None))
        self.assertIn("local storage", p["note"])
        self.assertEqual(self.sv.escrituras, [{
            "metodo": "POST", "ruta": "/mounts/options",
            "json": {"default_backup_mount": None}}])
        self.assertEqual(r, {"result": "ok", "default_backup_mount": None})

    async def test_otro_montaje_de_backup(self) -> None:
        self.sv.montajes.append({"name": "nas_otro", "type": "nfs", "usage": "backup",
                                 "read_only": False, "server": "192.0.2.11",
                                 "path": "/export/b"})
        vista, r = await self._confirmar("sv_set_default_backup_mount", name="nas_otro")
        self.assertEqual(vista["preview"]["to"], "nas_otro")
        self.assertEqual(r["default_backup_mount"], "nas_otro")

    async def test_rechazos_sin_token(self) -> None:
        r = await self.t["sv_set_default_backup_mount"](name="nas_media")
        self.assertEqual(r["error"], "not_a_backup_mount")
        self.assertNotIn("confirmation_token", r)
        r = await self.t["sv_set_default_backup_mount"](name="no_existe")
        self.assertEqual(r["error"], "mount_not_found")
        r = await self.t["sv_set_default_backup_mount"](name="mal nombre")
        self.assertEqual(r["error"], "invalid_argument")
        self.assertEqual(self.sv.escrituras, [])


# ── T009: token atado y secretos (FR-008, FR-009, FR-019, FR-020) ────────────


class TestTokenAtado(_Base):
    async def test_otra_contrasena_otro_usuario_otro_servidor(self) -> None:
        kw = self._cifs(username=USUARIO, password=CLAVE)
        vista = await self.t["sv_create_mount"](**kw)
        token = vista["confirmation_token"]
        for cambio in ({"password": "OTRA-CLAVE-019"}, {"username": "otro_usuario"},
                       {"server": "nas9.local"}):
            with self.subTest(cambio=cambio):
                r = await self.t["sv_create_mount"](**{**kw, **cambio},
                                                    confirmation_token=token)
                self.assertIn("does not match", r["error"])
                self.assertEqual(self.sv.escrituras, [])

    async def _cambia_y_confirma(self, tool: str, kw: dict, cambiar) -> dict:
        vista = await self.t[tool](**kw)
        cambiar()
        r = await self.t[tool](**kw, confirmation_token=vista["confirmation_token"])
        self.assertEqual(r.get("error"), "mount_changed", r)
        self.assertIn("new preview", r["detail"])
        self.assertEqual(self.sv.escrituras, [])
        return r

    async def test_estado_cambiado_al_editar(self) -> None:
        def cambiar():
            self.sv.montaje("nas_media")["server"] = "192.0.2.99"
        await self._cambia_y_confirma("sv_update_mount",
                                      {"name": "nas_media", "read_only": False}, cambiar)

    async def test_estado_cambiado_al_crear(self) -> None:
        def cambiar():
            self.sv.por_defecto = None
        await self._cambia_y_confirma("sv_create_mount", self._cifs(), cambiar)

    async def test_estado_cambiado_al_borrar(self) -> None:
        def cambiar():
            self.sv.backups.append(backup("nuevo001", "2026-11-10T03:00:00+00:00",
                                          ["nas_backups"]))
        await self._cambia_y_confirma("sv_delete_mount", {"name": "nas_backups"}, cambiar)

    async def test_estado_cambiado_en_el_por_defecto(self) -> None:
        def cambiar():
            self.sv.por_defecto = None
        await self._cambia_y_confirma("sv_set_default_backup_mount",
                                      {"name": "nas_backups"}, cambiar)

    async def test_mismo_estado_ejecuta(self) -> None:
        """Control: que el estado se lea dos veces no basta para fallar."""
        self.sv.estados["nas_media"] = "failed"
        vista = await self.t["sv_update_mount"](name="nas_media", read_only=False)
        # El estado de la unidad cambia solo y no cuenta (data-model).
        self.sv.estados["nas_media"] = "active"
        r = await self.t["sv_update_mount"](name="nas_media", read_only=False,
                                            confirmation_token=vista["confirmation_token"])
        self.assertEqual(r["result"], "ok")


class TestSecretos(_Base):
    async def test_crear_y_editar_sin_centinelas_en_ningun_sitio(self) -> None:
        with capture_logs() as eventos:
            vista, hecho = await self._confirmar(
                "sv_create_mount", **self._cifs(username=USUARIO, password=CLAVE))
            tokens_tras_crear = _ficheros_de_tokens()
            self.sv.errores[("PUT", "/mounts/nas_backups")] = error_al_montar()
            vista2, error = await self._confirmar(
                "sv_update_mount", name="nas_backups", username=USUARIO, password=CLAVE)
        self.assertIn("error", error)
        self._sin_centinelas(vista, hecho, vista2, error, eventos)
        for texto in (tokens_tras_crear, _ficheros_de_tokens()):
            self.assertNotIn(USUARIO, texto)
            self.assertNotIn(CLAVE, texto)
        # Y la carga sí las llevaba: si no, el test no probaría nada.
        self.assertEqual(self.sv.escrituras[0]["json"]["password"], CLAVE)

    async def test_eventos_de_log(self) -> None:
        with capture_logs() as eventos:
            await self._confirmar("sv_create_mount",
                                  **self._cifs(username=USUARIO, password=CLAVE))
            await self._confirmar("sv_update_mount", name="nas_media", server="192.0.2.20")
            await self._confirmar("sv_create_mount", name="usb9", type="disk",
                                  usage="media", device="/dev/sdq1")
        texto = _texto(eventos)
        for prohibido in ("nas2.local", "recurso2", SERVIDOR_NFS, "192.0.2.20", RUTA_NFS,
                          "/dev/sdq1"):
            self.assertNotIn(prohibido, texto)
        por_evento: dict[str, dict] = {}
        for e in eventos:
            por_evento.setdefault(e["event"], e)
        crear = por_evento["sv_create_mount_ok"]
        self.assertEqual((crear["mount"], crear["type"], crear["usage"], crear["credentials"]),
                         ("nas2", "cifs", "backup", "set"))
        self.assertIn("sv_create_mount_preview", por_evento)
        editar = por_evento["sv_update_mount_ok"]
        self.assertEqual(editar["changed"], ["server"])
        self.assertEqual(editar["mount"], "nas_media")


if __name__ == "__main__":
    unittest.main()
