"""Módulo común de /addons y /share (spec 034, tramo 1: T004, T007, T008, T009).

`hermes/folders.py` no tiene tools: raíces, validación de rutas (la MISMA de
`/config`, parametrizada por raíz), symlinks, huellas, recuentos, topes,
puntos de montaje e índice de apps locales. Todo con ficheros REALES en
carpetas temporales (`folders.ADDONS_BASE` y `folders.SHARE_BASE`
parcheadas) y datos ficticios (`ejemplo`, `otra`).

Independencia del sistema operativo: los symlinks se crean con un ayudante
que hace `skip` si el sistema operativo no lo permite (en el CI de Linux
corren siempre); los puntos de montaje, con el predicado sustituible
`folders.es_punto_de_montaje`; las fechas, con `os.utime(ns=…)`; el byte
nulo lo rechaza `folders` antes de `resolve()`.

Controles negativos comprobados (T015, anotados en el commit del tramo):
(a) `normalize_in_root` comparando con `CONFIG_BASE` → caen `TestRutas`;
(b) sin el rechazo explícito del byte nulo → cae
`test_rechaza_byte_nulo` en Windows (en Linux lo sigue rechazando
`resolve()`); (c) siguiendo symlinks en la huella → caen los de
`TestSymlinks`/`TestHuellas` que miran enlaces; (d) sin excluir `rootfs` →
cae `TestIndiceDeApps`; (g) sin el tope de entradas → cae `TestTopes`.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

from hermes import folders
from hermes.fs import PathTraversalError

_SRC = pathlib.Path(__file__).resolve().parents[1] / "hermes" / "src"


def _symlink(enlace: pathlib.Path, destino: os.PathLike | str, *, dir: bool = False) -> None:
    """Crea un symlink o salta el test si el sistema operativo no deja."""
    try:
        os.symlink(destino, enlace, target_is_directory=dir)
    except (OSError, NotImplementedError) as exc:  # Windows sin privilegio
        pytest.skip(f"el sistema operativo no deja crear symlinks: {exc}")


@pytest.fixture()
def raices(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, pathlib.Path]:
    addons = (tmp_path / "addons").resolve()
    share = (tmp_path / "share").resolve()
    addons.mkdir()
    share.mkdir()
    monkeypatch.setattr(folders, "ADDONS_BASE", addons)
    monkeypatch.setattr(folders, "SHARE_BASE", share)
    return {"addons": addons, "share": share}


# ── T004: raíces y carpeta ────────────────────────────────────────────────────


def _raices_en_subproceso(**entorno: str) -> dict[str, str]:
    """Importa `hermes.folders` en un proceso nuevo con el entorno dado: las
    raíces se resuelven al importar, y recargar el módulo aquí cambiaría las
    clases de error que ya tienen importadas otros tests."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERMES_ADDONS_BASE", "HERMES_SHARE_BASE")}
    env.update(entorno)
    env["PYTHONPATH"] = str(_SRC)
    codigo = ("import json; from hermes import folders; "
              "print(json.dumps([str(folders.ADDONS_BASE), str(folders.SHARE_BASE)]))")
    salida = subprocess.run([sys.executable, "-c", codigo], env=env,
                            capture_output=True, text=True, check=True)
    addons, share = json.loads(salida.stdout)
    return {"addons": addons, "share": share}


class TestRaices:
    def test_por_defecto_addons_y_share(self) -> None:
        r = _raices_en_subproceso()
        assert r["addons"] == str(pathlib.Path("/addons").resolve())
        assert r["share"] == str(pathlib.Path("/share").resolve())

    def test_salen_del_entorno(self, tmp_path: pathlib.Path) -> None:
        a, s = tmp_path / "a", tmp_path / "s"
        r = _raices_en_subproceso(HERMES_ADDONS_BASE=str(a), HERMES_SHARE_BASE=str(s))
        assert r["addons"] == str(a.resolve())
        assert r["share"] == str(s.resolve())

    def test_raiz_con_la_raiz_parcheada(self, raices) -> None:
        assert folders.raiz("addons") == raices["addons"]
        assert folders.raiz("share") == raices["share"]


class TestCarpeta:
    @pytest.mark.parametrize("folder", ["config", "", "ADDONS", "Share", "addons/",
                                        "/addons", None, 1, "ssl", "media"])
    def test_nombre_invalido_sin_tocar_el_disco(self, raices, monkeypatch, folder) -> None:
        def prohibido(*_a, **_k):  # pragma: no cover - solo si se toca el disco
            raise AssertionError("raiz() tocó el disco con un nombre inválido")

        monkeypatch.setattr(pathlib.Path, "is_dir", prohibido)
        with pytest.raises(folders.CarpetaInvalida) as ctx:
            folders.raiz(folder)
        respuesta = ctx.value.respuesta()
        assert respuesta["error"] == "invalid_argument"
        assert "'addons'" in respuesta["detail"] and "'share'" in respuesta["detail"]

    def test_raiz_inexistente(self, raices, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(folders, "ADDONS_BASE", tmp_path / "no_existe")
        with pytest.raises(folders.CarpetaNoDisponible) as ctx:
            folders.raiz("addons")
        assert ctx.value.respuesta()["error"] == "folder_unavailable"
        assert "/addons" in ctx.value.detail
        # La otra sigue disponible.
        assert folders.raiz("share") == raices["share"]

    def test_raiz_que_es_un_fichero(self, raices, monkeypatch, tmp_path) -> None:
        fichero = tmp_path / "fichero"
        fichero.write_text("x", encoding="utf-8")
        monkeypatch.setattr(folders, "SHARE_BASE", fichero)
        with pytest.raises(folders.CarpetaNoDisponible):
            folders.raiz("share")

    def test_normalizar_tambien_valida_la_carpeta(self, raices) -> None:
        with pytest.raises(folders.CarpetaInvalida):
            folders.normalizar("config", "x")
        with pytest.raises(folders.CarpetaInvalida):
            folders.normalizar_sin_seguir("config", "x")


# ── T007: rutas y symlinks ────────────────────────────────────────────────────

_OTRA = {"addons": "share", "share": "addons"}


@pytest.mark.parametrize("folder", ["addons", "share"])
class TestRutas:
    @pytest.mark.parametrize("ruta", [
        "..", "../x", "a/../../x", "%2e%2e/x", "/etc/passwd", "/config/x",
        "/homeassistant/x", "", "   ", "sub/" + "a" * 300,
    ])
    def test_rechaza(self, raices, folder, ruta) -> None:
        with pytest.raises(PathTraversalError):
            folders.normalizar(folder, ruta)

    def test_rechaza_la_otra_carpeta(self, raices, folder) -> None:
        with pytest.raises(PathTraversalError, match=f"outside /{folder}"):
            folders.normalizar(folder, f"/{_OTRA[folder]}/x")

    @pytest.mark.parametrize("ruta", ["a\x00b", "a%00b", "\x00", "sub/x\x00.yaml"])
    def test_rechaza_byte_nulo(self, raices, folder, ruta) -> None:
        # En Windows `resolve()` no lo rechaza: lo hace `folders` antes.
        with pytest.raises(PathTraversalError):
            folders.normalizar(folder, ruta)
        with pytest.raises(PathTraversalError):
            folders.normalizar_sin_seguir(folder, ruta)

    def test_acepta(self, raices, folder) -> None:
        base = raices[folder]
        assert folders.normalizar(folder, "x/y") == base / "x" / "y"
        assert folders.normalizar(folder, f"/{folder}/x/y") == base / "x" / "y"
        assert folders.normalizar(folder, f"/{folder}") == base
        assert folders.normalizar(folder, ".") == base
        assert folders.normalizar(folder, "a/../x") == base / "x"

    def test_es_raiz(self, raices, folder) -> None:
        base = raices[folder]
        assert folders.es_raiz(folder, folders.normalizar(folder, "."))
        assert folders.es_raiz(folder, folders.normalizar(folder, f"/{folder}"))
        assert not folders.es_raiz(folder, base / "x")
        assert folders.relativa(folder, base) == "."
        assert folders.relativa(folder, base / "x" / "y") == "x/y"

    def test_sin_seguir_rechaza_ultimo_nombre_especial(self, raices, folder) -> None:
        (raices[folder] / "x").mkdir()
        for ruta in (".", "..", "x/.", "x/..", f"/{folder}", f"/{folder}/", "./",
                     "../x", "x/../../y", "/etc/x"):
            with pytest.raises(PathTraversalError):
                folders.normalizar_sin_seguir(folder, ruta)

    def test_sin_seguir_acepta(self, raices, folder) -> None:
        base = raices[folder]
        (base / "x").mkdir()
        assert folders.normalizar_sin_seguir(folder, "x") == base / "x"
        assert folders.normalizar_sin_seguir(folder, "x/") == base / "x"
        assert folders.normalizar_sin_seguir(folder, "x/y") == base / "x" / "y"
        assert folders.normalizar_sin_seguir(folder, f"/{folder}/x/y") == base / "x" / "y"
        with pytest.raises(PathTraversalError):
            folders.normalizar_sin_seguir(folder, "x/" + "b" * 300)


@pytest.mark.parametrize("folder", ["addons", "share"])
class TestSymlinks:
    def test_dentro_se_resuelve(self, raices, folder) -> None:
        base = raices[folder]
        (base / "real").mkdir()
        (base / "real" / "f.txt").write_text("hola", encoding="utf-8")
        _symlink(base / "enlace", base / "real", dir=True)
        assert folders.normalizar(folder, "enlace/f.txt") == base / "real" / "f.txt"

    def test_fuera_es_traversal(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        _symlink(base / "escape", fuera, dir=True)
        with pytest.raises(PathTraversalError):
            folders.normalizar(folder, "escape")
        with pytest.raises(PathTraversalError):
            folders.normalizar(folder, "escape/x")
        # Como padre tampoco vale para la variante sin seguir.
        with pytest.raises(PathTraversalError):
            folders.normalizar_sin_seguir(folder, "escape/x")

    def test_sin_seguir_devuelve_el_enlace(self, raices, folder, tmp_path) -> None:
        base = raices[folder]
        fuera = tmp_path / "fuera.txt"
        fuera.write_text("x", encoding="utf-8")
        _symlink(base / "enlace", fuera)
        assert folders.normalizar_sin_seguir(folder, "enlace") == base / "enlace"
        assert (base / "enlace").is_symlink()


# ── T008: huellas, recuentos, topes y puntos de montaje ───────────────────────


def _arbol(base: pathlib.Path) -> None:
    (base / "a" / "b").mkdir(parents=True)
    (base / "a" / "uno.txt").write_text("uno", encoding="utf-8")
    (base / "a" / "b" / "dos.txt").write_text("dos!", encoding="utf-8")
    (base / "c.txt").write_text("c", encoding="utf-8")


class TestHuellas:
    def test_fichero_sha256(self, raices) -> None:
        f = raices["share"] / "f.txt"
        f.write_bytes(b"contenido")
        h = folders.huella(f)
        assert h == {"kind": "file", "sha256": hashlib.sha256(b"contenido").hexdigest()}
        f.write_bytes(b"contenidO")
        assert folders.huella(f) != h

    def test_fichero_grande_por_metadatos(self, raices, monkeypatch) -> None:
        monkeypatch.setattr(folders, "UMBRAL_SHA256_BYTES", 10)
        f = raices["share"] / "grande.bin"
        f.write_bytes(b"x" * 20)
        os.utime(f, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        h = folders.huella(f)
        assert set(h) == {"kind", "size", "mtime_ns", "ino"}
        assert h["kind"] == "file" and h["size"] == 20
        assert folders.huella(f) == h
        # 1 ms: la resolución de la fecha en NTFS es de 100 ns.
        os.utime(f, ns=(1_700_000_000_000_000_000, 1_700_000_000_001_000_000))
        assert folders.huella(f) != h

    def test_ausente(self, raices) -> None:
        assert folders.huella(raices["share"] / "no") == {"kind": "absent"}

    def test_symlink_su_destino_literal(self, raices, tmp_path) -> None:
        enlace = raices["share"] / "enlace"
        _symlink(enlace, "../fuera/x.txt")
        assert folders.huella(enlace) == {"kind": "symlink", "target": os.readlink(enlace)}

    def test_carpeta_estable_y_tamano_none_en_las_carpetas(self, raices) -> None:
        base = raices["share"]
        _arbol(base)
        h1 = folders.huella(base / "a")
        assert h1["kind"] == "dir" and h1["entries"] == 3
        assert len(h1["sha256"]) == 64
        assert folders.huella(base / "a") == h1
        lista = folders.recorrer(base / "a")
        assert [e[0] for e in lista] == ["b", "b/dos.txt", "uno.txt"]
        # Carpetas sin tamaño ni fecha en la lista (dependen del sistema de
        # ficheros; la fecha de una carpeta se vio cambiar sola en Windows).
        assert lista[0] == ("b", "dir", None, None)
        assert lista[1][1:3] == ("file", 4)

    @pytest.mark.parametrize("cambio", ["crear", "borrar", "renombrar", "modificar",
                                        "fecha"])
    def test_carpeta_cambia_con_cualquier_cambio(self, raices, cambio) -> None:
        base = raices["share"]
        _arbol(base)
        hondo = base / "a" / "b" / "dos.txt"
        os.utime(hondo, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        antes = folders.huella(base / "a")
        if cambio == "crear":
            (base / "a" / "b" / "nuevo.txt").write_text("", encoding="utf-8")
        elif cambio == "borrar":
            hondo.unlink()
        elif cambio == "renombrar":
            hondo.rename(base / "a" / "b" / "otro.txt")
        elif cambio == "modificar":
            hondo.write_text("dos!!", encoding="utf-8")
        else:  # mismo tamaño y contenido, otra fecha
            os.utime(hondo, ns=(1_600_000_000_000_000_000, 1_600_000_000_001_000_000))
        assert folders.huella(base / "a") != antes

    def test_carpeta_no_sigue_symlinks(self, raices, tmp_path) -> None:
        base = raices["share"]
        (base / "d").mkdir()
        otra = tmp_path / "otra"
        otra.mkdir()
        (otra / "f.txt").write_text("x", encoding="utf-8")
        _symlink(base / "d" / "enlace", otra, dir=True)
        h = folders.huella(base / "d")
        assert h["entries"] == 1
        assert [e[1] for e in folders.recorrer(base / "d")] == ["symlink"]
        (otra / "g.txt").write_text("y", encoding="utf-8")
        assert folders.huella(base / "d") == h


class TestRecuento:
    def test_recuento_y_muestra(self, raices) -> None:
        base = raices["addons"]
        _arbol(base)
        r = folders.recuento(base)
        assert r == {
            "files": 3, "dirs": 2, "symlinks": 0, "total_bytes": 3 + 4 + 1,
            "sample": ["a", "a/b", "a/b/dos.txt", "a/uno.txt", "c.txt"],
            "sample_truncated": False,
        }

    def test_muestra_de_20_en_orden(self, raices) -> None:
        base = raices["addons"] / "muchos"
        base.mkdir()
        for i in range(25):
            (base / f"f{i:02d}.txt").write_text("ab", encoding="utf-8")
        r = folders.recuento(base)
        assert r["files"] == 25 and r["total_bytes"] == 50
        assert r["sample"] == [f"f{i:02d}.txt" for i in range(20)]
        assert r["sample_truncated"] is True

    def test_cuenta_symlinks_sin_seguirlos(self, raices, tmp_path) -> None:
        base = raices["share"]
        (base / "d").mkdir()
        _symlink(base / "d" / "enlace", tmp_path, dir=True)
        r = folders.recuento(base / "d")
        assert (r["files"], r["dirs"], r["symlinks"], r["total_bytes"]) == (0, 0, 1, 0)


class TestTopes:
    def test_tope_de_entradas(self, raices, monkeypatch) -> None:
        base = raices["share"]
        for i in range(6):
            (base / f"f{i}").write_text("", encoding="utf-8")
        monkeypatch.setattr(folders, "MAX_ENTRADAS", 6)
        assert folders.recuento(base)["files"] == 6
        monkeypatch.setattr(folders, "MAX_ENTRADAS", 5)
        for funcion in (folders.recuento, folders.huella, folders.recorrer):
            with pytest.raises(folders.ArbolDemasiadoGrande) as ctx:
                funcion(base)
            assert ctx.value.respuesta()["error"] == "too_large_to_preview"

    def test_tope_de_tiempo(self, raices, monkeypatch) -> None:
        base = raices["share"]
        _arbol(base)
        monkeypatch.setattr(folders, "MAX_SEGUNDOS", 0)
        with pytest.raises(folders.ArbolDemasiadoGrande, match="took more than"):
            folders.huella(base)


class TestPuntosDeMontaje:
    def test_el_recorrido_no_entra(self, raices, monkeypatch) -> None:
        base = raices["share"]
        nas = base / "sub" / "nas"
        nas.mkdir(parents=True)
        (nas / "grabacion.mp4").write_text("x", encoding="utf-8")
        (base / "otra").mkdir()
        monkeypatch.setattr(folders, "es_punto_de_montaje", lambda p: pathlib.Path(p) == nas)
        lista = folders.recorrer(base)
        assert ("sub/nas", "mount", None, None) in lista
        assert all(not e[0].startswith("sub/nas/") for e in lista)
        assert folders.contiene_punto_de_montaje(base)
        assert folders.contiene_punto_de_montaje(base / "sub")
        assert folders.contiene_punto_de_montaje(nas)
        assert not folders.contiene_punto_de_montaje(base / "otra")
        assert not folders.contiene_punto_de_montaje(base / "no_existe")

    def test_sin_montajes(self, raices) -> None:
        # El predicado real, sobre carpetas temporales: ninguna es un montaje.
        _arbol(raices["share"])
        assert not folders.es_punto_de_montaje(raices["share"] / "a")
        assert not folders.contiene_punto_de_montaje(raices["share"] / "a")


# ── T009: índice de apps locales ──────────────────────────────────────────────


class TestIndiceDeApps:
    """Las reglas de `store/data.py` del Supervisor 2026.11 (research R-4).

    Control negativo comprobado (T015 d): sin excluir `rootfs`, aparece
    `x/rootfs/config.yaml` y cae `test_indice`.
    """

    @staticmethod
    def _poblar(base: pathlib.Path) -> None:
        def escribir(rel: str, texto: str) -> None:
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(texto, encoding="utf-8")

        escribir("ejemplo/config.yaml", "name: Ejemplo\nslug: ejemplo\nversion: '1.0'\n")
        escribir("ejemplo/Dockerfile", "FROM scratch\n")
        escribir("anidada/dev/otra/config.json", json.dumps({"name": "Otra", "slug": "otra"}))
        escribir(".oculta/config.yaml", "slug: oculta\n")
        escribir("x/rootfs/config.yaml", "slug: enrootfs\n")
        escribir("x/.git/config.yml", "slug: engit\n")
        escribir("rota/config.yaml", "slug: [sin cerrar\n")
        escribir("sinslug/config.yml", "name: Sin slug\n")
        escribir("numerico/config.yaml", "slug: 123\n")
        escribir("nocuenta/config.txt", "slug: txt\n")
        escribir("nocuenta/configuracion.yaml", "slug: otro_nombre\n")
        grande = "slug: grande\n" + "# relleno\n" * (2 * 1024 * 1024 // 10)
        escribir("grande/config.yaml", grande)

    def test_indice(self, raices) -> None:
        self._poblar(raices["addons"])
        indice = folders.indice_de_apps_locales()
        assert indice.apps == {
            "local_ejemplo": {"dir": "ejemplo", "config": "ejemplo/config.yaml"},
            "local_otra": {"dir": "anidada/dev/otra",
                           "config": "anidada/dev/otra/config.json"},
        }
        # Convergencia 2 (T055): lo que el Supervisor descartaría seguro
        # (YAML roto, sin slug, un slug que no es texto, o sin los campos
        # obligatorios de su esquema) no es «ilegible»; solo lo que Hermes no
        # lee (aquí, más de 1 MiB).
        assert indice.ilegibles == ["grande/config.yaml"]
        assert indice.no_legibles == {
            "grande/config.yaml": "it is larger than 1 MiB, which Hermes does not read"}
        # Convergencia 4 (T062): solo es «descartado» lo que el Supervisor
        # salta seguro (YAML roto, sin `name`); uno con `name` que el
        # esquema rechazaría puede tumbar la recarga y va a `rompen_recarga`.
        assert indice.descartados == {
            "numerico/config.yaml": "it has no 'name'",
            "rota/config.yaml": "it is not valid YAML",
        }
        assert set(indice.rompen_recarga) == {
            "anidada/dev/otra/config.json", "ejemplo/config.yaml", "sinslug/config.yml"}
        assert "it has no 'version'" in indice.rompen_recarga["sinslug/config.yml"]
        assert "it has no 'description'" in indice.rompen_recarga["ejemplo/config.yaml"]
        assert indice.app_de_carpeta("ejemplo") == "local_ejemplo"
        assert indice.app_de_carpeta("anidada/dev/otra") == "local_otra"
        assert indice.app_de_carpeta("anidada") is None

    def test_config_en_la_raiz(self, raices) -> None:
        (raices["addons"] / "config.yaml").write_text("slug: raiz\n", encoding="utf-8")
        indice = folders.indice_de_apps_locales()
        assert indice.apps == {"local_raiz": {"dir": ".", "config": "config.yaml"}}

    def test_sin_montaje(self, raices, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(folders, "ADDONS_BASE", tmp_path / "no")
        with pytest.raises(folders.CarpetaNoDisponible):
            folders.indice_de_apps_locales()

    def test_un_config_symlink_no_se_sigue(self, raices, tmp_path) -> None:
        fuera = tmp_path / "fuera.yaml"
        fuera.write_text("slug: fuera\n", encoding="utf-8")
        (raices["addons"] / "app").mkdir()
        _symlink(raices["addons"] / "app" / "config.yaml", fuera)
        indice = folders.indice_de_apps_locales()
        assert indice.apps == {}
        assert indice.ilegibles == ["app/config.yaml"]
