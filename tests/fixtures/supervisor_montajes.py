"""Supervisor simulado para los montajes de la spec 019 (CAP-083).

Reproduce la FORMA de las respuestas y el comportamiento del Supervisor
2026.11.0 leídos en su código (`supervisor/api/mounts.py`,
`mounts/validate.py`, `mounts/mount.py`, `api/backups.py`), con datos
ficticios: `nas.local`, IPs de documentación (RFC 5737), UUIDs inventados y
centinelas de texto. Nada sale de una instalación real (principio VIII).

Lo que importa del Supervisor real y se replica aquí:

- `GET /mounts` → `{default_backup_mount, mounts: [to_dict() + state +
  user_path]}`; `to_dict()` NUNCA lleva `username` ni `password` (salvo en la
  variante `filtra=True`, que simula un Supervisor que los dejara escapar).
- `POST /mounts` rechaza un nombre repetido; si el montaje es de uso
  `backup` y no hay montaje por defecto, pasa a serlo.
- `PUT /mounts/{n}` REEMPLAZA la configuración entera (lo que no viene,
  credenciales incluidas, se pierde); si deja de ser de `backup` y era el
  por defecto, el por defecto pasa a `None`.
- `DELETE /mounts/{n}` lo quita y, si era el por defecto, lo deja en `None`.
- `POST /mounts/options` rechaza un montaje que no es de uso `backup`.
- En un `disk`, `device` es solo de entrada: el Supervisor lo resuelve a
  `uuid` y `filesystem` y no lo guarda.
- `GET /backups` → `{backups: [...]}` con `location` y `locations` (lista de
  nombres; `None` es el disco local).

`sv_request` ya devuelve el campo `data` de la respuesta, como el cliente
real; un error del Supervisor llega como `HAConnectionError`.
"""

from __future__ import annotations

import copy
from typing import Any

from hermes.ha import HAConnectionError

# Centinelas de credenciales: si aparecen en una respuesta, un error, el log o
# el directorio de tokens, el tratamiento de secretos ha fallado.
USUARIO = "USUARIO-CENTINELA-019"
CLAVE = "CLAVE-CENTINELA-019"

# Lo que Hermes nunca debe escribir en su log (FR-020): servidor, recurso y
# ruta de los montajes de ejemplo.
SERVIDOR_CIFS = "nas.local"
SERVIDOR_NFS = "192.0.2.10"
RECURSO_CIFS = "backups"
RUTA_NFS = "/export/media"
UUID_DISCO = "1234-ABCD"

_RAIZ_POR_USO = {"backup": "/backup", "media": "/media", "share": "/share"}

# Claves de `to_dict()` por tipo (sin `skip_secrets=False` no hay credenciales).
_CLAVES_COMUNES = ("name", "type", "read_only", "usage")
_CLAVES_POR_TIPO = {
    "cifs": ("server", "port", "share", "version"),
    "nfs": ("server", "port", "path"),
    "disk": ("uuid", "filesystem"),
}


def montajes_base() -> list[dict[str, Any]]:
    """Configuración guardada en el Supervisor (con las credenciales CIFS,
    como en su `mounts.json`): un CIFS de backup con `version: null`, un NFS
    de medios y un disco de `share`."""
    return [
        {"name": "nas_backups", "type": "cifs", "usage": "backup",
         "read_only": False, "server": SERVIDOR_CIFS, "share": RECURSO_CIFS,
         "version": None, "username": USUARIO, "password": CLAVE},
        {"name": "nas_media", "type": "nfs", "usage": "media",
         "read_only": True, "server": SERVIDOR_NFS, "path": RUTA_NFS},
        {"name": "usb_share", "type": "disk", "usage": "share",
         "read_only": False, "uuid": UUID_DISCO, "filesystem": "exfat"},
    ]


def backup(slug: str, fecha: str, locations: list[str | None],
           nombre: str | None = None) -> dict[str, Any]:
    """Un backup de `GET /backups` con la forma de `_list_backups`."""
    return {
        "slug": slug, "name": nombre or f"Backup {slug}", "date": fecha,
        "type": "full", "size": 1.5, "size_bytes": 1_572_864,
        "location": locations[0], "locations": list(locations),
        "protected": False, "compressed": True,
        "content": {"homeassistant": True, "addons": [], "folders": []},
    }


def backups_de_ejemplo() -> list[dict[str, Any]]:
    """25 backups solo en `nas_backups` (para el recorte a 20), 2 en
    `nas_backups` y en local, y 3 solo en local. Fechas inventadas, todas
    distintas, en orden de lista NO cronológico."""
    out: list[dict[str, Any]] = []
    for i in range(25):
        # Orden de inserción ascendente: el recorte tiene que ordenar él.
        out.append(backup(f"nas{i:02d}ab", f"2026-10-{i + 1:02d}T03:00:00+00:00",
                          ["nas_backups"]))
    out.append(backup("ambos001", "2026-11-01T03:00:00+00:00", [None, "nas_backups"]))
    out.append(backup("ambos002", "2026-11-02T03:00:00+00:00", [None, "nas_backups"]))
    for i in range(3):
        out.append(backup(f"local{i:02d}", f"2026-09-0{i + 1}T03:00:00+00:00", [None]))
    return out


def error_al_montar() -> HAConnectionError:
    """Error del Supervisor al montar un CIFS que repite las credenciales
    (como un mensaje de `mount.cifs` que las citara)."""
    return HAConnectionError(
        "Supervisor error: Could not mount nas_backups: mount error(13): "
        f"Permission denied for user {USUARIO} with password {CLAVE}. "
        "Check the logs for details."
    )


class SupervisorDeMontajes:
    """Cliente simulado con estado: apunta cada petición (método, ruta y
    carga) y aplica las escrituras como el Supervisor real, para que lo leído
    de vuelta tras confirmar sea lo que Hermes mandó.

    - `errores[(método, ruta)]`: excepción que lanza esa petición.
    - `formas[(método, ruta)]`: respuesta cruda que sustituye a la normal
      (para las formas inesperadas).
    - `filtra=True`: `GET /mounts` devuelve también `username` y `password`.
    """

    def __init__(
        self,
        montajes: list[dict[str, Any]] | None = None,
        por_defecto: str | None = "nas_backups",
        backups: list[dict[str, Any]] | None = None,
        *,
        filtra: bool = False,
    ) -> None:
        self.montajes: list[dict[str, Any]] = (
            montajes_base() if montajes is None else copy.deepcopy(montajes))
        self.por_defecto = por_defecto
        self.backups = backups_de_ejemplo() if backups is None else copy.deepcopy(backups)
        self.filtra = filtra
        self.estados: dict[str, str] = {}
        self.errores: dict[tuple[str, str], Exception] = {}
        self.formas: dict[tuple[str, str], Any] = {}
        self.llamadas: list[dict[str, Any]] = []

    # ── Utilidades para los tests ─────────────────────────────────────────

    @property
    def escrituras(self) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["metodo"] != "GET"]

    def montaje(self, nombre: str) -> dict[str, Any] | None:
        return next((m for m in self.montajes if m["name"] == nombre), None)

    def publico(self, m: dict[str, Any]) -> dict[str, Any]:
        claves = _CLAVES_COMUNES + _CLAVES_POR_TIPO.get(m["type"], ())
        if self.filtra:
            claves += ("username", "password")
        out = {k: copy.deepcopy(m[k]) for k in claves if k in m}
        out["state"] = self.estados.get(m["name"], "active")
        raiz = _RAIZ_POR_USO.get(m.get("usage") or "")
        out["user_path"] = f"{raiz}/{m['name']}" if raiz else None
        return out

    # ── Cliente ───────────────────────────────────────────────────────────

    async def sv_request(
        self,
        method: str,
        sv_path: str,
        json_body: Any = None,
        params: Any = None,
        timeout_seconds: float = 60.0,
    ) -> Any:
        metodo = method.upper()
        self.llamadas.append({
            "metodo": metodo, "ruta": sv_path, "json": copy.deepcopy(json_body),
        })
        clave = (metodo, sv_path)
        if clave in self.errores:
            raise self.errores[clave]
        if clave in self.formas:
            return copy.deepcopy(self.formas[clave])
        return copy.deepcopy(self._atender(metodo, sv_path, json_body))

    def _no_existe(self, nombre: str) -> HAConnectionError:
        return HAConnectionError(
            f"Supervisor REST GET http://supervisor/mounts/{nombre} failed 404: "
            f'{{"result": "error", "message": "No mount exists with name {nombre}"}}',
            status=404)

    def _guardar(self, cuerpo: dict[str, Any]) -> dict[str, Any]:
        m = copy.deepcopy(cuerpo)
        if m.get("type") == "disk":
            # `device` es solo de entrada: el Supervisor lo resuelve.
            device = m.pop("device", None)
            if device and not m.get("uuid"):
                m["uuid"] = "5678-EF01"
            m.setdefault("filesystem", "ext4")
        m.setdefault("read_only", False)
        return m

    def _atender(self, metodo: str, ruta: str, cuerpo: Any) -> Any:
        if (metodo, ruta) == ("GET", "/mounts"):
            return {"default_backup_mount": self.por_defecto,
                    "mounts": [self.publico(m) for m in self.montajes]}
        if (metodo, ruta) == ("GET", "/backups"):
            return {"backups": self.backups}
        if (metodo, ruta) == ("POST", "/mounts"):
            if self.montaje(cuerpo["name"]):
                raise HAConnectionError(
                    "Supervisor error: A mount already exists with name "
                    f"{cuerpo['name']}")
            m = self._guardar(cuerpo)
            self.montajes.append(m)
            if m.get("usage") == "backup" and self.por_defecto is None:
                self.por_defecto = m["name"]
            return {}
        if (metodo, ruta) == ("POST", "/mounts/options"):
            nombre = cuerpo.get("default_backup_mount")
            if nombre is not None:
                m = self.montaje(nombre)
                if m is None:
                    raise self._no_existe(nombre)
                if m.get("usage") != "backup":
                    raise HAConnectionError(
                        f"Supervisor error: Mount {nombre} is not used for "
                        "backups, cannot use it as default backup mount")
            self.por_defecto = nombre
            return {}
        if ruta.startswith("/mounts/"):
            resto = ruta[len("/mounts/"):]
            nombre, _, accion = resto.partition("/")
            actual = self.montaje(nombre)
            if actual is None:
                raise self._no_existe(nombre)
            if metodo == "PUT" and not accion:
                m = self._guardar({**cuerpo, "name": nombre})
                self.montajes[self.montajes.index(actual)] = m
                if m.get("usage") != "backup" and self.por_defecto == nombre:
                    self.por_defecto = None
                return {}
            if metodo == "DELETE" and not accion:
                self.montajes.remove(actual)
                if self.por_defecto == nombre:
                    self.por_defecto = None
                return {}
            if metodo == "POST" and accion == "reload":
                self.estados[nombre] = "active"
                return {}
        raise HAConnectionError(
            f"Supervisor {metodo} {ruta} failed 404: not found", status=404)
